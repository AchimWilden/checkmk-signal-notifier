import hmac
import json
import logging
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Settings:
    signal_api_url: str
    signal_number: str
    signal_recipients: tuple[str, ...]
    notify_token: str
    max_message_length: int = 4000
    max_body_bytes: int = 16384


def load_settings(environ=None):
    environ = os.environ if environ is None else environ
    api_url = environ.get("SIGNAL_API_URL", "http://signal-api:8080").rstrip("/")
    signal_number = environ.get("SIGNAL_NUMBER", "").strip()
    recipients = tuple(
        item.strip()
        for item in environ.get("SIGNAL_RECIPIENTS", "").split(",")
        if item.strip()
    )
    token = environ.get("NOTIFY_TOKEN", "")

    if not api_url.startswith(("http://", "https://")):
        raise ValueError("SIGNAL_API_URL must use http or https")
    if not signal_number:
        raise ValueError("SIGNAL_NUMBER is required")
    if not recipients:
        raise ValueError("SIGNAL_RECIPIENTS must contain at least one recipient")
    if len(token) < 32:
        raise ValueError("NOTIFY_TOKEN must be at least 32 characters")

    return Settings(api_url, signal_number, recipients, token)


def process_notification(authorization, body, settings, opener=urlopen):
    expected = f"Bearer {settings.notify_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        return 401, {"error": "unauthorized"}

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return 400, {"error": "request body must be JSON"}

    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str) or not message.strip():
        return 400, {"error": "message is required"}
    if len(message) > settings.max_message_length:
        return 413, {"error": "message is too long"}

    signal_payload = json.dumps({
        "message": message,
        "number": settings.signal_number,
        "recipients": list(settings.signal_recipients),
    }).encode("utf-8")
    request = Request(
        f"{settings.signal_api_url}/v2/send",
        data=signal_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with opener(request, timeout=20) as response:
            status = response.status
    except HTTPError as error:
        logging.warning("Signal API returned HTTP %s", error.code)
        return 502, {"error": "Signal API rejected the notification"}
    except (URLError, TimeoutError, OSError) as error:
        logging.warning("Signal API request failed: %s", error.__class__.__name__)
        return 502, {"error": "Signal API is unavailable"}

    if not 200 <= status < 300:
        logging.warning("Signal API returned HTTP %s", status)
        return 502, {"error": "Signal API rejected the notification"}
    return 200, {"result": "accepted"}


def signal_api_healthy(settings, opener=urlopen):
    request = Request(f"{settings.signal_api_url}/v1/configuration", method="GET")
    try:
        with opener(request, timeout=5) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def make_handler(settings):
    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "SignalNotifyRelay"

        def respond(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/healthz":
                self.respond(404, {"error": "not found"})
            elif signal_api_healthy(settings):
                self.respond(200, {"status": "ok"})
            else:
                self.respond(503, {"status": "unavailable"})

        def do_POST(self):
            if self.path != "/notify":
                self.respond(404, {"error": "not found"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.respond(400, {"error": "invalid content length"})
                return
            if content_length <= 0:
                self.respond(400, {"error": "request body is required"})
                return
            if content_length > settings.max_body_bytes:
                self.respond(413, {"error": "request body is too large"})
                return

            body = self.rfile.read(content_length)
            status, payload = process_notification(
                self.headers.get("Authorization"), body, settings
            )
            self.respond(status, payload)

    return RequestHandler


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), make_handler(settings))
    server.daemon_threads = True
    logging.info("Signal notification relay listening on port 8080")
    server.serve_forever(poll_interval=1)


if __name__ == "__main__":
    main()
