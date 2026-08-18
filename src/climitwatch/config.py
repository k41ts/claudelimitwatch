"""Filesystem locations and user preferences.

Kept free of Qt imports so the headless debug CLI can use it too.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "ClimitWatch"

# --- Claude Code locations -------------------------------------------------

CLAUDE_DIR = Path.home() / ".claude"
CREDENTIALS_PATH = CLAUDE_DIR / ".credentials.json"
CLAUDE_CONFIG_PATH = Path.home() / ".claude.json"

# --- Endpoints (Claude Code CLI 2.1.234) -----------------------------------

API_BASE_URL = "https://api.anthropic.com"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
MANUAL_REDIRECT_URL = "https://platform.claude.com/oauth/code/callback"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_SCOPES = [
    "user:profile",
    "user:inference",
    "user:sessions:claude_code",
    "user:mcp_servers",
    "user:file_upload",
]
USER_AGENT = "climitwatch/0.1 (local usage monitor)"


IS_WINDOWS = sys.platform == "win32"


def app_dir() -> Path:
    """Per-user data directory, created on demand.

    Windows keeps everything under %LOCALAPPDATA%\\ClimitWatch; elsewhere the
    XDG base directory spec applies, so data lands in
    ~/.local/share/climitwatch.
    """
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        path = root / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
        path = root / APP_NAME.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Preferences: same place as the data on Windows, XDG config on Linux."""
    if IS_WINDOWS:
        return app_dir()
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    path = root / APP_NAME.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"


def accounts_path() -> Path:
    return app_dir() / "accounts.dat"


def cache_path() -> Path:
    return app_dir() / "snapshots.json"


def atomic_write(path: Path, data: str) -> None:
    """Write via a temp file in the same directory, then os.replace()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class Settings:
    """User preferences, persisted as JSON."""

    #: One of climitwatch.ui.theme.PALETTES ("cyberpunk" or "dark").
    theme: str = "cyberpunk"
    # Claude Code itself refetches /api/oauth/usage at most every 5 minutes
    # (cache write throttle) and treats the value as good for an hour.
    # Polling faster than that earns HTTP 429.
    poll_seconds: int = 300
    idle_poll_seconds: int = 900
    busy_poll_seconds: int = 120
    warn_threshold: float = 80.0
    danger_threshold: float = 95.0
    notifications: bool = True
    opacity: float = 0.92
    minibar_pos: list[int] | None = None
    minibar_visible: bool = True
    #: Every watched account gets its own row; the mini-bar context menu can
    #: narrow it down to one when the bar gets too wide.
    show_all_accounts: bool = True
    selected_account: str | None = None
    read_only_credentials: bool = False
    start_with_windows: bool = False
    reassert_topmost: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        path = settings_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        atomic_write(settings_path(), json.dumps(asdict(self), indent=2))
