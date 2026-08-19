from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase

User = get_user_model()


class ChatTestCase(TestCase):
    """Common setup for chat tests: two participants, alice and bob."""

    def setUp(self):
        # Keep django-ratelimit state from leaking between tests: the "user"
        # and "ip" keys are shared across the whole test run.
        caches["ratelimit"].clear()
        self.user = User.objects.create_user("alice", password="pw12345")
        self.other = User.objects.create_user("bob", password="pw12345")
