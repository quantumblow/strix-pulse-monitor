# Installing Strix Pulse Monitor on Linux

## Quick install (.deb)

```bash
sudo apt install ./strix-pulse-monitor_1.0.3_all.deb   # from Releases
```

If PySide6 is not present, install it:

```bash
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore \
  || pip install PySide6
```

## From source

```bash
git clone https://github.com/strix-tool/strix-pulse-monitor
cd strix-pulse-monitor
sudo ./linux/install.sh                 # system-wide
./linux/install.sh --user               # per-user
./linux/install.sh --user --autostart   # per-user + start with session
```

Or run directly:

```bash
sudo apt install python3-psutil
pip install PySide6
python3 pulse_monitor.py
```

## GPU notes

- **NVIDIA:** works via `nvidia-smi` (installed with the driver) — utilisation and VRAM
  (`memory.used` / `memory.total`).
- **AMD:** read from `/sys/class/drm/card*/device/` — `gpu_busy_percent` for utilisation and
  `mem_info_vram_used` / `mem_info_vram_total` for VRAM. No root, no tools.
- **Intel:** live per-cent needs privileged tooling, so the GPU row shows **N/A** by design
  (the widget never asks for root).

## Tray & always-on-top

Behavior varies by desktop environment. On GNOME, install a "tray icons" extension to see
the system-tray icon. KDE Plasma and XFCE work out of the box.

## Verify the download

```bash
sha256sum -c SHA256SUMS
```
