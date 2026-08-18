"""Detail panel: every account, every limit window."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..formatting import age_text, human_duration, local_time
from ..models import UsageSnapshot
from .theme import MeterBar, label_text, pal, panel_style


def _dim(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("dim", "true")
    label.setStyleSheet(f"color: {pal().text_dim.name()};")
    return label


class _AccountCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 10)
        self._layout.setSpacing(6)

        header = QHBoxLayout()
        self.title = QLabel("-")
        self.title.setProperty("heading", "true")
        self.title.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {pal().accent.name()};"
        )
        self.meta = _dim("")
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.meta)
        self._layout.addLayout(header)

        # The body is rebuilt from scratch on every update. It lives in its own
        # container widget so one deleteLater() takes the whole subtree with it:
        # clearing a layout by hand missed widgets nested deeper than one level,
        # which left orphaned labels floating over the header.
        self._body_host: QWidget | None = None
        self.body = QVBoxLayout()
        self._reset_body()

    def _reset_body(self) -> None:
        if self._body_host is not None:
            self._layout.removeWidget(self._body_host)
            self._body_host.setParent(None)
            self._body_host.deleteLater()
        host = QWidget(self)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._layout.addWidget(host)
        self._body_host = host
        self.body = layout

    def update_from(
        self,
        label: str,
        plan: str | None,
        snapshot: UsageSnapshot | None,
        error: str | None = None,
    ) -> None:
        self.title.setText(label_text(label))
        self._reset_body()

        if snapshot is None:
            self.meta.setText(plan or "")
            self.body.addWidget(_dim("Loading…"))
            return

        self.meta.setText(" · ".join(filter(None, [plan or snapshot.subscription_type, age_text(snapshot)])))
        if not snapshot.ok:
            message = QLabel(error or snapshot.error_short or "Unavailable")
            message.setWordWrap(True)
            message.setStyleSheet(f"color: {pal().danger.name()};")
            self.body.addWidget(message)
            return

        if error:
            # Last good numbers are still worth showing; flag them as stale.
            banner = QLabel(f"{error} · showing last known values")
            banner.setWordWrap(True)
            banner.setStyleSheet(f"color: {pal().warning.name()};")
            self.body.addWidget(banner)

        now = datetime.now(timezone.utc)
        for bucket in snapshot.buckets:
            row = QVBoxLayout()
            row.setSpacing(2)
            top = QHBoxLayout()
            name = QLabel(label_text(bucket.label) + ("  ◆" if bucket.is_active else ""))
            value = QLabel(label_text(f"{bucket.remaining:.0f}% left"))
            value.setStyleSheet(f"color: {pal().severity(bucket.severity).name()}; font-weight: 600;")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            top.addWidget(name)
            top.addStretch(1)
            top.addWidget(value)

            meter = MeterBar(height=8)
            meter.set_value(bucket.percent, bucket.severity)

            left = bucket.resets_in(now)
            detail = f"{bucket.percent:.0f}% used"
            if left is not None and left > 0:
                detail += f" · resets in {human_duration(left)} ({local_time(bucket.resets_at)})"
            elif bucket.resets_at is not None:
                detail += f" · reset due ({local_time(bucket.resets_at)})"

            row.addLayout(top)
            row.addWidget(meter)
            row.addWidget(_dim(detail))
            self.body.addLayout(row)

        spend = snapshot.spend
        if spend is not None and spend.enabled:
            used = spend.used_text or "?"
            cap = spend.limit_text or "no cap"
            self.body.addWidget(_dim(f"Usage credits: {used} of {cap}"))


class DetailPanel(QWidget):
    """Always-on-top window with the full breakdown."""

    refresh_requested = Signal()
    accounts_requested = Signal()
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("Claude Limit Watcher")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(panel_style())
        self.resize(380, 460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        self._cards_host = QWidget()
        self._cards = QVBoxLayout(self._cards_host)
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(12)
        self._cards.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._cards_host)
        outer.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_requested)
        accounts = QPushButton("Accounts…")
        accounts.clicked.connect(self.accounts_requested)
        settings = QPushButton("Settings…")
        settings.clicked.connect(self.settings_requested)
        buttons.addWidget(refresh)
        buttons.addWidget(accounts)
        buttons.addWidget(settings)
        buttons.addStretch(1)
        outer.addLayout(buttons)

        self._card_widgets: dict[str, _AccountCard] = {}

    def render_accounts(
        self, entries: list[tuple[str, str, str | None, UsageSnapshot | None, str | None]]
    ) -> None:
        """``entries`` is ``[(account_id, label, plan, snapshot, error), ...]``."""
        wanted = [entry[0] for entry in entries]
        for account_id in list(self._card_widgets):
            if account_id not in wanted:
                card = self._card_widgets.pop(account_id)
                self._cards.removeWidget(card)
                card.deleteLater()

        for index, (account_id, label, plan, snapshot, error) in enumerate(entries):
            card = self._card_widgets.get(account_id)
            if card is None:
                card = _AccountCard(self._cards_host)
                self._card_widgets[account_id] = card
                self._cards.insertWidget(index, card)
            card.update_from(label, plan, snapshot, error)
