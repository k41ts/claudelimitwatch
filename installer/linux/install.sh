#!/usr/bin/env bash
# Install Claude Limit Watcher for the current user (Linux).
#
# Everything lands under $HOME: no sudo, no system packages touched.
#
#   installer/linux/install.sh                 install from a source checkout
#   installer/linux/install.sh --binary PATH   install a prebuilt binary
#   installer/linux/install.sh --no-autostart  skip the XDG autostart entry
#   installer/linux/install.sh --no-launch     do not start the app afterwards
#
# Uninstall with installer/linux/uninstall.sh (add --purge to drop settings too).

set -euo pipefail

APP_NAME="climitwatch"
APP_DISPLAY="Claude Limit Watcher"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

# installer/linux -> repo root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BINARY=""
AUTOSTART=1
LAUNCH=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --binary) BINARY="${2:?--binary needs a path}"; shift 2 ;;
    --no-autostart) AUTOSTART=0; shift ;;
    --no-launch) LAUNCH=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '  %s\n' "$1"; }

# The app is single-instance: a survivor would make the new copy hand over and
# exit, which looks exactly like the install did nothing.
if pkill -f "$APP_NAME" 2>/dev/null; then
  step "Stopped a running instance"
  sleep 1
fi

mkdir -p "$PREFIX" "$BIN_DIR" "$DESKTOP_DIR" "$AUTOSTART_DIR"

if [[ -n "$BINARY" ]]; then
  [[ -f "$BINARY" ]] || { echo "no such file: $BINARY" >&2; exit 1; }
  step "Installing binary into $PREFIX"
  install -m 755 "$BINARY" "$PREFIX/ClimitWatch"
  EXEC_CMD="$PREFIX/ClimitWatch"
else
  command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
  step "Copying sources into $PREFIX"
  rm -rf "$PREFIX/src" "$PREFIX/launcher.py"
  cp -r "$REPO_ROOT/src" "$PREFIX/src"
  cp "$REPO_ROOT/launcher.py" "$PREFIX/launcher.py"

  step "Creating a virtualenv and installing dependencies"
  python3 -m venv "$PREFIX/venv"
  "$PREFIX/venv/bin/pip" install --quiet --upgrade pip
  "$PREFIX/venv/bin/pip" install --quiet PySide6 httpx
  # Optional: keyring storage for extra accounts. Without it the token file
  # falls back to 0600 permissions, which the app reports honestly.
  "$PREFIX/venv/bin/pip" install --quiet SecretStorage || \
    step "SecretStorage unavailable; extra accounts will use a 0600 file"
  EXEC_CMD="$PREFIX/venv/bin/python $PREFIX/launcher.py"
fi

step "Adding the $APP_NAME launcher to $BIN_DIR"
cat > "$BIN_DIR/$APP_NAME" <<LAUNCHER
#!/usr/bin/env bash
exec $EXEC_CMD "\$@"
LAUNCHER
chmod 755 "$BIN_DIR/$APP_NAME"

step "Installing icons"
for size in 48 128 256; do
  icon_src="$REPO_ROOT/assets/climitwatch-$size.png"
  if [[ -f "$icon_src" ]]; then
    mkdir -p "$ICON_DIR/${size}x${size}/apps"
    install -m 644 "$icon_src" "$ICON_DIR/${size}x${size}/apps/$APP_NAME.png"
  fi
done
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -q -t -f "$ICON_DIR" 2>/dev/null || true

write_desktop_entry() {
  cat > "$1" <<ENTRY
[Desktop Entry]
Type=Application
Name=$APP_DISPLAY
Comment=Remaining Claude usage limits, always on top
Exec=$EXEC_CMD
Icon=$APP_NAME
Terminal=false
Categories=Utility;Monitor;
X-GNOME-Autostart-enabled=true
ENTRY
  chmod 644 "$1"
}

step "Adding the application menu entry"
write_desktop_entry "$DESKTOP_DIR/$APP_NAME.desktop"
command -v update-desktop-database >/dev/null && \
  update-desktop-database -q "$DESKTOP_DIR" 2>/dev/null || true

if [[ $AUTOSTART -eq 1 ]]; then
  step "Enabling start at login"
  write_desktop_entry "$AUTOSTART_DIR/$APP_NAME.desktop"
fi

if [[ $LAUNCH -eq 1 ]]; then
  step "Starting the app"
  ("$BIN_DIR/$APP_NAME" >/dev/null 2>&1 &)
  sleep 3
  pgrep -f "$APP_NAME" >/dev/null || \
    echo "  WARNING: the app exited right after starting. Run '$BIN_DIR/$APP_NAME' in a terminal to see why."
fi

echo
echo "Installed to $PREFIX"
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "Run it with: $APP_NAME" ;;
  *) echo "Run it with: $BIN_DIR/$APP_NAME   ($BIN_DIR is not on your PATH)" ;;
esac
echo "Uninstall with: $(dirname "${BASH_SOURCE[0]}")/uninstall.sh"
