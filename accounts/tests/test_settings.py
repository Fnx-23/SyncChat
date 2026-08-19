import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from .base import AccountsTestCase
from .helpers import avatar_file


class SettingsTests(AccountsTestCase):
    def test_settings_requires_login(self):
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_profile_update(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings"),
            {
                "display_name": "Alice Wondering",
                "username": "alice",
                "email": "alice@example.com",
                "bio": "Curious developer",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "Alice Wondering")
        self.assertEqual(self.user.bio, "Curious developer")

    def test_profile_update_broadcasts_profile_change(self):
        """Saving the profile must push the new identity to every connected
        client (Bug 1: name/avatar changes were not real-time)."""
        calls = []

        class FakeChannelLayer:
            async def group_send(self, group, event):
                calls.append((group, event))

        self.client.force_login(self.user)
        with patch("chat.broadcast.get_channel_layer", return_value=FakeChannelLayer()):
            response = self.client.post(
                reverse("settings"),
                {
                    "display_name": "Alice Wondering",
                    "username": "alice",
                    "email": "alice@example.com",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            calls,
            [
                (
                    "presence",
                    {
                        "type": "chat.profile_update",
                        "user_id": self.user.id,
                        "username": "alice",
                        "name": "Alice Wondering",
                        "handle": "@alice",
                        "avatar": None,
                    },
                )
            ],
        )

    def test_username_already_taken(self):
        from .base import User

        User.objects.create_user("bob", password=self.PASSWORD)
        self.client.force_login(self.user)
        response = self.client.post(reverse("settings"), {"username": "bob"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already taken")

    def test_email_already_in_use(self):
        from .base import User

        User.objects.create_user("bob", email="bob@example.com", password=self.PASSWORD)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings"),
            {"username": "alice", "email": "bob@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in use")

    def test_settings_profile_form_is_post_multipart(self):
        """Avatar upload relies on profileForm.submit(); without a multipart POST
        form the file content is never sent and the avatar never updates."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        form_html = response.content.decode()
        start = form_html.index('<form id="profile-form"')
        end = form_html.index(">", start)
        tag = form_html[start:end]
        self.assertIn('method="post"', tag)
        self.assertIn('enctype="multipart/form-data"', tag)

    def test_avatar_uploaded(self):
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("settings"),
                {"username": "alice", "avatar": avatar_file()},
            )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.name.startswith("avatars/"))

    def test_avatar_rejects_non_image(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("avatar.txt", b"not an image", content_type="text/plain")
        response = self.client.post(reverse("settings"), {"username": "alice", "avatar": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "image")
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_avatar_rejects_oversized_upload(self):
        self.client.force_login(self.user)
        # A valid image that exceeds the (patched) avatar size cap: the size
        # check must run after the file passes Django's image validation.
        with (
            patch("core.images.MAX_AVATAR_SIZE", 10),
            tempfile.TemporaryDirectory() as media_root,
            override_settings(MEDIA_ROOT=media_root),
        ):
            response = self.client.post(
                reverse("settings"),
                {"username": "alice", "avatar": avatar_file()},
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Image is too large")
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_password_change(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings"),
            {
                "form_type": "password",
                "current_password": self.PASSWORD,
                "new_password": "brandNewPass7",
                "confirm_password": "brandNewPass7",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brandNewPass7"))

    def test_password_change_wrong_current(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings"),
            {
                "form_type": "password",
                "current_password": "notMyPassword",
                "new_password": "brandNewPass7",
                "confirm_password": "brandNewPass7",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "current password is incorrect")

    def test_password_change_mismatch(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings"),
            {
                "form_type": "password",
                "current_password": self.PASSWORD,
                "new_password": "brandNewPass7",
                "confirm_password": "different7",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match")

    def test_autosave_username(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings_autosave"),
            {"field": "username", "value": "newalice"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newalice")

    def test_autosave_display_name(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings_autosave"),
            {"field": "display_name", "value": "Alice Wonderland"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "Alice Wonderland")

    def test_autosave_broadcasts_profile_change(self):
        calls = []

        class FakeChannelLayer:
            async def group_send(self, group, event):
                calls.append((group, event))

        self.client.force_login(self.user)
        with patch("chat.broadcast.get_channel_layer", return_value=FakeChannelLayer()):
            response = self.client.post(
                reverse("settings_autosave"),
                {"field": "display_name", "value": "Alice Wonderland"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 1)
        group, event = calls[0]
        self.assertEqual(group, "presence")
        self.assertEqual(event["type"], "chat.profile_update")
        self.assertEqual(event["name"], "Alice Wonderland")
        self.assertEqual(event["handle"], "@alice")

    def test_autosave_duplicate_username(self):
        from .base import User

        User.objects.create_user("bob", password=self.PASSWORD)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings_autosave"),
            {"field": "username", "value": "bob"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("already taken", data["error"])

    def test_autosave_invalid_field(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings_autosave"),
            {"field": "password", "value": "hacker"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Invalid field", data["error"])

    def test_autosave_requires_login(self):
        response = self.client.post(
            reverse("settings_autosave"),
            {"field": "username", "value": "newalice"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
