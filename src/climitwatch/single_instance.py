"""Single-instance guard.

Two copies of the watcher double the request rate against an endpoint that
already rate-limits (Claude Code refetches usage at most every 5 minutes), so a
second launch hands off to the running one instead of starting its own poller.
"""

from __future__ import annotations

import getpass
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_MS = 400


def _socket_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - getuser is environment dependent
        user = "default"
    return f"climitwatch-{user}"


class SingleInstance(QObject):
    """Owns the lock, or reports that someone else does.

    ``activated`` fires when a second launch pings this instance, so the
    running app can pop its window instead of leaving the user wondering why
    nothing happened.
    """

    activated = Signal()

    def __init__(self, name: str | None = None) -> None:
        super().__init__()
        #: Overridable so tests never collide with a running app.
        self.name = name or _socket_name()
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        if self._ping_existing():
            return False

        server = QLocalServer(self)
        # A crashed instance can leave the socket behind; taking it over is
        # safe because we only get here when nothing answered the ping.
        QLocalServer.removeServer(self.name)
        if not server.listen(self.name):
            log.warning("Could not claim the instance lock: %s", server.errorString())
            return True  # Fail open: better a second window than no window.
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _ping_existing(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
            return False
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    def _on_connection(self) -> None:
        if self._server is None:
            return
        connection = self._server.nextPendingConnection()
        if connection is None:
            return
        connection.readyRead.connect(connection.readAll)
        connection.disconnected.connect(connection.deleteLater)
        self.activated.emit()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
