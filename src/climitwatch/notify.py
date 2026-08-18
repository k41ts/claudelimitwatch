"""Threshold and reset notifications.

Pure logic (no Qt) so it can be unit tested; the app turns the returned
:class:`Notification` values into tray balloons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import UsageSnapshot

LEVEL_NONE = 0
LEVEL_WARN = 1
LEVEL_DANGER = 2


@dataclass(frozen=True)
class Notification:
    title: str
    message: str
    level: int


@dataclass
class _BucketState:
    level: int = LEVEL_NONE
    resets_at: datetime | None = None
    seen: bool = False


@dataclass
class ThresholdNotifier:
    """Fires once per threshold crossing, and re-arms after each reset."""

    warn_threshold: float = 80.0
    danger_threshold: float = 95.0
    notify_on_reset: bool = True
    _state: dict[tuple[str, str], _BucketState] = field(default_factory=dict)

    def _level_for(self, percent: float) -> int:
        if percent >= self.danger_threshold:
            return LEVEL_DANGER
        if percent >= self.warn_threshold:
            return LEVEL_WARN
        return LEVEL_NONE

    def check(self, snapshot: UsageSnapshot, account_label: str | None = None) -> list[Notification]:
        if not snapshot.ok:
            return []
        label = account_label or snapshot.account_id
        out: list[Notification] = []
        for bucket in snapshot.buckets:
            key = (snapshot.account_id, bucket.key)
            state = self._state.get(key)
            if state is None:
                # First sighting: adopt the current level silently so starting
                # the app at 90% does not immediately spam a warning.
                self._state[key] = _BucketState(
                    level=self._level_for(bucket.percent), resets_at=bucket.resets_at, seen=True
                )
                continue

            window_rolled = (
                bucket.resets_at is not None
                and state.resets_at is not None
                and bucket.resets_at > state.resets_at
            )
            if window_rolled:
                if self.notify_on_reset and state.level >= LEVEL_WARN:
                    out.append(
                        Notification(
                            title=f"{bucket.label} reset",
                            message=f"{label}: back to {bucket.remaining:.0f}% left.",
                            level=LEVEL_NONE,
                        )
                    )
                state.level = LEVEL_NONE
            state.resets_at = bucket.resets_at

            level = self._level_for(bucket.percent)
            if level > state.level:
                out.append(
                    Notification(
                        title=f"{bucket.label} at {bucket.percent:.0f}%",
                        message=f"{label}: {bucket.remaining:.0f}% left.",
                        level=level,
                    )
                )
            state.level = level
        return out

    def forget(self, account_id: str) -> None:
        for key in [k for k in self._state if k[0] == account_id]:
            del self._state[key]
