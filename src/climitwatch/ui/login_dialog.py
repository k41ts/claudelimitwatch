"""Browser login: the loopback flow by default, copy-paste as a fallback."""

from __future__ import annotations

import logging
import webbrowser

import httpx
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..auth.callback_server import CallbackServer
from ..auth.oauth import (
    AuthError,
    PkceChallenge,
    TokenSet,
    authorize_url,
    exchange_code,
    new_pkce,
    split_pasted_code,
)
from .theme import panel_style

log = logging.getLogger(__name__)

LOGIN_TIMEOUT_SECONDS = 300


class _LoginWaiter(QThread):
    """Waits for the browser redirect, then exchanges the code."""

    finished_ok = Signal(object)  # TokenSet
    failed = Signal(str)

    def __init__(self, server: CallbackServer, pkce: PkceChallenge, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.pkce = pkce

    def run(self) -> None:
        result = self.server.wait(timeout=LOGIN_TIMEOUT_SECONDS)
        if result.error or not result.code:
            self.failed.emit(result.error or "No authorization code returned")
            return
        if result.state and result.state != self.pkce.state:
            self.failed.emit("State mismatch — login response did not match this request")
            return
        try:
            with httpx.Client(timeout=30.0) as client:
                tokens = exchange_code(
                    result.code,
                    self.pkce,
                    state=result.state,
                    client=client,
                    redirect_uri=self.server.redirect_uri,
                )
        except AuthError as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(tokens)


class LoginDialog(QDialog):
    """Sign in to an extra Claude account.

    Default path: open the browser, the page redirects back to a local
    listener, done. If the listener cannot bind (or the redirect never
    arrives), the copy-paste path is still there.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Claude account")
        self.setStyleSheet(panel_style())
        self.setMinimumWidth(430)

        self.pkce = new_pkce()
        self.tokens: TokenSet | None = None
        self.server: CallbackServer | None = None
        self.waiter: _LoginWaiter | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.intro = QLabel(
            "Sign in with the account you want to watch. The browser sends you "
            "straight back here when you approve."
        )
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)

        button_row = QHBoxLayout()
        self.sign_in_button = QPushButton("Sign in with browser")
        self.sign_in_button.setDefault(True)
        self.sign_in_button.clicked.connect(self._start_browser_login)
        self.manual_button = QPushButton("Use a code instead")
        self.manual_button.clicked.connect(self._start_manual_login)
        button_row.addWidget(self.sign_in_button)
        button_row.addWidget(self.manual_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("paste code#state here")
        self.code_input.returnPressed.connect(self._submit_pasted_code)
        self.code_input.hide()
        layout.addWidget(self.code_input)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._submit_pasted_code)
        self.connect_button.hide()
        layout.addWidget(self.connect_button)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        layout.addLayout(footer)

    # -- loopback flow ----------------------------------------------------

    def _start_browser_login(self) -> None:
        try:
            self.server = CallbackServer()
        except OSError as exc:
            log.warning("Could not start callback listener: %s", exc)
            self.status.setText(
                f"Could not open a local listener ({exc}). Use “Use a code instead”."
            )
            return

        url = authorize_url(self.pkce, redirect_uri=self.server.redirect_uri)
        self.sign_in_button.setEnabled(False)
        self.status.setText("Waiting for the browser… approve the login there.")

        self.waiter = _LoginWaiter(self.server, self.pkce, self)
        self.waiter.finished_ok.connect(self._on_tokens)
        self.waiter.failed.connect(self._on_failure)
        self.waiter.start()

        if not webbrowser.open(url):
            QGuiApplication.clipboard().setText(url)
            self.status.setText("Could not open a browser — the login link is on your clipboard.")

    def _on_tokens(self, tokens: TokenSet) -> None:
        self.tokens = tokens
        self._shutdown_server()
        self.accept()

    def _on_failure(self, message: str) -> None:
        self._shutdown_server()
        self.sign_in_button.setEnabled(True)
        self.status.setText(f"{message}. Try again, or use “Use a code instead”.")

    # -- copy-paste fallback ---------------------------------------------

    def _start_manual_login(self) -> None:
        self._shutdown_server()
        self.code_input.show()
        self.connect_button.show()
        self.code_input.setFocus()
        url = authorize_url(self.pkce)
        self.status.setText("Approve the login, then paste the code shown on that page.")
        if not webbrowser.open(url):
            QGuiApplication.clipboard().setText(url)
            self.status.setText("Login link copied to clipboard. Paste the code back here.")

    def _submit_pasted_code(self) -> None:
        pasted = self.code_input.text().strip()
        if not pasted:
            self.status.setText("Paste the code from the login page first.")
            return
        code, state = split_pasted_code(pasted)
        self.connect_button.setEnabled(False)
        self.status.setText("Exchanging code…")
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.tokens = exchange_code(code, self.pkce, state=state)
        except AuthError as exc:
            self.status.setText(str(exc))
            self.connect_button.setEnabled(True)
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.accept()

    # -- teardown ---------------------------------------------------------

    def _shutdown_server(self) -> None:
        if self.waiter is not None and self.waiter.isRunning():
            if self.server is not None:
                self.server.cancel()
            self.waiter.wait(2000)
        self.waiter = None
        if self.server is not None:
            self.server.close()
            self.server = None

    def reject(self) -> None:
        self._shutdown_server()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._shutdown_server()
        super().closeEvent(event)
