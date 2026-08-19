from django.test import Client
from django.urls import reverse

from .base import AccountsTestCase, User


class PrivacySettingEndpointTests(AccountsTestCase):
    """The /accounts/settings/privacy/ auto-save endpoint."""

    def _post(self, field, value):
        return self.client.post(
            reverse("privacy_setting"), {"field": field, "value": value}
        )

    # ---- authentication ----------------------------------------------------
    def test_update_requires_login(self):
        """An unauthenticated request can never change any setting."""
        response = self._post("show_online_status", "false")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("privacy_setting"))
        self.assertEqual(response.status_code, 405)

    def test_csrf_protected(self):
        """State-changing POSTs require a CSRF token."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            reverse("privacy_setting"),
            {"field": "show_online_status", "value": "false"},
        )
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.show_online_status)

    # ---- successful updates ------------------------------------------------
    def test_update_boolean_setting(self):
        self.client.force_login(self.user)
        response = self._post("show_online_status", "false")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.show_online_status)

    def test_update_read_receipts(self):
        self.client.force_login(self.user)
        response = self._post("read_receipts", "false")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.read_receipts)

    def test_update_profile_visibility(self):
        self.client.force_login(self.user)
        response = self._post("profile_visibility", "nobody")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.profile_visibility, "nobody")

    def test_updates_are_independent(self):
        """Saving one field must not reset the others."""
        self.client.force_login(self.user)
        self._post("read_receipts", "false")
        self.user.refresh_from_db()
        self.assertFalse(self.user.read_receipts)
        self.assertTrue(self.user.show_online_status)
        self.assertEqual(self.user.profile_visibility, "everyone")

    # ---- server-side validation -------------------------------------------
    def test_invalid_boolean_value_rejected(self):
        self.client.force_login(self.user)
        response = self._post("show_online_status", "maybe")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.show_online_status)

    def test_invalid_visibility_value_rejected(self):
        self.client.force_login(self.user)
        response = self._post("profile_visibility", "friends-only")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.profile_visibility, "everyone")

    def test_unknown_field_rejected(self):
        self.client.force_login(self.user)
        response = self._post("is_superuser", "true")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    # ---- isolation between accounts ----------------------------------------
    def test_user_cannot_modify_another_users_settings(self):
        """The endpoint only ever mutates the logged-in user's own row."""
        bob = User.objects.create_user("bob", password=self.PASSWORD)
        self.client.force_login(bob)
        response = self._post("show_online_status", "false")
        self.assertEqual(response.status_code, 200)
        bob.refresh_from_db()
        self.user.refresh_from_db()
        self.assertFalse(bob.show_online_status)
        self.assertTrue(self.user.show_online_status)

    # ---- persistence -------------------------------------------------------
    def test_saved_values_load_into_settings_page(self):
        """Opening Settings reflects the stored values (survives a refresh)."""
        self.user.show_online_status = False
        self.user.read_receipts = False
        self.user.profile_visibility = "nobody"
        self.user.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        html = response.content.decode()
        # Toggles rendered unchecked, select shows the stored option.
        self.assertNotIn('data-privacy-field="show_online_status" checked', html)
        self.assertNotIn('data-privacy-field="read_receipts" checked', html)
        self.assertIn('value="nobody" selected', html)

    def test_defaults_render_checked(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        html = response.content.decode()
        self.assertIn('data-privacy-field="show_online_status" checked', html)
        self.assertIn('data-privacy-field="read_receipts" checked', html)
        self.assertIn('value="everyone" selected', html)

    def test_setting_survives_logout_login(self):
        self.client.force_login(self.user)
        self._post("profile_visibility", "contacts")
        self.client.logout()
        # Log back in and reload the page: the stored value is still applied.
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        self.assertIn('value="contacts" selected', response.content.decode())
