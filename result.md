# Regression Test Result

## Problem 1
- Area: Real-time / Desktop Notifications
- Severity: MEDIUM
- File: static/js/dashboard.js:1431
- Problem: `notifyIncoming(data)` is called from the `syncchat:new_message` handler with data that only contains `sender` and `conversation_id` — it lacks `content` and `image`. Inside `notifyIncoming` (line 693), `const body = data.image ? "Shared a photo" : data.content` evaluates to `undefined`, so the desktop notification body displays the literal string "undefined".
- Steps to reproduce: Open SyncChat in two browsers (A and B). With A viewing a conversation with B, have B send a message to A from a *different* conversation while A's tab is hidden. A receives a desktop notification with body "undefined".
- Expected: Desktop notification body shows the message text or "New message".
- Actual: Desktop notification body shows "undefined".
- Likely cause: The `new_message` event broadcast via the presence group is a lightweight notification (only `sender` + `conversation_id`), but `notifyIncoming()` was written for the full `syncchat:message` event which includes `content` and `image`.
- Affected files/components: `static/js/dashboard.js` (line 1431, `notifyIncoming` call), `chat/consumers.py` (lines 141-150, `chat_new_message_notification` handler sends partial data).

## Problem 2
- Area: Real-time / Unread Badges
- Severity: LOW
- File: static/js/dashboard.js:1420
- Problem: `users.find((x) => x.id === convId)` uses strict equality (`===`). When a message is sent via WebSocket, `conversation_id` arrives as a string (from the URL regex capture in `chat/routing.py:7`), but `x.id` is a number (from the server-rendered JSON). The strict comparison `number === string` is always `false`, so the fast-path badge update (lines 1421-1427) is never taken for WS-sent messages. The code always falls through to `refreshConversation(convId)` (line 1429), requiring an extra network round-trip to update the badge.
- Steps to reproduce: Open the dashboard. Have another user send a message to a non-active conversation via WebSocket. Observe that the badge updates only after a brief network delay (visible in DevTools Network tab as a `/chat/conversations/<id>/detail/` request) rather than instantly.
- Expected: Badge updates instantly via the in-memory `users` array without a network request.
- Actual: Badge updates after a network round-trip because the `users.find` never matches.
- Likely cause: The WebSocket URL pattern (`re_path(r"^ws/chat/(?P<conversation_id>\d+)/$")`) captures `conversation_id` as a string, but the HTTP path sends it as an integer (`<int:pk>`). The `users.find` comparison doesn't account for this type difference.
- Affected files/components: `static/js/dashboard.js` (line 1420), `chat/routing.py` (line 7), `chat/consumers.py` (line 222, 277).
