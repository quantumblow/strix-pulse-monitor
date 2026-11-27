# Changelog

All notable changes to Strix Pulse Monitor are documented here. Format:
[Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
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
  than claiming Windows. A drop-in created by `install.sh --autostart` (or edited
  by hand) is preserved, and the checkbox reflects what is actually on disk.

### Security
- The Windows GPU-counter fallback now invokes **PowerShell by absolute path** instead of
  a bare name (defense-in-depth against `%PATH%` hijacking). See `SECURITY.md`.
