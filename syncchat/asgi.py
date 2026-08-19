"""
ASGI config for the SyncChat project.

Serves HTTP over Django and WebSockets through Channels.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "syncchat.settings")

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from chat.routing import websocket_urlpatterns  # noqa: E402


def get_websocket_application():
    """Build the authenticated WebSocket router (validated by Origin check)."""
    return AuthMiddlewareStack(URLRouter(websocket_urlpatterns))


# Reject WebSocket handshakes whose Origin is not one of ALLOWED_HOSTS.
# Without this, a third-party page could open a socket in the victim's
# browser and ride their session cookie (cross-site WebSocket hijacking).
application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(get_websocket_application()),
    }
)
