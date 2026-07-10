# Installing Strix Pulse Monitor on Windows

## Setup wizard (recommended)

Download **`Strix-Pulse-Monitor-Setup.exe`** from
[Releases](https://github.com/strix-tool/strix-pulse-monitor/releases) and run it. It is
a **per-user** install (no admin prompt), creates Start-Menu/optional Desktop shortcuts,
an optional "start with Windows" entry, and an uninstaller in **Apps & features**.

> Unsigned build → SmartScreen shows "unknown publisher" on first run. Choose
> **More info → Run anyway**, or verify the SHA-256 against `SHA256SUMS` first. Do not
> disable Defender.

## Build it yourself

On Windows with Python 3.10+ and NSIS:

```bat
windows\build.bat
makensis windows\PulseMonitor.nsi
```

`build.bat` produces `windows\dist\Strix Pulse Monitor.exe` (PyInstaller, no console);
`makensis` wraps it into the setup wizard.

## Run from source

```bat
pip install -r requirements.txt
python pulse_monitor.py
```
