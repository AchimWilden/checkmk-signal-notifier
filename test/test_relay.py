import json
import unittest
from urllib.error import HTTPError

from relay.app import Settings, process_notification, signal_api_healthy


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            signal_api_url="http://signal-api:8080",
            signal_number="+491111111111",
            signal_recipients=("+492222222222", "+493333333333"),
            notify_token="a" * 64,
        )

    def test_rejects_missing_or_wrong_bearer_token(self):
        called = False

        def opener(*args, **kwargs):
            nonlocal called
            called = True
            return FakeResponse(201)

        status, _ = process_notification(
            "Bearer wrong", b'{"message":"alert"}', self.settings, opener
        )

        self.assertEqual(status, 401)
        self.assertFalse(called)

    def test_rejects_invalid_or_empty_message(self):
        for body in (b"not json", b'{"message":"  "}', b'{"message":3}'):
            with self.subTest(body=body):
                status, _ = process_notification(
                    f"Bearer {self.settings.notify_token}", body, self.settings
                )
                self.assertEqual(status, 400)

    def test_forwards_message_to_signal_api(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeResponse(201)

        status, result = process_notification(
            f"Bearer {self.settings.notify_token}",
            json.dumps({"message": "Checkmk CRIT: disk"}).encode(),
            self.settings,
            opener,
        )

        self.assertEqual(status, 200)
        self.assertEqual(result, {"result": "accepted"})
        self.assertEqual(captured["url"], "http://signal-api:8080/v2/send")
        self.assertEqual(captured["payload"], {
            "message": "Checkmk CRIT: disk",
            "number": "+491111111111",
            "recipients": ["+492222222222", "+493333333333"],
        })
        self.assertEqual(captured["timeout"], 20)

    def test_maps_upstream_http_errors_to_gateway_error(self):
        def opener(*args, **kwargs):
            raise HTTPError("http://signal-api:8080/v2/send", 503, "unavailable", {}, None)

        status, result = process_notification(
            f"Bearer {self.settings.notify_token}",
            b'{"message":"alert"}',
            self.settings,
            opener,
        )

        self.assertEqual(status, 502)
        self.assertIn("error", result)

    def test_health_probe_requires_successful_signal_api_response(self):
        self.assertTrue(signal_api_healthy(self.settings, lambda *args, **kwargs: FakeResponse(200)))
        self.assertFalse(signal_api_healthy(self.settings, lambda *args, **kwargs: FakeResponse(503)))


if __name__ == "__main__":
    unittest.main()
