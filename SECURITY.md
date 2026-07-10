# Security Policy — Strix Pulse Monitor

## Reporting a vulnerability

Please report privately via GitHub Security Advisories (the repo's **Security** tab) or
the [Strix Advanced Tools](https://github.com/strix-tool) maintainer contacts — not a public
issue. We aim to acknowledge within 72 hours.

## Threat model

Strix Pulse Monitor is a **local, read-only** desktop widget. It:

- makes **no network connections** — it only *measures* traffic via `psutil` counters;
- requires **no elevation / admin**;
- spawns **no shell** — the two subprocesses (`nvidia-smi`, and on Windows a
  `Get-Counter` query) use fixed argument lists with no user input;
- uses **no dynamic code** (no `eval`/`exec`/`pickle`).

## Hardening

- **PowerShell by absolute path (Windows).** The GPU-counter fallback invokes
  `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe` by full path, so a
  hijacked `%PATH%` cannot substitute a rogue `powershell.exe`.
- **Validated settings.** `settings.json` is parsed field-by-field (only integer `x`/`y`
  and boolean `pinned` accepted) and written atomically — a corrupt or tampered file is
  ignored, never crashes the app.
- **GPU reads are sandboxed on a daemon thread** with timeouts, so a slow/hung counter
  can never freeze the UI, and any parse error resets the reading to N/A.
- **Linux GPU source is unprivileged** — it reads `gpu_busy_percent` from sysfs (no root,
  no extra tools). Intel GPUs (which need privileged tooling) degrade to N/A rather than
  requesting elevation.

## Data & privacy

The only file written is `settings.json` (window position + pin state) under
`%APPDATA%\PulseMonitor` (Windows) or `~/.config/PulseMonitor` (Linux). No personal data,
no telemetry, nothing leaves your machine.
