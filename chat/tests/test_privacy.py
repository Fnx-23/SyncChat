from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.urls import reverse

from ..broadcast import build_presence_event
from ..models import Conversation, Message
from ..routing import websocket_urlpatterns
from ..views import _profile_info_visible
from .base import ChatTestCase, User

app = URLRouter(websocket_urlpatterns)


class _PayloadMixin:
    def _conversation_of(self, viewer):
        response = self.client.get(reverse("dashboard"))
        return response.context["conversations_data"]["conversations"][0]

    def _search_result(self, username):
        response = self.client.get(reverse("search_users"), {"q": username})
        users = response.json()["users"]
        return next(u for u in users if u["username"] == username)


class OnlineStatusPrivacyTests(_PayloadMixin, ChatTestCase):
    """The show_online_status setting hides online/last-seen from others."""

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create()
        self.conversation.participants.add(self.user, self.other)

    def test_online_status_visible_by_default(self):
        self.other.is_online = True
        self.other.save()  # auto_now refreshes last_seen
        self.client.force_login(self.user)
        conv = self._conversation_of(self.user)
        self.assertTrue(conv["online"])
        self.assertIsNotNone(conv["last_seen"])

    def test_online_status_hidden_when_disabled(self):
        self.other.is_online = True
        self.other.show_online_status = False
        self.other.save()
        self.client.force_login(self.user)
        conv = self._conversation_of(self.user)
        self.assertFalse(conv["online"])
        self.assertIsNone(conv["last_seen"])

    def test_search_masks_online_status(self):
        self.other.is_online = True
        self.other.show_online_status = False
        self.other.save()
        self.client.force_login(self.user)
        result = self._search_result("bob")
        self.assertFalse(result["online"])
        self.assertIsNone(result["last_seen"])


class ReadReceiptPrivacyTests(ChatTestCase):
    """The read_receipts setting controls whether the sender learns of a read."""

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create()
        self.conversation.participants.add(self.user, self.other)

    def _sent_message_payload(self):
        # alice is the sender/viewer; her own message carries the read flag.
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        return next(m for m in conv["messages"] if m["from"] == "me")

    def test_read_receipt_visible_by_default(self):
        msg = Message.objects.create(
            conversation=self.conversation, sender=self.user, content="seen?"
        )
        msg.is_read = True
        msg.save()
        self.client.force_login(self.user)
        self.assertIs(self._sent_message_payload().get("read"), True)

    def test_read_receipt_hidden_when_reader_disables(self):
        msg = Message.objects.create(
            conversation=self.conversation, sender=self.user, content="seen?"
        )
        msg.is_read = True
        msg.save()
        # bob (the reader) turns receipts off, so alice never sees the flag.
        self.other.read_receipts = False
        self.other.save()
        self.client.force_login(self.user)
        self.assertNotIn("read", self._sent_message_payload())

    def test_mark_read_broadcasts_when_receipts_enabled(self):
        calls = []

        class FakeChannelLayer:
            async def group_send(self, group, event):
                calls.append((group, event))

        Message.objects.create(
            conversation=self.conversation, sender=self.user, content="hi"
        )
        with patch("chat.views.get_channel_layer", return_value=FakeChannelLayer()):
            self.client.force_login(self.other)  # bob reads, receipts on (default)
            response = self.client.post(
                reverse("conversation_read", kwargs={"pk": self.conversation.id})
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["type"], "chat.read")

    def test_mark_read_skips_broadcast_when_reader_disables_receipts(self):
        calls = []

        class FakeChannelLayer:
            async def group_send(self, group, event):
                calls.append((group, event))

        msg = Message.objects.create(
            conversation=self.conversation, sender=self.user, content="hi"
        )
        self.other.read_receipts = False
        self.other.save()
        with patch("chat.views.get_channel_layer", return_value=FakeChannelLayer()):
            self.client.force_login(self.other)  # bob reads with receipts off
            response = self.client.post(
                reverse("conversation_read", kwargs={"pk": self.conversation.id})
            )
        self.assertEqual(response.status_code, 200)
        # No realtime "seen" is emitted...
        self.assertEqual(calls, [])
        # ...but the message is still marked read so unread state stays correct.
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)


class ProfileVisibilityPrivacyTests(_PayloadMixin, ChatTestCase):
    """The profile_visibility setting gates bio / email exposure."""

    def setUp(self):
        super().setUp()
        self.other.bio = "bob's bio"
        self.other.email = "bob@example.com"
        self.other.save()

    def _share_conversation(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

    def test_profile_visible_to_partner_by_default(self):
        self._share_conversation()
        self.client.force_login(self.user)
        conv = self._conversation_of(self.user)
        self.assertEqual(conv["bio"], "bob's bio")
        self.assertEqual(conv["email"], "bob@example.com")

    def test_profile_hidden_when_visibility_nobody(self):
        self.other.profile_visibility = "nobody"
        self.other.save()
        self._share_conversation()
        self.client.force_login(self.user)
        conv = self._conversation_of(self.user)
        self.assertEqual(conv["bio"], "")
        self.assertEqual(conv["email"], "")

    def test_contacts_visibility_shows_profile_to_conversation_partner(self):
        self.other.profile_visibility = "contacts"
        self.other.save()
        self._share_conversation()
        self.client.force_login(self.user)
        conv = self._conversation_of(self.user)
        self.assertEqual(conv["bio"], "bob's bio")

    def test_search_everyone_visible_to_stranger(self):
        # carol shares no conversation with bob but bob is visible to everyone.
        carol = User.objects.create_user("carol", password="pw12345")
        self.client.force_login(carol)
        self.assertEqual(self._search_result("bob")["bio"], "bob's bio")

    def test_search_contacts_hidden_from_stranger(self):
        self.other.profile_visibility = "contacts"
        self.other.save()
        carol = User.objects.create_user("carol", password="pw12345")
        self.client.force_login(carol)
        self.assertEqual(self._search_result("bob")["bio"], "")

    def test_search_contacts_visible_to_contact(self):
        self.other.profile_visibility = "contacts"
        self.other.save()
        self._share_conversation()  # alice and bob now share a conversation
        self.client.force_login(self.user)
        self.assertEqual(self._search_result("bob")["bio"], "bob's bio")


class ProfileVisibilityHelperTests(ChatTestCase):
    """Unit coverage for the visibility helper's edge cases."""

    def test_owner_always_sees_own_profile(self):
        self.user.profile_visibility = "nobody"
        self.assertTrue(_profile_info_visible(self.user, viewer=self.user))

    def test_contacts_fails_closed_for_unknown_viewer(self):
        self.other.profile_visibility = "contacts"
        # No viewer supplied: a "contacts-only" profile stays hidden.
        self.assertFalse(_profile_info_visible(self.other, viewer=None))

    def test_nobody_hides_from_everyone(self):
        self.other.profile_visibility = "nobody"
        self.assertFalse(_profile_info_visible(self.other, viewer=self.user))


class PresenceRealtimeMaskingTests(ChatTestCase):
    """Realtime presence frames honour show_online_status."""

    def test_build_presence_event_masks_when_disabled(self):
        self.other.show_online_status = False
        self.other.save()
        event = build_presence_event(self.other, True)
        self.assertFalse(event["online"])
        self.assertIsNone(event["last_seen"])

    def test_build_presence_event_shows_when_enabled(self):
        event = build_presence_event(self.user, True)
        self.assertTrue(event["online"])
        self.assertIsNotNone(event["last_seen"])

    def test_presence_broadcast_masks_hidden_online_status(self):
        self.user.show_online_status = False
        self.user.save()

        async def body():
            communicator = WebsocketCommunicator(app, "/ws/presence/")
            communicator.scope["user"] = self.user
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "presence")
            self.assertEqual(event["username"], "alice")
            self.assertFalse(event["online"])
            self.assertIsNone(event["last_seen"])
            await communicator.disconnect()

        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 0):
            async_to_sync(body)()
