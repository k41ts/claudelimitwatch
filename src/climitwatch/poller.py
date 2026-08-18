"""Background polling loop.

Runs on its own QThread so the UI never blocks on HTTP. The cadence adapts:
slower when the mini bar is hidden, faster when a limit is close to full, with
exponential backoff after errors and an extra poll right after a window resets.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal

from .accounts import AccountManager
from .api.client import UsageClient
from .config import Settings
from .models import UsageSnapshot

log = logging.getLogger(__name__)

BACKOFF_STEPS = (300, 600, 900, 1800)
#: Poll a few seconds after a window is due to reset, so the new number lands.
RESET_GRACE_SECONDS = 15

#: Hard floor. The CLI refetches at most every 5 minutes; going far below
#: that on top of Claude Code's own polling triggers HTTP 429.
MIN_INTERVAL_SECONDS = 60.0


class PollerWorker(QObject):
    """Polls every enabled account in a loop until :meth:`stop` is called."""

    snapshot_ready = Signal(object)  # UsageSnapshot
    cycle_finished = Signal(list)  # list[UsageSnapshot]
    #: Seconds until the next attempt, so the UI can show a countdown
    #: instead of a bare error that looks stuck.
    next_poll_in = Signal(float)
    accounts_changed = Signal()

    def __init__(
        self, manager: AccountManager, settings: Settings, initial_delay: float = 0.0
    ) -> None:
        super().__init__()
        self.manager = manager
        self.settings = settings
        #: Restarting the app should not cost a fetch when the cached data is
        #: still within the polling window.
        self._initial_delay = max(0.0, initial_delay)
        self._wake = threading.Event()
        self._stopping = False
        self._error_streak = 0
        self._ui_visible = True
        self._client: UsageClient | None = None

    # -- control (thread-safe) -------------------------------------------

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    def refresh_now(self) -> None:
        self._wake.set()

    def reset_backoff(self) -> None:
        """Drop the error streak so the next attempt uses the normal cadence."""
        self._error_streak = 0

    def set_ui_visible(self, visible: bool) -> None:
        self._ui_visible = visible

    # -- loop -------------------------------------------------------------

    def run(self) -> None:
        self._client = UsageClient()
        try:
            if self._initial_delay > 0:
                self.next_poll_in.emit(self._initial_delay)
                self._wake.wait(self._initial_delay)
                self._wake.clear()
            while not self._stopping:
                snapshots = self._poll_once()
                if self._stopping:
                    break
                interval = self._next_interval(snapshots)
                self.next_poll_in.emit(interval)
                self._wake.wait(interval)
                self._wake.clear()
        finally:
            self._client.close()
            self._client = None

    def _poll_once(self) -> list[UsageSnapshot]:
        assert self._client is not None
        snapshots: list[UsageSnapshot] = []
        for source in list(self.manager.enabled_sources()):
            if self._stopping:
                break
            snapshot = self.manager.poll(source, self._client)
            snapshots.append(snapshot)
            self.snapshot_ready.emit(snapshot)
        if snapshots:
            self.cycle_finished.emit(snapshots)
        # Any failure backs the whole loop off: a 429 is account-wide, and
        # hammering on behalf of the accounts that still work makes it worse.
        self._error_streak = (
            self._error_streak + 1 if any(not s.ok for s in snapshots) else 0
        )
        return snapshots

    def _next_interval(self, snapshots: list[UsageSnapshot]) -> float:
        if self._error_streak:
            backoff = float(BACKOFF_STEPS[min(self._error_streak - 1, len(BACKOFF_STEPS) - 1)])
            # Never come back sooner than the server asked us to.
            asked = max((s.retry_after or 0.0) for s in snapshots) if snapshots else 0.0
            return max(backoff, asked)

        settings = self.settings
        interval = float(settings.poll_seconds)
        if not self._ui_visible:
            interval = float(settings.idle_poll_seconds)
        elif self._is_busy(snapshots, settings.warn_threshold):
            interval = float(settings.busy_poll_seconds)

        due = self._seconds_to_next_reset(snapshots)
        if due is not None and 0 < due < interval:
            interval = due
        return max(MIN_INTERVAL_SECONDS, interval)

    @staticmethod
    def _is_busy(snapshots: list[UsageSnapshot], threshold: float) -> bool:
        return any(b.percent >= threshold for s in snapshots for b in s.buckets)

    @staticmethod
    def _seconds_to_next_reset(snapshots: list[UsageSnapshot]) -> float | None:
        now = datetime.now(timezone.utc)
        pending = [
            left + RESET_GRACE_SECONDS
            for snapshot in snapshots
            for bucket in snapshot.buckets
            if (left := bucket.resets_in(now)) is not None and left > 0
        ]
        return min(pending) if pending else None
