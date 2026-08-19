"""Theme preference resolution, shared by templates and views.

Resolution priority for a logged-in user:
  1. The user's saved DB preference (``theme`` field) — one of
     ``'light'``, ``'dark'``, ``'system'``.
  2. Fall back to ``'system'`` (the model default).

``'system'`` resolves to either ``'light'`` or ``'dark'`` based on the request
``prefers-color-scheme`` header when available, otherwise defaults to light.

The context processor exposes two values to every template:
  ``theme_pref``     — the raw preference ('light'|'dark'|'system')
  ``theme_resolved`` — the concrete value to apply ('light'|'dark'), so the
                      inline no-flash script can set ``data-theme`` without
                      waiting for matchMedia.
"""

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_SYSTEM = "system"

VALID_THEMES = (THEME_LIGHT, THEME_DARK, THEME_SYSTEM)


def _prefers_dark(request):
    """Return True if the client signals a dark OS preference via the
    ``Sec-CH-Prefers-Color-Scheme`` or ``prefers-color-scheme`` header.

    Not all browsers send these headers, so an unknown preference falls back
    to light (also the model default). This is only needed to resolve
    ``'system'`` on the server; JS handles live OS changes after load.
    """
    if request is None:
        return False
    headers = (request.headers or {})
    value = headers.get("Sec-CH-Prefers-Color-Scheme") or headers.get("prefers-color-scheme")
    if not value:
        return False
    # The header is either a bare token ('dark') or a quality list ('dark;...').
    return value.split(",")[0].split(";")[0].strip().lower() == THEME_DARK


def resolve_theme(user):
    """Return ``(pref, resolved)`` for a user (or anonymous) without a request.

    For anonymous users there is no DB preference, so ``pref`` is empty and
    the inline script relies on localStorage / OS preference instead.
    """
    pref = ""
    if user is not None and getattr(user, "is_authenticated", False):
        pref = getattr(user, "theme", "") or THEME_SYSTEM
        if pref not in VALID_THEMES:
            pref = THEME_SYSTEM
    return pref, ""  # no request -> can't resolve 'system' server-side


def request_theme(request):
    """Return ``(pref, resolved)`` for a request, resolving 'system' if possible."""
    pref, _ = resolve_theme(getattr(request, "user", None))
    if pref == THEME_SYSTEM:
        resolved = THEME_DARK if _prefers_dark(request) else THEME_LIGHT
    else:
        resolved = pref or ""
    return pref, resolved


def theme_context(request):
    """Context processor: expose theme_pref + theme_resolved to all templates."""
    pref, resolved = request_theme(request)
    return {"theme_pref": pref, "theme_resolved": resolved}
