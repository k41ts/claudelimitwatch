"""Application controller: wires the poller thread to the overlay widgets."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QPoint, QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart, cache
from .accounts import AccountManager
from .config import Settings
from .formatting import compact_line, human_duration
from .models import UsageSnapshot
from .notify import LEVEL_DANGER, LEVEL_WARN, ThresholdNotifier
from .poller import PollerWorker
from .ui.accounts_dialog import AccountsDialog
from .ui.minibar import MiniBar
from .ui.panel import DetailPanel
from .ui.settings_dialog import SettingsDialog
from .ui.theme import set_theme
from .ui.tray import TrayIcon

log = logging.getLogger(__name__)

UI_TICK_MS = 15_000

#: Mini-bar wording: the row has room for a status plus a countdown, not a
#: sentence. The panel still shows the full message.
COMPACT_ERRORS = {
    "Rate limited by the API": "rate limited",
    "Login expired": "login expired",
    "Offline": "offline",
    "Unavailable": "unavailable",
    "Auth failed": "auth failed",
}
TOPMOST_TICK_MS = 5_000


class WatcherApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.settings = Settings.load()
        set_theme(self.settings.theme)
        self.manager = AccountManager(read_only_credentials=self.settings.read_only_credentials)
        self.snapshots: dict[str, UsageSnapshot] = cache.load_snapshots()
        #: Short, human error per account; the numbers above stay as they were.
        self.errors: dict[str, str] = {}
        #: Monotonic deadline of the next poll attempt, for the countdown.
        self._next_poll_at: float | None = None
        self.notifier = ThresholdNotifier(
            warn_threshold=self.settings.warn_threshold,
            danger_threshold=self.settings.danger_threshold,
        )

        self._apply_cached_identities()

        self.minibar = MiniBar(opacity=self.settings.opacity)
        self.panel = DetailPanel()
        self.tray = TrayIcon(self)

        self._wire_ui()
        self._restore_geometry()

        self.thread = QThread(self)
        self.worker = PollerWorker(self.manager, self.settings)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.snapshot_ready.connect(self._on_snapshot, Qt.ConnectionType.QueuedConnection)
        self.worker.cycle_finished.connect(self._on_cycle, Qt.ConnectionType.QueuedConnection)
        self.worker.next_poll_in.connect(self._on_next_poll, Qt.ConnectionType.QueuedConnection)

        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self.render)
        self._ui_timer.start(UI_TICK_MS)

        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._keep_on_top)
        if self.settings.reassert_topmost:
            self._topmost_timer.start(TOPMOST_TICK_MS)

    def _apply_cached_identities(self) -> None:
        """Name accounts from the last resolved profile, not from a guess.

        ~/.claude.json can name a different account than the token in
        .credentials.json belongs to, and the profile call that corrects it is
        exactly what fails when the API rate limits us.
        """
        cached = cache.load_identities()
        for source in self.manager.sources:
            entry = cached.get(source.account.id)
            if not entry:
                continue
            label = entry.get("label")
            if label:
                source.account.label = label
            if entry.get("email"):
                source.account.email = entry["email"]
            if entry.get("plan"):
                source.account.plan = entry["plan"]

    def _save_identities(self) -> None:
        cache.save_identities(
            {
                s.account.id: {
                    "label": s.account.label,
                    "email": s.account.email,
                    "plan": s.account.plan,
                }
                for s in self.manager.sources
            }
        )

    # -- setup ------------------------------------------------------------

    def _wire_ui(self) -> None:
        self.minibar.clicked.connect(self.toggle_panel)
        self.minibar.context_requested.connect(self._show_context_menu)
        self.minibar.moved.connect(self._save_position)

        self.panel.refresh_requested.connect(self.refresh_now)
        self.panel.accounts_requested.connect(self.show_accounts)
        self.panel.settings_requested.connect(self.show_settings)

        self.tray.toggle_requested.connect(self.toggle_minibar)
        self.tray.panel_requested.connect(self.show_panel)
        self.tray.refresh_requested.connect(self.refresh_now)
        self.tray.accounts_requested.connect(self.show_accounts)
        self.tray.settings_requested.connect(self.show_settings)
        self.tray.quit_requested.connect(self.quit)

    def _restore_geometry(self) -> None:
        pos = self.settings.minibar_pos
        if pos and len(pos) == 2:
            self.minibar.move(QPoint(int(pos[0]), int(pos[1])))
        else:
            screen = self.app.primaryScreen().availableGeometry()
            self.minibar.move(screen.right() - 400, screen.top() + 24)

    def _clamp_to_screen(self) -> None:
        """Keep the bar fully on a monitor after resizing or a display change."""
        screen = self.app.screenAt(self.minibar.pos()) or self.app.primaryScreen()
        bounds = screen.availableGeometry()
        frame = self.minibar.frameGeometry()
        x = min(max(frame.x(), bounds.left()), max(bounds.right() - frame.width(), bounds.left()))
        y = min(max(frame.y(), bounds.top()), max(bounds.bottom() - frame.height(), bounds.top()))
        if (x, y) != (frame.x(), frame.y()):
            self.minibar.move(x, y)

    def start(self) -> None:
        # The registry is the source of truth: the installer (or the user, via
        # Task Manager's Startup tab) can change it behind our back.
        registered = autostart.is_enabled()
        if registered != self.settings.start_with_windows:
            self.settings.start_with_windows = registered
            self.settings.save()
        elif registered:
            # Refresh the path in case the app was moved or reinstalled.
            autostart.enable()
        self.tray.show()
        if self.settings.minibar_visible:
            self.minibar.show()
            self.minibar.apply_platform_flags()
        self.render()
        self.thread.start()
        if not self.manager.sources:
            self.tray.showMessage(
                "No accounts yet",
                "Log in with Claude Code, or add an account from the tray menu.",
                QSystemTrayIcon.MessageIcon.Information,
            )

    # -- polling results --------------------------------------------------

    def _on_snapshot(self, snapshot: UsageSnapshot) -> None:
        previous = self.snapshots.get(snapshot.account_id)
        if snapshot.ok:
            self.snapshots[snapshot.account_id] = snapshot
            self.errors.pop(snapshot.account_id, None)
        else:
            # Keep the last good numbers on screen; surface a short reason.
            log.info("Poll failed for %s: %s", snapshot.account_id, snapshot.error)
            self.errors[snapshot.account_id] = snapshot.error_short or "Unavailable"
            if previous is None or not previous.ok:
                self.snapshots[snapshot.account_id] = snapshot

        if self.settings.notifications and snapshot.ok:
            source = self.manager.source(snapshot.account_id)
            label = source.account.display if source else snapshot.account_id
            for note in self.notifier.check(snapshot, label):
                icon = (
                    QSystemTrayIcon.MessageIcon.Critical
                    if note.level == LEVEL_DANGER
                    else QSystemTrayIcon.MessageIcon.Warning
                    if note.level == LEVEL_WARN
                    else QSystemTrayIcon.MessageIcon.Information
                )
                self.tray.showMessage(note.title, note.message, icon)
        self.render()

    def _on_cycle(self, _snapshots: list[UsageSnapshot]) -> None:
        cache.save_snapshots(self.snapshots)
        self._save_identities()

    def _on_next_poll(self, seconds: float) -> None:
        self._next_poll_at = time.monotonic() + seconds
        self.render()

    def _error_text(self, account_id: str, compact: bool = False) -> str | None:
        """Error plus a retry countdown, so a long backoff reads as waiting."""
        error = self.errors.get(account_id)
        if not error:
            return None
        if compact:
            # The mini bar has one short slot; keep the countdown visible.
            error = COMPACT_ERRORS.get(error, error)
        if self._next_poll_at is None:
            return error
        remaining = self._next_poll_at - time.monotonic()
        if remaining <= 0:
            return f"{error} - retrying" if not compact else f"{error} now"
        return f"{error} - retry {human_duration(remaining)}" if not compact else (
            f"{error} {human_duration(remaining)}"
        )

    # -- rendering --------------------------------------------------------

    def _visible_sources(self):
        sources = self.manager.sources
        if self.settings.show_all_accounts or len(sources) <= 1:
            return sources
        selected = self.settings.selected_account
        chosen = next((s for s in sources if s.account.id == selected), None)
        return [chosen or sources[0]]

    def _display_labels(self) -> dict[str, str]:
        """Unique label per account.

        Two accounts can carry the same name before their profiles resolve
        (~/.claude.json may name a different account than the stored token), so
        collisions fall back to the email, then to the source.
        """
        labels = {s.account.id: s.account.display for s in self.manager.sources}
        seen: dict[str, list[str]] = {}
        for account_id, label in labels.items():
            seen.setdefault(label, []).append(account_id)

        for label, ids in seen.items():
            if len(ids) < 2:
                continue
            for account_id in ids:
                source = self.manager.source(account_id)
                if source is None:
                    continue
                email = source.account.email
                if email and email != label:
                    labels[account_id] = email
                else:
                    origin = "Claude Code" if source.account.source == "claude-code" else "added"
                    labels[account_id] = f"{label} ({origin})"
        return labels

    def render(self) -> None:
        labels = self._display_labels()
        minibar_entries = [
            (
                s.account.id,
                labels[s.account.id],
                self.snapshots.get(s.account.id),
                self._error_text(s.account.id, compact=True),
            )
            for s in self._visible_sources()
        ]
        self.minibar.render_accounts(minibar_entries)
        self._clamp_to_screen()

        self.panel.render_accounts(
            [
                (
                    s.account.id,
                    labels[s.account.id],
                    s.account.plan,
                    self.snapshots.get(s.account.id),
                    self._error_text(s.account.id),
                )
                for s in self.manager.sources
            ]
        )
        self._update_tray()

    def _update_tray(self) -> None:
        worst_percent = 0.0
        severity = "normal"
        lines: list[str] = []
        for source in self.manager.sources:
            snapshot = self.snapshots.get(source.account.id)
            if snapshot is None:
                continue
            lines.append(f"{source.account.display}: {compact_line(snapshot)}")
            if snapshot.ok:
                for bucket in snapshot.buckets:
                    if bucket.percent > worst_percent:
                        worst_percent = bucket.percent
                if snapshot.worst_severity == "danger" or (
                    severity != "danger" and snapshot.worst_severity == "warning"
                ):
                    severity = snapshot.worst_severity
        tooltip = "\n".join(lines) or "Claude Limit Watcher"
        self.tray.update_status(worst_percent, severity, tooltip)

    def _keep_on_top(self) -> None:
        self.minibar.keep_on_top()

    # -- actions ----------------------------------------------------------

    def refresh_now(self) -> None:
        # Clear the backoff: an explicit Refresh means try again right now.
        self.worker.reset_backoff()
        self._next_poll_at = None
        self.worker.refresh_now()

    def toggle_minibar(self) -> None:
        visible = not self.minibar.isVisible()
        if visible:
            self.minibar.show()
            self.minibar.apply_platform_flags()
        else:
            self.minibar.hide()
        self.settings.minibar_visible = visible
        self.settings.save()
        self.tray.set_minibar_visible(visible)
        self.worker.set_ui_visible(visible)

    def toggle_panel(self) -> None:
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.show_panel()

    def show_panel(self) -> None:
        self.render()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def show_accounts(self) -> None:
        dialog = AccountsDialog(self.manager, self.panel if self.panel.isVisible() else None)
        dialog.accounts_changed.connect(self.render)
        dialog.exec()
        self.render()
        self.refresh_now()

    def show_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.panel if self.panel.isVisible() else None)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        settings = dialog.apply_to_settings()
        self.minibar.setWindowOpacity(settings.opacity)
        self.notifier.warn_threshold = settings.warn_threshold
        self.notifier.danger_threshold = settings.danger_threshold
        if settings.reassert_topmost and not self._topmost_timer.isActive():
            self._topmost_timer.start(TOPMOST_TICK_MS)
        elif not settings.reassert_topmost:
            self._topmost_timer.stop()
        self.render()
        self.refresh_now()

    def _save_position(self, pos: QPoint) -> None:
        self.settings.minibar_pos = [pos.x(), pos.y()]
        self.settings.save()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu()
        menu.addAction("Details…", self.show_panel)
        menu.addAction("Refresh now", self.refresh_now)
        if len(self.manager.sources) > 1:
            switch = menu.addMenu("Show account")
            for source in self.manager.sources:
                action = switch.addAction(source.account.display)
                action.setCheckable(True)
                action.setChecked(source.account.id == self.settings.selected_account)
                action.triggered.connect(
                    lambda _checked=False, account_id=source.account.id: self._select_account(account_id)
                )
            all_action = switch.addAction("All accounts")
            all_action.setCheckable(True)
            all_action.setChecked(self.settings.show_all_accounts)
            all_action.triggered.connect(self._show_all_accounts)
        menu.addSeparator()
        menu.addAction("Accounts…", self.show_accounts)
        menu.addAction("Settings…", self.show_settings)
        menu.addSeparator()
        menu.addAction("Hide mini bar", self.toggle_minibar)
        menu.addAction("Quit", self.quit)
        menu.exec(global_pos)

    def _select_account(self, account_id: str) -> None:
        self.settings.selected_account = account_id
        self.settings.show_all_accounts = False
        self.settings.save()
        self.render()

    def _show_all_accounts(self) -> None:
        self.settings.show_all_accounts = True
        self.settings.save()
        self.render()

    def quit(self) -> None:
        cache.save_snapshots(self.snapshots)
        self.worker.stop()
        self.thread.quit()
        if not self.thread.wait(4000):
            log.warning("Poller thread did not stop in time")
        self.tray.hide()
        self.app.quit()

    # -- misc -------------------------------------------------------------

    def report_startup_error(self, message: str) -> None:
        QMessageBox.critical(None, "Claude Limit Watcher", message)


def stale_seconds(snapshot: UsageSnapshot) -> float:
    return snapshot.age_seconds(datetime.now(timezone.utc))
