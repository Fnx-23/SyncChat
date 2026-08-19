from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ClearOrphanedBlockedDeliveryTests(TransactionTestCase):
    # MigrationExecutor needs to run real schema operations, which SQLite cannot
    # do inside a transaction, so this uses TransactionTestCase.
    """Data migration 0011: reveal blocked_delivery flags whose block is gone."""

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_clears_orphaned_flags_keeps_active_block(self):
        # accounts/0003 adds User.theme, which the DB already has; pin it so the
        # historical model matches the live schema during the chat rewind.
        migrate_from = [
            ("chat", "0010_message_blocked_delivery"),
            ("accounts", "0003_user_theme"),
        ]
        migrate_to = [("chat", "0011_clear_orphaned_blocked_delivery")]
        apps = self._migrate(migrate_from)

        Conversation = apps.get_model("chat", "Conversation")
        Message = apps.get_model("chat", "Message")
        Block = apps.get_model("chat", "Block")
        User = apps.get_model("accounts", "User")

        # A pair with no block: the flag is orphaned and must be cleared.
        carol = User.objects.create_user("carol", password="pw12345")
        dave = User.objects.create_user("dave", password="pw12345")
        plain = Conversation.objects.create()
        plain.participants.add(carol, dave)
        orphaned = Message.objects.create(
            conversation=plain,
            sender=carol,
            content="no block anymore",
            blocked_delivery=True,
        )

        # A pair where the receiver still blocks the sender: flag stays hidden.
        alice = User.objects.create_user("alice", password="pw12345")
        bob = User.objects.create_user("bob", password="pw12345")
        blocked_conv = Conversation.objects.create()
        blocked_conv.participants.add(alice, bob)
        Block.objects.create(blocker=bob, blocked=alice)
        still_hidden = Message.objects.create(
            conversation=blocked_conv,
            sender=alice,
            content="still blocked",
            blocked_delivery=True,
        )

        apps = self._migrate(migrate_to)
        Message = apps.get_model("chat", "Message")
        self.assertFalse(
            Message.objects.get(pk=orphaned.pk).blocked_delivery,
            msg=f"rows={list(Message.objects.values_list('id','content','blocked_delivery'))}",
        )
        self.assertTrue(Message.objects.get(pk=still_hidden.pk).blocked_delivery)
