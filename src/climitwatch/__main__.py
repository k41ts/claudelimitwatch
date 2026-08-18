"""Entry point: python -m climitwatch"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .app import WatcherApp
from .config import APP_NAME
from .single_instance import SingleInstance
from .ui.win import platform_warning


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance()
    if not instance.try_acquire():
        # Another copy owns the poller; it has been told to show itself.
        logging.info("%s is already running; handing over to it", APP_NAME)
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(
            None,
            APP_NAME,
            "No system tray is available; the mini bar will still work, "
            "but there will be no tray icon or notifications.",
        )

    warning = platform_warning()
    if warning:
        logging.warning(warning)

    watcher = WatcherApp(app)
    instance.activated.connect(watcher.show_panel)
    watcher.start()
    try:
        return app.exec()
    finally:
        instance.release()


if __name__ == "__main__":
    sys.exit(main())
