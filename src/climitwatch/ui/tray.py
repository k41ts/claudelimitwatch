"""System tray icon and menu."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .theme import pal, severity_color




def usage_icon(percent: float, severity: str) -> QIcon:
    """A donut whose filled arc is the percentage used."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRect(7, 7, size - 14, size - 14)

    pen = QPen(pal().track, 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.drawArc(rect, 0, 360 * 16)

    if percent > 0:
        pen.setColor(severity_color(severity))
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * min(100.0, percent) / 100.0))
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    toggle_requested = Signal()
    panel_requested = Signal()
    refresh_requested = Signal()
    accounts_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIcon(usage_icon(0, "normal"))
        self.setToolTip("Claude Limit Watcher")

        menu = QMenu()
        self.toggle_action = QAction("Hide mini bar", menu)
        self.toggle_action.triggered.connect(self.toggle_requested)
        menu.addAction(self.toggle_action)

        details = QAction("Details…", menu)
        details.triggered.connect(self.panel_requested)
        menu.addAction(details)

        refresh = QAction("Refresh now", menu)
        refresh.triggered.connect(self.refresh_requested)
        menu.addAction(refresh)
        menu.addSeparator()

        accounts = QAction("Accounts…", menu)
        accounts.triggered.connect(self.accounts_requested)
        menu.addAction(accounts)

        settings = QAction("Settings…", menu)
        settings.triggered.connect(self.settings_requested)
        menu.addAction(settings)
        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(quit_action)

        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_requested.emit()

    def set_minibar_visible(self, visible: bool) -> None:
        self.toggle_action.setText("Hide mini bar" if visible else "Show mini bar")

    def update_status(self, percent: float, severity: str, tooltip: str) -> None:
        self.setIcon(usage_icon(percent, severity))
        self.setToolTip(tooltip)

    def menu(self) -> QMenu:
        return self._menu
