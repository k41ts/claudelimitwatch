from datetime import datetime, timedelta, timezone

from climitwatch.config import Settings
from climitwatch.models import LimitBucket, UsageSnapshot
from climitwatch.poller import BACKOFF_STEPS, PollerWorker


def make_snapshot(percent: float, resets_in_seconds: float | None = None) -> UsageSnapshot:
    now = datetime.now(timezone.utc)
    resets_at = now + timedelta(seconds=resets_in_seconds) if resets_in_seconds else None
    return UsageSnapshot(
        account_id="acct",
        fetched_at=now,
        buckets=(LimitBucket(key="session", label="Session (5h)", percent=percent, resets_at=resets_at),),
    )


def worker() -> PollerWorker:
    return PollerWorker(manager=None, settings=Settings())  # type: ignore[arg-type]


def test_default_interval_matches_the_cli_cache_window():
    assert worker()._next_interval([make_snapshot(10)]) == 300


def test_hidden_ui_slows_down():
    w = worker()
    w.set_ui_visible(False)
    assert w._next_interval([make_snapshot(10)]) == 900


def test_near_limit_speeds_up():
    assert worker()._next_interval([make_snapshot(85)]) == 120


def test_imminent_reset_wins_over_interval():
    interval = worker()._next_interval([make_snapshot(10, resets_in_seconds=90)])
    assert 60 <= interval < 300


def test_interval_never_drops_below_the_floor():
    # Even an imminent reset must not poll faster than the floor.
    assert worker()._next_interval([make_snapshot(99, resets_in_seconds=1)]) == 60


def test_error_streak_backs_off():
    w = worker()
    failed = UsageSnapshot(account_id="acct", fetched_at=datetime.now(timezone.utc), error="boom")
    for expected in BACKOFF_STEPS:
        w._error_streak += 1
        assert w._next_interval([failed]) == expected
    w._error_streak += 1
    assert w._next_interval([failed]) == BACKOFF_STEPS[-1]


def test_retry_after_header_wins_over_backoff():
    w = worker()
    w._error_streak = 1
    limited = UsageSnapshot(
        account_id="acct",
        fetched_at=datetime.now(timezone.utc),
        error="HTTP 429",
        error_short="Rate limited by the API",
        retry_after=2400.0,
    )
    assert w._next_interval([limited]) == 2400.0


def test_one_failing_account_backs_off_the_whole_loop():
    w = worker()
    ok = make_snapshot(10)
    failed = UsageSnapshot(account_id="b", fetched_at=datetime.now(timezone.utc), error="boom")
    w._error_streak = 1
    assert w._next_interval([ok, failed]) == BACKOFF_STEPS[0]


def test_reset_backoff_restores_the_normal_cadence():
    w = worker()
    failed = UsageSnapshot(account_id="acct", fetched_at=datetime.now(timezone.utc), error="boom")
    w._error_streak = 3
    assert w._next_interval([failed]) == BACKOFF_STEPS[2]

    # A manual Refresh must not leave the user waiting out the backoff.
    w.reset_backoff()
    assert w._next_interval([make_snapshot(10)]) == 300
