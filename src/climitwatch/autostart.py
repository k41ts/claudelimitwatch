"""Run the watcher when the desktop session starts.

Two backends, picked by platform:

* **Windows** — a shortcut in the Startup folder plus the ``StartupApproved``
  record that gives it an On/Off row in Settings. A plain ``Run`` value also
  launches at logon but never appeared in that list on Windows 11.
* **Linux** — an XDG autostart desktop entry in ``~/.config/autostart``, which
  every mainstream desktop environment reads.

Both backends expose the same calls: :func:`is_enabled`, :func:`enable`,
:func:`disable`, :func:`apply`.
"""

from __future__ import annotations

import logging
import os
import shlex
import sys
from pathlib import Path

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

APP_DISPLAY = "Claude Limit Watcher"

# --- Windows locations ------------------------------------------------------

#: Legacy mechanism. Still read (and cleaned up) so upgrades migrate.
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

# --- Linux locations --------------------------------------------------------

DESKTOP_FILE_NAME = "climitwatch.desktop"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _target() -> tuple[str, str]:
    """(executable, arguments) that starts the app."""
    if is_frozen():
        return str(Path(sys.executable).resolve()), ""

    interpreter = Path(sys.executable)
    if IS_WINDOWS:
        # pythonw keeps a console window from flashing at logon.
        windowless = interpreter.with_name("pythonw.exe")
        if windowless.exists():
            interpreter = windowless
    launcher = Path(__file__).resolve().parents[2] / "launcher.py"
    arguments = f'"{launcher}"' if IS_WINDOWS else shlex.quote(str(launcher))
    return str(interpreter), arguments


def launch_command() -> str:
    """Full command line, for display and for the desktop entry."""
    target, arguments = _target()
    if IS_WINDOWS:
        return f'"{target}" {arguments}'.strip()
    parts = [shlex.quote(target)]
    if arguments:
        parts.append(arguments)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Windows backend
# ---------------------------------------------------------------------------


def startup_dir() -> Path:
    """%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


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
        f"$l.Description = '{APP_DISPLAY}'; "
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


def _read_shortcut_target() -> str | None:
    """What the installed shortcut really points at.

    Diagnostics must not guess: a source checkout and an installed build
    register different commands, and the interesting question is always which
    one the desktop will actually run.
    """
    import subprocess

    script = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$l = $s.CreateShortcut('{shortcut_path()}'); "
        "Write-Output ($l.TargetPath + '|' + $l.Arguments)"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Could not read the shortcut: %s", exc)
        return None
    target, _, arguments = result.stdout.strip().partition("|")
    if not target:
        return None
    return f'"{target}" {arguments}'.strip()


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


def _delete_registry_value(key_path: str, name: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, name)
    except OSError:
        pass


def has_legacy_run_entry() -> bool:
    return IS_WINDOWS and _registry_value_exists(RUN_KEY, VALUE_NAME)


def _drop_legacy_run_entry() -> None:
    """Old installs used a Run value; keep only one mechanism active."""
    _delete_registry_value(RUN_KEY, VALUE_NAME)
    _delete_registry_value(APPROVED_RUN_KEY, VALUE_NAME)


def _windows_is_enabled() -> bool:
    return shortcut_path().exists() or has_legacy_run_entry()


def _windows_enable() -> bool:
    if not _create_shortcut():
        return False
    _set_approval(APPROVED_FOLDER_KEY, SHORTCUT_NAME)
    _drop_legacy_run_entry()
    return True


def _windows_disable() -> bool:
    _delete_registry_value(APPROVED_FOLDER_KEY, SHORTCUT_NAME)
    _drop_legacy_run_entry()
    try:
        shortcut_path().unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Could not remove the startup shortcut: %s", exc)
        return False
    return True


# ---------------------------------------------------------------------------
# Linux backend (XDG autostart)
# ---------------------------------------------------------------------------


def autostart_dir() -> Path:
    """$XDG_CONFIG_HOME/autostart, the spec-defined location."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "autostart"


def desktop_entry_path() -> Path:
    return autostart_dir() / DESKTOP_FILE_NAME


def desktop_entry_text() -> str:
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={APP_DISPLAY}",
            "Comment=Remaining Claude usage limits, always on top",
            f"Exec={launch_command()}",
            "Icon=climitwatch",
            "Terminal=false",
            "Categories=Utility;Monitor;",
            "X-GNOME-Autostart-enabled=true",
            "",
        ]
    )


def _linux_is_enabled() -> bool:
    path = desktop_entry_path()
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    # Desktops treat this key as an off switch even when the file is present,
    # so honour it instead of reporting a false positive.
    return "X-GNOME-Autostart-enabled=false" not in text


def _linux_enable() -> bool:
    path = desktop_entry_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry_text(), encoding="utf-8")
        path.chmod(0o644)
    except OSError as exc:
        log.warning("Could not write the autostart entry: %s", exc)
        return False
    return True


def _linux_disable() -> bool:
    try:
        desktop_entry_path().unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Could not remove the autostart entry: %s", exc)
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def supported() -> bool:
    return IS_WINDOWS or IS_LINUX


def is_enabled() -> bool:
    if IS_WINDOWS:
        return _windows_is_enabled()
    if IS_LINUX:
        return _linux_is_enabled()
    return False


def is_listed() -> bool:
    """Whether the desktop has an On/Off record for our startup item.

    Windows keeps that state in the registry; on Linux the desktop entry file
    is itself the record.
    """
    if IS_WINDOWS:
        return _registry_value_exists(APPROVED_FOLDER_KEY, SHORTCUT_NAME) or (
            _registry_value_exists(APPROVED_RUN_KEY, VALUE_NAME)
        )
    if IS_LINUX:
        return desktop_entry_path().exists()
    return False


def current_command() -> str | None:
    """What will actually run at logon, for display and debugging."""
    if not is_enabled():
        return None
    if IS_LINUX:
        try:
            for line in desktop_entry_path().read_text(encoding="utf-8").splitlines():
                if line.startswith("Exec="):
                    return line[len("Exec=") :]
        except OSError:
            return None
        return None
    if IS_WINDOWS:
        if shortcut_path().exists():
            return _read_shortcut_target() or launch_command()
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
                return str(value)
        except OSError:
            return None
    return launch_command()


def enable() -> bool:
    """Register (or refresh) the logon entry. Returns True on success."""
    if IS_WINDOWS:
        return _windows_enable()
    if IS_LINUX:
        return _linux_enable()
    return False


def disable() -> bool:
    """Remove the logon entry. A missing entry counts as success."""
    if IS_WINDOWS:
        return _windows_disable()
    if IS_LINUX:
        return _linux_disable()
    return False


def apply(enabled: bool) -> bool:
    return enable() if enabled else disable()
