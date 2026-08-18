import uuid

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from climitwatch.single_instance import SingleInstance  # noqa: E402


@pytest.fixture(autouse=True)
def _app(qt_app):
    """Widgets and local sockets share the one QApplication from conftest."""


@pytest.fixture()
def lock_name():
    """A per-test socket name, so a running ClimitWatch cannot interfere."""
    return f"climitwatch-test-{uuid.uuid4().hex[:12]}"


def test_first_instance_acquires_and_second_is_refused(lock_name):
    first = SingleInstance(lock_name)
    try:
        assert first.try_acquire() is True
        second = SingleInstance(lock_name)
        assert second.try_acquire() is False
    finally:
        first.release()


def test_lock_is_reusable_after_release(lock_name):
    first = SingleInstance(lock_name)
    assert first.try_acquire() is True
    first.release()

    second = SingleInstance(lock_name)
    try:
        assert second.try_acquire() is True
    finally:
        second.release()


def test_second_launch_pings_the_owner(lock_name):
    owner = SingleInstance(lock_name)
    pinged: list[bool] = []
    owner.activated.connect(lambda: pinged.append(True))
    try:
        assert owner.try_acquire() is True
        assert SingleInstance(lock_name).try_acquire() is False
        QCoreApplication.processEvents()
        assert pinged, "the running instance should have been told to show itself"
    finally:
        owner.release()
