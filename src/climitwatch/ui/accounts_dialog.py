"""Add, list and remove watched accounts."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..accounts import CLAUDE_CODE_ID, AccountManager
from ..api.client import UsageClient
from .login_dialog import LoginDialog
from .theme import panel_style

log = logging.getLogger(__name__)


class AccountsDialog(QDialog):
    """The account list, with add/remove."""

    accounts_changed = Signal()

    def __init__(self, manager: AccountManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Accounts")
        self.setStyleSheet(panel_style())
        self.resize(420, 300)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        note = QLabel(
            "The Claude Code account is read from ~/.claude/.credentials.json. "
            "Added accounts use their own tokens and never touch that file."
        )
        note.setWordWrap(True)
        note.setProperty("dim", "true")
        layout.addWidget(note)

        buttons = QHBoxLayout()
        add = QPushButton("Add account…")
        add.clicked.connect(self._add)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(add)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.list.currentItemChanged.connect(self._sync_buttons)
        self.reload()

    def reload(self) -> None:
        self.list.clear()
        for account in self.manager.accounts:
            source = self.manager.source(account.id)
            suffix = " (needs login)" if source is not None and source.needs_login else ""
            origin = "Claude Code" if account.source == "claude-code" else "added"
            item = QListWidgetItem(f"{account.display} — {account.plan or '?'} [{origin}]{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, account.id)
            self.list.addItem(item)
        self._sync_buttons()

    def _selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _sync_buttons(self) -> None:
        account_id = self._selected_id()
        self.remove_button.setEnabled(bool(account_id) and account_id != CLAUDE_CODE_ID)

    def _add(self) -> None:
        dialog = LoginDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.tokens is None:
            return
        with UsageClient() as client:
            account = self.manager.add_logged_in_account(dialog.tokens, client)
        self.reload()
        self.accounts_changed.emit()
        QMessageBox.information(self, "Account added", f"Now watching {account.display}.")

    def _remove(self) -> None:
        account_id = self._selected_id()
        if not account_id or account_id == CLAUDE_CODE_ID:
            return
        source = self.manager.source(account_id)
        label = source.account.display if source else account_id
        confirm = QMessageBox.question(
            self,
            "Remove account",
            f"Stop watching {label}? Its stored token will be deleted.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.manager.remove_account(account_id)
        self.reload()
        self.accounts_changed.emit()
