"""Template context processors shared across the project."""

from django.contrib.messages import get_messages


def django_messages_context(request):
    """Serialize Django flash messages into a JSON-safe list for toast.js.

    ``json_script`` only emits whole JSON values, so the list is built in
    Python and rendered with a single ``json_script`` tag in ``base.html``.
    """
    return {
        "django_messages": [
            {"text": m.message, "type": m.tags or "info"}
            for m in get_messages(request)
        ]
    }
