"""Linux autostart backend (XDG desktop entry).

Runs on any platform: the backend is selected by module-level flags, so the
Linux path can be exercised from Windows CI by flipping them. What this cannot
prove is that a real desktop environment honours the entry — that needs a Linux
session.
"""

import shlex
import sys
from pathlib import Path

import pytest

from climitwatch import autostart


@pytest.fixture()
def linux(monkeypatch, tmp_path):
    """Pretend to be Linux, with XDG_CONFIG_HOME under tmp_path."""
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    monkeypatch.setattr(autostart, "IS_LINUX", True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path / "config" / "autostart"


def test_disabled_by_default(linux):
    assert autostart.is_enabled() is False
    assert autostart.is_listed() is False
    assert autostart.current_command() is None


def test_enable_writes_a_desktop_entry(linux):
    assert autostart.enable() is True

    entry = autostart.desktop_entry_path()
    assert entry == linux / "climitwatch.desktop"
    assert entry.exists()

    text = entry.read_text(encoding="utf-8")
    assert text.startswith("[Desktop Entry]")
    assert "Type=Application" in text
    assert "Name=Claude Limit Watcher" in text
    assert "Terminal=false" in text
    assert "X-GNOME-Autostart-enabled=true" in text
    assert autostart.is_enabled() is True
    assert autostart.is_listed() is True


def test_exec_line_is_runnable(linux):
    autostart.enable()
    exec_line = autostart.current_command()

    assert exec_line
    parts = shlex.split(exec_line)  # must survive shell-style parsing
    assert Path(parts[0]).name.lower().startswith("python") or parts[0].endswith("ClimitWatch")
    if len(parts) > 1:
        assert parts[1].endswith("launcher.py")


def test_paths_with_spaces_stay_quoted(linux, monkeypatch):
    """A space in the install path must not split the Exec line in two."""
    monkeypatch.setattr(autostart, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", "/opt/my apps/ClimitWatch", raising=False)

    autostart.enable()
    parts = shlex.split(autostart.current_command())

    # Path.resolve() rewrites the POSIX path when these tests run on Windows,
    # so assert the quoting property rather than the literal path.
    assert len(parts) == 1
    assert "my apps" in parts[0]
    assert parts[0].endswith("ClimitWatch")


def test_disable_removes_the_entry(linux):
    autostart.enable()
    assert autostart.disable() is True
    assert not autostart.desktop_entry_path().exists()
    assert autostart.is_enabled() is False


def test_disable_is_idempotent(linux):
    assert autostart.disable() is True
    assert autostart.disable() is True


def test_desktop_switch_off_counts_as_disabled(linux):
    """GNOME flips this key instead of deleting the file."""
    autostart.enable()
    entry = autostart.desktop_entry_path()
    entry.write_text(
        entry.read_text(encoding="utf-8").replace(
            "X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-enabled=false"
        ),
        encoding="utf-8",
    )

    assert autostart.is_enabled() is False
    assert autostart.is_listed() is True  # the file is still there


def test_enable_refreshes_a_stale_entry(linux):
    autostart.enable()
    entry = autostart.desktop_entry_path()
    entry.write_text("[Desktop Entry]\nExec=/old/path\n", encoding="utf-8")

    autostart.enable()
    assert "/old/path" not in entry.read_text(encoding="utf-8")


def test_apply_switches_both_ways(linux):
    autostart.apply(True)
    assert autostart.is_enabled() is True
    autostart.apply(False)
    assert autostart.is_enabled() is False


def test_unsupported_platform_is_a_no_op(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    monkeypatch.setattr(autostart, "IS_LINUX", False)

    assert autostart.supported() is False
    assert autostart.is_enabled() is False
    assert autostart.enable() is False
    assert autostart.disable() is False
