import json
import time

import pytest

from climitwatch.auth import cc_credentials as cc
from climitwatch.auth.cc_credentials import ClaudeCodeCredentials
from climitwatch.auth.oauth import AuthError, TokenSet


def write_creds(path, access="tok-a", refresh="ref-a", ttl_seconds=3600, extra=None):
    payload = {
        "claudeAiOauth": {
            "accessToken": access,
            "refreshToken": refresh,
            "expiresAt": int((time.time() + ttl_seconds) * 1000),
            "scopes": ["user:profile", "user:inference"],
            "subscriptionType": "pro",
        },
        "trustedDeviceToken": "device-token",
        "mcpOAuth": {"supabase|abc": {"accessToken": "mcp-token"}},
    }
    if extra:
        payload["claudeAiOauth"].update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


@pytest.fixture()
def creds_file(tmp_path):
    path = tmp_path / ".credentials.json"
    write_creds(path)
    return path


def test_load_reads_token_block(creds_file):
    tokens = ClaudeCodeCredentials(creds_file).load()
    assert tokens is not None
    assert tokens.access_token == "tok-a"
    assert tokens.refresh_token == "ref-a"
    assert tokens.subscription_type == "pro"
    assert not tokens.needs_refresh()


def test_missing_file_is_not_fatal(tmp_path):
    creds = ClaudeCodeCredentials(tmp_path / "nope.json")
    assert creds.load() is None
    assert not creds.available
    with pytest.raises(AuthError):
        creds.ensure_fresh()


def test_fresh_token_is_returned_untouched(creds_file):
    before = creds_file.read_text(encoding="utf-8")
    tokens = ClaudeCodeCredentials(creds_file).ensure_fresh()
    assert tokens.access_token == "tok-a"
    assert creds_file.read_text(encoding="utf-8") == before


def test_refresh_writes_back_and_preserves_other_fields(creds_file, monkeypatch):
    write_creds(creds_file, ttl_seconds=60)

    def fake_refresh(tokens, client=None):
        assert tokens.refresh_token == "ref-a"
        return TokenSet(
            access_token="tok-b",
            refresh_token="ref-b",
            expires_at_ms=int((time.time() + 3600) * 1000),
            scopes=("user:profile",),
        )

    monkeypatch.setattr(cc, "refresh_tokens", fake_refresh)
    creds = ClaudeCodeCredentials(creds_file)
    tokens = creds.ensure_fresh()

    assert tokens.access_token == "tok-b"
    saved = json.loads(creds_file.read_text(encoding="utf-8"))
    assert saved["claudeAiOauth"]["accessToken"] == "tok-b"
    assert saved["claudeAiOauth"]["refreshToken"] == "ref-b"
    assert saved["claudeAiOauth"]["subscriptionType"] == "pro"
    assert saved["trustedDeviceToken"] == "device-token"
    assert saved["mcpOAuth"]["supabase|abc"]["accessToken"] == "mcp-token"
    assert creds_file.with_suffix(creds_file.suffix + ".climitwatch.bak").exists()


def test_adopts_cli_token_when_cli_refreshed_first(creds_file, monkeypatch):
    write_creds(creds_file, ttl_seconds=60)

    def boom(tokens, client=None):  # pragma: no cover - must not run
        raise AssertionError("should not refresh; the CLI already did")

    monkeypatch.setattr(cc, "refresh_tokens", boom)
    creds = ClaudeCodeCredentials(creds_file)
    # Simulate Claude Code rotating the pair between our read and our refresh.
    original_load = creds.load
    calls = {"n": 0}

    def load_with_cli_race():
        calls["n"] += 1
        if calls["n"] == 2:
            write_creds(creds_file, access="cli-tok", refresh="cli-ref", ttl_seconds=3600)
        return original_load()

    monkeypatch.setattr(creds, "load", load_with_cli_race)
    assert creds.ensure_fresh().access_token == "cli-tok"


def test_race_during_refresh_keeps_tokens_in_memory(creds_file, monkeypatch):
    write_creds(creds_file, ttl_seconds=60)

    def fake_refresh(tokens, client=None):
        # The CLI finishes its own refresh while our request is in flight.
        write_creds(creds_file, access="cli-tok", refresh="cli-ref", ttl_seconds=3600)
        return TokenSet(
            access_token="ours",
            refresh_token="ours-ref",
            expires_at_ms=int((time.time() + 3600) * 1000),
        )

    monkeypatch.setattr(cc, "refresh_tokens", fake_refresh)
    creds = ClaudeCodeCredentials(creds_file)
    tokens = creds.ensure_fresh()

    assert tokens.access_token == "ours"
    saved = json.loads(creds_file.read_text(encoding="utf-8"))
    assert saved["claudeAiOauth"]["accessToken"] == "cli-tok", "must not clobber the CLI"
    # A second call reuses the in-memory pair instead of refreshing again.
    assert creds.ensure_fresh().access_token == "ours"


def test_read_only_mode_never_writes(creds_file, monkeypatch):
    write_creds(creds_file, ttl_seconds=60)
    monkeypatch.setattr(cc, "refresh_tokens", lambda *a, **k: pytest.fail("no refresh in read-only"))
    creds = ClaudeCodeCredentials(creds_file, read_only=True)
    assert creds.ensure_fresh().access_token == "tok-a"


def test_read_only_mode_raises_once_expired(creds_file, monkeypatch):
    write_creds(creds_file, ttl_seconds=-10)
    monkeypatch.setattr(cc, "refresh_tokens", lambda *a, **k: pytest.fail("no refresh in read-only"))
    creds = ClaudeCodeCredentials(creds_file, read_only=True)
    with pytest.raises(AuthError):
        creds.ensure_fresh()
