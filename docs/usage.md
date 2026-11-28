# Using Strix Pulse Monitor

The widget appears as a small frameless card. It sits at desktop level by
default, so normal windows cover it; switch it to "Always on top" to keep it
above every other window.

| Action | How |
|---|---|
| Move it | Left-click and drag anywhere on the card |
| Resize it | Drag any of the four corners |
| Zoom it | Ctrl + mouse wheel (5 % per notch) |
| Pin / lock position | Click the pin button (locks moving; corner resizing still works) |
| Float above / behind other windows | Right-click the widget or tray icon → "Always on top / bottom" (checked = floats above) |
| Hide to tray | Click ✕ |
| Show / hide again | Click the tray icon |
| Exit completely | Right-click the tray icon → Exit |

> On a Wayland session the stacking hint is compositor-dependent; the X11
> session applies it through EWMH.

## Window size and zoom

The card scales proportionally between **0.5× and 4×**, and the chosen size is
remembered across launches.

- **Ctrl + mouse wheel** changes the scale by **5 % per notch**, anchored under
  the pointer so the card grows or shrinks around what you are looking at.
- **Drag a corner** to resize: both dimensions scale together, the opposite
  corner stays fixed, and the grab zone is `clamp(14 × scale, 10, 24)` px.
  The pin only locks moving, so a pinned widget can still be resized.
- **Text stops growing at 2×** even when the card is larger; below 1× the text
  shrinks along with the window. Rows and bars always keep the window's scale.

## What the rows mean

- **CPU / RAM / Storage** — percentage in use.
- **GPU** — utilisation (the bar) from NVIDIA/AMD plus VRAM used/total next to it,
  e.g. `8% 1.8/16G`; **N/A** if no supported source.
- **NET** — live download / upload throughput.

## Settings

Window position, scale (`scale` key, 0.5–4.0), pin and layering state are
saved automatically and restored next launch:

- **Windows:** `%APPDATA%\PulseMonitor\settings.json`
- **Linux:** `~/.config/PulseMonitor/settings.json`

## Customization

Open `pulse_monitor.py` — the top has a **theme tokens** section (accent colors, background
opacity `BG`, refresh interval `REFRESH_MS`, and the widget width at 1×, which the zoom scales).
