"""Autostart via a Startup-folder shortcut.

Tests redirect the shortcut into a temp folder and the approval records into a
throwaway HKCU namespace, so the real logon configuration is never touched.
"""

import sys
import uuid
from pathlib import Path

import pytest

from climitwatch import autostart

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only feature")


@pytest.fixture()
def sandbox(monkeypatch, tmp_path):
    """Point every side effect at temp locations."""
    base = rf"Software\ClimitWatchTests\{uuid.uuid4().hex[:12]}"
    folder_key = base + r"\StartupFolder"
    run_key = base + r"\Run"
    approved_run_key = base + r"\ApprovedRun"

    startup = tmp_path / "Startup"
    startup.mkdir()

    monkeypatch.setattr(autostart, "startup_dir", lambda: startup)
    monkeypatch.setattr(autostart, "APPROVED_FOLDER_KEY", folder_key)
    monkeypatch.setattr(autostart, "APPROVED_RUN_KEY", approved_run_key)
    monkeypatch.setattr(autostart, "RUN_KEY", run_key)
    yield startup

    import winreg

    for key in (folder_key, run_key, approved_run_key, base):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass


def test_disabled_by_default(sandbox):
    assert autostart.is_enabled() is False
    assert autostart.is_listed() is False


def test_enable_creates_a_real_shortcut(sandbox):
    assert autostart.enable() is True

    link = autostart.shortcut_path()
    assert link.exists()
    assert link.parent == sandbox
    assert link.suffix == ".lnk"
    assert link.stat().st_size > 0
    assert autostart.is_enabled() is True


def test_enable_registers_the_on_off_record(sandbox):
    """Without this record Windows shows no toggle for the item."""
    autostart.enable()
    assert autostart.is_listed() is True

    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.APPROVED_FOLDER_KEY) as key:
        value, kind = winreg.QueryValueEx(key, autostart.SHORTCUT_NAME)
    assert kind == winreg.REG_BINARY
    assert bytes(value)[0] == 2, "0x02 is the 'enabled' marker"
    assert len(bytes(value)) == 12


def test_disable_removes_shortcut_and_record(sandbox):
    autostart.enable()
    assert autostart.disable() is True
    assert not autostart.shortcut_path().exists()
    assert autostart.is_enabled() is False
    assert autostart.is_listed() is False


def test_disable_is_idempotent(sandbox):
    assert autostart.disable() is True
    assert autostart.disable() is True


def test_apply_switches_both_ways(sandbox):
    autostart.apply(True)
    assert autostart.is_enabled() is True
    autostart.apply(False)
    assert autostart.is_enabled() is False


def test_legacy_run_entry_is_migrated_away(sandbox):
    """Old installs used a Run value; only one mechanism may stay active."""
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, autostart.VALUE_NAME, 0, winreg.REG_SZ, r'"C:\old\path.exe"')
    assert autostart.has_legacy_run_entry() is True
    assert autostart.is_enabled() is True  # the old entry still counts

    autostart.enable()
    assert autostart.has_legacy_run_entry() is False
    assert autostart.shortcut_path().exists()


def test_enable_refreshes_a_stale_shortcut(sandbox):
    autostart.enable()
    link = autostart.shortcut_path()
    link.write_bytes(b"not a shortcut")

    autostart.enable()
    assert link.stat().st_size > len(b"not a shortcut")


def test_frozen_build_targets_the_exe(monkeypatch):
    monkeypatch.setattr(autostart, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\ClimitWatch.exe", raising=False)
    target, arguments = autostart._target()
    assert target == r"C:\Apps\ClimitWatch.exe"
    assert arguments == ""


def test_source_checkout_targets_the_launcher(monkeypatch):
    monkeypatch.setattr(autostart, "is_frozen", lambda: False)
    target, arguments = autostart._target()
    assert Path(target).name.lower().startswith("python")
    assert "launcher.py" in arguments


def test_current_command_reports_the_shortcut_target(sandbox):
    autostart.enable()
    command = autostart.current_command()
    assert command is not None
    assert command.startswith('"')
