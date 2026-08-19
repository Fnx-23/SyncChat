import tempfile

from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse

from chat.models import Block, Conversation, Message

from .base import AccountsTestCase, User
from .helpers import avatar_file


class DeleteAccountTests(AccountsTestCase):
    def setUp(self):
        super().setUp()
        # A second, unrelated account that must survive alice's deletion.
        self.bob = User.objects.create_user(
            "bob", email="bob@example.com", password=self.PASSWORD
        )
        self.url = reverse("delete_account")

    # ---- access control -------------------------------------------------

    def test_delete_account_requires_login(self):
        response = self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_account_rejects_get(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    # ---- confirmation / re-authentication -------------------------------

    def test_delete_account_requires_confirmation(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"password": self.PASSWORD})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_account_requires_correct_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url, {"password": "wrong-password", "confirm": "true"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_account_requires_non_empty_password(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"password": "", "confirm": "true"})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    # ---- successful deletion --------------------------------------------

    def test_delete_account_success(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url, {"password": self.PASSWORD, "confirm": "true"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["redirect"], reverse("login"))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_session_invalidated_after_deletion(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})
        # The session is flushed, so a follow-up request is anonymous and the
        # login-required dashboard bounces to the login page.
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_deleted_account_cannot_log_in_again(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": self.PASSWORD}
        )
        # Login re-renders with an error rather than redirecting to the dashboard.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="alice").exists())

    # ---- related data handling ------------------------------------------

    def test_only_own_account_is_deleted(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.bob.pk).exists())

    def test_wrong_password_does_not_touch_related_data(self):
        conv = Conversation.objects.create()
        conv.participants.add(self.user, self.bob)
        Message.objects.create(conversation=conv, sender=self.user, content="hi")
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "nope", "confirm": "true"})
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Conversation.objects.filter(pk=conv.pk).exists())
        self.assertEqual(Message.objects.filter(sender=self.user).count(), 1)

    def test_blocks_removed_in_both_directions(self):
        carol = User.objects.create_user("carol", password=self.PASSWORD)
        Block.objects.create(blocker=self.user, blocked=self.bob)
        Block.objects.create(blocker=carol, blocked=self.user)
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})
        # No block row references the deleted user in either direction.
        self.assertFalse(Block.objects.filter(blocker=self.user.pk).exists())
        self.assertFalse(Block.objects.filter(blocked=self.user.pk).exists())
        # Unrelated users are untouched.
        self.assertTrue(User.objects.filter(pk=carol.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.bob.pk).exists())

    def test_shared_conversation_preserves_other_users_data(self):
        conv = Conversation.objects.create()
        conv.participants.add(self.user, self.bob)
        Message.objects.create(conversation=conv, sender=self.user, content="from alice")
        bob_msg = Message.objects.create(
            conversation=conv, sender=self.bob, content="from bob"
        )
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})

        # The conversation still has a living participant, so it and bob's
        # message survive; only alice's message (her own data) is gone.
        conv.refresh_from_db()
        self.assertTrue(Conversation.objects.filter(pk=conv.pk).exists())
        self.assertTrue(Message.objects.filter(pk=bob_msg.pk).exists())
        self.assertFalse(Message.objects.filter(sender=self.user.pk).exists())
        self.assertEqual(list(conv.participants.all()), [self.bob])

    def test_empty_conversation_is_removed(self):
        # A conversation left with no participants is a true orphan.
        conv = Conversation.objects.create()
        conv.participants.add(self.user)
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})
        self.assertFalse(Conversation.objects.filter(pk=conv.pk).exists())

    def test_no_broken_foreign_keys_remain(self):
        conv = Conversation.objects.create()
        conv.participants.add(self.user, self.bob)
        Message.objects.create(conversation=conv, sender=self.user, content="x")
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": self.PASSWORD, "confirm": "true"})
        # No message or block still points at the deleted user.
        self.assertFalse(Message.objects.filter(sender=self.user.pk).exists())
        self.assertFalse(Block.objects.filter(blocker=self.user.pk).exists())
        self.assertFalse(Block.objects.filter(blocked=self.user.pk).exists())

    def test_avatar_file_removed_from_storage(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.user.avatar = avatar_file()
                self.user.save(update_fields=["avatar"])
                avatar_name = self.user.avatar.name
                self.assertTrue(default_storage.exists(avatar_name))

                self.client.force_login(self.user)
                self.client.post(
                    self.url, {"password": self.PASSWORD, "confirm": "true"}
                )

                self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
                self.assertFalse(default_storage.exists(avatar_name))
