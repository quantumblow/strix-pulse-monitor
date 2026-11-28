#!/usr/bin/env bash
# Build a .deb for Strix Pulse Monitor.
#   ./linux/build-deb.sh [VERSION]     (default 1.0.4)
set -euo pipefail
VERSION="${1:-1.0.4}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PKG="strix-pulse-monitor"
STAGE="$(mktemp -d)"; ROOT="$STAGE/pkg"

mkdir -p "$ROOT/DEBIAN" "$ROOT/opt/$PKG" "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" \
         "$ROOT/usr/share/doc/$PKG"

install -m 0644 "$REPO/pulse_monitor.py" "$ROOT/opt/$PKG/pulse_monitor.py"
install -m 0644 "$REPO/strix_i18n.py"    "$ROOT/opt/$PKG/strix_i18n.py"
# Bundled UI translations (13 languages).
mkdir -p "$ROOT/opt/$PKG/i18n"
install -m 0644 "$REPO/i18n/"*.json      "$ROOT/opt/$PKG/i18n/"
install -m 0755 "$REPO/linux/strix-pulse-monitor" "$ROOT/usr/bin/strix-pulse-monitor"
install -m 0644 "$REPO/linux/strix-pulse-monitor.desktop" "$ROOT/usr/share/applications/strix-pulse-monitor.desktop"
[ -f "$REPO/linux/strix-pulse-monitor.svg" ] \
    && install -m 0644 "$REPO/linux/strix-pulse-monitor.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/strix-pulse-monitor.svg" || true
[ -f "$REPO/LICENSE" ] && install -m 0644 "$REPO/LICENSE" "$ROOT/usr/share/doc/$PKG/copyright" || true

# psutil is packaged; PySide6 apt names vary, so it is a Recommends + runtime check.
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: all
Maintainer: Strix Advanced Tools <noreply@users.noreply.github.com>
Depends: python3, python3-psutil
Recommends: python3-pyside6.qtwidgets, python3-pyside6.qtgui, python3-pyside6.qtcore
Section: utils
Priority: optional
Homepage: https://github.com/quantumblow/strix-pulse-monitor
Description: Always-on-top system monitor widget
 A frameless, draggable desktop widget showing live CPU, GPU, RAM and disk
 usage plus real-time network download/upload. No network, no telemetry.
EOF

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true
if ! python3 -c 'import PySide6' >/dev/null 2>&1; then
    echo "Note: PySide6 is required. Install it: sudo apt install python3-pyside6.qtwidgets (or pip install PySide6)"
fi
exit 0
EOF
chmod 0755 "$ROOT/DEBIAN/postinst"

mkdir -p "$REPO/dist"
OUT="$REPO/dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$ROOT" "$OUT"
echo "Built: $OUT"
rm -rf "$STAGE"
