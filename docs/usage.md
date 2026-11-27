# Using Strix Pulse Monitor

The widget appears as a small frameless card, always on top.

| Action | How |
|---|---|
| Move it | Left-click and drag anywhere on the card |
| Pin / lock position | Click the pin button (locks so drags are ignored) |
| Hide to tray | Click ✕ |
| Show / hide again | Click the tray icon |
| Exit completely | Right-click the tray icon → Exit |

## What the rows mean

- **CPU / RAM / Storage** — percentage in use.
- **GPU** — utilisation (the bar) from NVIDIA/AMD plus VRAM used/total next to it,
  e.g. `8% 1.8/16G`; **N/A** if no supported source.
- **NET** — live download / upload throughput.

## Settings

Window position and pin state are saved automatically and restored next launch:

- **Windows:** `%APPDATA%\PulseMonitor\settings.json`
- **Linux:** `~/.config/PulseMonitor/settings.json`

## Customization

Open `pulse_monitor.py` — the top has a **theme tokens** section (accent colors, background
opacity `BG`, refresh interval `REFRESH_MS`, and the widget width).
