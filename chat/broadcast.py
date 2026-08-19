"""Builders for the frames broadcast to the conversation group.

Both the HTTP send view and the WebSocket consumer construct the same
"chat.message" frame; keeping the builder here means the two paths can
never drift apart.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def build_message_event(message):
    """Return the channel-layer event for a stored message."""
    return {
        "type": "chat.message",
        "id": message.id,
        "sender": message.sender.username,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "image": message.image.url if message.image else None,
    }


def build_profile_update_event(user):
    """Return the channel-layer event announcing a user's profile changed."""
    return {
        "type": "chat.profile_update",
        "user_id": user.id,
        "username": user.username,
        "name": user.display_name or user.username,
        "handle": f"@{user.username}",
        "avatar": user.avatar.url if user.avatar else None,
    }


def broadcast_profile_update(user):
    """Announce ``user``'s profile change (name/avatar) to every client.

    The "presence" group is a global room joined by every authenticated
    WebSocket, so a name/avatar update reaches all open clients instantly.
    Clients match the frame to conversations by user id / username;
    conversations whose participant blocked the client are anonymized (null
    user id, empty username), so they never receive an identity update.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        "presence",
        build_profile_update_event(user),
    )


def build_presence_event(user, online):
    """Return the channel-layer event announcing a presence change.

    Honours the user's ``show_online_status`` privacy setting: when it is
    disabled the user is always announced as offline with no last-seen
    timestamp, so other clients can never infer their activity.
    """
    show = getattr(user, "show_online_status", True)
    return {
        "type": "chat.presence",
        "username": user.username,
        "online": online if show else False,
        "last_seen": (
            user.last_seen.isoformat() if user.last_seen else None
        ) if show else None,
    }


def build_new_message_notification_event(sender_username, conversation_id):
    """Return a lightweight channel-layer event for a new message notification."""
    return {
        "type": "chat.new_message_notification",
        "sender": sender_username,
        "conversation_id": conversation_id,
    }


def broadcast_new_message_notification(user, conversation_id):
    """Send a new-message notification to every connected client via the presence group.

    Clients that have the conversation open already receive the full message
    through their conversation WebSocket. This notification targets the global
    presence group so clients with other conversations open (or no conversation
    open) can update unread badges and trigger desktop notifications.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        "presence",
        build_new_message_notification_event(user.username, conversation_id),
    )


def broadcast_presence(user, online):
    """Persist ``user.is_online`` and announce it to every connected client.

    Used by the synchronous logout view; the WebSocket consumer keeps its own
    async path so it never needs the async_to_sync bridge.
    """
    user.is_online = online
    user.save(update_fields=["is_online", "last_seen"])
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        "presence",
        build_presence_event(user, online),
    )
