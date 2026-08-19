# SyncChat

Real-time chat application built with Django 6 + Channels (WebSockets).

## Tech stack

- **Backend** — Django 6.0, Channels 4, Daphne (ASGI server)
- **Frontend** — Vanilla HTML/CSS/JS served through Django templates
- **Auth** — Django's built-in session auth (login / signup / settings)
- **Realtime** — WebSocket consumers for live messaging
- **Tooling** — ruff (lint/format) via pre-commit

## Project structure

```
SyncChat/
├── manage.py
├── syncchat/        # project config (settings, urls, asgi, wsgi)
├── accounts/        # auth app (login, signup, profile settings)
├── chat/            # chat app (dashboard, models, consumers, routing)
├── core/            # home/root views, error handlers, shared image validation
├── templates/       # base.html, components/, errors/
├── static/          # css/, js/, images/
├── media/           # profile_pictures/, chat_images/
└── docs/            # ERD, wireframes, screenshots
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # optional: ruff + pre-commit

cp .env.example .env   # or edit the existing .env
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000 — unauthenticated visitors are sent to login;
signed-in users land on the dashboard at `/chat/`.

## Linting

```bash
ruff check .
ruff format --check .
pre-commit install   # runs ruff on every commit
```

## Testing

```bash
python manage.py test
```

Tests live in per-app packages (`chat/tests/`, `accounts/tests/`) split by
area: models, dashboard + paginated history, conversation start/search, HTTP
sending + upload validation, WebSocket consumers, and security/rate limits.

## Production notes

- **Redis** — set `REDIS_URL` in `.env` and install `channels-redis` +
  `django-redis` to swap the in-memory channel layer and the locmem rate-limit
  cache for shared Redis backends (required for multi-process deploys).
- **Static/media** — run `python manage.py collectstatic` and serve
  `STATIC_ROOT` (`staticfiles/`) and `MEDIA_ROOT` (`media/`) from your web
  server; Django does not serve these in production.
- **Secrets** — set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, and list your
  domains in `DJANGO_ALLOWED_HOSTS`. Add SSL redirect, secure cookies, and
  HSTS via the environment before deploying (see the security review).

## Notes

- The chat dashboard is wired to the backend: the conversation list,
  message history, unread counts and profile details are rendered from
  the database, sending flows through the WebSocket consumer, and
  opening a conversation marks incoming messages as read.
- The dashboard payload caps message history to the latest 50 per
  conversation; older messages are fetched on demand from
  `GET /chat/conversations/<pk>/history/?before=<message_id>` when the
  thread is scrolled to the top.
- 1:1 conversations are deduplicated with a unique `pair_key`
  (`<min-user-id>:<max-user-id>`), so racing "start" requests cannot
  create duplicate chats.
- The "New conversation" button in the sidebar searches for other users
  and opens (or reuses) a 1:1 conversation with them.
- WebSocket presence: connecting/disconnecting marks `is_online` (and
  `last_seen`) and broadcasts online/offline events to all connected
  users, which the dashboard reflects in the chat header live.
- WebSocket handshakes are validated against `ALLOWED_HOSTS` (Origin
  check) to prevent cross-site WebSocket hijacking.
- Request throttling (django-ratelimit) limits login/signup, message
  sending, conversation starts, and searches. Limits use the dedicated
  `ratelimit` cache — swap the locmem backend for a shared one such as
  Redis so limits apply across processes in production.
- Uploaded images (messages and avatars) are capped by file size, format,
  and dimensions. Logout is POST-only (CSRF-protected form) so pages
  cannot force a user out.
