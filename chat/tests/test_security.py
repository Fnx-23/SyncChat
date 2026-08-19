from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ..models import Conversation
from .base import ChatTestCase
from .helpers import huge_dimension_png, image_file


class SecurityTests(ChatTestCase):
    """Validation that hostile uploads and payloads are rejected."""

    def test_huge_dimension_image_rejected(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"image": huge_dimension_png()},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("dimensions are too large", response.json()["error"])

    def test_corrupt_image_rejected(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"image": SimpleUploadedFile("pic.png", b"junk", content_type="image/png")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a valid image", response.json()["error"])

    def test_oversized_image_rejected(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("big.png", b"\x00" * 500, content_type="image/png")
        with patch("core.images.MAX_IMAGE_SIZE", 100):
            response = self.client.post(
                reverse("conversation_send", kwargs={"pk": conversation.id}),
                {"image": upload},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.json()["error"])

    def test_oversized_avatar_rejected(self):
        import tempfile

        from django.test import override_settings

        # A valid image that exceeds the (patched) avatar size cap.
        with (
            patch("core.images.MAX_AVATAR_SIZE", 10),
            tempfile.TemporaryDirectory() as media_root,
            override_settings(MEDIA_ROOT=media_root),
        ):
            self.client.force_login(self.user)
            response = self.client.post(
                reverse("settings"),
                {"username": self.user.username, "avatar": image_file()},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Image is too large", response.content.decode())
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)
