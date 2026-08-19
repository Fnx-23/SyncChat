from django.core.exceptions import ValidationError
from django.db import IntegrityError

from ..models import Block, Conversation, Message, blocks_exist
from .base import ChatTestCase


class ModelTests(ChatTestCase):
    def test_message_created_in_conversation(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content="Hello",
        )
        self.assertEqual(conversation.messages.count(), 1)
        self.assertEqual(Message.objects.first().sender, self.user)

    def test_message_requires_content_or_image(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        message = Message(conversation=conversation, sender=self.user)
        with self.assertRaises(ValidationError):
            message.full_clean()

        with self.assertRaises(IntegrityError):
            Message.objects.create(conversation=conversation, sender=self.user)

    def test_conversation_ordering_is_most_recent_first(self):
        conversation = Conversation.objects.create()
        older = Conversation.objects.create()
        self.assertEqual(
            list(Conversation.objects.values_list("id", flat=True)),
            [older.id, conversation.id],
        )

    def test_message_ordering_is_chronological(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        first = Message.objects.create(conversation=conversation, sender=self.user, content="first")
        second = Message.objects.create(
            conversation=conversation, sender=self.user, content="second"
        )
        self.assertEqual(
            list(conversation.messages.values_list("id", flat=True)),
            [first.id, second.id],
        )

    def test_pair_key_uniqueness_is_enforced(self):
        Conversation.objects.create(pair_key="1:2")
        with self.assertRaises(IntegrityError):
            Conversation.objects.create(pair_key="1:2")

    def test_multiple_unkeyed_conversations_allowed(self):
        # Legacy conversations without a pair key remain valid (NULL is not
        # constrained as unique), which lets pre-migration data keep working.
        Conversation.objects.create()
        Conversation.objects.create()
        self.assertEqual(Conversation.objects.count(), 2)

    def test_block_unique_constraint_is_enforced(self):
        Block.objects.create(blocker=self.user, blocked=self.other)
        with self.assertRaises(IntegrityError):
            Block.objects.create(blocker=self.user, blocked=self.other)

    def test_block_rejects_self_block(self):
        with self.assertRaises(IntegrityError):
            Block.objects.create(blocker=self.user, blocked=self.user)

    def test_blocks_exist_checks_either_direction(self):
        Block.objects.create(blocker=self.user, blocked=self.other)
        self.assertTrue(blocks_exist(self.user, self.other))
        # Direction is irrelevant — blocking is symmetric in effect.
        self.assertTrue(blocks_exist(self.other, self.user))
        self.assertFalse(blocks_exist(self.user, self.user))
