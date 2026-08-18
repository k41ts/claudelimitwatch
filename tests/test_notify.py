from datetime import datetime, timedelta, timezone

from climitwatch.models import LimitBucket, UsageSnapshot
from climitwatch.notify import LEVEL_DANGER, LEVEL_WARN, ThresholdNotifier

NOW = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)


def snapshot(percent: float, resets_at: datetime | None = None) -> UsageSnapshot:
    return UsageSnapshot(
        account_id="acct",
        fetched_at=NOW,
        buckets=(
            LimitBucket(
                key="session",
                label="Session (5h)",
                percent=percent,
                resets_at=resets_at or NOW + timedelta(hours=1),
            ),
        ),
    )


def test_first_sighting_is_silent():
    notifier = ThresholdNotifier()
    assert notifier.check(snapshot(92)) == []


def test_fires_once_per_threshold():
    notifier = ThresholdNotifier()
    notifier.check(snapshot(10))

    warn = notifier.check(snapshot(85))
    assert len(warn) == 1 and warn[0].level == LEVEL_WARN

    assert notifier.check(snapshot(88)) == []

    danger = notifier.check(snapshot(96))
    assert len(danger) == 1 and danger[0].level == LEVEL_DANGER

    assert notifier.check(snapshot(99)) == []


def test_reset_rearms_and_announces():
    notifier = ThresholdNotifier()
    first_window = NOW + timedelta(hours=1)
    notifier.check(snapshot(10, first_window))
    notifier.check(snapshot(96, first_window))

    later = first_window + timedelta(hours=5)
    reset_notes = notifier.check(snapshot(3, later))
    assert len(reset_notes) == 1
    assert "reset" in reset_notes[0].title.lower()

    again = notifier.check(snapshot(85, later))
    assert len(again) == 1 and again[0].level == LEVEL_WARN


def test_failed_snapshot_never_notifies():
    notifier = ThresholdNotifier()
    notifier.check(snapshot(10))
    failed = UsageSnapshot(account_id="acct", fetched_at=NOW, error="network down")
    assert notifier.check(failed) == []


def test_custom_thresholds():
    notifier = ThresholdNotifier(warn_threshold=50, danger_threshold=60)
    notifier.check(snapshot(10))
    assert notifier.check(snapshot(55))[0].level == LEVEL_WARN
    assert notifier.check(snapshot(65))[0].level == LEVEL_DANGER
