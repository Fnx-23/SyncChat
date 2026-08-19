from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class BackfillDisplayNameTests(TransactionTestCase):
    """Data migration 0004: copy first_name (the old signup full-name storage)
    into display_name so existing users' real names show up in conversation
    headers and Settings."""

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_backfills_display_name_from_first_name(self):
        migrate_from = [("accounts", "0003_user_theme")]
        migrate_to = [("accounts", "0004_backfill_display_name")]
        apps = self._migrate(migrate_from)

        User = apps.get_model("accounts", "User")
        legacy = User.objects.create_user("legacy", password="pw12345")
        legacy.first_name = "Legacy User"
        legacy.save(update_fields=["first_name"])

        # A user who already has a display_name must not be overwritten, and a
        # user with no first_name must be left alone.
        already_set = User.objects.create_user("named", password="pw12345")
        already_set.first_name = "Legacy Name"
        already_set.display_name = "Preferred Name"
        already_set.save(update_fields=["first_name", "display_name"])

        User.objects.create_user("blank", password="pw12345")

        apps = self._migrate(migrate_to)
        User = apps.get_model("accounts", "User")
        self.assertEqual(User.objects.get(username="legacy").display_name, "Legacy User")
        self.assertEqual(User.objects.get(username="named").display_name, "Preferred Name")
        self.assertEqual(User.objects.get(username="blank").display_name, "")
