"""Launching the app must not cost API calls when cached data is still fresh.

The endpoint rate-limits without publishing a budget, so every avoidable
request matters — a restart loop was what tripped it during development.
"""

import datetime

import pytest

pytest.importorskip("PySide6")

from climitwatch.app import WatcherApp  # noqa: E402
from climitwatch.config import Settings  # noqa: E402
from climitwatch.models import Account, LimitBucket, UsageSnapshot  # noqa: E402


class FakeSource:
    def __init__(self, account):
        self.account = account
        self.needs_login = False


class FakeManager:
    def __init__(self, accounts):
        self._sources = [FakeSource(a) for a in accounts]

    @property
    def sources(self):
        return list(self._sources)

    def source(self, account_id):
        return next((s for s in self._sources if s.account.id == account_id), None)


def snapshot(age_seconds: float, ok: bool = True) -> UsageSnapshot:
    fetched = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age_seconds)
    return UsageSnapshot(
        account_id="a",
        fetched_at=fetched,
        buckets=(LimitBucket("session", "Session (5h)", 10.0),) if ok else (),
        error=None if ok else "boom",
    )


@pytest.fixture()
def watcher(qt_app):
    app = WatcherApp.__new__(WatcherApp)  # only the delay maths is under test
    app.settings = Settings()
    app.manager = FakeManager([Account(id="a", label="A", source="claude-code")])
    app.snapshots = {}
    return app


def test_fresh_cache_defers_the_first_poll(watcher):
    watcher.snapshots = {"a": snapshot(age_seconds=60)}
    delay = watcher._initial_poll_delay()
    assert delay == pytest.approx(watcher.settings.poll_seconds - 60, abs=2)


def test_stale_cache_polls_immediately(watcher):
    watcher.snapshots = {"a": snapshot(age_seconds=watcher.settings.poll_seconds + 30)}
    assert watcher._initial_poll_delay() == 0.0


def test_missing_cache_polls_immediately(watcher):
    assert watcher._initial_poll_delay() == 0.0


def test_failed_cached_snapshot_polls_immediately(watcher):
    watcher.snapshots = {"a": snapshot(age_seconds=10, ok=False)}
    assert watcher._initial_poll_delay() == 0.0


def test_one_uncached_account_forces_a_poll(watcher):
    watcher.manager = FakeManager(
        [Account(id="a", label="A", source="claude-code"), Account(id="b", label="B", source="app")]
    )
    watcher.snapshots = {"a": snapshot(age_seconds=10)}
    assert watcher._initial_poll_delay() == 0.0


def test_no_accounts_needs_no_delay(watcher):
    watcher.manager = FakeManager([])
    assert watcher._initial_poll_delay() == 0.0
