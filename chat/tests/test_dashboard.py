from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from ..models import Conversation, Message
from .base import ChatTestCase, User
from .helpers import image_file


class DashboardTests(ChatTestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_dashboard_renders_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_exposes_conversations_data(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Message.objects.create(conversation=conversation, sender=self.user, content="Hey")
        Message.objects.create(conversation=conversation, sender=self.other, content="Hi!")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        data = response.context["conversations_data"]
        self.assertEqual(data["me"], "alice")
        self.assertEqual(len(data["conversations"]), 1)
        conv = data["conversations"][0]
        self.assertEqual(conv["id"], conversation.id)
        self.assertEqual(conv["name"], self.other.username)
        self.assertEqual(conv["handle"], "@bob")
        self.assertIn("last_seen", conv)
        self.assertEqual(conv["lastMessage"], "Hi!")
        self.assertEqual(conv["unread"], 1)
        self.assertFalse(conv["hasMore"])
        self.assertEqual(
            [(m["from"], m["text"]) for m in conv["messages"]],
            [("me", "Hey"), ("them", "Hi!")],
        )
        # Raw per-message timestamps so the client can format times and date
        # separators in the browser's timezone.
        self.assertTrue(all("created_at" in m for m in conv["messages"]))

    def test_dashboard_exposes_me_profile(self):
        """The current user's own identity (Bug 1): the client needs it to
        render the real avatar in the sidebar footer and to match incoming
        profile-update frames to the logged-in user."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        data = response.context["conversations_data"]
        profile = data["me_profile"]
        self.assertEqual(profile["username"], "alice")
        self.assertEqual(profile["name"], "alice")
        self.assertEqual(profile["handle"], "@alice")

    def test_dashboard_uses_display_name_when_set(self):
        """Bug 3: conversation headers must show the full name (display_name)
        when present, with @username as the secondary handle."""
        self.other.display_name = "Robert Bobson"
        self.other.save()
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Message.objects.create(conversation=conversation, sender=self.other, content="Hi!")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertEqual(conv["name"], "Robert Bobson")
        self.assertEqual(conv["handle"], "@bob")

    def test_dashboard_only_includes_user_conversations(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        Conversation.objects.create().participants.add(self.other, outsider)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        data = response.context["conversations_data"]
        self.assertEqual(data["conversations"], [])

    def test_dashboard_counts_unread_messages(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Message.objects.create(conversation=conversation, sender=self.other, content="one")
        Message.objects.create(conversation=conversation, sender=self.other, content="two")
        Message.objects.create(conversation=conversation, sender=self.user, content="mine")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertEqual(conv["unread"], 2)

    def test_dashboard_exposes_unread_total(self):
        first = Conversation.objects.create()
        first.participants.add(self.user, self.other)
        second = Conversation.objects.create()
        second.participants.add(self.user, self.other)
        Message.objects.create(conversation=first, sender=self.other, content="one")
        Message.objects.create(conversation=first, sender=self.other, content="two")
        Message.objects.create(conversation=second, sender=self.other, content="three")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["conversations_data"]["unread_total"], 3)

    def test_dashboard_payload_marks_read_for_sent_messages(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        mine_read = Message.objects.create(
            conversation=conversation, sender=self.user, content="read"
        )
        mine_read.is_read = True
        mine_read.save()
        Message.objects.create(conversation=conversation, sender=self.user, content="unread")
        Message.objects.create(conversation=conversation, sender=self.other, content="theirs")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        flags = [(m["from"], m.get("read")) for m in conv["messages"]]
        self.assertIn(("me", True), flags)
        self.assertIn(("me", False), flags)
        self.assertIn(("them", None), flags)

    def test_dashboard_caps_message_history(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        for i in range(60):
            Message.objects.create(conversation=conversation, sender=self.other, content=f"m{i}")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        messages = conv["messages"]
        self.assertEqual(len(messages), 50)
        self.assertTrue(conv["hasMore"])
        # The 50 most recent messages, in chronological order.
        self.assertEqual(messages[0]["text"], "m10")
        self.assertEqual(messages[-1]["text"], "m59")

    def test_dashboard_payload_includes_image_url(self):
        import tempfile

        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            Message.objects.create(
                conversation=conversation,
                sender=self.other,
                content="",
                image=image_file(),
            )
            self.client.force_login(self.user)
            response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertEqual(conv["mediaCount"], 1)
        self.assertEqual(len(conv["media"]), 1)
        self.assertTrue(conv["media"][0].startswith("/media/chat_images/"))
        self.assertTrue(conv["messages"][0]["image"].startswith("/media/chat_images/"))

    def test_dashboard_media_list_is_limited(self):
        import tempfile

        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            for i in range(15):
                Message.objects.create(
                    conversation=conversation,
                    sender=self.other,
                    content="",
                    image=image_file(name=f"pic{i}.png"),
                )
            self.client.force_login(self.user)
            response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertEqual(conv["mediaCount"], 15)
        self.assertEqual(len(conv["media"]), 12)


class MarkConversationReadTests(ChatTestCase):
    def test_mark_read_requires_login(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        url = reverse("conversation_read", kwargs={"pk": conversation.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_mark_read_marks_others_messages_read(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        theirs = Message.objects.create(conversation=conversation, sender=self.other, content="hey")
        self.client.force_login(self.user)
        response = self.client.post(reverse("conversation_read", kwargs={"pk": conversation.id}))
        self.assertEqual(response.status_code, 200)
        theirs.refresh_from_db()
        self.assertTrue(theirs.is_read)
        mine = Message.objects.create(conversation=conversation, sender=self.user, content="mine")
        self.assertFalse(mine.is_read)

    def test_mark_read_round_trip_updates_senders_payload(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Message.objects.create(conversation=conversation, sender=self.user, content="delivered")
        # The recipient opens the conversation, marking incoming messages read.
        self.client.force_login(self.other)
        self.client.post(reverse("conversation_read", kwargs={"pk": conversation.id}))
        # The sender's dashboard now shows "Seen" for the delivered message.
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertEqual(
            [(m["text"], m.get("read")) for m in conv["messages"]],
            [("delivered", True)],
        )

    def test_mark_read_denied_for_non_participant(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        conversation = Conversation.objects.create()
        conversation.participants.add(self.other, outsider)
        self.client.force_login(self.user)
        response = self.client.post(reverse("conversation_read", kwargs={"pk": conversation.id}))
        self.assertEqual(response.status_code, 404)

    def test_mark_read_broadcasts_read_receipt(self):
        calls = []

        class FakeChannelLayer:
            async def group_send(self, group, event):
                calls.append((group, event))

        with patch("chat.views.get_channel_layer", return_value=FakeChannelLayer()):
            conversation = Conversation.objects.create()
            conversation.participants.add(self.user, self.other)
            Message.objects.create(conversation=conversation, sender=self.other, content="hey")
            self.client.force_login(self.user)
            response = self.client.post(
                reverse("conversation_read", kwargs={"pk": conversation.id})
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            calls,
            [
                (
                    f"conversation_{conversation.id}",
                    {
                        "type": "chat.read",
                        "conversation_id": conversation.id,
                        "reader": "alice",
                    },
                )
            ],
        )

    def test_mark_read_skips_broadcast_when_nothing_new(self):
        calls = []

        class FakeChannelLayer:
            async def group_send(self, group, event):
                calls.append((group, event))

        with patch("chat.views.get_channel_layer", return_value=FakeChannelLayer()):
            conversation = Conversation.objects.create()
            conversation.participants.add(self.user, self.other)
            self.client.force_login(self.user)
            self.client.post(reverse("conversation_read", kwargs={"pk": conversation.id}))
        self.assertEqual(calls, [])


class ConversationHistoryTests(ChatTestCase):
    def _make_conversation(self, count):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        for i in range(count):
            Message.objects.create(conversation=conversation, sender=self.other, content=f"m{i}")
        return conversation

    def test_history_requires_login(self):
        conversation = self._make_conversation(2)
        url = reverse("conversation_history", kwargs={"pk": conversation.id})
        response = self.client.get(url, {"before": 1})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_history_returns_older_messages(self):
        conversation = self._make_conversation(5)
        self.client.force_login(self.user)
        messages = list(conversation.messages.order_by("id"))
        # Ask for everything older than the newest message.
        response = self.client.get(
            reverse("conversation_history", kwargs={"pk": conversation.id}),
            {"before": messages[-1].id},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [m["text"] for m in payload["messages"]],
            ["m0", "m1", "m2", "m3"],
        )
        self.assertFalse(payload["has_more"])

    def test_history_paginates(self):
        conversation = self._make_conversation(61)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("conversation_history", kwargs={"pk": conversation.id}),
            {"before": conversation.messages.order_by("-id").first().id + 1},
        )
        payload = response.json()
        self.assertEqual(len(payload["messages"]), 50)
        self.assertTrue(payload["has_more"])

    def test_history_denied_for_non_participant(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        conversation = Conversation.objects.create()
        conversation.participants.add(self.other, outsider)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("conversation_history", kwargs={"pk": conversation.id}),
            {"before": 1},
        )
        self.assertEqual(response.status_code, 404)

    def test_history_rejects_invalid_before(self):
        conversation = self._make_conversation(2)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("conversation_history", kwargs={"pk": conversation.id}),
            {"before": "abc"},
        )
        self.assertEqual(response.status_code, 400)


class ConversationHistoryRateLimitTests(ChatTestCase):
    def test_history_limited(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        for i in range(60):
            Message.objects.create(conversation=conversation, sender=self.other, content=f"m{i}")
        self.client.force_login(self.user)
        url = reverse("conversation_history", kwargs={"pk": conversation.id})
        for _ in range(60):
            response = self.client.get(url, {"before": 999999})
            self.assertEqual(response.status_code, 200)
        response = self.client.get(url, {"before": 999999})
        self.assertEqual(response.status_code, 429)
