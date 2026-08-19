import asyncio
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from ..models import Block, Conversation, Message
from ..routing import websocket_urlpatterns
from .base import ChatTestCase

app = URLRouter(websocket_urlpatterns)


async def _async_connect(user, conversation_id):
    """Connect a user to a conversation room; returns (communicator, accepted)."""
    communicator = WebsocketCommunicator(app, f"/ws/chat/{conversation_id}/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    return communicator, connected


async def _async_presence_connect(user):
    """Connect a user to the application-wide presence socket."""
    communicator = WebsocketCommunicator(app, "/ws/presence/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    return communicator, connected


class ConsumerTests(ChatTestCase):
    """WebSocket behaviour, driven in a single event loop per test.

    Each test sets up its data synchronously, then runs the async body once
    through async_to_sync so the communicator and the consumer share one loop.
    """

    def test_connect_rejects_anonymous(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            communicator = WebsocketCommunicator(app, f"/ws/chat/{conversation.id}/")
            communicator.scope["user"] = AnonymousUser()
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(body)()

    def test_connect_rejects_non_participant(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        outsider = get_user_model().objects.create_user("carol", password="pw12345")

        async def body():
            communicator, connected = await _async_connect(outsider, conversation.id)
            self.assertFalse(connected)
            await communicator.disconnect()

        async_to_sync(body)()

    def test_connect_marks_user_online(self):
        async def body():
            communicator, connected = await _async_presence_connect(self.user)
            self.assertTrue(connected)
            await database_sync_to_async(self.user.refresh_from_db)()
            self.assertTrue(self.user.is_online)
            await communicator.disconnect()
            await asyncio.sleep(0.1)
            await database_sync_to_async(self.user.refresh_from_db)()
            self.assertFalse(self.user.is_online)

        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 0):
            async_to_sync(body)()

    def test_connect_presence_broadcast(self):
        async def body():
            communicator, connected = await _async_presence_connect(self.user)
            self.assertTrue(connected)
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "presence")
            self.assertEqual(event["username"], "alice")
            self.assertTrue(event["online"])
            await communicator.disconnect()

        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 0):
            async_to_sync(body)()

    def test_receive_persists_and_broadcasts_message(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "Hello via websocket"})
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "chat.message")
            self.assertEqual(event["sender"], "alice")
            self.assertEqual(event["content"], "Hello via websocket")
            self.assertIsNone(event["image"])
            await communicator.disconnect()

        async_to_sync(body)()
        self.assertEqual(Message.objects.filter(conversation=conversation).count(), 1)

    def test_receive_bumps_conversation_updated_at(self):
        # A message sent over the WebSocket must bump updated_at (the sidebar
        # sorts by it), matching the HTTP send path.
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        before = conversation.updated_at

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "bump updated_at"})
            await communicator.receive_json_from()
            await communicator.disconnect()

        async_to_sync(body)()
        message = Message.objects.get(conversation=conversation)
        conversation.refresh_from_db()
        self.assertEqual(conversation.updated_at, message.created_at)
        self.assertGreaterEqual(conversation.updated_at, before)

    def test_receive_stores_sender_authoritatively(self):
        # The sender comes from the authenticated scope, never the payload.
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "spoofed sender"})
            await communicator.receive_json_from()
            await communicator.disconnect()

        async_to_sync(body)()
        message = Message.objects.get(conversation=conversation)
        self.assertEqual(message.sender, self.user)

    def test_receive_ignores_empty_content(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "   "})
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        async_to_sync(body)()
        self.assertEqual(Message.objects.count(), 0)

    def test_receive_ignores_oversized_content(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "x" * 4001})
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        async_to_sync(body)()
        self.assertEqual(Message.objects.count(), 0)

    def test_receive_ignores_invalid_json(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_to(text_data="this is not json")
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        async_to_sync(body)()
        self.assertEqual(Message.objects.count(), 0)

    def test_typing_event(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"type": "typing", "value": True})
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "typing")
            self.assertEqual(event["username"], "alice")
            self.assertTrue(event["typing"])
            await communicator.disconnect()

        async_to_sync(body)()

    def test_presence_broadcast_on_disconnect(self):
        async def body():
            alice, _ = await _async_presence_connect(self.user)
            await alice.receive_json_from()  # alice's own online event
            bob, connected = await _async_presence_connect(self.other)
            self.assertTrue(connected)
            await bob.receive_json_from()  # bob's own online event
            await alice.disconnect()
            event = await asyncio.wait_for(bob.receive_json_from(), timeout=1)
            self.assertEqual(event["type"], "presence")
            self.assertEqual(event["username"], "alice")
            self.assertFalse(event["online"])
            await bob.disconnect()

        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 0):
            async_to_sync(body)()

    def test_origin_validation_rejects_foreign_origin(self):
        validated = AllowedHostsOriginValidator(app)

        async def body():
            communicator = WebsocketCommunicator(validated, "/ws/chat/1/")
            communicator.scope["headers"] = [(b"origin", b"http://evil.example")]
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(body)()

    def test_receive_drops_message_when_blocked(self):
        # A blocked user's message is silently dropped: no broadcast, no row.
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Block.objects.create(blocker=self.user, blocked=self.other)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "blocked message"})
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(communicator.receive_json_from(), timeout=0.2)
            await communicator.disconnect()

        async_to_sync(body)()
        self.assertEqual(Message.objects.count(), 0)

    def test_receive_drops_message_when_receiver_blocked_sender(self):
        # The other participant blocked the sender. The send is dropped too —
        # no broadcast, no row — so the conversation is frozen in both
        # directions.
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        Block.objects.create(blocker=self.other, blocked=self.user)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "blocked message"})
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(communicator.receive_json_from(), timeout=0.2)
            await communicator.disconnect()

        async_to_sync(body)()
        self.assertEqual(Message.objects.count(), 0)

    def test_block_change_frame_forwards_to_client(self):
        # The block/unblock views broadcast a chat.block_change frame to the
        # conversation group; the consumer forwards it as a block_change
        # message so the frontend can re-fetch the conversation.
        from channels.layers import get_channel_layer

        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)

        async def body():
            layer = get_channel_layer()
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await layer.group_send(
                f"conversation_{conversation.id}",
                {"type": "chat.block_change", "conversation_id": conversation.id},
            )
            frame = await asyncio.wait_for(communicator.receive_json_from(), timeout=1)
            self.assertEqual(frame["type"], "block_change")
            self.assertEqual(frame["conversation_id"], conversation.id)
            await communicator.disconnect()

        async_to_sync(body)()

    def test_profile_update_frame_forwards_to_client(self):
        # The settings views broadcast a chat.profile_update frame to the
        # presence group; the consumer forwards it as a "profile" message so
        # the frontend can update avatars and names in real time.
        from channels.layers import get_channel_layer

        async def body():
            layer = get_channel_layer()
            communicator, connected = await _async_presence_connect(self.user)
            self.assertTrue(connected)
            await communicator.receive_json_from()  # own online event
            await layer.group_send(
                "presence",
                {
                    "type": "chat.profile_update",
                    "user_id": self.other.id,
                    "username": "bob",
                    "name": "Robert Bobson",
                    "handle": "@bob",
                    "avatar": None,
                },
            )
            frame = await asyncio.wait_for(communicator.receive_json_from(), timeout=1)
            self.assertEqual(frame["type"], "profile")
            self.assertEqual(frame["user_id"], self.other.id)
            self.assertEqual(frame["username"], "bob")
            self.assertEqual(frame["name"], "Robert Bobson")
            self.assertEqual(frame["handle"], "@bob")
            await communicator.disconnect()

        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 0):
            async_to_sync(body)()

    def test_send_clears_soft_deletion(self):
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, self.other)
        conversation.deleted_by.add(self.user)

        async def body():
            communicator, connected = await _async_connect(self.user, conversation.id)
            self.assertTrue(connected)
            await communicator.send_json_to({"content": "back again"})
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "chat.message")
            await communicator.disconnect()

        async_to_sync(body)()
        self.assertFalse(conversation.deleted_by.exists())


class PresenceConsumerTests(ChatTestCase):
    """Application-wide presence socket: grace period, reconnect, heartbeat."""

    def tearDown(self):
        # Cancel in-flight "mark offline" tasks so none of them fires inside a
        # later test (the asgiref background loop outlives each test method).
        from .. import consumers as consumers_module

        async def cleanup():
            for task in list(consumers_module._OFFLINE_TASKS.values()):
                task.cancel()
            consumers_module._OFFLINE_TASKS.clear()
            consumers_module.PRESENCE_CONNECTIONS.clear()

        async_to_sync(cleanup)()

    def test_presence_rejects_anonymous(self):
        async def body():
            communicator = WebsocketCommunicator(app, "/ws/presence/")
            communicator.scope["user"] = AnonymousUser()
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(body)()

    def test_reconnect_within_grace_no_offline_flip(self):
        # Navigating between pages closes one socket and opens another quickly.
        # The grace period must absorb the gap: a peer sees no Offline frame.
        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 1):
            async def body():
                alice1, _ = await _async_presence_connect(self.user)
                await alice1.receive_json_from()  # alice online
                bob, _ = await _async_presence_connect(self.other)
                await bob.receive_json_from()  # bob online
                await alice1.disconnect()
                await asyncio.sleep(0.2)
                # No offline broadcast reached bob during the grace window.
                self.assertTrue(await bob.receive_nothing())
                alice2, _ = await _async_presence_connect(self.user)
                await alice2.receive_json_from()  # alice re-announced online
                await alice2.disconnect()
                await bob.disconnect()

            async_to_sync(body)()

    def test_reconnect_within_grace_keeps_user_online(self):
        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 1):
            async def body():
                first, connected = await _async_presence_connect(self.user)
                self.assertTrue(connected)
                await first.receive_json_from()
                await first.disconnect()
                # Grace period is still running: the user remains online.
                await database_sync_to_async(self.user.refresh_from_db)()
                self.assertTrue(self.user.is_online)
                await asyncio.sleep(0.2)
                second, connected = await _async_presence_connect(self.user)
                self.assertTrue(connected)
                await database_sync_to_async(self.user.refresh_from_db)()
                self.assertTrue(self.user.is_online)
                await second.disconnect()

            async_to_sync(body)()

    def test_multiple_tabs_keep_user_online(self):
        # Closing one tab must not take the user offline while another stays.
        # Only the first tab announces Online; the second is silent.
        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 0.5):
            async def body():
                tab1, connected = await _async_presence_connect(self.user)
                self.assertTrue(connected)
                await tab1.receive_json_from()  # alice online (first tab)
                tab2, connected = await _async_presence_connect(self.user)
                self.assertTrue(connected)
                await tab1.disconnect()
                await asyncio.sleep(0.1)
                await database_sync_to_async(self.user.refresh_from_db)()
                self.assertTrue(self.user.is_online)
                await tab2.disconnect()

            async_to_sync(body)()

    def test_ping_receives_pong(self):
        async def body():
            communicator, connected = await _async_presence_connect(self.user)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await communicator.send_json_to({"type": "ping"})
            frame = await asyncio.wait_for(communicator.receive_json_from(), timeout=1)
            self.assertEqual(frame["type"], "pong")
            await communicator.disconnect()

        with patch("chat.consumers.PRESENCE_GRACE_PERIOD", 0):
            async_to_sync(body)()

    def test_heartbeat_timeout_marks_offline(self):
        # A client that stops sending heartbeats is force-closed: offline now.
        with patch("chat.consumers.PRESENCE_WATCHDOG_INTERVAL", 0.05), patch(
            "chat.consumers.PRESENCE_HEARTBEAT_TIMEOUT", 0.1
        ):
            async def body():
                communicator, connected = await _async_presence_connect(self.user)
                self.assertTrue(connected)
                await communicator.receive_json_from()
                await asyncio.sleep(0.4)
                await database_sync_to_async(self.user.refresh_from_db)()
                self.assertFalse(self.user.is_online)

            async_to_sync(body)()

    def test_hidden_tab_gets_longer_heartbeat_window(self):
        # Browsers throttle timers in hidden tabs, so the hidden window must be
        # longer than the foreground one.
        with patch("chat.consumers.PRESENCE_WATCHDOG_INTERVAL", 0.05), patch(
            "chat.consumers.PRESENCE_HEARTBEAT_TIMEOUT", 0.1
        ), patch("chat.consumers.PRESENCE_HIDDEN_TIMEOUT", 0.5):
            async def body():
                communicator, connected = await _async_presence_connect(self.user)
                self.assertTrue(connected)
                await communicator.receive_json_from()
                await communicator.send_json_to({"type": "visibility", "hidden": True})
                # Past the foreground window but inside the hidden one: alive.
                await asyncio.sleep(0.3)
                await database_sync_to_async(self.user.refresh_from_db)()
                self.assertTrue(self.user.is_online)
                # Past the hidden window too: offline.
                await asyncio.sleep(0.4)
                await database_sync_to_async(self.user.refresh_from_db)()
                self.assertFalse(self.user.is_online)

            async_to_sync(body)()
