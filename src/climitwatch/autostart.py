"""Run the watcher when Windows starts.

Uses the per-user Run key (``HKCU``), so no admin rights and no scheduled task
are involved -- and removing the entry is just as cheap as adding it.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

#: Legacy mechanism. Still read (and cleaned up) so upgrades migrate, but a
#: fresh enable() uses the Startup folder instead: a plain Run value never
#: showed up in Settings > Apps > Startup on Windows 11 here, while a shortcut
#: is something the user can see and manage directly.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ClimitWatch"

#: Windows records the On/Off state of startup items here, keyed by Run value
#: name or by shortcut file name.
APPROVED_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
APPROVED_FOLDER_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
)
#: First DWORD 0x02 = enabled, 0x03 = disabled by the user; the trailing 8 bytes
#: are a FILETIME that Windows accepts as zeroes.
APPROVED_ENABLED = bytes([2] + [0] * 11)

SHORTCUT_NAME = "Claude Limit Watcher.lnk"

_IS_WINDOWS = sys.platform == "win32"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_command() -> str:
    """The command Windows should run at logon, quoted for the registry."""
    if is_frozen():
        return f'"{Path(sys.executable).resolve()}"'

    # Source checkout: launcher.py puts src/ on sys.path itself, and pythonw
    # keeps the console window from flashing.
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = interpreter
    launcher = Path(__file__).resolve().parents[2] / "launcher.py"
    return f'"{pythonw}" "{launcher}"'


def startup_dir() -> Path:
    """%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"""
    import os

    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def _target() -> tuple[str, str]:
    """(exe, arguments) for the shortcut."""
    if is_frozen():
        return str(Path(sys.executable).resolve()), ""
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = interpreter
    launcher = Path(__file__).resolve().parents[2] / "launcher.py"
    return str(pythonw), f'"{launcher}"'


def _create_shortcut() -> bool:
    """Write the .lnk via WScript.Shell (no extra dependency needed)."""
    import subprocess

    target, arguments = _target()
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$l = $s.CreateShortcut('{link}'); "
        f"$l.TargetPath = '{target}'; "
        f"$l.Arguments = '{arguments}'; "
        f"$l.WorkingDirectory = '{Path(target).parent}'; "
        "$l.Description = 'Claude Limit Watcher'; "
        "$l.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Could not create the startup shortcut: %s", exc)
        return False
    return link.exists()


def _registry_value_exists(key_path: str, name: str) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, name)
    except OSError:
        return False
    return True


def _set_approval(key_path: str, name: str) -> None:
    import winreg

    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_BINARY, APPROVED_ENABLED)
    except OSError as exc:  # Not fatal: the shortcut alone still autostarts.
        log.debug("Could not write startup approval: %s", exc)


def _delete_value(key_path: str, name: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, name)
    except OSError:
        pass


def has_legacy_run_entry() -> bool:
    return _IS_WINDOWS and _registry_value_exists(RUN_KEY, VALUE_NAME)


def _drop_legacy_run_entry() -> None:
    """Old installs used a Run value; keep only one mechanism active."""
    _delete_value(RUN_KEY, VALUE_NAME)
    _delete_value(APPROVED_RUN_KEY, VALUE_NAME)


def is_enabled() -> bool:
    if not _IS_WINDOWS:
        return False
    return shortcut_path().exists() or has_legacy_run_entry()


def current_command() -> str | None:
    """What will actually run at logon, for display and debugging."""
    if not _IS_WINDOWS:
        return None
    if shortcut_path().exists():
        target, arguments = _target()
        return f'"{target}" {arguments}'.strip()
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def is_listed() -> bool:
    """Whether Windows has an On/Off record for our startup item."""
    if not _IS_WINDOWS:
        return False
    return _registry_value_exists(APPROVED_FOLDER_KEY, SHORTCUT_NAME) or _registry_value_exists(
        APPROVED_RUN_KEY, VALUE_NAME
    )


def enable() -> bool:
    """Create (or refresh) the logon shortcut. Returns True on success."""
    if not _IS_WINDOWS:
        return False
    if not _create_shortcut():
        return False
    _set_approval(APPROVED_FOLDER_KEY, SHORTCUT_NAME)
    _drop_legacy_run_entry()
    return True


def disable() -> bool:
    """Remove the logon shortcut and any legacy entry."""
    if not _IS_WINDOWS:
        return False
    _delete_value(APPROVED_FOLDER_KEY, SHORTCUT_NAME)
    _drop_legacy_run_entry()
    try:
        shortcut_path().unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Could not remove the startup shortcut: %s", exc)
        return False
    return True


def apply(enabled: bool) -> bool:
    return enable() if enabled else disable()
