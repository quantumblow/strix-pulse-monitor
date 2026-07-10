
# Strix Pulse Monitor

> A sleek, always-on-top **desktop system monitor** — live CPU, GPU, RAM and disk
> usage plus real-time network download/upload, in a frameless glass widget you can
> drag anywhere. Offline, no telemetry.

[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-blue.svg)](#installation)
[![Security](https://img.shields.io/badge/security-hardened-success.svg)](SECURITY.md)

Part of the open-source **[Strix Advanced Tools](https://github.com/strix-tool)** suite.

## Features

- Live **CPU, GPU, RAM, Storage** usage and **network down/up** traffic, refreshed once a second.
- **Frameless glass widget** — drag to move, pin to lock, hide to tray.
- **GPU support:** NVIDIA via `nvidia-smi`; on Windows, Intel/AMD via GPU performance
  counters; on **Linux, AMD via sysfs** (`gpu_busy_percent`, no root). Falls back to N/A gracefully.
- Position & pin state saved and restored between runs.
- **Hardened:** no network, no shell strings, no elevation. Settings are validated on load
  and written atomically. See [SECURITY.md](SECURITY.md).

## Screenshots

See [`docs/screenshots/`](docs/screenshots/).

## Installation

### Windows

Download **`Strix Pulse Monitor Setup.exe`** from
[Releases](https://github.com/strix-tool/strix-pulse-monitor/releases) and run the
wizard. Or run from source:

```bat
pip install -r requirements.txt
python pulse_monitor.py
```

> Unsigned build → SmartScreen shows "unknown publisher" on first run; choose
> **More info → Run anyway**. See [docs/install-windows.md](docs/install-windows.md).

### Linux (Ubuntu / Debian)

```bash
sudo apt install ./strix-pulse-monitor_1.0.0_all.deb     # from Releases
# or from source:
sudo ./linux/install.sh            # add --user for a per-user install
./linux/install.sh --user --autostart   # start automatically with your session
```

Requires `python3-psutil` and **PySide6** (`python3-pyside6.*` or `pip install PySide6`).
Details: [docs/install-linux.md](docs/install-linux.md).

## Controls

| Action | How |
|---|---|
| Move | Left-click and drag |
| Pin / lock | Click the pin button |
| Hide to tray | Click ✕ |
| Show/hide | Click the tray icon |
| Exit | Right-click tray → Exit |

## Start automatically

- **Windows:** put a shortcut to the app in `shell:startup`.
- **Linux:** `./linux/install.sh --user --autostart`, or copy the `.desktop` into
  `~/.config/autostart`.

## Requirements

| Component | Windows | Linux |
|---|---|---|
| Python 3.10+ | from source | `python3` |
| PySide6 | `pip` | `python3-pyside6.*` / `pip` |
| psutil | `pip` | `python3-psutil` |

## License

[MIT](LICENSE) © 2026 Strix Advanced Tools.
