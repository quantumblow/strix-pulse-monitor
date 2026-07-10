#!/usr/bin/env bash
# Strix Pulse Monitor — Linux uninstaller.
#   sudo ./uninstall.sh   |   ./uninstall.sh --user
set -euo pipefail
MODE="system"; [ "${1:-}" = "--user" ] && MODE="user"
if [ "$MODE" = "system" ]; then
    [ "$(id -u)" -ne 0 ] && { echo "Need root (or --user)"; exit 1; }
    APPDIR=/opt/strix-pulse-monitor; BINDIR=/usr/local/bin
    DESKTOPDIR=/usr/share/applications; ICONDIR=/usr/share/icons/hicolor/scalable/apps
else
    APPDIR="$HOME/.local/share/strix-pulse-monitor"; BINDIR="$HOME/.local/bin"
    DESKTOPDIR="$HOME/.local/share/applications"; ICONDIR="$HOME/.local/share/icons/hicolor/scalable/apps"
fi
rm -rf "$APPDIR"
rm -f  "$BINDIR/strix-pulse-monitor" "$DESKTOPDIR/strix-pulse-monitor.desktop" "$ICONDIR/strix-pulse-monitor.svg"
rm -f  "$HOME/.config/autostart/strix-pulse-monitor.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DESKTOPDIR" || true
echo "Removed Strix Pulse Monitor. (Config in ~/.config/PulseMonitor left intact.)"
