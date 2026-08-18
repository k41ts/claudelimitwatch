"""Loopback redirect listener for the browser login flow.

The OAuth server accepts any ``http://localhost:<port>/callback`` redirect (the
CLI itself binds an ephemeral port on 127.0.0.1), so the browser can hand the
authorization code straight back to the app -- no copy-paste.
"""

from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

CALLBACK_PATH = "/callback"

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
 body {{ background:#18181b; color:#f4f4f5; font:16px/1.6 "Segoe UI",system-ui,sans-serif;
        display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
 .card {{ text-align:center; max-width:28rem; padding:2rem; }}
 h1 {{ font-size:1.25rem; margin:0 0 .5rem; color:{color}; }}
 p {{ color:#a1a1aa; margin:0; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{body}</p></div></body></html>
"""


@dataclass(frozen=True)
class CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


class _Handler(BaseHTTPRequestHandler):
    server_version = "climitwatch"

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        error = params.get("error", [None])[0]
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if error or not code:
            self._respond(
                400,
                "Login failed",
                error or "No authorization code was returned.",
                "#f87171",
            )
            result = CallbackResult(error=error or "No authorization code returned")
        else:
            self._respond(
                200,
                "You're signed in",
                "Claude Limit Watcher has the account now. You can close this tab.",
                "#4ade80",
            )
            result = CallbackResult(code=code, state=state)

        self.server.result = result  # type: ignore[attr-defined]
        self.server.received.set()  # type: ignore[attr-defined]

    def _respond(self, status: int, title: str, body: str, color: str) -> None:
        page = _PAGE.format(title=title, body=body, color=color).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("callback server: " + fmt, *args)


class _DualStackServer(HTTPServer):
    """Listen on ::1 *and* 127.0.0.1.

    Windows browsers usually resolve ``localhost`` to ``::1`` first; an
    IPv4-only listener makes every login wait out a connection failure before
    the browser retries.
    """

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _make_server(port: int) -> HTTPServer:
    try:
        return _DualStackServer(("::", port), _Handler)
    except OSError as exc:
        log.debug("IPv6 listener unavailable (%s); falling back to IPv4", exc)
        return HTTPServer(("127.0.0.1", port), _Handler)


class CallbackServer:
    """One-shot loopback listener.

    Usage::

        with CallbackServer() as server:
            webbrowser.open(authorize_url(pkce, redirect_uri=server.redirect_uri))
            result = server.wait(timeout=300)
    """

    def __init__(self, port: int = 0) -> None:
        self._server = _make_server(port)
        self._server.received = threading.Event()  # type: ignore[attr-defined]
        self._server.result = CallbackResult(error="No response")  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self.port}{CALLBACK_PATH}"

    def wait(self, timeout: float = 300.0) -> CallbackResult:
        if not self._server.received.wait(timeout):  # type: ignore[attr-defined]
            return CallbackResult(error="Timed out waiting for the browser")
        return self._server.result  # type: ignore[attr-defined]

    def cancel(self) -> None:
        """Unblock a pending :meth:`wait` (used when the user hits Cancel)."""
        self._server.result = CallbackResult(error="Login cancelled")  # type: ignore[attr-defined]
        self._server.received.set()  # type: ignore[attr-defined]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "CallbackServer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
