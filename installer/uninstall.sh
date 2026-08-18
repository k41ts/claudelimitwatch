#!/usr/bin/env bash
# Remove Claude Limit Watcher for the current user (Linux).
#
#   ./uninstall.sh           keep settings and saved accounts
#   ./uninstall.sh --purge   delete them too
#
# ~/.claude is never touched.

set -euo pipefail

APP_NAME="climitwatch"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_NAME"

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

step() { printf '  %s\n' "$1"; }

if pkill -f "$APP_NAME" 2>/dev/null; then
  step "Stopped the running copy"
  sleep 1
fi

step "Removing the autostart entry"
rm -f "$AUTOSTART_DIR/$APP_NAME.desktop"

step "Removing the menu entry and icons"
rm -f "$DESKTOP_DIR/$APP_NAME.desktop"
for size in 48 128 256; do
  rm -f "$ICON_DIR/${size}x${size}/apps/$APP_NAME.png"
done

step "Removing the launcher"
rm -f "$BIN_DIR/$APP_NAME"

if [[ $PURGE -eq 1 ]]; then
  step "Deleting settings and saved accounts"
  rm -rf "$CONFIG_DIR" "$PREFIX"
else
  # The venv and sources live in $PREFIX; settings and accounts do too on
  # Linux, so keep the data files and drop only the program itself.
  step "Removing program files (settings and accounts kept in $CONFIG_DIR)"
  rm -rf "$PREFIX/venv" "$PREFIX/src" "$PREFIX/launcher.py" "$PREFIX/ClimitWatch"
fi

command -v update-desktop-database >/dev/null && \
  update-desktop-database -q "$DESKTOP_DIR" 2>/dev/null || true

echo
echo "Claude Limit Watcher removed."
[[ $PURGE -eq 0 ]] && echo "Saved accounts kept. Re-run with --purge to delete them."
exit 0
