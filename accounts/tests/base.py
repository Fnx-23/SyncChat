from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase

User = get_user_model()


class AccountsTestCase(TestCase):
    """Shared setup for account tests: a default user and a safe password."""

    PASSWORD = "str0ngPassword9"

    def setUp(self):
        # Keep django-ratelimit state from leaking between tests: the "ip"
        # key used by signup/login is shared across the whole run.
        caches["ratelimit"].clear()
        self.user = User.objects.create_user(
            "alice", email="alice@example.com", password=self.PASSWORD
        )
