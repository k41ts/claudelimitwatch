"""Preferences dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from .. import autostart
from ..config import Settings
from .theme import PALETTES, panel_style


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setStyleSheet(panel_style())
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self.theme = QComboBox()
        for name in PALETTES:
            self.theme.addItem(name.capitalize(), name)
        index = self.theme.findData(settings.theme)
        self.theme.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Theme", self.theme)

        self.poll = QSpinBox()
        self.poll.setRange(30, 600)
        self.poll.setSuffix(" s")
        self.poll.setValue(settings.poll_seconds)
        form.addRow("Poll interval", self.poll)

        self.idle_poll = QSpinBox()
        self.idle_poll.setRange(60, 3600)
        self.idle_poll.setSuffix(" s")
        self.idle_poll.setValue(settings.idle_poll_seconds)
        form.addRow("When hidden", self.idle_poll)

        self.busy_poll = QSpinBox()
        self.busy_poll.setRange(30, 600)
        self.busy_poll.setSuffix(" s")
        self.busy_poll.setValue(settings.busy_poll_seconds)
        form.addRow("When near a limit", self.busy_poll)

        self.warn = QSpinBox()
        self.warn.setRange(50, 99)
        self.warn.setSuffix(" %")
        self.warn.setValue(int(settings.warn_threshold))
        form.addRow("Warn at", self.warn)

        self.danger = QSpinBox()
        self.danger.setRange(60, 100)
        self.danger.setSuffix(" %")
        self.danger.setValue(int(settings.danger_threshold))
        form.addRow("Alert at", self.danger)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(40, 100)
        self.opacity.setValue(int(settings.opacity * 100))
        form.addRow("Overlay opacity", self.opacity)

        self.notifications = QCheckBox("Show notifications")
        self.notifications.setChecked(settings.notifications)
        form.addRow("", self.notifications)

        self.show_all = QCheckBox("Show every account in the mini bar")
        self.show_all.setChecked(settings.show_all_accounts)
        form.addRow("", self.show_all)

        self.topmost = QCheckBox("Keep re-asserting always-on-top")
        self.topmost.setChecked(settings.reassert_topmost)
        form.addRow("", self.topmost)

        self.autostart = QCheckBox(
            "Start with Windows" if autostart.IS_WINDOWS else "Start at login"
        )
        # Reflect the registry, not just our own settings file: the entry
        # may have been removed by the uninstaller or another tool.
        self.autostart.setChecked(autostart.is_enabled())
        form.addRow("", self.autostart)

        self.autostart.setEnabled(autostart.supported())

        self.read_only = QCheckBox("Never write ~/.claude/.credentials.json")
        self.read_only.setChecked(settings.read_only_credentials)
        form.addRow("", self.read_only)

        layout.addLayout(form)
        hint = QLabel(
            "Theme and read-only mode take effect on restart. Read-only mode stops the "
            "watcher from refreshing the Claude Code token, so numbers go stale about an "
            "hour after the CLI last ran."
        )
        hint.setWordWrap(True)
        hint.setProperty("dim", "true")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_to_settings(self) -> Settings:
        s = self.settings
        s.theme = self.theme.currentData()
        s.poll_seconds = self.poll.value()
        s.idle_poll_seconds = self.idle_poll.value()
        s.busy_poll_seconds = self.busy_poll.value()
        s.warn_threshold = float(self.warn.value())
        s.danger_threshold = float(self.danger.value())
        s.opacity = self.opacity.value() / 100.0
        s.notifications = self.notifications.isChecked()
        s.show_all_accounts = self.show_all.isChecked()
        s.reassert_topmost = self.topmost.isChecked()
        s.read_only_credentials = self.read_only.isChecked()
        s.start_with_windows = self.autostart.isChecked()
        autostart.apply(s.start_with_windows)
        s.save()
        return s
