from django.db import migrations


def backfill_pair_keys(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    seen = set()
    for conversation in Conversation.objects.all().order_by("id"):
        user_ids = list(
            conversation.participants.values_list("id", flat=True).order_by("id")
        )
        if len(user_ids) == 2:
            key = f"{user_ids[0]}:{user_ids[1]}"
            if key in seen:
                # Legacy duplicate pair: leave the key unset so the unique
                # constraint still holds; the app finds the canonical one.
                conversation.pair_key = None
            else:
                conversation.pair_key = key
                seen.add(key)
        conversation.save(update_fields=["pair_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_conversation_pair_key"),
    ]

    operations = [
        migrations.RunPython(backfill_pair_keys, migrations.RunPython.noop),
    ]
