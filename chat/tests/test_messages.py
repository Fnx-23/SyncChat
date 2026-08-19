import tempfile
from unittest.mock import patch

from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from ..models import Conversation, Message
from .base import ChatTestCase, User
from .helpers import huge_dimension_png, image_file


class SendMessageTests(ChatTestCase):
    def test_requires_login(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        url = reverse("conversation_send", kwargs={"pk": conversation.id})
        response = self.client.post(url, {"content": "hi"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_sends_text_message(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "Hi there!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["message"]["from"], "me")
        self.assertEqual(response.json()["message"]["text"], "Hi there!")
        message = Message.objects.get(conversation=conversation)
        self.assertEqual(message.content, "Hi there!")
        self.assertFalse(message.image)

    def test_sends_image_message(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.user)
            response = self.client.post(
                reverse("conversation_send", kwargs={"pk": conversation.id}),
                {"image": image_file()},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.get(conversation=conversation).content, "")
        self.assertTrue(
            Message.objects.get(conversation=conversation).image.name.startswith("chat_images/")
        )

    def test_sends_message_with_caption(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.user)
            response = self.client.post(
                reverse("conversation_send", kwargs={"pk": conversation.id}),
                {"content": "look at this", "image": image_file()},
            )
        self.assertEqual(response.status_code, 200)
        message = Message.objects.get(conversation=conversation)
        self.assertEqual(message.content, "look at this")
        self.assertIsNotNone(message.image)

    def test_accepts_all_allowed_image_types(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        for content_type in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            response = self.client.post(
                reverse("conversation_send", kwargs={"pk": conversation.id}),
                {"image": image_file(content_type=content_type)},
            )
            self.assertEqual(
                response.status_code,
                200,
                f"content type {content_type} should be accepted",
            )

    def test_rejects_disallowed_content_type(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"image": image_file(content_type="image/heic")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only JPEG, PNG, WebP, and GIF", response.json()["error"])

    def test_rejects_non_image_file(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"image": SimpleUploadedFile("doc.txt", b"hello", content_type="text/plain")},
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_corrupt_image(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"image": SimpleUploadedFile("pic.png", b"not a png", content_type="image/png")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a valid image", response.json()["error"])

    def test_rejects_empty_message(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), 0)

    def test_rejects_whitespace_only_message(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "   "},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), 0)

    def test_rejects_message_too_long(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "x" * 4001},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("too long", response.json()["error"])
        self.assertEqual(Message.objects.count(), 0)

    def test_rejects_oversized_image(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        big = SimpleUploadedFile("big.png", b"\x00" * 200, content_type="image/png")
        with patch("core.images.MAX_IMAGE_SIZE", 100):
            response = self.client.post(
                reverse("conversation_send", kwargs={"pk": conversation.id}),
                {"image": big},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.json()["error"])

    def test_rejects_image_with_huge_dimensions(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"image": huge_dimension_png()},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("dimensions are too large", response.json()["error"])

    def test_denied_for_non_participant(self):
        outsider = User.objects.create_user("carol", password="pw12345")
        conversation = Conversation.objects.create()
        conversation.participants.add(self.other, outsider)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "hi"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Message.objects.count(), 0)

    def test_broadcasts_to_group(self):
        calls = []

        class FakeChannelLayer:
            async def group_send(self, group, event):
                calls.append((group, event))

        with patch("chat.views.get_channel_layer", return_value=FakeChannelLayer()):
            conversation = Conversation.objects.create()
            conversation.participants.add(self.user, self.other)
            self.client.force_login(self.user)
            response = self.client.post(
                reverse("conversation_send", kwargs={"pk": conversation.id}),
                {"content": "group hello"},
            )
        self.assertEqual(response.status_code, 200)
        group, event = calls[0]
        self.assertEqual(group, f"conversation_{conversation.id}")
        self.assertEqual(event["type"], "chat.message")
        self.assertEqual(event["content"], "group hello")
        self.assertEqual(event["sender"], "alice")

    def test_bump_conversation_updated_at(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        original = conversation.updated_at
        self.client.force_login(self.user)
        self.client.post(
            reverse("conversation_send", kwargs={"pk": conversation.id}),
            {"content": "bump me"},
        )
        conversation.refresh_from_db()
        self.assertGreater(conversation.updated_at, original)


class SendMessageRateLimitTests(ChatTestCase):
    def setUp(self):
        super().setUp()
        caches["ratelimit"].clear()

    def test_send_message_limited(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        self.client.force_login(self.user)
        url = reverse("conversation_send", kwargs={"pk": conversation.id})
        for _ in range(30):
            response = self.client.post(url, {"content": "hi"})
            self.assertEqual(response.status_code, 200)
        response = self.client.post(url, {"content": "hi"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("too quickly", response.json()["error"])
