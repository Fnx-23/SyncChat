from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

MAX_MESSAGE_LENGTH = 4000


class Conversation(models.Model):
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="conversations",
    )
    # Users who muted this conversation (per-user, persisted).
    muted_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="muted_conversations",
        blank=True,
    )
    # Users who soft-deleted this conversation. The conversation and its
    # messages are kept; only the current user's view hides it. A new message
    # clears this for everyone so the chat reappears.
    deleted_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="deleted_conversations",
        blank=True,
    )
    # Deterministic "<min_user_id>:<max_user_id>" key for a 1:1 conversation.
    # The unique constraint prevents two users from accidentally owning two
    # chats with each other, even when "start" requests race. null marks
    # legacy conversations that predate pair keys (see migration 0006).
    pair_key = models.CharField(  # noqa: DJ001
        max_length=40, null=True, default=None, unique=True, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["-updated_at"], name="chat_conv_upd_desc_idx"),
        ]

    def __str__(self):
        names = ", ".join(p.username for p in self.participants.all()[:3])
        return f"Conversation ({names})"


class Block(models.Model):
    """A user blocking another user. Blocking is symmetric in effect: once a
    block exists in either direction, neither user can message the other."""

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["blocker", "blocked"], name="unique_blocker_blocked"
            ),
            models.CheckConstraint(
                condition=~models.Q(blocker=models.F("blocked")), name="block_not_self"
            ),
        ]

    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked.username}"


def blocks_exist(a, b):
    """True if a block exists between two users in either direction."""
    return Block.objects.filter(
        models.Q(blocker=a, blocked=b) | models.Q(blocker=b, blocked=a)
    ).exists()


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    content = models.TextField(blank=True, max_length=MAX_MESSAGE_LENGTH)
    image = models.ImageField(upload_to="chat_images/", blank=True, null=True)
    is_read = models.BooleanField(default=False)
    # True when the receiver had blocked the sender, so the message was stored
    # but never delivered (no websocket event, no unread increment, and it is
    # hidden from the receiver's history). From the sender's perspective the
    # message sent normally.
    blocked_delivery = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="chat_msg_conv_created_idx"),
            models.Index(fields=["conversation", "is_read"], name="chat_msg_conv_read_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(content__gt="") | models.Q(image__gt=""),
                name="chat_message_has_content_or_image",
            ),
        ]

    def __str__(self):
        return f"{self.sender.username}: {self.content[:40]}"

    def clean(self):
        super().clean()
        if not self.content.strip() and not self.image:
            raise ValidationError("A message must have text content or an image.")
