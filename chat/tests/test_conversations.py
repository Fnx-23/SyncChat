import json

from django.urls import reverse

from ..models import Block, Conversation, Message
from .base import ChatTestCase, User


class StartConversationTests(ChatTestCase):
    def test_requires_login(self):
        response = self.client.post(reverse("start_conversation"), {"user_id": self.other.id})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_creates(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_conversation"), {"user_id": self.other.id})
        self.assertEqual(response.status_code, 200)
        conversation = Conversation.objects.get()
        self.assertEqual(conversation.participants.count(), 2)
        self.assertIsNotNone(conversation.pair_key)
        self.assertEqual(response.json()["conversation"]["id"], conversation.id)

    def test_reuses_existing(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_conversation"), {"user_id": self.other.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation"]["id"], conversation.id)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_creates_new_pair_key_conversation(self):
        # A conversation that already has a pair key is found and reused.
        conversation = Conversation.objects.create(pair_key=f"{self.user.id}:{self.other.id}")
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_conversation"), {"user_id": self.other.id})
        self.assertEqual(response.json()["conversation"]["id"], conversation.id)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_rejects_self(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_conversation"), {"user_id": self.user.id})
        self.assertEqual(response.status_code, 400)

    def test_rejects_missing_user(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_conversation"), {"user_id": 99999})
        self.assertEqual(response.status_code, 404)

    def test_rejects_missing_user_id(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_conversation"))
        self.assertEqual(response.status_code, 400)


class SearchUsersTests(ChatTestCase):
    def test_requires_login(self):
        response = self.client.get(reverse("search_users"), {"q": "bob"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_matches_and_excludes_self(self):
        self.other.display_name = "Robert Bobson"
        self.other.email = "bob@example.com"
        self.other.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("search_users"), {"q": "bob"})
        self.assertEqual(response.status_code, 200)
        users = response.json()["users"]
        usernames = [u["username"] for u in users]
        self.assertIn("bob", usernames)
        self.assertNotIn("alice", usernames)
        self.assertEqual(users[0]["name"], "Robert Bobson")

    def test_without_query_returns_others(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("search_users"))
        users = response.json()["users"]
        self.assertEqual([u["username"] for u in users], ["bob"])


class SearchConversationsTests(ChatTestCase):
    def test_requires_login(self):
        response = self.client.get(reverse("search_conversations"), {"q": "bob"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_matches_participant_name(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.get(reverse("search_conversations"), {"q": "bob"})
        self.assertEqual(response.status_code, 200)
        ids = [c["id"] for c in response.json()["conversations"]]
        self.assertIn(conversation.id, ids)

    def test_matches_message_content(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Message.objects.create(
            conversation=conversation,
            sender=self.other,
            content="meet at the park",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("search_conversations"), {"q": "park"})
        ids = [c["id"] for c in response.json()["conversations"]]
        self.assertIn(conversation.id, ids)

    def test_excludes_foreign_conversations(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        conversation = Conversation.objects.create()
        conversation.participants.add(self.other, outsider)
        Message.objects.create(
            conversation=conversation,
            sender=self.other,
            content="secret park meeting",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("search_conversations"), {"q": "park"})
        self.assertEqual(response.json()["conversations"], [])

    def test_empty_query(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("search_conversations"))
        self.assertEqual(response.json()["conversations"], [])


class SearchMessagesTests(ChatTestCase):
    def test_requires_login(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        url = reverse("conversation_search", kwargs={"pk": conversation.id})
        response = self.client.get(url, {"q": "hi"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_returns_matches(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Message.objects.create(
            conversation=conversation,
            sender=self.other,
            content="hello world",
        )
        Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content="nothing here",
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("conversation_search", kwargs={"pk": conversation.id}),
            {"q": "hello"},
        )
        messages = response.json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], "hello world")
        self.assertEqual(messages[0]["from"], "them")

    def test_denied_for_non_participant(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        conversation = Conversation.objects.create()
        conversation.participants.add(self.other, outsider)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("conversation_search", kwargs={"pk": conversation.id}),
            {"q": "hi"},
        )
        self.assertEqual(response.status_code, 404)

    def test_empty_query(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.get(reverse("conversation_search", kwargs={"pk": conversation.id}))
        self.assertEqual(response.json()["messages"], [])


class ToggleMuteTests(ChatTestCase):
    def _make_conversation(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        return conversation

    def test_mute_requires_login(self):
        conversation = self._make_conversation()
        response = self.client.post(reverse("conversation_mute", kwargs={"pk": conversation.id}))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_mute_toggles_and_persists(self):
        conversation = self._make_conversation()
        self.client.force_login(self.user)

        # Mute.
        response = self.client.post(reverse("conversation_mute", kwargs={"pk": conversation.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "muted": True})
        self.assertTrue(conversation.muted_by.filter(id=self.user.id).exists())

        # Unmute.
        response = self.client.post(reverse("conversation_mute", kwargs={"pk": conversation.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "muted": False})
        self.assertFalse(conversation.muted_by.filter(id=self.user.id).exists())

    def test_mute_is_per_user(self):
        conversation = self._make_conversation()
        self.client.force_login(self.user)
        self.client.post(reverse("conversation_mute", kwargs={"pk": conversation.id}))
        # The other participant is unaffected by alice's mute.
        self.assertFalse(conversation.muted_by.filter(id=self.other.id).exists())
        self.client.force_login(self.other)
        response = self.client.post(reverse("conversation_mute", kwargs={"pk": conversation.id}))
        self.assertEqual(response.json(), {"ok": True, "muted": True})
        self.assertEqual(set(conversation.muted_by.all()), {self.user, self.other})

    def test_mute_denied_for_non_participant(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(outsider)
        response = self.client.post(reverse("conversation_mute", kwargs={"pk": conversation.id}))
        self.assertEqual(response.status_code, 404)

    def test_mute_denied_for_missing_conversation(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("conversation_mute", kwargs={"pk": 99999}))
        self.assertEqual(response.status_code, 404)

    def test_mute_state_survives_refresh(self):
        """Simulates a page refresh: after muting, the dashboard payload still
        reports ``muted: True`` for that conversation."""
        conversation = self._make_conversation()
        self.client.force_login(self.user)
        response = self.client.post(reverse("conversation_mute", kwargs={"pk": conversation.id}))
        self.assertEqual(response.json()["muted"], True)

        # "Refresh" — reload the dashboard and read the payload again.
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertEqual(conv["muted"], True)

    def test_dashboard_defaults_to_unmuted(self):
        Conversation.objects.create().participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertIs(conv["muted"], False)


class ConversationPayloadTests(ChatTestCase):
    """The conversation payload must carry the other participant's user id so
    the New Chat modal's "Recent" entries can start/open the right chat."""

    def test_payload_includes_other_user_id(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        conv = response.context["conversations_data"]["conversations"][0]
        self.assertEqual(conv["userId"], self.other.id)
        # The conversation id itself is a separate, larger value.
        self.assertEqual(conv["id"], conversation.id)
        self.assertNotEqual(conv["userId"], conv["id"])

    def test_start_endpoint_returns_user_id(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("start_conversation"), {"user_id": self.other.id}
        )
        conv = response.json()["conversation"]
        self.assertEqual(conv["userId"], self.other.id)


class BlockTests(ChatTestCase):
    def _make_conversation(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        return conversation

    def _block(self, blocker, blocked):
        Block.objects.create(blocker=blocker, blocked=blocked)

    def test_block_requires_login(self):
        response = self.client.post(reverse("block_user", kwargs={"user_id": self.other.id}))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_block_persists(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("block_user", kwargs={"user_id": self.other.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "blocked": True})
        self.assertTrue(
            Block.objects.filter(blocker=self.user, blocked=self.other).exists()
        )

    def test_block_is_idempotent(self):
        self.client.force_login(self.user)
        for _ in range(2):
            response = self.client.post(
                reverse("block_user", kwargs={"user_id": self.other.id})
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True, "blocked": True})
        self.assertEqual(
            Block.objects.filter(blocker=self.user, blocked=self.other).count(), 1
        )

    def test_block_self_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("block_user", kwargs={"user_id": self.user.id}))
        self.assertEqual(response.status_code, 400)

    def test_block_missing_user_returns_404(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("block_user", kwargs={"user_id": 99999}))
        self.assertEqual(response.status_code, 404)

    def test_send_blocked_after_blocking(self):
        conversation = self._make_conversation()
        self._block(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "still there?"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(conversation.messages.count(), 0)

    def test_send_when_blocked_by_receiver_is_rejected(self):
        # Alice blocks Bob. Bob cannot send: the conversation is frozen in both
        # directions. The attempt is rejected with 403 and no message record is
        # created.
        conversation = self._make_conversation()
        self._block(self.user, self.other)  # Alice (self.user) blocks Bob (self.other)
        self.client.force_login(self.other)  # Bob sends
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "hello?"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(conversation.messages.count(), 0)

    def test_blocked_user_payload_is_anonymized(self):
        # Alice blocks Bob. Bob's dashboard shows the conversation but Alice is
        # reduced to an anonymous "Unknown User": no identity, no media, no
        # history, no unread.
        conversation = self._make_conversation()
        Message.objects.create(
            conversation=conversation, sender=self.user, content="secret", is_read=False
        )
        self._block(self.user, self.other)  # Alice (self.user) blocks Bob (self.other)
        self.client.force_login(self.other)  # Bob views the dashboard
        resp = self.client.get(reverse("dashboard"))
        data = resp.context["conversations_data"]

        convo = data["conversations"][0]
        self.assertEqual(convo["id"], conversation.id)
        self.assertTrue(convo["blockedMe"])
        self.assertEqual(convo["name"], "Unknown User")
        self.assertEqual(convo["username"], "")
        self.assertIsNone(convo["avatar"])
        self.assertIsNone(convo["userId"])
        self.assertFalse(convo["online"])
        self.assertEqual(convo["media"], [])
        self.assertEqual(convo["mediaCount"], 0)
        self.assertEqual(convo["unread"], 0)
        self.assertEqual(convo["messages"], [])
        self.assertEqual(data["unread_total"], 0)

        # The blocker's identity is never exposed anywhere in the payload.
        blob = json.dumps(data)
        self.assertNotIn("secret", blob)
        self.assertNotIn(self.user.username, blob)
        self.assertNotIn(f'"userId": {self.user.id}', blob)

    def test_blocked_user_detail_payload_is_anonymized(self):
        conversation = self._make_conversation()
        Message.objects.create(
            conversation=conversation, sender=self.user, content="secret", is_read=False
        )
        self._block(self.user, self.other)  # Alice (self.user) blocks Bob (self.other)
        self.client.force_login(self.other)
        resp = self.client.get(
            reverse("conversation_detail", kwargs={"pk": conversation.id})
        )
        self.assertEqual(resp.status_code, 200)
        convo = resp.json()["conversation"]
        self.assertTrue(convo["blockedMe"])
        self.assertEqual(convo["name"], "Unknown User")
        self.assertIsNone(convo["userId"])
        self.assertEqual(convo["messages"], [])
        self.assertEqual(convo["unread"], 0)
        self.assertNotIn("secret", json.dumps(convo))

    def test_start_conversation_blocked(self):
        self._block(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_conversation"), {"user_id": self.other.id})
        self.assertEqual(response.status_code, 403)

    def test_dashboard_keeps_blocked_conversation_visible(self):
        conversation = self._make_conversation()
        Message.objects.create(
            conversation=conversation, sender=self.other, content="unread!", is_read=False
        )
        self._block(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        data = response.context["conversations_data"]
        # Blocked conversations remain visible and readable.
        self.assertEqual(len(data["conversations"]), 1)
        self.assertEqual(data["conversations"][0]["id"], conversation.id)
        self.assertEqual(data["conversations"][0]["unread"], 1)
        self.assertEqual(data["unread_total"], 1)
        texts = [m["text"] for m in data["conversations"][0]["messages"]]
        self.assertIn("unread!", texts)

    def test_blocked_conversation_visible_to_both_participants(self):
        conversation = self._make_conversation()
        self._block(self.user, self.other)
        # Neither participant is hidden: both still see the conversation.
        for user in (self.user, self.other):
            self.client.force_login(user)
            response = self.client.get(reverse("dashboard"))
            data = response.context["conversations_data"]
            self.assertEqual(len(data["conversations"]), 1)
            self.assertEqual(data["conversations"][0]["id"], conversation.id)

    def test_unblock_restores_message_sending(self):
        conversation = self._make_conversation()
        self._block(self.user, self.other)
        self.client.force_login(self.user)
        # Blocked: sending is rejected.
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "still there?"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(conversation.messages.count(), 0)
        # Unblock, then sending works again.
        response = self.client.post(reverse("unblock_user", kwargs={"user_id": self.other.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "blocked": False})
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "hello again"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(conversation.messages.count(), 1)

    def test_unblock_reveals_blocked_delivery_messages(self):
        # Messages the unblocked user sent while blocked (blocked_delivery=True)
        # are hidden from the receiver; unblocking reveals them so the full
        # history is restored.
        conversation = self._make_conversation()
        self._block(self.user, self.other)
        hidden = Message.objects.create(
            conversation=conversation,
            sender=self.other,
            content="sent while blocked",
            blocked_delivery=True,
        )
        Message.objects.create(
            conversation=conversation, sender=self.other, content="visible"
        )
        self.client.force_login(self.user)
        # Hidden from the receiver before unblocking.
        response = self.client.get(
            reverse("conversation_detail", kwargs={"pk": conversation.id})
        )
        texts = [m["text"] for m in response.json()["conversation"]["messages"]]
        self.assertNotIn("sent while blocked", texts)
        self.assertIn("visible", texts)
        # Unblock reveals the flagged message.
        response = self.client.post(reverse("unblock_user", kwargs={"user_id": self.other.id}))
        self.assertEqual(response.status_code, 200)
        hidden.refresh_from_db()
        self.assertFalse(hidden.blocked_delivery)
        response = self.client.get(
            reverse("conversation_detail", kwargs={"pk": conversation.id})
        )
        texts = [m["text"] for m in response.json()["conversation"]["messages"]]
        self.assertIn("sent while blocked", texts)

    def test_search_hides_blocked_conversation(self):
        self._make_conversation()
        self._block(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("search_conversations"), {"q": self.other.username}
        )
        self.assertEqual(response.json()["conversations"], [])


class DeleteConversationTests(ChatTestCase):
    def _make_conversation(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        return conversation

    def _delete_url(self, pk):
        return reverse("conversation_delete", kwargs={"pk": pk})

    def test_delete_requires_login(self):
        conversation = self._make_conversation()
        response = self.client.post(self._delete_url(conversation.id))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_delete_persists_and_hides_on_refresh(self):
        conversation = self._make_conversation()
        self.client.force_login(self.user)
        response = self.client.post(self._delete_url(conversation.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "deleted": True})
        self.assertTrue(conversation.deleted_by.filter(id=self.user.id).exists())
        # "Refresh" — the conversation stays hidden on the next dashboard load.
        data = self.client.get(reverse("dashboard")).context["conversations_data"]
        self.assertEqual(data["conversations"], [])

    def test_delete_is_idempotent(self):
        conversation = self._make_conversation()
        self.client.force_login(self.user)
        for _ in range(2):
            response = self.client.post(self._delete_url(conversation.id))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True, "deleted": True})
        self.assertEqual(
            conversation.deleted_by.filter(id=self.user.id).count(), 1
        )

    def test_delete_denied_for_non_participant(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        conversation = self._make_conversation()
        self.client.force_login(outsider)
        response = self.client.post(self._delete_url(conversation.id))
        self.assertEqual(response.status_code, 404)

    def test_delete_missing_conversation_returns_404(self):
        self.client.force_login(self.user)
        response = self.client.post(self._delete_url(99999))
        self.assertEqual(response.status_code, 404)

    def test_delete_only_affects_current_user(self):
        conversation = self._make_conversation()
        Message.objects.create(
            conversation=conversation, sender=self.user, content="hello"
        )
        self.client.force_login(self.user)
        self.client.post(self._delete_url(conversation.id))
        # The other participant still has the conversation and its messages.
        self.client.force_login(self.other)
        data = self.client.get(reverse("dashboard")).context["conversations_data"]
        self.assertEqual(len(data["conversations"]), 1)
        self.assertEqual(data["conversations"][0]["id"], conversation.id)
        self.assertEqual(data["conversations"][0]["messages"][0]["text"], "hello")
        self.assertEqual(conversation.messages.count(), 1)  # nothing deleted

    def test_search_hides_deleted_conversation(self):
        conversation = self._make_conversation()
        self.client.force_login(self.user)
        self.client.post(self._delete_url(conversation.id))
        response = self.client.get(
            reverse("search_conversations"), {"q": self.other.username}
        )
        self.assertEqual(response.json()["conversations"], [])

    def test_sender_message_restores_deleted_conversation(self):
        conversation = self._make_conversation()
        self.client.force_login(self.user)
        self.client.post(self._delete_url(conversation.id))
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "hey, back again"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(conversation.deleted_by.exists())
        data = self.client.get(reverse("dashboard")).context["conversations_data"]
        self.assertEqual([c["id"] for c in data["conversations"]], [conversation.id])

    def test_other_user_message_restores_deleted_conversation(self):
        conversation = self._make_conversation()
        self.client.force_login(self.user)
        self.client.post(self._delete_url(conversation.id))
        # Bob sends a message; alice's deleted state is cleared too.
        self.client.force_login(self.other)
        self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "still here"},
        )
        self.assertFalse(conversation.deleted_by.exists())
