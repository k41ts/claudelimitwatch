"""Platform window tweaks. Windows-specific, no-ops elsewhere."""

from __future__ import annotations

import ctypes
import logging
import os
import sys

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080


def reassert_topmost(win_id: int) -> None:
    """Push the window back to the top of the z-order.

    Other topmost windows (and Windows itself, after a full-screen app takes
    over) can bump us down; calling this on a timer keeps the overlay visible.
    Exclusive-fullscreen apps still cover it -- that is a Windows limitation.
    """
    if not _IS_WINDOWS or not win_id:
        return
    try:
        ctypes.windll.user32.SetWindowPos(
            int(win_id), HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except OSError:
        pass


def make_non_activating(win_id: int) -> None:
    """Stop the overlay from stealing focus when clicked."""
    if not _IS_WINDOWS or not win_id:
        return
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(int(win_id), GWL_EXSTYLE)
        user32.SetWindowLongW(int(win_id), GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except OSError:
        pass


def platform_warning() -> str | None:
    """A caveat worth telling the user about this session, if any.

    Wayland compositors own the stacking order: Qt asks to stay on top, but
    the request is advisory and most compositors ignore it. Better to say so
    than to let the overlay quietly sink behind other windows.
    """
    if _IS_WINDOWS:
        return None
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return (
            "Wayland session detected: the compositor decides window stacking, "
            "so always-on-top may not work. An X11/Xorg session behaves as expected."
        )
    return None
