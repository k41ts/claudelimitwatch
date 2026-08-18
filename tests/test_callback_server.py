import threading
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from climitwatch.auth.callback_server import CallbackServer
from climitwatch.auth.oauth import authorize_url, new_pkce
from climitwatch.config import MANUAL_REDIRECT_URL


@pytest.fixture()
def server():
    srv = CallbackServer()
    yield srv
    srv.close()


def test_redirect_uri_points_at_the_bound_port(server):
    assert server.port > 0
    assert server.redirect_uri == f"http://localhost:{server.port}/callback"


def test_receives_code_and_state(server):
    result_box = {}

    def wait():
        result_box["result"] = server.wait(timeout=5)

    waiter = threading.Thread(target=wait)
    waiter.start()

    response = httpx.get(f"{server.redirect_uri}?code=abc123&state=xyz", timeout=5)
    waiter.join(5)

    assert response.status_code == 200
    assert "signed in" in response.text.lower()
    result = result_box["result"]
    assert result.code == "abc123"
    assert result.state == "xyz"
    assert result.error is None


def test_reports_provider_error(server):
    result_box = {}
    waiter = threading.Thread(target=lambda: result_box.update(result=server.wait(timeout=5)))
    waiter.start()

    response = httpx.get(f"{server.redirect_uri}?error=access_denied", timeout=5)
    waiter.join(5)

    assert response.status_code == 400
    assert result_box["result"].error == "access_denied"
    assert result_box["result"].code is None


def test_cancel_unblocks_wait(server):
    result_box = {}
    waiter = threading.Thread(target=lambda: result_box.update(result=server.wait(timeout=5)))
    waiter.start()
    server.cancel()
    waiter.join(5)
    assert "cancelled" in (result_box["result"].error or "").lower()


def test_unknown_path_is_ignored(server):
    assert httpx.get(f"http://localhost:{server.port}/favicon.ico", timeout=5).status_code == 404


def test_authorize_url_uses_the_loopback_redirect(server):
    pkce = new_pkce()
    params = parse_qs(urlparse(authorize_url(pkce, redirect_uri=server.redirect_uri)).query)
    assert params["redirect_uri"] == [server.redirect_uri]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [pkce.challenge]
    assert params["state"] == [pkce.state]


def test_authorize_url_defaults_to_manual_redirect():
    params = parse_qs(urlparse(authorize_url(new_pkce())).query)
    assert params["redirect_uri"] == [MANUAL_REDIRECT_URL]
