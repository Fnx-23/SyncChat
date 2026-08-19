from unittest import mock

from django.test import Client
from django.urls import reverse

from .base import AccountsTestCase


class SignUpTests(AccountsTestCase):
    def _valid_data(self, **overrides):
        data = {
            "full_name": "Alice Example",
            "username": "newbie",
            "email": "newbie@example.com",
            "password1": self.PASSWORD,
            "password2": self.PASSWORD,
        }
        data.update(overrides)
        return data

    def test_signup_page_loads(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)

    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(reverse("signup"), self._valid_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))
        from .base import User

        user = User.objects.get(username="newbie")
        self.assertEqual(user.email, "newbie@example.com")
        # The signup "full name" is the app's canonical display_name: it must
        # show up in Settings and in conversation headers (it used to be saved
        # to first_name, which nothing displays).
        self.assertEqual(user.display_name, "Alice Example")
        self.assertEqual(user.first_name, "")
        # Follow-up request shows the session is authenticated.
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_signup_full_name_appears_in_settings(self):
        self.client.post(reverse("signup"), self._valid_data())
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Example")

    def test_signup_requires_matching_passwords(self):
        response = self.client.post(reverse("signup"), self._valid_data(password2="different"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The two password fields")
        from .base import User

        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_signup_rejects_duplicate_username(self):
        response = self.client.post(reverse("signup"), self._valid_data(username="alice"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "username")

    def test_signup_rejects_html_username(self):
        response = self.client.post(
            reverse("signup"), self._valid_data(username="<script>alert(1)</script>")
        )
        self.assertEqual(response.status_code, 200)
        from .base import User

        self.assertFalse(User.objects.filter(username__contains="script").exists())

    def test_signup_redirects_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))

    def test_signup_rate_limited(self):
        for _ in range(5):
            self.client.post(reverse("signup"), self._valid_data(password2="nope"))
        response = self.client.post(reverse("signup"), self._valid_data(password2="nope"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many sign-up attempts")


class LoginTests(AccountsTestCase):
    def test_login_page_loads(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)

    def test_login_success(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": self.PASSWORD}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard"))
        # The session is authenticated: the next request reaches the dashboard.
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_login_failure_stays_on_page_with_clear_error(self):
        response = self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password.")

    def test_login_failure_keeps_username_filled(self):
        response = self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="alice"')

    def test_login_redirects_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 302)

    def test_login_rate_limited(self):
        for _ in range(10):
            self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        response = self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many login attempts")


class LoginFlowRegressionTests(AccountsTestCase):
    """Prove the full login chain — POST reaches the view, CSRF passes, the
    form validates, authenticate() returns the user, login() writes the
    session, and a success redirects to /chat/. Guards the regression where
    valid credentials only re-rendered the page."""

    def test_post_reaches_login_view(self):
        ok = self.client.post(
            reverse("login"), {"username": "alice", "password": self.PASSWORD}
        )
        self.assertEqual(ok.status_code, 302)
        # Fresh client for the bad attempt: the first is now authenticated and
        # would be redirected away by redirect_authenticated_user.
        bad = Client().post(reverse("login"), {"username": "alice", "password": "nope"})
        # Handled by the view, not bounced by 404/405.
        self.assertEqual(bad.status_code, 200)

    def test_csrf_enforced_login_succeeds_with_token(self):
        import re

        c = Client(enforce_csrf_checks=True)
        page = c.get(reverse("login"))
        self.assertEqual(page.status_code, 200)
        self.assertIsNotNone(c.cookies.get("csrftoken"))
        token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()
        ).group(1)
        response = c.post(
            reverse("login"),
            {
                "csrfmiddlewaretoken": token,
                "username": "alice",
                "password": self.PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_csrf_missing_token_rejected(self):
        c = Client(enforce_csrf_checks=True)
        c.get(reverse("login"))
        response = c.post(reverse("login"), {"username": "alice", "password": self.PASSWORD})
        self.assertEqual(response.status_code, 403)

    def test_form_validation_rejects_bad_credentials(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": "nope"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertContains(response, "Invalid username or password.")

    def test_authenticate_and_login_invoked(self):
        # Spy on the two auth primitives the view relies on. wraps= keeps the
        # real behaviour, so the session still ends up authenticated.
        from django.contrib.auth import authenticate as real_authenticate
        from django.contrib.auth import login as real_login

        with (
            mock.patch(
                "django.contrib.auth.forms.authenticate", wraps=real_authenticate
            ) as authenticate_spy,
            mock.patch(
                "django.contrib.auth.views.auth_login", wraps=real_login
            ) as login_spy,
        ):
            response = self.client.post(
                reverse("login"), {"username": "alice", "password": self.PASSWORD}
            )
        self.assertEqual(response.status_code, 302)
        authenticate_spy.assert_called()
        login_spy.assert_called_once()
        # login() actually wrote the session.
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.id)

    def test_success_redirects_to_chat(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": self.PASSWORD}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/chat/")


class LogoutTests(AccountsTestCase):
    def test_logout_post_logs_out(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        # The session is gone: the dashboard now bounces to login.
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_logout_get_returns_405(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 405)

    def test_logout_marks_user_offline(self):
        # Logout must flip presence to Offline immediately; the browser closes
        # the presence socket, so the server cannot wait for the grace period.
        self.user.is_online = True
        self.user.save(update_fields=["is_online"])
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_online)
