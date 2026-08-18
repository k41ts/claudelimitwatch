"""The account Claude Code itself is logged into.

Tokens live in ``~/.claude/.credentials.json`` and are shared with the CLI, so
every write here is atomic and every refresh is preceded (and followed) by a
re-read: if Claude Code rotated the token first, we adopt its token instead of
clobbering it.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import CLAUDE_CONFIG_PATH, CREDENTIALS_PATH
from ..config import atomic_write
from .oauth import AuthError, TokenSet, refresh_tokens

log = logging.getLogger(__name__)

OAUTH_KEY = "claudeAiOauth"


@dataclass(frozen=True)
class ClaudeAccountInfo:
    account_uuid: str | None = None
    email: str | None = None
    display_name: str | None = None
    plan: str | None = None
    organization_name: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.email or (self.account_uuid or "Claude Code")[:8]


def read_account_info(path: Path = CLAUDE_CONFIG_PATH) -> ClaudeAccountInfo:
    """Identity of the currently logged-in CLI account (no tokens involved)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ClaudeAccountInfo()
    account = raw.get("oauthAccount") if isinstance(raw, dict) else None
    if not isinstance(account, dict):
        return ClaudeAccountInfo()
    return ClaudeAccountInfo(
        account_uuid=account.get("accountUuid"),
        email=account.get("emailAddress"),
        display_name=account.get("displayName"),
        plan=account.get("organizationType") or account.get("subscriptionType"),
        organization_name=account.get("organizationName"),
    )


class ClaudeCodeCredentials:
    """Read (and, unless read-only, refresh) the CLI credential file."""

    def __init__(self, path: Path = CREDENTIALS_PATH, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        self._backed_up = False
        #: Set when we refreshed but declined to write because the CLI won the race.
        self._detached: TokenSet | None = None

    # -- reading ----------------------------------------------------------

    def _read_raw(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("Cannot read %s: %s", self.path.name, exc)
            return None
        return raw if isinstance(raw, dict) else None

    def load(self) -> TokenSet | None:
        raw = self._read_raw()
        if not raw:
            return None
        block = raw.get(OAUTH_KEY)
        if not isinstance(block, dict):
            return None
        access = block.get("accessToken")
        if not isinstance(access, str) or not access:
            return None
        scopes = block.get("scopes")
        expires_at = block.get("expiresAt")
        refresh_expires = block.get("refreshTokenExpiresAt")
        return TokenSet(
            access_token=access,
            refresh_token=block.get("refreshToken") if isinstance(block.get("refreshToken"), str) else None,
            expires_at_ms=int(expires_at) if isinstance(expires_at, (int, float)) else 0,
            refresh_expires_at_ms=int(refresh_expires) if isinstance(refresh_expires, (int, float)) else None,
            scopes=tuple(scopes) if isinstance(scopes, list) else (),
            subscription_type=block.get("subscriptionType") if isinstance(block.get("subscriptionType"), str) else None,
        )

    @property
    def available(self) -> bool:
        return self.path.exists()

    # -- writing ----------------------------------------------------------

    def _backup_once(self) -> None:
        if self._backed_up:
            return
        backup = self.path.with_suffix(self.path.suffix + ".climitwatch.bak")
        try:
            if not backup.exists():
                shutil.copy2(self.path, backup)
        except OSError as exc:
            log.warning("Could not create credential backup: %s", exc)
        self._backed_up = True

    def _write(self, tokens: TokenSet) -> bool:
        """Merge fresh tokens into the file, preserving every other field."""
        raw = self._read_raw()
        if raw is None:
            return False
        block = dict(raw.get(OAUTH_KEY) or {})
        block["accessToken"] = tokens.access_token
        if tokens.refresh_token:
            block["refreshToken"] = tokens.refresh_token
        block["expiresAt"] = tokens.expires_at_ms
        if tokens.refresh_expires_at_ms:
            block["refreshTokenExpiresAt"] = tokens.refresh_expires_at_ms
        if tokens.scopes:
            block["scopes"] = list(tokens.scopes)
        raw[OAUTH_KEY] = block

        self._backup_once()
        try:
            atomic_write(self.path, json.dumps(raw, indent=2))
        except OSError as exc:
            log.warning("Could not write credentials: %s", exc)
            return False
        return True

    # -- refresh ----------------------------------------------------------

    def ensure_fresh(self, client: httpx.Client | None = None) -> TokenSet:
        """Return a usable token, refreshing it if it is about to expire.

        Race protocol with the CLI, which refreshes the same file:
        re-read immediately before refreshing (the CLI may have just rotated
        the token, in which case we simply adopt it), and re-read again
        afterwards -- if the file moved on while our request was in flight we
        keep our own tokens in memory instead of overwriting the CLI's.
        """
        tokens = self.load()
        if tokens is None:
            raise AuthError("Claude Code is not logged in on this machine", needs_login=True)

        if self._detached is not None and not self._detached.needs_refresh():
            return self._detached

        if not tokens.needs_refresh():
            self._detached = None
            return tokens

        # The CLI may have refreshed a moment ago.
        latest = self.load()
        if latest and latest.access_token != tokens.access_token and not latest.needs_refresh():
            self._detached = None
            return latest
        tokens = latest or tokens

        if self.read_only:
            if tokens.expired:
                raise AuthError(
                    "Access token expired and read-only mode is on - open Claude Code to refresh it"
                )
            return tokens

        fresh = refresh_tokens(tokens, client=client)

        after = self.load()
        if after and after.refresh_token != tokens.refresh_token:
            # Claude Code rotated the pair while we were refreshing. Leave the
            # file to it and keep our own tokens for this process only.
            log.info("Credential file changed during refresh; keeping tokens in memory")
            self._detached = fresh
            return fresh

        if self._write(fresh):
            self._detached = None
        else:
            self._detached = fresh
        return fresh
