"""Shared Qt fixture.

One process may hold exactly one application object, and widgets need a full
QApplication (a bare QCoreApplication makes widget construction hang). So every
Qt-touching test goes through this single session-scoped fixture.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
