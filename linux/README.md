# Strix Pulse Monitor — Linux packaging

The app (`../pulse_monitor.py`) is cross-platform PySide6 + psutil. On Linux it reads
GPU utilisation (and VRAM, where the driver exposes it) from AMD sysfs
(`gpu_busy_percent`, `mem_info_vram_*`) or NVIDIA `nvidia-smi`; other GPUs show N/A.
Only packaging lives in this folder.

## Files

| File | Purpose |
|---|---|
| `strix-pulse-monitor` | Launcher — checks python3 / PySide6 / psutil, then runs the app. |
| `strix-pulse-monitor.desktop` | Application-menu (and autostart) entry. |
| `install.sh` / `uninstall.sh` | Install/remove (system or `--user`, optional `--autostart`). |
| `build-deb.sh` | Build a `.deb`. |

## Runtime dependencies

```bash
sudo apt install python3 python3-psutil
# PySide6 (name varies by release):
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore \
  || pip install PySide6
```

## Build a .deb

```bash
./linux/build-deb.sh 1.0.0
sudo apt install ./dist/strix-pulse-monitor_1.0.0_all.deb
```

PySide6 is a `Recommends` (not a hard `Depends`) because the package name differs across
Ubuntu releases; the launcher and postinst print a clear hint if it is missing.

## Notes

- Frameless "always on top" and the tray icon behave differently across desktop
  environments (GNOME needs an extension for tray icons; KDE/XFCE work out of the box).
  The widget degrades gracefully.
- Scripts are LF-only (`.gitattributes`).
