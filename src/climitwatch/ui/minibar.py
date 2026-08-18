"""The always-on-top mini bar."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..formatting import human_duration
from ..models import SEVERITY_DANGER, UsageSnapshot
from .theme import (
    MeterBar,
    elide,
    label_text,
    pal,
    round_rect_background,
    severity_color,
    value_font,
)
from .win import make_non_activating, reassert_topmost

STALE_AFTER_SECONDS = 300
BLINK_MS = 650


class _AccountRow(QWidget):
    """One account: status dot, name, session meter, weekly meter, next reset."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.severity = "normal"
        self.dot = QLabel("◆" if pal().chamfer else "●")
        self.dot.setFixedWidth(12)
        self.name = QLabel("-")
        self.name.setMinimumWidth(74)
        name_font = QFont("Segoe UI", 9)
        name_font.setBold(True)
        if pal().letter_spacing:
            name_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, pal().letter_spacing)
        self.name.setFont(name_font)

        self.session_label = QLabel(label_text("5h -"))
        self.session_meter = MeterBar()
        self.session_meter.setFixedWidth(58)
        self.weekly_label = QLabel(label_text("7d -"))
        self.weekly_meter = MeterBar()
        self.weekly_meter.setFixedWidth(58)
        self.reset_label = QLabel("")

        for widget in (self.session_label, self.weekly_label, self.reset_label):
            widget.setFont(value_font())
        self.reset_label.setStyleSheet(f"color: {pal().text_dim.name()};")
        self.name.setStyleSheet(f"color: {pal().text.name()};")

        layout.addWidget(self.dot)
        layout.addWidget(self.name)
        layout.addWidget(self.session_label)
        layout.addWidget(self.session_meter)
        layout.addWidget(self.weekly_label)
        layout.addWidget(self.weekly_meter)
        layout.addWidget(self.reset_label)
        layout.addStretch(1)

    def set_dot(self, severity: str, dimmed: bool = False) -> None:
        self.severity = severity
        color = severity_color(severity)
        if dimmed:
            color = color.darker(260)
        self.dot.setStyleSheet(f"color: {color.name()};")

    def _set_value_label(self, label: QLabel, text: str, severity: str) -> None:
        label.setText(label_text(text))
        label.setStyleSheet(f"color: {severity_color(severity).name()};")

    def update_from(
        self, label: str, snapshot: UsageSnapshot | None, error: str | None = None
    ) -> None:
        self.name.setText(label_text(elide(label, 18)))
        if snapshot is None:
            self.set_dot("stale")
            self._set_value_label(self.session_label, "5h -", "stale")
            self._set_value_label(self.weekly_label, "7d -", "stale")
            self.reset_label.setText(label_text("linking…"))
            return

        now = datetime.now(timezone.utc)
        stale = bool(error) or snapshot.age_seconds(now) > STALE_AFTER_SECONDS or not snapshot.ok
        self.set_dot("stale" if stale else snapshot.worst_severity)

        if not snapshot.ok:
            self._set_value_label(self.session_label, "5h ?", "stale")
            self._set_value_label(self.weekly_label, "7d ?", "stale")
            self.reset_label.setText(label_text(elide(error or snapshot.error_short or "error", 26)))
            self.session_meter.set_value(0, "stale")
            self.weekly_meter.set_value(0, "stale")
            return

        for bucket, text_label, meter, prefix in (
            (snapshot.session, self.session_label, self.session_meter, "5h"),
            (snapshot.weekly, self.weekly_label, self.weekly_meter, "7d"),
        ):
            if bucket is None:
                self._set_value_label(text_label, f"{prefix} -", "stale")
                meter.set_value(0, "stale")
                continue
            severity = "stale" if stale else bucket.severity
            self._set_value_label(text_label, f"{prefix} {bucket.remaining:.0f}%", severity)
            meter.set_value(bucket.percent, severity)

        if error:
            # Numbers stay on screen -- they are simply the last ones we got.
            self.reset_label.setText(label_text(elide(error, 26)))
            return

        soonest = min(
            (b for b in snapshot.buckets if (b.resets_in(now) or 0) > 0),
            key=lambda b: b.resets_in(now) or 0,
            default=None,
        )
        self.reset_label.setText(
            label_text(f"reset {human_duration(soonest.resets_in(now))}") if soonest else ""
        )


class MiniBar(QWidget):
    """Frameless strip that floats above other windows."""

    clicked = Signal()
    context_requested = Signal(QPoint)
    moved = Signal(QPoint)

    def __init__(self, opacity: float = 0.92) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Claude Limit Watcher")
        self.setWindowOpacity(opacity)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.mapToGlobal(pos))
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 9, 14, 9)
        self._layout.setSpacing(5)
        self._rows: dict[str, _AccountRow] = {}
        self._drag_origin: QPoint | None = None
        self._dragged = False

        # Rows at danger level pulse their status dot; the timer only runs
        # while at least one row is actually in that state.
        self._blink_on = True
        self._blink = QTimer(self)
        self._blink.setInterval(BLINK_MS)
        self._blink.timeout.connect(self._tick_blink)

    # -- content ----------------------------------------------------------

    def render_accounts(
        self, entries: list[tuple[str, str, UsageSnapshot | None, str | None]]
    ) -> None:
        """``entries`` is ``[(account_id, label, snapshot, error), ...]``."""
        wanted = [entry[0] for entry in entries]
        for account_id in list(self._rows):
            if account_id not in wanted:
                row = self._rows.pop(account_id)
                self._layout.removeWidget(row)
                row.deleteLater()

        for index, (account_id, label, snapshot, error) in enumerate(entries):
            row = self._rows.get(account_id)
            if row is None:
                row = _AccountRow(self)
                self._rows[account_id] = row
                self._layout.insertWidget(index, row)
            row.update_from(label, snapshot, error)

        self._sync_blink()
        self.adjustSize()

    def _sync_blink(self) -> None:
        alarming = any(row.severity == SEVERITY_DANGER for row in self._rows.values())
        if alarming and not self._blink.isActive():
            self._blink.start()
        elif not alarming and self._blink.isActive():
            self._blink.stop()
            self._blink_on = True
            for row in self._rows.values():
                row.set_dot(row.severity)

    def _tick_blink(self) -> None:
        self._blink_on = not self._blink_on
        for row in self._rows.values():
            if row.severity == SEVERITY_DANGER:
                row.set_dot(row.severity, dimmed=not self._blink_on)

    # -- window behaviour -------------------------------------------------

    def apply_platform_flags(self) -> None:
        make_non_activating(int(self.winId()))

    def keep_on_top(self) -> None:
        if self.isVisible():
            reassert_topmost(int(self.winId()))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        round_rect_background(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            self._dragged = True
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragged:
                self.moved.emit(self.pos())
            else:
                self.clicked.emit()
            self._drag_origin = None
            event.accept()
