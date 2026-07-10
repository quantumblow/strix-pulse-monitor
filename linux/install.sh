#!/usr/bin/env bash
# Strix Pulse Monitor — Linux installer (Ubuntu/Debian).
#   sudo ./install.sh          # system-wide
#        ./install.sh --user   # per-user (no root)
#        ./install.sh --user --autostart   # also start with the session
set -euo pipefail

MODE="system"; AUTOSTART="no"
for a in "$@"; do
    [ "$a" = "--user" ] && MODE="user"
    [ "$a" = "--autostart" ] && AUTOSTART="yes"
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$MODE" = "system" ]; then
    [ "$(id -u)" -ne 0 ] && { echo "System install needs root (or use --user)"; exit 1; }
    APPDIR=/opt/strix-pulse-monitor; BINDIR=/usr/local/bin
    DESKTOPDIR=/usr/share/applications; ICONDIR=/usr/share/icons/hicolor/scalable/apps
else
    APPDIR="$HOME/.local/share/strix-pulse-monitor"; BINDIR="$HOME/.local/bin"
    DESKTOPDIR="$HOME/.local/share/applications"; ICONDIR="$HOME/.local/share/icons/hicolor/scalable/apps"
fi

echo "==> Installing runtime dependencies (best-effort)…"
if command -v apt-get >/dev/null 2>&1; then
    SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
    $SUDO apt-get update -qq || true
    # PySide6 apt package names vary by release; try, then fall back to pip.
    $SUDO apt-get install -y python3 python3-psutil python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore 2>/dev/null \
        || $SUDO apt-get install -y python3 python3-psutil 2>/dev/null || true
    if ! python3 -c 'import PySide6' >/dev/null 2>&1; then
        if [ "$(id -u)" -ne 0 ]; then
            echo "  PySide6 not available via apt; installing via pip (--user)…"
            python3 -m pip install --user PySide6 || pip3 install --user PySide6 || \
                echo "  Could not install PySide6 automatically — see linux/README.md"
        else
            # Never pip-install as root: it would land in /root/.local where the
            # target user can't see it. Tell the user to install it themselves.
            echo "  PySide6 not found. Install it (NOT as root), e.g.:"
            echo "    sudo apt install python3-pyside6.qtwidgets   # or:  pip install --user PySide6"
        fi
    fi
else
    echo "  Non-apt system: install python3, python3-psutil and PySide6 yourself."
fi

echo "==> Installing app to $APPDIR"
mkdir -p "$APPDIR" "$BINDIR" "$DESKTOPDIR" "$ICONDIR"
install -m 0644 "$REPO/pulse_monitor.py" "$APPDIR/pulse_monitor.py"
install -m 0644 "$REPO/strix_i18n.py"    "$APPDIR/strix_i18n.py"
# Bundled UI translations (13 languages).
mkdir -p "$APPDIR/i18n"
install -m 0644 "$REPO/i18n/"*.json      "$APPDIR/i18n/"
install -m 0755 "$REPO/linux/strix-pulse-monitor" "$BINDIR/strix-pulse-monitor"
install -m 0644 "$REPO/linux/strix-pulse-monitor.desktop" "$DESKTOPDIR/strix-pulse-monitor.desktop"
[ -f "$REPO/linux/strix-pulse-monitor.svg" ] \
    && install -m 0644 "$REPO/linux/strix-pulse-monitor.svg" "$ICONDIR/strix-pulse-monitor.svg" || true

if [ "$AUTOSTART" = "yes" ]; then
    AUTODIR="$HOME/.config/autostart"; mkdir -p "$AUTODIR"
    install -m 0644 "$REPO/linux/strix-pulse-monitor.desktop" "$AUTODIR/strix-pulse-monitor.desktop"
    echo "==> Enabled autostart (~/.config/autostart)."
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DESKTOPDIR" || true
echo "==> Done. Launch from your menu or run: strix-pulse-monitor"
[ "$MODE" = "user" ] && echo "    (Ensure $BINDIR is on your PATH.)"
