"""OAuth pieces shared by both account sources.

Mirrors what the Claude Code CLI does: PKCE authorization-code flow against
platform.claude.com with the CLI client id, and refresh-token rotation on the
same endpoint. Tokens live for about an hour, so refresh is the normal path.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import (
    AUTHORIZE_URL,
    MANUAL_REDIRECT_URL,
    OAUTH_CLIENT_ID,
    OAUTH_SCOPES,
    TOKEN_URL,
    USER_AGENT,
)

#: Refresh when the access token has less than this many seconds left.
REFRESH_MARGIN_SECONDS = 300


class AuthError(Exception):
    """Refresh or exchange failed."""

    def __init__(self, message: str, *, needs_login: bool = False) -> None:
        super().__init__(message)
        self.needs_login = needs_login


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_at_ms: int = 0
    refresh_expires_at_ms: int | None = None
    scopes: tuple[str, ...] = ()
    subscription_type: str | None = None

    @property
    def seconds_left(self) -> float:
        return self.expires_at_ms / 1000.0 - time.time()

    @property
    def expired(self) -> bool:
        return self.seconds_left <= 0

    def needs_refresh(self, margin: int = REFRESH_MARGIN_SECONDS) -> bool:
        return self.seconds_left <= margin

    def redacted(self) -> str:
        tail = self.access_token[-6:] if self.access_token else "?"
        return f"TokenSet(...{tail}, {int(self.seconds_left)}s left)"


@dataclass(frozen=True)
class PkceChallenge:
    verifier: str
    challenge: str
    state: str


def new_pkce() -> PkceChallenge:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    state = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    return PkceChallenge(verifier=verifier, challenge=challenge, state=state)


def authorize_url(
    pkce: PkceChallenge,
    scopes: list[str] | None = None,
    redirect_uri: str | None = None,
) -> str:
    """Browser URL for the login flow.

    With ``redirect_uri`` pointing at a local ``CallbackServer`` the browser
    hands the code straight back to the app. Without it, the user lands on the
    platform.claude.com page that shows a ``code#state`` string to paste in.
    """
    params = {
        "code": "true",
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri or MANUAL_REDIRECT_URL,
        "scope": " ".join(scopes or OAUTH_SCOPES),
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        "state": pkce.state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def split_pasted_code(pasted: str) -> tuple[str, str | None]:
    """The callback page hands out ``<code>#<state>``."""
    text = pasted.strip()
    if "#" in text:
        code, _, state = text.partition("#")
        return code.strip(), state.strip() or None
    return text, None


def _token_set_from_response(data: dict[str, Any], fallback_refresh: str | None) -> TokenSet:
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        raise AuthError("Token response had no access_token")
    expires_in = data.get("expires_in")
    expires_at_ms = int(
        (time.time() + (float(expires_in) if isinstance(expires_in, (int, float)) else 3600)) * 1000
    )
    refresh_expires_in = data.get("refresh_token_expires_in")
    refresh_expires_at_ms = (
        int((time.time() + float(refresh_expires_in)) * 1000)
        if isinstance(refresh_expires_in, (int, float))
        else None
    )
    scope = data.get("scope")
    scopes = tuple(scope.split()) if isinstance(scope, str) else ()
    refresh = data.get("refresh_token")
    return TokenSet(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else fallback_refresh,
        expires_at_ms=expires_at_ms,
        refresh_expires_at_ms=refresh_expires_at_ms,
        scopes=scopes,
    )


def _post_token(body: dict[str, Any], client: httpx.Client | None = None) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
    try:
        response = client.post(TOKEN_URL, json=body, headers={"Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        raise AuthError(f"Token request failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        detail = ""
        try:
            payload = response.json()
            detail = str(payload.get("error") or payload.get("error_description") or "")
        except ValueError:
            detail = response.text[:200]
        needs_login = response.status_code in (400, 401) and "invalid_grant" in detail
        if needs_login and body.get("grant_type") == "authorization_code":
            raise AuthError(
                "That login code was already used or has expired — start the login again",
                needs_login=True,
            )
        raise AuthError(
            f"Token endpoint returned {response.status_code}: {detail or 'no detail'}",
            needs_login=needs_login,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise AuthError("Token endpoint returned non-JSON body") from exc


def refresh_tokens(tokens: TokenSet, client: httpx.Client | None = None) -> TokenSet:
    """Exchange the refresh token for a new access token (rotating the pair)."""
    if not tokens.refresh_token:
        raise AuthError("No refresh token stored", needs_login=True)
    data = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        },
        client=client,
    )
    fresh = _token_set_from_response(data, fallback_refresh=tokens.refresh_token)
    return replace(fresh, subscription_type=tokens.subscription_type)


def exchange_code(
    code: str,
    pkce: PkceChallenge,
    state: str | None = None,
    client: httpx.Client | None = None,
    redirect_uri: str | None = None,
) -> TokenSet:
    """Complete the login flow.

    ``redirect_uri`` must match the one used to build the authorize URL.
    """
    data = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri or MANUAL_REDIRECT_URL,
            "client_id": OAUTH_CLIENT_ID,
            "code_verifier": pkce.verifier,
            "state": state or pkce.state,
        },
        client=client,
    )
    return _token_set_from_response(data, fallback_refresh=None)
