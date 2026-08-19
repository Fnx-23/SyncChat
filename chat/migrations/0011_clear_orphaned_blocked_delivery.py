# Data migration: reveal messages flagged blocked_delivery when the block that
# hid them no longer exists.
#
# blocked_delivery=True means "the receiver had blocked the sender when the
# message was stored". Such messages are hidden from the receiver indefinitely;
# once the receiver unblocks the sender, they should be visible again. Older
# data contains orphaned flags from blocks that were later removed, so clear
# every flag whose blocker/blocked relationship no longer exists.

from django.db import migrations


def clear_orphaned_blocked_delivery(apps, schema_editor):
    Message = apps.get_model("chat", "Message")
    Block = apps.get_model("chat", "Block")
    for message in Message.objects.filter(blocked_delivery=True):
        sender_id = message.sender_id
        receiver_ids = message.conversation.participants.exclude(id=sender_id).values_list(
            "id", flat=True
        )
        for receiver_id in receiver_ids:
            if not Block.objects.filter(
                blocker_id=receiver_id, blocked_id=sender_id
            ).exists():
                Message.objects.filter(pk=message.pk).update(blocked_delivery=False)
                break


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_message_blocked_delivery"),
    ]

    operations = [
        migrations.RunPython(clear_orphaned_blocked_delivery, migrations.RunPython.noop),
    ]
