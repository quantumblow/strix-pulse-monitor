# Changelog

All notable changes to Strix Pulse Monitor are documented here. Format:
[Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [1.0.3] - 2026-11-28

### Added
- **Window scaling (0.5×–4×)** — Ctrl + mouse wheel zooms in 5 % steps around
  the pointer; the scale is saved as `scale` in `settings.json` (default 1.0)
  and restored on launch. Zoomed windows are nudged back inside the screen so
  the card can never grow out of reach.
- **Four-corner resizing** — drag any corner for a uniform resize that keeps the
  opposite corner anchored. The grab zone is `clamp(14 × scale, 10, 24)` px, and
  Pin only locks *moving*: a pinned widget can still be resized.
- **Font scale cap** — text tracks the window when shrinking below 1× but stops
  growing at **2×**, while the card and its rows keep scaling up to 4×.
- **Scaling tests** — `tests/` covers scale math, settings validation,
  Ctrl+wheel, corner anchoring, the pin exception and persistence;
  `tests/README.md` documents the manual X11 pass (0.5/1/2/4 screenshots,
  four-corner cursors, geometry and restart).

### Changed
- **Smoother zoom and corner drags** — each scale change now applies size and
  position with a single `setGeometry` request instead of re-applying fixed-size
  constraints every frame, and the shadow layer count is capped at large
  scales. The root layout no longer constrains the top-level size, so a resize
  produces one native configure per frame instead of an extra minimum-size
  resize (which made the window appear to jump sideways). Pointer-anchored
  wheel zoom keeps the window under the cursor instead of walking away.
- **Eased Ctrl+wheel zoom** — a wheel notch still adds exactly 5 %, but the card
  now eases to the new scale in roughly 120 ms instead of jumping in one frame.
  Rapid notches retarget the same animation, and the final scale is persisted
  when it settles.
- Version defaults bumped to **1.0.3** in the `.deb` builder and the NSIS
  installer fallback (release builds still take the tag version).

## [1.0.2] - 2026-11-28

### Added
- **Window layering toggle** — a new "Always on top / bottom" item in the tray
  menu and the widget context menu switches between floating above normal
  windows (`WindowStaysOnTopHint`) and the previous desktop-level behaviour
  (`WindowStaysOnBottomHint`). On X11 the runtime switch is applied with an EWMH
  `_NET_WM_STATE` client message, because Qt only honours those flags when the
  native window is created. The choice is persisted as `on_top` in
  `settings.json` and restored on launch.
- **GPU VRAM readout** — the GPU row now shows memory used/total next to utilisation
  (`8% 1.8/16G`), and the tray tooltip lists it too. NVIDIA comes from `nvidia-smi`
  `memory.used`/`memory.total`; AMD from `mem_info_vram_used`/`mem_info_vram_total` in
  the same sysfs directory as `gpu_busy_percent`. Windows GPU counters stay
  utilisation-only, and unsupported backends keep the old percentage-only row.
- **Native Linux support** — launcher, `.desktop` entry, `install.sh`/`uninstall.sh`
  (with `--autostart`), and a `.deb` builder.
- **Linux GPU utilisation** via AMD sysfs (`gpu_busy_percent`, no root); NVIDIA continues
  to work through `nvidia-smi`. Intel GPUs degrade gracefully to N/A.
- XDG-aware config directory on Linux (`~/.config/PulseMonitor`).
- Windows setup wizard: PyInstaller spec + `build.bat` + per-user NSIS installer
  (`PulseMonitor.nsi`) with optional desktop shortcut and "start with Windows".

### Changed
- Unified on the full PySide6 widget; the old **Pulse Lite** edition is superseded
  (its source was not recoverable and its features are a subset of this app).

### Fixed
- **Autostart on Linux** — the tray toggle now creates/removes the XDG drop-in
  (`~/.config/autostart/strix-pulse-monitor.desktop`) instead of silently doing
  nothing outside Windows, and the menu entry reads **"Start on login"** rather
  than claiming Windows. The drop-in runs the interpreter the app is using
  rather than the launcher, because a login session's `PATH` often lacks the
  Python that has PySide6 (e.g. a conda install), and it is regenerated when
  out of date so older entries self-heal. The checkbox reflects what is on disk.

### Security
- The Windows GPU-counter fallback now invokes **PowerShell by absolute path** instead of
  a bare name (defense-in-depth against `%PATH%` hijacking). See `SECURITY.md`.
