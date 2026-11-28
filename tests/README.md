# Tests

## Automated

```bash
python -m pytest tests -q
```

Requires Python 3.10+, PySide6 and psutil. The widget tests force Qt's
**offscreen** platform (see `conftest.py`) so they never depend on a window
manager, a tray or the current desktop session; `DISPLAY` is not needed.

- `test_scaling.py` — pure helpers: the 0.5–4.0 clamp, 5 % wheel steps, the 2×
  font cap, the `clamp(14 × scale, 10, 24)` grip, corner hit-testing, uniform
  drag math, opposite-corner anchoring, layout metrics and settings validation.
- `test_scaling_ui.py` — a real `PulseWidget` driven through its event
  handlers: Ctrl+wheel (step, pointer anchor, clamping), font cap on the actual
  labels, the four corner cursors, resizing from every corner, Pin locking
  moving but not resizing, and scale/position persistence across a reload.

## Manual X11 pass

The automated tests cannot cover window-manager behaviour. The v1.0.3 release
was checked on a real X11 session with `xdotool` + ImageMagick against a
throw-away config:

```bash
CFG=$(mktemp -d)
XDG_CONFIG_HOME="$CFG" python3 pulse_monitor.py &
```

1. **Scales** — with the pointer over the card, Ctrl+wheel up four notches gives
   `scale: 1.2` in `$CFG/PulseMonitor/settings.json`; scrolling down clamps at
   `0.5`, scrolling up clamps at `4.0`. Capture the window at 0.5/1/2/4 by
   writing `"scale"` into `settings.json` before launch and compare the physical
   size with `layout_metrics(scale)`.
2. **Corners** — grab each corner: the cursor becomes a diagonal resize cursor,
   both dimensions scale together and the opposite corner does not move. The
   grab zone is 10 px at 0.5×, 14 px at 1× and 24 px from 2× up.
3. **Pin** — with Pin on, dragging the body does not move the card, but dragging
   a corner still resizes it.
4. **Persistence** — restart the app: `scale`, `x`, `y` and the resulting window
   geometry are restored from `settings.json`.
5. **Screenshots** — `import -window <id> shot.png` then
   `convert shot.png -background '#343a46' -flatten shot-flat.png` (the card is
   translucent, so flatten it before sharing).
