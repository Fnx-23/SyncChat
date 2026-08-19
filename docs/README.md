# Docs

Design and project documentation for SyncChat.

- `ERD.png` — entity-relationship diagram for the data model.
  Current model: `accounts.User` (bio, avatar, is_online, last_seen);
  `chat.Conversation` (M:N `accounts.User`) (1:N) `chat.Message`.
- `wireframes.png` — initial UI wireframes.
- `screenshots/` — screenshots of the running app (login, signup,
  dashboard, settings).
