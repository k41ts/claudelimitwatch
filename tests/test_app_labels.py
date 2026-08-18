"""Account naming: cached identities and collision handling."""

import pytest

pytest.importorskip("PySide6")

from climitwatch import cache  # noqa: E402
from climitwatch.app import WatcherApp  # noqa: E402
from climitwatch.models import Account  # noqa: E402


class FakeSource:
    def __init__(self, account):
        self.account = account
        self.needs_login = False
        self.last_error = None


class FakeManager:
    def __init__(self, accounts):
        self._sources = [FakeSource(a) for a in accounts]

    @property
    def sources(self):
        return list(self._sources)

    def source(self, account_id):
        return next((s for s in self._sources if s.account.id == account_id), None)

    def enabled_sources(self):
        return iter(self._sources)


@pytest.fixture()
def app_stub(qt_app, monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "cache_path", lambda: tmp_path / "snapshots.json")
    watcher = WatcherApp.__new__(WatcherApp)  # skip Qt setup; only labels are under test
    return watcher


def test_collision_falls_back_to_email(app_stub):
    app_stub.manager = FakeManager(
        [
            Account(id="claude-code", label="Vina", source="claude-code", email="one@example.com"),
            Account(id="stored", label="Vina", source="app", email="two@example.com"),
        ]
    )
    labels = app_stub._display_labels()
    assert labels["claude-code"] == "one@example.com"
    assert labels["stored"] == "two@example.com"


def test_collision_without_email_marks_the_source(app_stub):
    app_stub.manager = FakeManager(
        [
            Account(id="claude-code", label="Vina", source="claude-code"),
            Account(id="stored", label="Vina", source="app"),
        ]
    )
    labels = app_stub._display_labels()
    assert labels["claude-code"] == "Vina (Claude Code)"
    assert labels["stored"] == "Vina (added)"


def test_distinct_labels_are_left_alone(app_stub):
    app_stub.manager = FakeManager(
        [
            Account(id="a", label="Alpha", source="claude-code", email="a@example.com"),
            Account(id="b", label="Beta", source="app", email="b@example.com"),
        ]
    )
    labels = app_stub._display_labels()
    assert labels == {"a": "Alpha", "b": "Beta"}


def test_cached_identity_overrides_a_stale_guess(app_stub, monkeypatch):
    app_stub.manager = FakeManager(
        [Account(id="claude-code", label="Vina", source="claude-code", email="stale@example.com")]
    )
    cache.save_identities(
        {"claude-code": {"label": "real@example.com", "email": "real@example.com", "plan": "max"}}
    )

    app_stub._apply_cached_identities()
    account = app_stub.manager.source("claude-code").account
    assert account.label == "real@example.com"
    assert account.email == "real@example.com"
    assert account.plan == "max"


def test_identities_round_trip(app_stub):
    app_stub.manager = FakeManager(
        [Account(id="a", label="Alpha", source="app", email="a@example.com", plan="pro")]
    )
    app_stub._save_identities()
    assert cache.load_identities()["a"]["email"] == "a@example.com"
