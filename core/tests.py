import json

from django.contrib import messages as messages_api
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase


class DjangoMessagesScriptTests(SimpleTestCase):
    """The base.html django-messages script must stay valid JSON.

    Historically the block built the array by slicing json_script output,
    which produced broken JSON and silently disabled every server flash
    message (toasts). It now renders one json_script tag from a Python-built
    list.
    """

    # The session backend writes to the default database.
    databases = {"default"}

    def _request_with_messages(self):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: HttpResponse()).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: HttpResponse()).process_request(request)
        return request

    def _render(self, request):
        return render_to_string("base.html", {}, request=request)

    def test_django_messages_script_is_valid_json(self):
        request = self._request_with_messages()
        messages_api.success(request, "Hello <b>world</b> & \"quotes\"")
        messages_api.error(request, "Something broke")

        html = self._render(request)
        marker = '<script id="django-messages" type="application/json">'
        self.assertIn(marker, html)
        start = html.index(marker) + len(marker)
        end = html.index("</script>", start)
        payload = json.loads(html[start:end])  # must not raise

        self.assertEqual(
            [m["text"] for m in payload],
            ["Hello <b>world</b> & \"quotes\"", "Something broke"],
        )
        self.assertEqual([m["type"] for m in payload], ["success", "error"])

    def test_no_messages_means_no_script(self):
        request = self._request_with_messages()
        self.assertNotIn("django-messages", self._render(request))

    def test_special_characters_survive_round_trip(self):
        request = self._request_with_messages()
        text = "</script><script>alert(1)</script> & <b>'x'</b>"
        messages_api.warning(request, text)

        html = self._render(request)
        marker = 'id="django-messages" type="application/json">'
        start = html.index(marker) + len(marker)
        end = html.index("</script>", start)
        payload = json.loads(html[start:end])
        self.assertEqual(payload[0]["text"], text)
        self.assertEqual(payload[0]["type"], "warning")
