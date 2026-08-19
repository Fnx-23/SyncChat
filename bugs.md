# SyncChat — Production-Readiness Audit Report

Audit date: 2026-08-05 · Stack: Django 6.0.7, Channels 4/Daphne, SQLite (live), custom `accounts.User`

Full test suite: **177 tests, all passing**. `python manage.py check` passes (2 silenced ratelimit notes). Ruff clean on all changed files (only 2 pre-existing `E501` long lines remain in `chat/views.py:277,280`, not introduced here).

---

## Fixed Bugs

### Bug #1 — Avatar upload never saved (settings form was GET)
- **Symptom:** picking a new avatar showed a preview then reverted; nothing was persisted.
- **Cause:** `settings.html` `<form id="profile-form">` had no `method="post"` → browser sent GET, file never reached the view.
- **Fix:** form is now `method="post" enctype="multipart/form-data"` (settings.html:92).
- **Verified:** `test_settings_profile_form_is_post_multipart`; all settings tests pass.

### Bug #2 — Conversation history disappearing after refresh
- **Symptom:** after a block/unblock round-trip the full history was permanently hidden from the blocked user (one message was orphan-flagged `blocked_delivery=True`); also the sidebar order was stale after a refresh.
- **Cause (two parts):**
  1. `UnblockUserView` cleared blocks but left `blocked_delivery=True` rows hidden from the receiver.
  2. The WebSocket send path (`ChatConsumer._save_message`) never bumped `conversation.updated_at`, unlike the HTTP path, so the sidebar re-ordered incorrectly after refresh.
- **Fix:** unblock now clears `blocked_delivery` for the affected rows; the WS save path mirrors the HTTP bump. New migration `chat/migrations/0011_clear_orphaned_blocked_delivery.py` cleaned the live DB (0 orphaned rows remaining).
- **Verified:** `test_unblock_reveals_blocked_delivery_messages`, `test_receive_bumps_conversation_updated_at`, `chat/tests/test_migrations.py`; live end-to-end round-trip on :8765.

### Bug #3 — Server flash messages (toasts) never displayed — **new this audit**
- **Symptom:** "Welcome back, X!" / "Your profile has been updated" messages never appeared as toasts.
- **Cause:** `base.html` built the `django-messages` JSON by slicing `json_script` output:
  `{{ message|escapejs|safe|json_script:"msg"|slice:"1:-1" }}` rendered `script id="msg" type="application/json">"…"</script` — **malformed JSON**, so `toast.js`'s `JSON.parse` threw and every flash message was silently dropped (verified by rendering the template).
- **Fix:** new context processor `core/context_processors.py::django_messages_context` builds a JSON-safe list of `{text, type}`; `base.html` renders it with a single `json_script` tag (correctly HTML/JS-escaped).
- **Verified:** `core/tests.py` (valid JSON round-trip incl. `<script>`/quote payloads, no-message case); live login → dashboard renders `[{"text": "Welcome back, …", "type": "success"}]` and consumes it on the next request.

### Bug #4 — Message times shown in UTC & date separators always "Today" — **new this audit**
- **Symptom:** every bubble's timestamp read as UTC (server `TIME_ZONE`), and chat date separators never split — all messages labelled "Today".
- **Cause:** `_message_payload` sent only a pre-formatted `time` label (server timezone) and **no raw timestamp**; `dashboard.js` used `m.timestamp || Date.now()`, so every message fell back to "now" → one separator, no splits.
- **Fix:** `_message_payload` now includes `created_at` (ISO); `dashboard.js` formats bubble times and separators client-side in the browser's timezone (`fmtTime`/`fmtListTime`), with `m.time` as fallback for optimistic sends. Sidebar "time" column now uses `u.ts` client-side too.
- **Verified:** `test_dashboard_exposes_conversations_data` asserts `created_at` on every message; live dashboard payload has `created_at` on all 20 messages of the test conversation.

### Bug #5 — `userId` leaked for "blocked-me" conversations (privacy) — **new this audit**
- **Symptom:** when the other participant had blocked you, the conversation payload anonymized name/avatar/username but still exposed the blocker's numeric `userId`, contradicting the documented privacy model ("identity … never sent to this client").
- **Fix:** `_conversation_payload` sets `"userId": None` when `blocked_me`; `dashboard.js` also excludes `blockedMe` conversations from the New-Chat modal's "Recent" list (they can't be used to start a chat anyway).
- **Verified:** `test_blocked_user_payload_is_anonymized` / `test_blocked_user_detail_payload_is_anonymized` now assert `userId is None` and the blocker's id never appears in the payload.

---

## Remaining Issues

1. **Dead controls in Settings.** The Privacy toggles (Online Status / Read Receipts / Profile Visibility), the Notifications toggles (Desktop / Message / Sound), and the Danger Zone **"Delete Account"** button have no JS handlers and no backend endpoints — they are decorative and do nothing (settings.html:269–342, 375–381). Either wire them to the model (add `User` fields + endpoints) or remove them. Recommend starting with "Delete Account" (safety-critical), which needs confirmation + cascade handling.
2. **Soft privacy leak in `BlockStatusView`** (`chat/views.py:407`). A blocked user can still call `/chat/users/<id>/block-status/` and receive `blockedMe: true`, confirming they were blocked (the UI intentionally hides this, Instagram-style). Consider returning an anonymous/unavailable response for that case.
3. **No real-time delivery for non-active conversations.** The WebSocket subscribes only to the currently-open conversation (`websocket.js connect(id)`), so incoming messages to *other* conversations don't bump the sidebar unread badge until reload/select. Working as designed, but it is a real-time gap vs. typical messengers.
4. **N+1 block queries in `_conversation_payload`** (`chat/views.py:209-210`): two `Block.exists()` queries per conversation on the dashboard. Fine at small scale; pass the already-computed blocker/blocked id sets into the payload builder for large accounts.
5. **Production hardening not wired (all are env-driven; default = dev):**
   - `SECRET_KEY` falls back to `django-insecure-dev-only-change-me` (settings.py:23).
   - `DEBUG` defaults to `True`; `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` / HSTS / `SECURE_SSL_REDIRECT` unset → 5 `check --deploy` warnings.
   - `syncchat/urls.py:16-23` serves `/static/` and `/media/` via `django.views.static.serve` unconditionally — fine for dev, but production should serve media/static from nginx/CDN/S3 (and the `serve` route should be removed or DEBUG-gated).
   - No CSP / SRI; Google Fonts loaded from `fonts.googleapis.com` (external dependency + privacy).
   - Ratelimit keys use `ip`/`user` with no reverse-proxy / `X-Forwarded-For` trust config for production.
6. **Multi-tab presence flicker.** Each tab opens its own WebSocket and toggles `is_online`; closing one tab while another is open can briefly flip the user to offline. Needs connection ref-counting for a real fix.
7. Minor: `BlockedUsersView` (`chat/views.py:434`) reads `block.created_at` behind a redundant `hasattr` guard — the field exists on every row, so `blockedAt` is always populated; the guard can be simplified away.

---

## Improvements Added This Audit

- `core/context_processors.py` — flash-message serialization (Bug #3).
- Per-message `created_at` in every payload + client-side local-timezone rendering (Bug #4) — also fixes chat date separators.
- `userId` hidden for blocked-me conversations + filtered from Recent modal (Bug #5).
- New tests: `core/tests.py` (3), plus strengthened assertions in `test_dashboard.py` / `test_conversations.py`.
- Live server on :8765 restarted and re-verified after all backend changes.

---

## Follow-up Audit (same day): Real-time Profile Sync + Display-Name Fix

Three backend/frontend synchronization bugs were reported and fixed.

### Bug A — Avatar/full-name changes never reached other clients in real time
- **Symptom:** after uploading an avatar or editing the full name, only the editing client's page updated; everyone else kept the old avatar/name until refresh. The sidebar footer even rendered a placeholder (hashed-color initials) instead of the real avatar.
- **Cause:** no profile-change event existed. `chat/broadcast.py` only built `chat.message` frames; `ChatConsumer` had no profile handler; the settings views saved without broadcasting.
- **Fix:**
  - `chat/broadcast.py` gains `build_profile_update_event(user)` + `broadcast_profile_update(user)`, which group-sends a `chat.profile_update` frame to the **`presence` group** (joined by every authenticated WebSocket, so *all* open clients — including clients viewing other conversations — get the update instantly).
  - `ChatConsumer.chat_profile_update` forwards it as a `{"type": "profile", user_id, username, name, handle, avatar}` frame.
  - `accounts/views.py` fires the broadcast from both `settings_view` (full profile/avatar POST) and `settings_autosave` (per-field autosave).
  - Dashboard payload now carries `me_profile` (real avatar/name); `dashboard.js` renders the sidebar footer avatar from it (`renderOwnAvatar`) and the new `syncchat:profile` handler updates the `users[]` cache and re-renders the conversation list, chat header and details panel in place. `websocket.js` dispatches `syncchat:profile`.
  - Privacy preserved: blocked-me conversations stay anonymized (no identity is ever sent, so no profile update can leak); the frontend ignores profile frames for `blockedMe` users and identity is matched by `user_id`/`username` from authenticated state.
- **Verified:** `test_profile_update_broadcasts_profile_change`, `test_autosave_broadcasts_profile_change`, `test_profile_update_frame_forwards_to_client`, `test_dashboard_exposes_me_profile`; live E2E on :8765 — test3 changes display name, test2's open WebSocket receives the `profile` frame in <1s.

### Bug B — Signup "Full Name" never appeared in Settings or headers
- **Symptom:** the full name entered at signup was empty in Settings and absent from conversation headers.
- **Cause:** `SignUpForm.save()` stored the value in `user.first_name`, but the rest of the app (Settings form, every identity payload, `User.__str__`) reads `display_name` — the two fields never met.
- **Fix:** `SignUpForm.save()` now stores `full_name` into `display_name` (forms.py:31). New data migration `accounts/migrations/0004_backfill_display_name.py` copies `first_name` → `display_name` for existing accounts (applied to the live DB: `test3` backfilled).
- **Verified:** `test_signup_creates_user_and_logs_in` now asserts `display_name == "Alice Example"`; new `test_signup_full_name_appears_in_settings`; `accounts/tests/test_migrations.py` proves the backfill (respecting already-set `display_name`).

### Bug C — Conversation headers showed @username instead of the full name
- **Symptom:** name-rendering used the username everywhere, so a contact with a set full name still appeared as `@username`.
- **Cause:** the payloads built name from the wrong source and none exposed the display name separately from the handle.
- **Fix:** `_participant_payload` (used by conversations, search, blocked-users, details) now returns `name = display_name or username` and `handle = "@username"` — full name is primary, username is the secondary handle everywhere (conversation list, chat header, profile sidebar, search results, new-chat modal). `me_profile` follows the same rule.
- **Verified:** `test_dashboard_uses_display_name_when_set` (`name: "Robert Bobson"`, `handle: "@bob"`); live dashboard shows `test3` → `name: "test 3"`, `handle: "@test3"`.

### New/changed tests (162 → 169)
- `accounts/tests/test_auth.py` — signup stores `display_name`; name appears on the settings page.
- `accounts/tests/test_settings.py` — profile save and autosave both broadcast `chat.profile_update` to `presence`.
- `accounts/tests/test_migrations.py` — `0004` backfill correctness.
- `chat/tests/test_dashboard.py` — `me_profile` present; display-name precedence.
- `chat/tests/test_consumers.py` — `chat.profile_update` frame forwarded as `profile`.

---

| Area | Status |
|------|--------|
| Backend correctness (auth, chat, block privacy, history) | ~95% — all known functional bugs fixed; remaining items are architectural/scale |
| Frontend / UI | ~90% — core flows verified; settings stubs + multi-tab presence remain |
| Security | ~75% — solid CSRF/XSS/upload/WS-Origin handling; production TLS/cookie/HSTS config is unset by design (env-gated) |
| Production readiness | ~70% — needs env config (secret, secure cookies, HSTS, DB) and nginx/CDN media serving; code itself is deploy-clean |
| Testing | ~95% — 162 tests passing; the remaining coverage gap is the dead settings controls |

**Overall: the application is functionally sound and safe for a dev/local deployment. The single most valuable next step is production configuration (secret, TLS/cookie flags, DB, media serving), followed by implementing or removing the stub settings controls.**

---

## Bug #4 — Presence went Offline on every page change (application-wide fix) — **new this session**

- **Symptom:** a user navigating from `/chat` to `/settings` (or any authenticated page) instantly showed as Offline to others; returning to `/chat` flipped them back Online. Presence tracked the page, not the person.
- **Cause:** presence was welded to `ChatConsumer`, and the chat socket only exists on `/chat` (`websocket.js` is loaded only by `dashboard.html`). Leaving the page closed the socket → `ChatConsumer.disconnect` marked the user Offline; returning re-opened it → Online again.
- **Fix — dedicated application-wide presence socket:**
  - New `PresenceConsumer` at `/ws/presence/` (`chat/consumers.py`), loaded on *every* authenticated page via `base.html` (`{% if user.is_authenticated %}` include of `static/js/presence.js`). `ChatConsumer` no longer touches `is_online`/`last_seen` at all — messaging/typing/read/block behaviour is unchanged (chat socket smoke-tested live).
  - Per-user connection refcount (`PRESENCE_CONNECTIONS`) so multiple tabs / navigation restarts don't double-toggle Online.
  - `PRESENCE_GRACE_PERIOD = 45`s: after the last socket closes a deadline task waits; any reconnect cancels it, so page navigation and quick reconnects never flip Offline. `_OFFLINE_TASKS[user_id]` tracks the in-flight task.
  - Heartbeat watchdog: the client pings every ~20s; the server force-closes (and marks Offline immediately) a socket silent for `PRESENCE_HEARTBEAT_TIMEOUT = 60`s foreground / `PRESENCE_HIDDEN_TIMEOUT = 300`s when the tab reports `visibility: hidden` (browsers throttle timers in background tabs).
  - `LogoutView` calls sync `broadcast_presence(user, False)` (`chat/broadcast.py::broadcast_presence`) so logout flips Offline instantly — the browser closes the socket so the grace period can't be waited out. The `chat.presence`/`chat.profile_update` frames still flow over the **`presence` group** with the same wire shape, so the profile-broadcast fix from the last audit is preserved (the profile handler moved verbatim into `PresenceConsumer`).
- **Verified:** 48 consumer/auth tests including new `PresenceConsumerTests` (grace keeps online across reconnect, no offline blip to peers, multi-tab, ping/pong, heartbeat timeout → offline, hidden-tab longer window, anonymous rejected); new `test_logout_marks_user_offline`; full suite 177 tests passing; live E2E on :8765 — test2 sees **no** Offline frame while test3 closes and re-opens the socket within the grace window, then test2 receives test3's Offline frame immediately on logout.

### New/changed tests (169 → 177)
- `chat/tests/test_consumers.py` — presence tests moved to `/ws/presence/`; chat-socket tests no longer drain a fake "own presence" frame; new `PresenceConsumerTests` (grace/reconnect/heartbeat/watchdog/anonymous).
- `accounts/tests/test_auth.py` — `test_logout_marks_user_offline` (logout persists `is_online = False`).

| Area | Status |
|------|--------|
| Backend correctness (auth, chat, block privacy, history, presence) | ~95% — presence is now application-wide; remaining items are architectural/scale |
| Frontend / UI | ~92% — core flows + global presence verified; stub settings controls remain |
| Security | ~75% — solid CSRF/XSS/upload/WS-Origin handling; production TLS/cookie/HSTS config is unset by design (env-gated) |
| Production readiness | ~70% — needs env config (secret, secure cookies, HSTS, DB) and nginx/CDN media serving; presence state is in-process, so multi-worker deploys need a Redis-backed store keyed by user id |
| Testing | ~95% — 177 tests passing; the remaining coverage gap is the dead settings controls |
