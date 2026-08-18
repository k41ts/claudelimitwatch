"""Request budget per poll: one usage call, and a profile call only when needed."""

import datetime

import pytest

from climitwatch.accounts import AccountManager, AccountSource
from climitwatch.auth.oauth import TokenSet
from climitwatch.models import Account

USAGE_PAYLOAD = {
    "five_hour": {"utilization": 12.0, "resets_at": "2026-08-19T04:00:00+00:00"},
    "seven_day": {"utilization": 40.0, "resets_at": "2026-08-22T04:00:00+00:00"},
}
PROFILE_PAYLOAD = {
    "account": {"email": "resolved@example.com", "uuid": "u1"},
    "organization": {"organization_type": "claude_pro"},
}


class RecordingClient:
    def __init__(self):
        self.usage_calls = 0
        self.profile_calls = 0

    def fetch_usage(self, token):
        self.usage_calls += 1
        return USAGE_PAYLOAD

    def fetch_profile(self, token):
        self.profile_calls += 1
        return PROFILE_PAYLOAD


class StubSource(AccountSource):
    def __init__(self, account):
        super().__init__(account)

    def ensure_fresh(self, client):
        return TokenSet(
            access_token="token",
            expires_at_ms=int((datetime.datetime.now().timestamp() + 3600) * 1000),
        )


@pytest.fixture()
def manager(monkeypatch, tmp_path):
    from climitwatch.auth import store

    monkeypatch.setattr(store, "accounts_path", lambda: tmp_path / "accounts.dat")
    monkeypatch.setattr(AccountManager, "reload", lambda self: None)
    instance = AccountManager.__new__(AccountManager)
    instance._sources = []
    instance._profile_fetched = set()
    return instance


def test_known_account_costs_one_request(manager):
    """A cached identity means the profile call is dead weight."""
    source = StubSource(Account(id="a", label="A", source="app", email="known@example.com"))
    client = RecordingClient()

    manager.poll(source, client)

    assert client.usage_calls == 1
    assert client.profile_calls == 0


def test_unknown_account_resolves_its_name_once(manager):
    source = StubSource(Account(id="a", label="a", source="app"))
    client = RecordingClient()

    manager.poll(source, client)
    assert client.profile_calls == 1
    assert source.account.email == "resolved@example.com"

    for _ in range(3):
        manager.poll(source, client)
    assert client.profile_calls == 1, "the name is resolved once, not per poll"
    assert client.usage_calls == 4


def test_snapshot_carries_the_parsed_buckets(manager):
    source = StubSource(Account(id="a", label="A", source="app", email="known@example.com"))
    snapshot = manager.poll(source, RecordingClient())

    assert snapshot.ok
    assert snapshot.session is not None and snapshot.session.percent == 12
    assert snapshot.weekly is not None and snapshot.weekly.percent == 40
