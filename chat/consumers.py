import asyncio
import json
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model

from .broadcast import build_message_event, build_presence_event
from .models import MAX_MESSAGE_LENGTH, Block, Conversation, Message

# ---------------------------------------------------------------------------
# Presence tracking
#
# Presence is application-wide: a dedicated /ws/presence/ socket is kept open
# on every authenticated page (not just /chat), so navigating between pages
# never toggles a user Offline.
#
# A user is Online while at least one presence socket is open. They go
# Offline only when:
#   * the last socket closes and the grace period passes (covers quick page
#     transitions / reconnects),
#   * their heartbeat times out and the watchdog force-closes the socket,
#   * they log out (see accounts.views.LogoutView).
#
# The per-process dicts below are correct for the single-process dev server
# (InMemory channel layer). A multi-worker production deployment would need a
# shared store (e.g. Redis) keyed by user id.
# ---------------------------------------------------------------------------

# Seconds without any frame from a visible client before its socket is closed.
PRESENCE_HEARTBEAT_TIMEOUT = 60
# Seconds without any frame from a hidden (backgrounded) tab. Browsers throttle
# timers in hidden tabs, so pings arrive far less often; keep the window long.
PRESENCE_HIDDEN_TIMEOUT = 300
# How long to wait after the last socket closes before declaring Offline.
PRESENCE_GRACE_PERIOD = 45
# How often the per-connection watchdog wakes up.
PRESENCE_WATCHDOG_INTERVAL = 5

PRESENCE_CONNECTIONS = {}
_OFFLINE_TASKS = {}


class PresenceConsumer(AsyncWebsocketConsumer):
    """Global presence socket: one per authenticated browser, on every page.

    Keeps ``is_online`` accurate application-wide and pushes online/offline
    frames (and profile updates) to everyone through the "presence" group.
    """

    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return

        self._hidden = False
        self._force_offline = False
        self._registered = True
        self._last_activity = time.time()

        conns = PRESENCE_CONNECTIONS.setdefault(self.user.id, set())
        was_offline = not conns
        conns.add(self.channel_name)

        # Cancel any pending "mark offline" task so quick reconnects (page
        # navigation, socket recovery) never flip the user to Offline.
        pending = _OFFLINE_TASKS.pop(self.user.id, None)
        if pending is not None:
            pending.cancel()

        await self.channel_layer.group_add("presence", self.channel_name)
        await self.accept()

        if was_offline:
            await self._announce_online()

        self._watchdog = asyncio.get_running_loop().create_task(self._watchdog_loop())

    async def disconnect(self, close_code):
        if not getattr(self, "_registered", False):
            return
        if getattr(self, "_watchdog", None) is not None:
            self._watchdog.cancel()
        await self.channel_layer.group_discard("presence", self.channel_name)
        conns = PRESENCE_CONNECTIONS.get(self.user.id)
        if conns is not None:
            conns.discard(self.channel_name)
            if not conns:
                PRESENCE_CONNECTIONS.pop(self.user.id, None)
                if self._force_offline:
                    # The watchdog gave up on this client: it is really gone,
                    # so go Offline now rather than waiting out the grace.
                    await self._mark_offline_now()
                else:
                    task = asyncio.get_running_loop().create_task(
                        self._mark_offline_after_grace(self.user.id)
                    )
                    _OFFLINE_TASKS[self.user.id] = task

    async def receive(self, text_data=None):
        self._last_activity = time.time()
        try:
            payload = json.loads(text_data or "{}")
        except (TypeError, ValueError):
            return

        msg_type = payload.get("type")
        if msg_type == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))
        elif msg_type == "visibility":
            self._hidden = bool(payload.get("hidden"))

    async def chat_presence(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "presence",
                    "username": event["username"],
                    "online": event["online"],
                    "last_seen": event.get("last_seen"),
                }
            )
        )

    async def chat_profile_update(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "profile",
                    "user_id": event["user_id"],
                    "username": event["username"],
                    "name": event["name"],
                    "handle": event["handle"],
                    "avatar": event.get("avatar"),
                }
            )
        )

    async def chat_new_message_notification(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "new_message",
                    "sender": event["sender"],
                    "conversation_id": event["conversation_id"],
                }
            )
        )

    async def _watchdog_loop(self):
        # Close the socket when the client stops sending heartbeats (network
        # loss, hung connection). A hidden tab gets a much longer window.
        try:
            while True:
                await asyncio.sleep(PRESENCE_WATCHDOG_INTERVAL)
                window = PRESENCE_HIDDEN_TIMEOUT if self._hidden else PRESENCE_HEARTBEAT_TIMEOUT
                if time.time() - self._last_activity > window:
                    self._force_offline = True
                    # Flip Offline directly: the protocol teardown that would
                    # call disconnect() may never reach us for a dead link.
                    await self._mark_offline_now()
                    await self.close()
                    return
        except asyncio.CancelledError:
            return

    async def _announce_online(self):
        event = await self._set_online_flag(True)
        if event is None:
            return
        await self.channel_layer.group_send("presence", event)

    async def _mark_offline_now(self):
        event = await self._flip_offline(self.user.id)
        if event:
            await self.channel_layer.group_send("presence", event)

    async def _mark_offline_after_grace(self, user_id):
        try:
            await asyncio.sleep(PRESENCE_GRACE_PERIOD)
            if PRESENCE_CONNECTIONS.get(user_id):
                return  # a tab reconnected before the grace period ended
            event = await self._flip_offline(user_id)
            if event:
                await self.channel_layer.group_send("presence", event)
        except asyncio.CancelledError:
            return
        finally:
            _OFFLINE_TASKS.pop(user_id, None)

    @database_sync_to_async
    def _set_online_flag(self, online):
        user = get_user_model().objects.filter(pk=self.user.id).first()
        if user is None:
            return None
        user.is_online = online
        # Limit the save to these two fields so auto_now refreshes last_seen
        # without rewriting the whole user row on every connect/disconnect.
        user.save(update_fields=["is_online", "last_seen"])
        # build_presence_event masks online/last_seen when the user disabled
        # their online-status privacy setting, so the frame never leaks it.
        return build_presence_event(user, online)

    @database_sync_to_async
    def _flip_offline(self, user_id):
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None or not user.is_online:
            return None
        user.is_online = False
        user.save(update_fields=["is_online", "last_seen"])
        return build_presence_event(user, False)


class ChatConsumer(AsyncWebsocketConsumer):
    """Broadcasts messages and typing/read/block frames within a conversation
    group. Presence is handled application-wide by PresenceConsumer."""

    async def connect(self):
        self.user = self.scope["user"]
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.group_name = f"conversation_{self.conversation_id}"

        if not self.user.is_authenticated:
            await self.close()
            return

        if not await self._is_participant(self.conversation_id, self.user):
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None):
        try:
            payload = json.loads(text_data or "{}")
        except (TypeError, ValueError):
            return

        if payload.get("type") == "typing":
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "chat.typing",
                    "conversation_id": int(self.conversation_id),
                    "username": self.user.username,
                    "typing": bool(payload.get("value")),
                },
            )
            return

        content = str(payload.get("content", "")).strip()
        if not content or len(content) > MAX_MESSAGE_LENGTH:
            return

        # Privacy-focused blocking: a block in either direction freezes the
        # conversation. Messages are dropped entirely — no row is created, so
        # neither side can push new content into a blocked conversation.
        if await self._sender_blocked_receiver():
            return
        if await self._receiver_blocked_sender():
            return

        message = await self._save_message(self.conversation_id, self.user, content)

        await self.channel_layer.group_send(self.group_name, build_message_event(message))
        await self.channel_layer.group_send(
            "presence",
            {
                "type": "chat.new_message_notification",
                "sender": self.user.username,
                "conversation_id": self.conversation_id,
            },
        )

    async def chat_message(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat.message",
                    "id": event["id"],
                    "conversation_id": int(self.conversation_id),
                    "sender": event["sender"],
                    "content": event["content"],
                    "image": event.get("image"),
                    "created_at": event["created_at"],
                }
            )
        )

    async def chat_typing(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "typing",
                    "conversation_id": event["conversation_id"],
                    "username": event["username"],
                    "typing": event["typing"],
                }
            )
        )

    async def chat_read(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "read",
                    "conversation_id": event["conversation_id"],
                    "reader": event["reader"],
                }
            )
        )

    async def chat_block_change(self, event):
        """Forward a block/unblock change so both sides re-fetch and re-render."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "block_change",
                    "conversation_id": event["conversation_id"],
                }
            )
        )

    @database_sync_to_async
    def _is_participant(self, conversation_id, user):
        return Conversation.objects.filter(id=conversation_id, participants=user).exists()

    @database_sync_to_async
    def _sender_blocked_receiver(self):
        """True if ``self.user`` (the sender) has blocked the other participant."""
        conversation = Conversation.objects.filter(
            id=self.conversation_id, participants=self.user
        ).first()
        if conversation is None:
            return False
        other = conversation.participants.exclude(id=self.user.id).first()
        if other is None:
            return False
        return Block.objects.filter(blocker=self.user, blocked=other).exists()

    @database_sync_to_async
    def _receiver_blocked_sender(self):
        """True if the other participant has blocked ``self.user`` (the sender)."""
        conversation = Conversation.objects.filter(
            id=self.conversation_id, participants=self.user
        ).first()
        if conversation is None:
            return False
        other = conversation.participants.exclude(id=self.user.id).first()
        if other is None:
            return False
        return Block.objects.filter(blocker=other, blocked=self.user).exists()

    @database_sync_to_async
    def _save_message(self, conversation_id, user, content):
        conversation = Conversation.objects.get(id=conversation_id, participants=user)
        message = Message.objects.create(
            conversation=conversation,
            sender=user,
            content=content,
        )
        conversation.register_new_message(message)
        return message
