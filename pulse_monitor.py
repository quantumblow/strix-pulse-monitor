"""
PULSE — Personal Desktop System Monitor  (v2, security & stability audited)
A Rainmeter-style, always-on-top, draggable desktop widget for Windows 11.

Features:
  • Live CPU, GPU, RAM, Storage usage + real-time network down/up traffic
  • Frameless glass design with painted soft shadow (no Qt effect glitches)
  • Drag anywhere to reposition, Pin (📌) to lock in place
  • Right-click context menu on the widget itself
  • Position & settings persist atomically; restored position is clamped
    to visible screen area (safe after monitor changes)
  • Single-instance guard — launching twice won't spawn duplicates
  • System tray icon with live stats tooltip (show / hide / exit)

Security notes:
  • No network access, no elevated privileges required
  • All subprocess calls use fixed argument lists (no shell=True, no user input)
  • Settings file is validated on load; writes are atomic (temp + replace)
  • Reads system counters only via psutil / nvidia-smi / Windows perf counters

Requires: Python 3.10+, PySide6, psutil   (pip install -r requirements.txt)
Run:      double-click run_pulse.bat  (or: pythonw pulse_monitor.py)
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time

import psutil
from PySide6.QtCore import QLockFile, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QIcon,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QPushButton, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from strix_i18n import (Translator, LANGS, LANG_CODES, LANG_NAME,
                        detect_os_lang)

# Module-wide translator. The saved/OS language is applied (in main() and again
# in PulseWidget) BEFORE any widgets are built, so every user-facing string is
# created already translated. _() is the shorthand every such string flows
# through; runtime values are passed as named placeholders, e.g.
# _("{app} is already running.", app=APP_NAME), keeping placeholder names
# identical across all languages.
APP_NAME = "Pulse Monitor"          # product name — brand, never translated
_TR = Translator()


def _(s, **kw):
    return _TR(s, **kw)

# ============================================================================
# Theme tokens — "midnight instrument panel" (edit freely, it's your widget)
# ============================================================================
BG          = QColor(12, 14, 20, 216)     # glass card fill (alpha = opacity)
BG_EDGE     = QColor(255, 255, 255, 20)   # hairline border
TEXT_MAIN   = "#E8EAF0"
TEXT_DIM    = "#6B7280"
ACCENTS = {
    "CPU":  "#4FC3F7",   # signal blue
    "GPU":  "#B388FF",   # violet
    "RAM":  "#69F0AE",   # mint
    "DISK": "#FFD54F",   # amber
    "DOWN": "#40C4FF",
    "UP":   "#FF8A65",
}
WARN_COLOR   = "#FF5252"  # bars turn red at/above this threshold
WARN_AT      = 90.0
WIDGET_WIDTH = 300        # card width in px
SHADOW_PAD   = 12         # margin reserved around the card for the soft shadow
CORNER       = 14         # card corner radius
REFRESH_MS   = 1000       # UI refresh interval

if os.name == "nt":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                              "PulseMonitor")
else:
    CONFIG_DIR = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "PulseMonitor")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
LOCK_FILE   = os.path.join(CONFIG_DIR, "pulse.lock")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Resolve PowerShell by ABSOLUTE path on Windows (defense-in-depth: never let a
# hijacked %PATH% substitute a rogue powershell.exe). No-op elsewhere.
if os.name == "nt":
    _POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                               "System32", "WindowsPowerShell", "v1.0",
                               "powershell.exe")
else:
    _POWERSHELL = "powershell"


# ============================================================================
# GPU backend — NVIDIA first, Windows GPU perf counters as fallback.
# Runs on a daemon thread so a slow counter can never freeze the UI.
# ============================================================================
class GpuReader:
    def __init__(self):
        self.percent: float | None = None       # None → "N/A"
        self._amd_path = None
        self._nvsmi = None
        self._mode = self._detect()
        # PowerShell counter sampling is expensive; poll it less often. The
        # NVIDIA CLI and the AMD sysfs read are cheap.
        self._interval = 4.0 if self._mode == "wincounter" else 1.5
        if self._mode:
            threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _amdgpu_busy_path() -> str | None:
        # AMD GPUs expose live utilisation (0-100) in sysfs, readable without
        # root: /sys/class/drm/card*/device/gpu_busy_percent
        try:
            import glob
            for p in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
                if os.access(p, os.R_OK):
                    return p
        except Exception:
            pass
        return None

    @staticmethod
    def _find_nvidia_smi() -> str | None:
        # Resolve to an ABSOLUTE path UNDER A TRUSTED ROOT so a rogue nvidia-smi
        # earlier in the search order can never be executed instead. This matters
        # on Windows, where shutil.which() searches the CURRENT DIRECTORY first —
        # a bare-name lookup can otherwise resolve to a planted nvidia-smi.exe in
        # the process CWD (e.g. the app's own folder). realpath alone does NOT
        # help there, so both branches enforce a trusted-directory allowlist.
        p = shutil.which("nvidia-smi")
        if not p:
            return None
        rp = os.path.realpath(p)
        if not os.path.isfile(rp):
            return None
        if os.name == "nt":
            return rp if GpuReader._win_under_trusted_root(rp) else None
        return rp if os.path.dirname(rp) in (
            "/usr/bin", "/bin", "/usr/local/bin", "/usr/local/nvidia/bin") else None

    @staticmethod
    def _win_under_trusted_root(rp: str) -> bool:
        """True if rp resolves under System32 or an NVIDIA install dir (Windows)."""
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        roots = [os.path.join(sysroot, "System32")]
        for pf in (os.environ.get("ProgramFiles"),
                   os.environ.get("ProgramW6432"),
                   os.environ.get("ProgramFiles(x86)")):
            if pf:
                roots.append(os.path.join(pf, "NVIDIA Corporation"))
        rpn = os.path.normcase(rp)
        for root in roots:
            rootn = os.path.normcase(root)
            try:
                if os.path.commonpath([rpn, rootn]) == rootn:
                    return True
            except ValueError:
                continue          # different drive → not this root
        return False

    def _detect(self) -> str | None:
        self._nvsmi = self._find_nvidia_smi()
        if self._nvsmi:
            return "nvidia"
        if os.name == "nt":
            return "wincounter"
        # Linux: AMD sysfs utilisation if present (Intel needs privileged tools,
        # so it degrades to N/A rather than requiring root).
        self._amd_path = self._amdgpu_busy_path()
        if self._amd_path:
            return "amdgpu"
        return None

    def _loop(self):
        while True:
            try:
                if self._mode == "nvidia":
                    self._read_nvidia()
                elif self._mode == "amdgpu":
                    self._read_amdgpu()
                else:
                    self._read_windows_counter()
            except Exception:
                self.percent = None
            time.sleep(self._interval)

    def _read_amdgpu(self):
        with open(self._amd_path, "r") as f:
            self.percent = max(0.0, min(float(f.read().strip()), 100.0))

    def _read_nvidia(self):
        out = subprocess.run(
            [self._nvsmi, "--query-gpu=utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=_NO_WINDOW,
        )
        first = out.stdout.strip().splitlines()[0]
        self.percent = max(0.0, min(float(first), 100.0))

    def _read_windows_counter(self):
        # Sum of all 3D-engine utilisation counters (covers Intel/AMD iGPUs).
        ps = (r"(Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage')"
              r".CounterSamples | Measure-Object CookedValue -Sum | "
              r"Select-Object -ExpandProperty Sum")
        out = subprocess.run(
            [_POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=8,
            creationflags=_NO_WINDOW,
        )
        val = out.stdout.strip().replace(",", ".")
        self.percent = max(0.0, min(float(val), 100.0)) if val else None


# ============================================================================
# Helpers
# ============================================================================
def human_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec >= 1024 ** 2:
        return f"{bytes_per_sec / 1024 ** 2:6.2f} MB/s"
    if bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:6.1f} KB/s"
    return f"{bytes_per_sec:6.0f}  B/s"


def human_gb(nbytes: float) -> str:
    return f"{nbytes / 1024 ** 3:.1f}"


def load_settings() -> dict:
    """Load and *validate* settings — a corrupt/tampered file is ignored."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        out = {}
        if isinstance(raw.get("x"), int) and isinstance(raw.get("y"), int):
            out["x"], out["y"] = raw["x"], raw["y"]
        if isinstance(raw.get("pinned"), bool):
            out["pinned"] = raw["pinned"]
        if isinstance(raw.get("autostart"), bool):
            out["autostart"] = raw["autostart"]
        if isinstance(raw.get("lang"), str) and raw["lang"] in LANG_CODES:
            out["lang"] = raw["lang"]
        return out
    except Exception:
        return {}


def load_lang() -> str:
    """Saved UI language wins; otherwise fall back to the OS language."""
    saved = load_settings().get("lang")
    return saved if saved in LANG_CODES else detect_os_lang()


def save_settings(data: dict):
    """Atomic write: never leaves a half-written settings file behind."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception:
        pass


def _linux_autostart_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "strix-pulse-monitor.desktop")


def _linux_autostart_exec() -> list[str]:
    """Absolute command that starts the widget — never resolved via $PATH."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    for p in ("/usr/bin/strix-pulse-monitor",
              "/usr/local/bin/strix-pulse-monitor",
              os.path.expanduser("~/.local/bin/strix-pulse-monitor")):
        if os.access(p, os.X_OK):
            return [p]
    script = os.path.abspath(__file__)
    return [sys.executable, script] if os.path.isfile(script) else []


def _desktop_quote(arg: str) -> str:
    # .desktop Exec quoting: escape backslashes first, then double quotes.
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_linux_autostart(path: str) -> None:
    argv = _linux_autostart_exec()
    if not argv:
        return
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Strix Pulse Monitor\n"
        "Comment=Always-on-top system monitor widget\n"
        f"Exec={' '.join(_desktop_quote(a) for a in argv)}\n"
        "Icon=strix-pulse-monitor\n"
        "Terminal=false\n"
        "Categories=Utility;System;Monitor;\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(entry)
    os.replace(tmp, path)


def ensure_autostart(enable: bool):
    """Enable/disable starting the widget at login.

    Windows manages a per-user HKCU ...\\Run value (installed exe only); Linux
    manages an XDG autostart drop-in. When enabling, an existing drop-in is
    left untouched, so entries created by install.sh --autostart (or edited by
    hand) keep their settings. Wrapped so it can never break startup."""
    if os.name == "nt":
        exe = sys.executable if getattr(sys, "frozen", False) else None
        try:
            import winreg
            run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0,
                                winreg.KEY_SET_VALUE) as key:
                if enable and exe:
                    winreg.SetValueEx(key, "Strix Pulse Monitor", 0,
                                      winreg.REG_SZ, f'"{exe}"')
                else:
                    try:
                        winreg.DeleteValue(key, "Strix Pulse Monitor")
                    except FileNotFoundError:
                        pass
        except Exception:
            pass
        return

    try:
        path = _linux_autostart_path()
        if enable:
            if not os.path.exists(path):
                _write_linux_autostart(path)
        else:
            os.unlink(path)
    except FileNotFoundError:
        pass
    except Exception:
        pass


# ============================================================================
# UI building blocks
# ============================================================================
class MeterBar(QWidget):
    """A labelled horizontal usage bar: NAME | thin track+fill | value text."""

    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self.accent = QColor(accent)
        self.value: float = -1.0    # -1 → N/A
        self.text = "--"
        self.label = label
        self.setFixedHeight(30)

    def set(self, percent: float | None, text: str):
        self.value = -1.0 if percent is None else max(0.0, min(percent, 100.0))
        self.text = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QColor(TEXT_DIM))
        p.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
        p.drawText(QRectF(0, 0, 52, h), Qt.AlignVCenter | Qt.AlignLeft, self.label)

        bar_x, bar_w, bar_h = 56, w - 56 - 92, 6
        bar_y = (h - bar_h) / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 3, 3)
        p.fillPath(track, QColor(255, 255, 255, 22))

        if self.value >= 0:
            color = QColor(WARN_COLOR) if self.value >= WARN_AT else self.accent
            fill_w = bar_w * self.value / 100.0
            if fill_w > 1:
                fill = QPainterPath()
                fill.addRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 3, 3)
                p.fillPath(fill, color)

        p.setPen(QColor(TEXT_MAIN))
        p.setFont(QFont("Consolas", 8))
        p.drawText(QRectF(w - 90, 0, 90, h), Qt.AlignVCenter | Qt.AlignRight,
                   self.text)
        p.end()


class NetRow(QWidget):
    """Download / upload live traffic row with direction arrows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.down = 0.0
        self.up = 0.0
        self.setFixedHeight(26)

    def set(self, down_bps: float, up_bps: float):
        self.down, self.up = down_bps, up_bps
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h, half = self.height(), self.width() / 2
        p.setFont(QFont("Consolas", 9))
        p.setPen(QColor(ACCENTS["DOWN"]))
        p.drawText(QRectF(0, 0, half, h), Qt.AlignVCenter | Qt.AlignLeft,
                   "▼ " + human_speed(self.down))
        p.setPen(QColor(ACCENTS["UP"]))
        p.drawText(QRectF(half, 0, half, h), Qt.AlignVCenter | Qt.AlignRight,
                   "▲ " + human_speed(self.up))
        p.end()


# ============================================================================
# Main widget window
# ============================================================================
class PulseWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        # Apply the saved UI language (falling back to the OS language) BEFORE
        # any widgets are built, so every string is created already translated.
        saved_lang = self.settings.get("lang")
        _TR.set(saved_lang if saved_lang in LANG_CODES else detect_os_lang())
        self.pinned = self.settings.get("pinned", False)
        if os.name == "nt":
            self.autostart = self.settings.get("autostart", True)
        else:
            # The XDG drop-in is the source of truth: it may pre-date the app
            # (install.sh --autostart) or have been edited by hand.
            self.autostart = os.path.exists(_linux_autostart_path())
        ensure_autostart(self.autostart)   # keep the login entry in sync
        self._drag_offset: QPoint | None = None
        self._quitting = False

        self.setWindowTitle(APP_NAME)
        # Desktop widget: sit at the BOTTOM of the z-order so normal windows
        # (folders, browsers, etc.) cover it - it stays on the desktop instead
        # of floating on top of everything.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool |
                            Qt.WindowStaysOnBottomHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WIDGET_WIDTH + SHADOW_PAD * 2)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.gpu = GpuReader()
        self._last_net = psutil.net_io_counters()
        self._last_t = time.monotonic()
        psutil.cpu_percent(interval=None)  # prime the counter

        self._build_ui()
        self._build_tray()
        self._restore_position()
        self._apply_cursor()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)
        self.refresh()

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        pad = SHADOW_PAD
        root.setContentsMargins(pad + 16, pad + 12, pad + 16, pad + 14)
        root.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("PULSE")
        title.setStyleSheet(f"color:{TEXT_MAIN}; letter-spacing:4px;")
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.sub = QLabel(_("system monitor"))
        self.sub.setStyleSheet(f"color:{TEXT_DIM};")
        self.sub.setFont(QFont("Segoe UI", 7))

        self.pin_btn = QPushButton()
        self.pin_btn.clicked.connect(self.toggle_pin)
        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip(_("Hide to tray"))
        self.close_btn.clicked.connect(self.hide)
        for b in (self.pin_btn, self.close_btn):
            b.setFixedSize(22, 22)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(
                "QPushButton{background:rgba(255,255,255,0.06); color:#9CA3AF;"
                " border:none; border-radius:11px; font-size:10px;}"
                "QPushButton:hover{background:rgba(255,255,255,0.16);"
                " color:#fff;}")

        header.addWidget(title)
        header.addSpacing(6)
        header.addWidget(self.sub)
        header.addStretch()
        header.addWidget(self.pin_btn)
        header.addWidget(self.close_btn)
        root.addLayout(header)

        self.cpu_bar  = MeterBar("CPU",  ACCENTS["CPU"])
        self.gpu_bar  = MeterBar("GPU",  ACCENTS["GPU"])
        self.ram_bar  = MeterBar("RAM",  ACCENTS["RAM"])
        self.disk_bar = MeterBar("DISK", ACCENTS["DISK"])
        for bar in (self.cpu_bar, self.gpu_bar, self.ram_bar, self.disk_bar):
            root.addWidget(bar)

        net_label = QLabel("NETWORK")
        net_label.setFont(QFont("Segoe UI", 7, QFont.DemiBold))
        net_label.setStyleSheet(
            f"color:{TEXT_DIM}; letter-spacing:2px; margin-top:4px;")
        root.addWidget(net_label)
        self.net_row = NetRow()
        root.addWidget(self.net_row)

        self._update_pin_icon()

    def paintEvent(self, _):
        """Card + hand-painted soft shadow.

        A QGraphicsDropShadowEffect on a top-level translucent window renders
        unreliably on Windows (clipping/artifacts), so the shadow is painted
        manually as fading rounded outlines inside the reserved margin.
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(self.rect()).adjusted(SHADOW_PAD, SHADOW_PAD,
                                            -SHADOW_PAD, -SHADOW_PAD)
        # soft shadow: expanding translucent outlines
        p.setBrush(Qt.NoBrush)
        for i in range(SHADOW_PAD, 0, -1):
            alpha = int(38 * (1 - i / (SHADOW_PAD + 1)) ** 2)
            p.setPen(QPen(QColor(0, 0, 0, alpha), 2))
            p.drawRoundedRect(card.adjusted(-i, -i + 2, i, i + 2),
                              CORNER + i * 0.6, CORNER + i * 0.6)
        # glass card
        path = QPainterPath()
        path.addRoundedRect(card, CORNER, CORNER)
        p.fillPath(path, BG)
        p.setPen(QPen(BG_EDGE, 1))
        p.drawPath(path)
        p.end()

    # ---------------- data refresh ----------------
    def refresh(self):
        cpu = psutil.cpu_percent(interval=None)
        try:
            freq = psutil.cpu_freq()
            freq_txt = f"{freq.current / 1000:.1f}GHz" if freq else ""
        except Exception:
            freq_txt = ""
        self.cpu_bar.set(cpu, f"{cpu:4.0f}%  {freq_txt}")

        g = self.gpu.percent
        self.gpu_bar.set(g, "  N/A" if g is None else f"{g:4.0f}%")

        vm = psutil.virtual_memory()
        self.ram_bar.set(vm.percent,
                         f"{human_gb(vm.used)}/{human_gb(vm.total)}G")

        total = used = 0
        for part in psutil.disk_partitions(all=False):
            if "cdrom" in part.opts or not part.fstype:
                continue
            try:
                du = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            total += du.total
            used += du.used
        if total:
            self.disk_bar.set(used / total * 100,
                              f"{human_gb(used)}/{human_gb(total)}G")
        else:
            self.disk_bar.set(None, "  N/A")

        now = time.monotonic()
        net = psutil.net_io_counters()
        dt = max(now - self._last_t, 1e-6)
        down = max(0.0, (net.bytes_recv - self._last_net.bytes_recv) / dt)
        up = max(0.0, (net.bytes_sent - self._last_net.bytes_sent) / dt)
        self._last_net, self._last_t = net, now
        self.net_row.set(down, up)

        self.tray.setToolTip(
            f"{APP_NAME}\nCPU {cpu:.0f}%   RAM {vm.percent:.0f}%\n"
            f"▼ {human_speed(down).strip()}   ▲ {human_speed(up).strip()}")

    # ---------------- drag & pin ----------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.pinned:
            self._drag_offset = (e.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and not self.pinned:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, _):
        if self._drag_offset is not None:
            self._drag_offset = None
            self._persist()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self._update_pin_icon()
        self._apply_cursor()
        self._persist()

    def toggle_autostart(self):
        self.autostart = not self.autostart
        ensure_autostart(self.autostart)
        self.act_auto.setChecked(self.autostart)   # keep tray menu in sync
        self._persist()

    def _apply_cursor(self):
        self.setCursor(Qt.ArrowCursor if self.pinned else Qt.SizeAllCursor)

    def _update_pin_icon(self):
        self.pin_btn.setText("📌" if self.pinned else "📍")
        self.pin_btn.setToolTip(_("Unpin — allow dragging") if self.pinned
                                else _("Pin — lock position"))

    def _persist(self):
        self.settings.update({"x": self.x(), "y": self.y(),
                              "pinned": self.pinned,
                              "autostart": self.autostart})
        save_settings(self.settings)

    def _restore_position(self):
        x, y = self.settings.get("x"), self.settings.get("y")
        screen = QApplication.primaryScreen().availableGeometry()
        if x is None or y is None:
            x = screen.right() - self.width() - 16
            y = screen.top() + 16
        # Clamp into the visible virtual desktop so the widget can never be
        # restored off-screen after a monitor change.
        virt = QApplication.primaryScreen().availableVirtualGeometry()
        x = max(virt.left(), min(x, virt.right() - 60))
        y = max(virt.top(), min(y, virt.bottom() - 60))
        self.move(x, y)

    # ---------------- language ----------------
    def _make_language_menu(self, parent) -> QMenu:
        """A fresh 'Language' submenu: 13 checkable, mutually-exclusive entries
        (each shown in its own native name) that switch the UI language."""
        menu = QMenu(_("Language"), parent)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for code in LANG_CODES:
            act = QAction(LANG_NAME[code], menu)
            act.setCheckable(True)
            act.setChecked(code == _TR.lang)
            group.addAction(act)
            act.triggered.connect(
                lambda checked=False, c=code: self._set_language(c))
            menu.addAction(act)
        return menu

    def _set_language(self, code):
        if code not in LANG_CODES or code == _TR.lang:
            return
        _TR.set(code)
        self.settings["lang"] = code
        save_settings(self.settings)
        self.retranslate()

    def retranslate(self):
        """Re-apply every persistent user-facing string after a language change.
        The context menu is rebuilt on each right-click (so it always uses the
        current language and needs no work here); the window header and the tray
        menu are long-lived, so their text is refreshed live."""
        self.setWindowTitle(APP_NAME)
        self.sub.setText(_("system monitor"))
        self.close_btn.setToolTip(_("Hide to tray"))
        self._update_pin_icon()
        self.act_show.setText(_("Show / Hide"))
        self.act_pin.setText(_("Toggle Pin"))
        self.act_auto.setText(_("Start on login"))
        self.act_quit.setText(_("Exit"))
        self.tray_lang_menu.setTitle(_("Language"))
        for act, code in zip(self.tray_lang_menu.actions(), LANG_CODES):
            act.setChecked(code == _TR.lang)

    # ---------------- context menu ----------------
    def _show_context_menu(self, pos):
        menu = QMenu(self)
        act_pin = menu.addAction(_("Unpin") if self.pinned else _("Pin"))
        act_hide = menu.addAction(_("Hide to tray"))
        act_auto = menu.addAction(_("Start on login"))
        act_auto.setCheckable(True)
        act_auto.setChecked(self.autostart)
        menu.addMenu(self._make_language_menu(menu))
        menu.addSeparator()
        act_quit = menu.addAction(_("Exit"))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == act_pin:
            self.toggle_pin()
        elif chosen == act_hide:
            self.hide()
        elif chosen == act_auto:
            self.toggle_autostart()
        elif chosen == act_quit:
            self._quit()

    # ---------------- system tray ----------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._make_tray_icon(), self)
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        self.act_show = QAction(_("Show / Hide"), menu)
        self.act_show.triggered.connect(self._toggle_visible)
        self.act_pin = QAction(_("Toggle Pin"), menu)
        self.act_pin.triggered.connect(self.toggle_pin)
        self.act_auto = QAction(_("Start on login"), menu)
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(self.autostart)
        self.act_auto.triggered.connect(self.toggle_autostart)
        self.act_quit = QAction(_("Exit"), menu)
        self.act_quit.triggered.connect(self._quit)
        self.tray_lang_menu = self._make_language_menu(menu)
        menu.addAction(self.act_show)
        menu.addAction(self.act_pin)
        menu.addAction(self.act_auto)
        menu.addMenu(self.tray_lang_menu)
        menu.addSeparator()
        menu.addAction(self.act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._toggle_visible()
            if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _make_tray_icon(self) -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#0C0E14"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        p.setPen(QPen(QColor(ACCENTS["CPU"]), 6,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPoint(10, 34), QPoint(22, 34), QPoint(28, 18),
                        QPoint(36, 46), QPoint(42, 34), QPoint(54, 34)])
        p.end()
        return QIcon(pm)

    def _toggle_visible(self):
        self.setVisible(not self.isVisible())

    def _quit(self):
        self._quitting = True
        self._persist()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        if self._quitting:
            e.accept()
            return
        # Closing the window only hides it; Exit lives in the menus.
        e.ignore()
        self.hide()


# ============================================================================
def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Apply the UI language before any dialog (e.g. the single-instance notice)
    # can be shown. PulseWidget re-applies it from its own loaded settings.
    _TR.set(load_lang())

    # Single-instance guard: a second launch exits quietly with a notice.
    os.makedirs(CONFIG_DIR, exist_ok=True)
    lock = QLockFile(LOCK_FILE)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, APP_NAME,
            _("{app} is already running.\nCheck your system tray.",
              app=APP_NAME))
        sys.exit(0)

    widget = PulseWidget()
    widget.show()
    exit_code = app.exec()
    lock.unlock()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
