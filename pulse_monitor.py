"""
PULSE — Personal Desktop System Monitor  (v2, security & stability audited)
A Rainmeter-style, always-on-top, draggable desktop widget for Windows 11.

Features:
  • Live CPU, GPU (utilisation + VRAM), RAM, Storage + network down/up traffic
  • Frameless glass design with painted soft shadow (no Qt effect glitches)
  • Drag anywhere to reposition, Pin (📌) to lock in place
  • Uniform 0.5×–4× window scaling: corner drag or Ctrl+wheel (10 %/notch),
    with text capped at 2× so a large card stays sharp
  • Switch between always-on-top and desktop-level layering from the menus
  • Right-click context menu on the widget itself
  • Position, scale & settings persist atomically; restored position is
    clamped to the visible screen area (safe after monitor changes)
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

import base64
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time

import psutil
from PySide6.QtCore import (QElapsedTimer, QLockFile, QPoint, QRectF, QSize,
                            Qt, QTimer, QUrl)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor,
                           QDesktopServices, QFont, QFontMetricsF, QIcon,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QLayout, QMenu, QMessageBox, QPushButton,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from strix_i18n import (Translator, LANGS, LANG_CODES, LANG_NAME,
                        detect_os_lang)

# Module-wide translator. The saved/OS language is applied (in main() and again
# in PulseWidget) BEFORE any widgets are built, so every user-facing string is
# created already translated. _() is the shorthand every such string flows
# through; runtime values are passed as named placeholders, e.g.
# _("{app} is already running.", app=APP_NAME), keeping placeholder names
# identical across all languages.
APP_NAME = "Pulse Monitor"          # product name — brand, never translated
APP_VERSION = "1.0.4"
GITHUB_URL = "https://github.com/quantumblow/strix-pulse-monitor"
ABOUT_SCALE = 1.5                   # About card is laid out at 1× then enlarged
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
WIDGET_WIDTH = 300        # card width at 1.0× (px)
METER_LABEL_GAP = 8       # px at 1.0× between the label column and the track
METER_TEXT_GAP = 8        # px at 1.0× between the track and the value text
SHADOW_PAD   = 12         # margin reserved around the card for the soft shadow
CORNER       = 14         # card corner radius at 1.0×
REFRESH_MS   = 1000       # UI refresh interval

# ---- window scaling --------------------------------------------------------
# The whole card scales uniformly; text stops growing at FONT_SCALE_MAX so a
# very large widget stays legible without turning into billboard-sized digits.
SCALE_MIN       = 0.5
SCALE_MAX       = 4.0
SCALE_STEP      = 0.10    # one wheel notch = 10 % of the current scale
FONT_SCALE_MAX  = 2.0
DEFAULT_SCALE   = 1.0
RESIZE_GRIP     = 14      # corner hit zone at 1.0× (px), clamped below
RESIZE_GRIP_MIN = 10
RESIZE_GRIP_MAX = 24
SHADOW_MAX_STEPS = 24     # cap the shadow layers at large scales
# Ctrl+wheel zoom animation duration (ms). Smoothstep spreads the step evenly
# over it instead of front-loading most of the movement into the first frame.
ZOOM_EASE_MS = 320
BASE_WIDTH      = WIDGET_WIDTH + SHADOW_PAD * 2

# Base layout heights (px at 1.0×). Kept here so the window size, the layout
# metrics and the row widgets all derive from the same numbers.
HEADER_H     = 22
METER_H      = 30
NET_LABEL_H  = 21
NET_ROW_H    = 26
ROW_SPACING  = 6
CONTENT_PAD_X = 16        # inner padding between the card edge and the content
CONTENT_PAD_TOP = 12
CONTENT_PAD_BOTTOM = 14

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
        # (used GiB, total GiB) of GPU memory, or None when the backend cannot
        # report it. Stored as one tuple so the UI never sees a half-updated
        # pair from two different samples.
        self.vram: tuple[float, float] | None = None
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

    # ---- value parsing -----------------------------------------------------
    @staticmethod
    def _pct(text: str) -> float | None:
        try:
            return max(0.0, min(float(text), 100.0))
        except (TypeError, ValueError):
            return None           # "[N/A]", "[Unknown Error]", empty, …

    @staticmethod
    def _vram(used: str, total: str) -> tuple[float, float] | None:
        """(used, total) in MiB → (used, total) in GiB, or None if unusable."""
        try:
            u, t = float(used), float(total)
        except (TypeError, ValueError):
            return None           # "[N/A]" on MIG/older drivers
        if t <= 0 or u < 0:
            return None
        return (u / 1024.0, t / 1024.0)

    @staticmethod
    def _sysfs_vram(base: str) -> tuple[float, float] | None:
        # amdgpu exposes VRAM in bytes next to gpu_busy_percent; absent on
        # older kernels and on non-AMD GPUs, hence the soft failure.
        try:
            with open(os.path.join(base, "mem_info_vram_used"), "r") as f:
                used = int(f.read().strip())
            with open(os.path.join(base, "mem_info_vram_total"), "r") as f:
                total = int(f.read().strip())
        except (OSError, ValueError):
            return None
        if total <= 0 or used < 0:
            return None
        return (used / 1024 ** 3, total / 1024 ** 3)

    def _nvidia_query(self, fields: str) -> str | None:
        """First GPU's CSV line for `fields`, or None if the query fails."""
        try:
            out = subprocess.run(
                [self._nvsmi, f"--query-gpu={fields}",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        lines = out.stdout.strip().splitlines()
        return lines[0].strip() if lines else None

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
                self.vram = None
            time.sleep(self._interval)

    def _read_amdgpu(self):
        with open(self._amd_path, "r") as f:
            self.percent = self._pct(f.read().strip())
        # VRAM lives in the same sysfs directory as gpu_busy_percent.
        self.vram = self._sysfs_vram(os.path.dirname(self._amd_path))

    def _read_nvidia(self):
        # One query for all three fields — nvidia-smi costs ~20 ms, so asking
        # for memory.used/total adds negligible overhead.
        line = self._nvidia_query("utilization.gpu,memory.used,memory.total")
        parts = [p.strip() for p in line.split(",")] if line else []
        if len(parts) < 3:
            # Older drivers may not know the memory fields; keep the bar alive
            # with utilisation only instead of going N/A.
            line = self._nvidia_query("utilization.gpu")
            parts = [line] if line else []
        if not parts:
            self.percent = None
            self.vram = None
            return
        self.percent = self._pct(parts[0])
        self.vram = self._vram(parts[1], parts[2]) if len(parts) >= 3 else None

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


def human_vram(used_gb: float, total_gb: float) -> str:
    """'1.8/16G' — used in GiB with one decimal; the total is shown whole when
    the driver's reserved-memory sliver (e.g. 16303 of 16384 MiB) is just
    rounding noise, and with a decimal for small iGPU carve-outs (0.5G)."""
    whole = round(total_gb)
    total = (f"{whole:d}" if abs(total_gb - whole) <= 0.15
             else f"{total_gb:.1f}")
    return f"{used_gb:.1f}/{total}G"


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
        if isinstance(raw.get("on_top"), bool):
            out["on_top"] = raw["on_top"]
        # Scale is clamped instead of rejected: an old/tampered value can only
        # ever produce a usable window, never a 0× or 999× one.
        scale = raw.get("scale")
        if isinstance(scale, (int, float)) and not isinstance(scale, bool):
            out["scale"] = clamp_scale(scale)
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


# ============================================================================
# Scaling helpers
# ============================================================================
def clamp_scale(value) -> float:
    """Any user/settings value → a usable scale in [SCALE_MIN, SCALE_MAX]."""
    try:
        s = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SCALE
    if not math.isfinite(s):
        return DEFAULT_SCALE
    return round(max(SCALE_MIN, min(s, SCALE_MAX)), 3)


def zoomed_scale(current, notches: float) -> float:
    """One wheel notch (120 units) = SCALE_STEP; fractional deltas allowed."""
    return clamp_scale(clamp_scale(current) + notches * SCALE_STEP)


def capped_font_scale(scale) -> float:
    """Text follows the window down, but never past FONT_SCALE_MAX up."""
    return min(clamp_scale(scale), FONT_SCALE_MAX)


def scaled_point_size(base_pt: float, scale) -> float:
    # Qt can render fractional point sizes; 1 pt is the practical floor.
    return max(1.0, base_pt * capped_font_scale(scale))


def resize_grip(scale) -> int:
    """How far the corner hit zone reaches past the shadow margin (10–24 px)."""
    return max(RESIZE_GRIP_MIN,
               min(RESIZE_GRIP_MAX, round(RESIZE_GRIP * clamp_scale(scale))))


CORNER_CURSORS = {
    "top-left": Qt.SizeFDiagCursor,
    "bottom-right": Qt.SizeFDiagCursor,
    "top-right": Qt.SizeBDiagCursor,
    "bottom-left": Qt.SizeBDiagCursor,
}


def resize_corner(pos: QPoint, width: int, height: int, scale) -> str | None:
    """Which corner (if any) is under `pos` inside the window rect.

    The window rect includes the shadow margin, so the visible card corner sits
    `SHADOW_PAD` px in from it. The grab area therefore starts at the window
    edge (so the shadow margin also works) and extends one grip length past the
    card corner, which puts the rounded corner itself inside the hit zone.
    """
    s = clamp_scale(scale)
    edge = round(SHADOW_PAD * s) + resize_grip(s)
    if pos.x() < edge:
        horizontal = "left"
    elif pos.x() >= width - edge:
        horizontal = "right"
    else:
        return None
    if pos.y() < edge:
        vertical = "top"
    elif pos.y() >= height - edge:
        vertical = "bottom"
    else:
        return None
    return f"{vertical}-{horizontal}"


def corner_drag_scale(corner: str, dx: int, dy: int, base_width: int,
                      base_height: int, start_scale: float) -> float:
    """Uniform scale from a corner drag.

    The mouse delta is projected onto the window diagonal, so dragging along
    the diagonal tracks the pointer exactly while an off-axis drag still feels
    proportional instead of snapping to the dominant axis.
    """
    sign_x = -1 if "left" in corner else 1
    sign_y = -1 if "top" in corner else 1
    denom = base_width * base_width + base_height * base_height
    if denom <= 0:
        return clamp_scale(start_scale)
    delta = (sign_x * dx * base_width + sign_y * dy * base_height) / denom
    return clamp_scale(start_scale + delta)


def corner_resize_pos(corner: str, anchor: QPoint, width: int, height: int) -> QPoint:
    """Top-left for a resized window, keeping the opposite corner anchored."""
    x = anchor.x() - width if "left" in corner else anchor.x()
    y = anchor.y() - height if "top" in corner else anchor.y()
    return QPoint(x, y)


def layout_metrics(scale) -> dict:
    """Every pixel metric of the card at `scale`, derived from the base sizes.

    Returning the window height together with the row heights guarantees the
    fixed-size window and its layout agree exactly at every scale.
    """
    s = clamp_scale(scale)
    margin_x = round((SHADOW_PAD + CONTENT_PAD_X) * s)
    margin_top = round((SHADOW_PAD + CONTENT_PAD_TOP) * s)
    margin_bottom = round((SHADOW_PAD + CONTENT_PAD_BOTTOM) * s)
    spacing = round(ROW_SPACING * s)
    header = round(HEADER_H * s)
    meter = round(METER_H * s)
    net_label = round(NET_LABEL_H * s)
    net_row = round(NET_ROW_H * s)
    height = (margin_top + margin_bottom + header + 6 * spacing
              + 4 * meter + net_label + net_row)
    return {
        "margin_left": margin_x,
        "margin_right": margin_x,
        "margin_top": margin_top,
        "margin_bottom": margin_bottom,
        "spacing": spacing,
        "header": header,
        "meter": meter,
        "net_label": net_label,
        "net_row": net_row,
        "width": round(BASE_WIDTH * s),
        "height": height,
    }


def _x11_set_stacking(win_id: int, on_top: bool) -> bool:
    """Restack an already-mapped X11 window through EWMH.

    Qt applies ``WindowStaysOnTop/BottomHint`` only when the native window is
    created; changing the flag at runtime leaves ``_NET_WM_STATE`` empty, so the
    window manager never restacks. Sending the standard client message is the
    portable EWMH way to do it. Returns False where X11/EWMH is unavailable
    (Windows, Wayland, headless platforms).
    """
    if os.name == "nt" or not os.environ.get("DISPLAY"):
        return False
    if (os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("XDG_SESSION_TYPE") == "wayland"):
        return False
    try:
        import ctypes
        import ctypes.util

        class _ClientMessage(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_int),
                ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong),
                ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int),
                ("data", ctypes.c_long * 5),
            ]

        class _Event(ctypes.Union):
            _fields_ = [("xclient", _ClientMessage), ("pad", ctypes.c_long * 24)]

        lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                    ctypes.c_int]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                   ctypes.c_int, ctypes.c_long,
                                   ctypes.POINTER(_Event)]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]

        dpy = lib.XOpenDisplay(None)
        if not dpy:
            return False
        try:
            root = lib.XDefaultRootWindow(dpy)
            state = lib.XInternAtom(dpy, b"_NET_WM_STATE", 0)
            above = lib.XInternAtom(dpy, b"_NET_WM_STATE_ABOVE", 0)
            below = lib.XInternAtom(dpy, b"_NET_WM_STATE_BELOW", 0)
            if not (state and above and below):
                return False

            def send(action, atom):
                ev = _Event()
                ev.xclient.type = 33            # ClientMessage
                ev.xclient.send_event = 1
                ev.xclient.display = dpy
                ev.xclient.window = win_id
                ev.xclient.message_type = state
                ev.xclient.format = 32
                ev.xclient.data[0] = action     # 0=remove, 1=add
                ev.xclient.data[1] = atom
                ev.xclient.data[3] = 1          # source: application
                lib.XSendEvent(dpy, root, 0, (1 << 20) | (1 << 19),
                               ctypes.byref(ev))

            # A window cannot be both: remove the other state, then add ours.
            send(0, below if on_top else above)
            send(1, above if on_top else below)
            lib.XFlush(dpy)
            return True
        finally:
            lib.XCloseDisplay(dpy)
    except Exception:
        return False


def _linux_autostart_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "strix-pulse-monitor.desktop")


def _linux_autostart_exec() -> list[str]:
    """Absolute command that starts this instance — never resolved via $PATH.

    Run the interpreter this process already uses instead of the packaged
    launcher: a login session commonly has a different PATH than the shell that
    started the app (e.g. a conda Python), and the launcher's `python3` lookup
    would then pick an interpreter without PySide6."""
    if getattr(sys, "frozen", False):
        return [os.path.abspath(sys.executable)]
    script = os.path.abspath(__file__)
    if os.path.isfile(script):
        return [os.path.abspath(sys.executable), script]
    return []


def _desktop_quote(arg: str) -> str:
    # .desktop Exec quoting: escape backslashes first, then double quotes.
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _linux_autostart_entry() -> str | None:
    argv = _linux_autostart_exec()
    if not argv:
        return None
    return (
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


def _write_linux_autostart(path: str, entry: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(entry)
    os.replace(tmp, path)


def ensure_autostart(enable: bool):
    """Enable/disable starting the widget at login.

    Windows manages a per-user HKCU ...\\Run value (installed exe only); Linux
    manages an XDG autostart drop-in. The app owns that drop-in: it is written
    from the current interpreter when missing or out of date, so entries from
    earlier versions (or install.sh --autostart) converge on a command that
    also works with the login session's PATH. Wrapped so it can never break
    startup."""
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
        if not enable:
            os.unlink(path)
            return
        entry = _linux_autostart_entry()
        if entry is None:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = None
        if current != entry:
            _write_linux_autostart(path, entry)
    except FileNotFoundError:
        pass
    except Exception:
        pass


# ============================================================================
# UI building blocks
# ============================================================================
class MeterBar(QWidget):
    """A labelled horizontal usage bar: NAME | thin track+fill | value text.

    Dimensions scale with the window; the fonts follow the capped scale so the
    bar geometry keeps growing past 2× while the text stays put.
    """

    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self.accent = QColor(accent)
        self.value: float = -1.0    # -1 → N/A
        self.text = "--"
        self.label = label
        self.scale = DEFAULT_SCALE
        self.leading = 0            # shared label column width, set by the card
        self.value_column = 0       # shared value column width, set by the card
        self.setFixedHeight(METER_H)

    def set_scale(self, scale):
        self.scale = clamp_scale(scale)
        self.setFixedHeight(round(METER_H * self.scale))
        self.update()

    def set_columns(self, leading: int, value_column: int):
        """Share the label/value columns so every row has the same track."""
        self.leading = max(0, int(leading))
        self.value_column = max(0, int(value_column))
        self.update()

    def set(self, percent: float | None, text: str):
        self.value = -1.0 if percent is None else max(0.0, min(percent, 100.0))
        self.text = text
        self.update()

    def _font(self, base_pt: float, weight=QFont.Normal) -> QFont:
        f = QFont("Segoe UI")
        f.setPointSizeF(scaled_point_size(base_pt, self.scale))
        f.setWeight(weight)
        return f

    def label_width(self) -> float:
        """Pixel width of this row's label at the current (capped) font size."""
        return QFontMetricsF(self._font(8, QFont.DemiBold)).horizontalAdvance(
            self.label)

    def value_width(self) -> float:
        """Pixel width of the current value text at the capped font size."""
        return QFontMetricsF(self._font(8)).horizontalAdvance(self.text)

    def _value_gap(self) -> int:
        return max(2, round(METER_TEXT_GAP * capped_font_scale(self.scale)))

    def _column_width(self) -> float:
        # `value_column` is the widest value across all rows; the fallback only
        # matters for the instant between a text change and the parent's sync.
        return max(self.value_column, self.value_width())

    def track_width(self) -> float:
        """Track length: it hugs the label on the left and the value on the right.

        The label and value columns are shared by every row and measured at the
        capped font size, so the tracks are all the same length while still
        stopping just before the right-aligned value column. The text columns
        stop growing at 2× while the card keeps growing to 4×, which is what
        prevents the large empty gutters the fixed `52 × scale` / `106 × scale`
        columns used to leave around the bar.
        """
        return max(1.0, self.width() - self.leading
                   - self._column_width() - self._value_gap())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        value_w = self._column_width()
        bar_x = self.leading
        bar_w = self.track_width()
        bar_h = max(1, round(6 * self.scale))
        radius = max(1.0, bar_h / 2.0)
        bar_y = (h - bar_h) / 2

        p.setPen(QColor(TEXT_DIM))
        p.setFont(self._font(8, QFont.DemiBold))
        p.drawText(QRectF(0, 0, bar_x, h), Qt.AlignVCenter | Qt.AlignLeft,
                   self.label)

        track = QPainterPath()
        track.addRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), radius,
                             radius)
        p.fillPath(track, QColor(255, 255, 255, 22))

        if self.value >= 0:
            color = QColor(WARN_COLOR) if self.value >= WARN_AT else self.accent
            fill_w = bar_w * self.value / 100.0
            if fill_w > 1:
                fill = QPainterPath()
                fill.addRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h),
                                    radius, radius)
                p.fillPath(fill, color)

        p.setPen(QColor(TEXT_MAIN))
        p.setFont(self._font(8))
        p.drawText(QRectF(w - value_w, 0, value_w, h),
                   Qt.AlignVCenter | Qt.AlignRight, self.text)
        p.end()


class NetRow(QWidget):
    """Download / upload live traffic row with direction arrows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.down = 0.0
        self.up = 0.0
        self.scale = DEFAULT_SCALE
        self.setFixedHeight(NET_ROW_H)

    def set_scale(self, scale):
        self.scale = clamp_scale(scale)
        self.setFixedHeight(round(NET_ROW_H * self.scale))
        self.update()

    def set(self, down_bps: float, up_bps: float):
        self.down, self.up = down_bps, up_bps
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h, half = self.height(), self.width() / 2
        f = QFont("Consolas")
        f.setPointSizeF(scaled_point_size(9, self.scale))
        p.setFont(f)
        p.setPen(QColor(ACCENTS["DOWN"]))
        p.drawText(QRectF(0, 0, half, h), Qt.AlignVCenter | Qt.AlignLeft,
                   "▼ " + human_speed(self.down))
        p.setPen(QColor(ACCENTS["UP"]))
        p.drawText(QRectF(half, 0, half, h), Qt.AlignVCenter | Qt.AlignRight,
                   "▲ " + human_speed(self.up))
        p.end()


# 96 px GitHub mark (white cat on a dark disc), inlined as a PNG so the
# app remains a single file plus its i18n JSON. Generated from the official
# Octocat mark; base64 decoding ignores the line breaks.
_GITHUB_MARK_PNG = """
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
"""


def github_icon() -> QIcon:
    """The GitHub mark for the About box (with a painted fallback)."""
    pm = QPixmap()
    try:
        pm.loadFromData(base64.b64decode(_GITHUB_MARK_PNG), "PNG")
    except Exception:
        pm = QPixmap()
    if pm.isNull():
        # Keep the About box usable even on a Qt build without a PNG plugin.
        pm = QPixmap(96, 96)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0C0E14"))
        p.drawEllipse(4, 4, 88, 88)
        p.setPen(QColor(TEXT_MAIN))
        p.setFont(QFont("Segoe UI", 30, QFont.Bold))
        p.drawText(pm.rect(), Qt.AlignCenter, "GH")
        p.end()
    return QIcon(pm)


def _open_url(url: str) -> bool:
    """Open a fixed external URL in the user's default browser."""
    return QDesktopServices.openUrl(QUrl(url))


class AboutDialog(QDialog):
    """Modal About card: version and a clickable GitHub mark.

    The dialog is deliberately fixed-size: a resizable About box would only add
    empty space (the type is fixed), and the previous fixed width allowed the
    window manager to stretch only the height. It is laid out at a larger,
    readable size instead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{_('About')} {APP_NAME}")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        k = ABOUT_SCALE

        def px(value: float) -> int:
            return max(1, int(value * k + 0.5))

        self.setStyleSheet(
            "QDialog{background:#12141C;}"
            "QLabel{color:#E8EAF0;}"
            f"QLabel#brand{{color:#E8EAF0;font-size:{px(28)}px;"
            f"font-weight:700;letter-spacing:{px(7)}px;}}"
            f"QLabel#appInfo{{color:#9CA3AF;font-size:{px(15)}px;}}"
            f"QLabel#repo{{color:#6B7280;font-size:{px(13)}px;}}"
            f"QLabel#copyright{{color:#4B5563;font-size:{px(11)}px;}}"
            "QPushButton#githubButton{background:transparent;border:none;"
            f"border-radius:{px(34)}px;}}"
            "QPushButton#githubButton:hover{background:rgba(255,255,255,0.08);}"
            "QPushButton#closeButton{background:rgba(255,255,255,0.06);"
            "color:#E8EAF0;border:none;"
            f"border-radius:{px(7)}px;"
            f"padding:{px(8)}px {px(28)}px;font-size:{px(13)}px;}}"
            "QPushButton#closeButton:hover{background:rgba(255,255,255,0.14);}")

        root = QVBoxLayout(self)
        root.setContentsMargins(px(30), px(30), px(30), px(26))
        root.setSpacing(px(5))

        brand = QLabel("PULSE")
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignCenter)
        info = QLabel(f"{APP_NAME}  ·  "
                      f"{_('Version {version}', version=APP_VERSION)}")
        info.setObjectName("appInfo")
        info.setAlignment(Qt.AlignCenter)
        # Exposed for tests and for anyone who wants to read the shown version.
        self.version_label = info

        root.addWidget(brand)
        root.addWidget(info)
        root.addSpacing(px(12))

        self.github_btn = QPushButton()
        self.github_btn.setObjectName("githubButton")
        self.github_btn.setIcon(github_icon())
        self.github_btn.setIconSize(QSize(px(60), px(60)))
        self.github_btn.setFixedSize(px(68), px(68))
        self.github_btn.setCursor(Qt.PointingHandCursor)
        self.github_btn.setAccessibleName("GitHub")
        self.github_btn.setAccessibleDescription(
            _("Open the GitHub repository"))
        self.github_btn.setToolTip(_("Open the GitHub repository"))
        self.github_btn.clicked.connect(self.open_github)
        root.addWidget(self.github_btn, alignment=Qt.AlignHCenter)

        repo = QLabel(GITHUB_URL.removeprefix("https://"))
        repo.setObjectName("repo")
        repo.setAlignment(Qt.AlignCenter)
        repo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(repo)
        copyright_label = QLabel("© 2026 Strix Advanced Tools")
        copyright_label.setObjectName("copyright")
        copyright_label.setAlignment(Qt.AlignCenter)
        root.addWidget(copyright_label)

        close = QPushButton(_("Close"))
        close.setObjectName("closeButton")
        close.setCursor(Qt.PointingHandCursor)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        root.addSpacing(px(20))
        root.addWidget(close, alignment=Qt.AlignHCenter)

        # Lock both dimensions after the layout has measured itself: the old
        # fixed width let the WM change only the height, which looked broken.
        self.setFixedWidth(px(460))
        self.adjustSize()
        self.setFixedSize(px(460), self.height())

    def open_github(self):
        _open_url(GITHUB_URL)


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
        self.on_top = self.settings.get("on_top", False)
        if os.name == "nt":
            self.autostart = self.settings.get("autostart", True)
        else:
            # The XDG drop-in is the source of truth for the checkbox; it is
            # regenerated from the running interpreter when out of date.
            self.autostart = os.path.exists(_linux_autostart_path())
        ensure_autostart(self.autostart)   # keep the login entry in sync
        self.scale = clamp_scale(self.settings.get("scale", DEFAULT_SCALE))
        self._base_size = QSize(BASE_WIDTH, layout_metrics(1.0)["height"])
        self._drag_offset: QPoint | None = None
        self._resize: dict | None = None
        self._quitting = False
        # Ctrl+wheel does not jump straight to the new scale: a short
        # time-based ease-out makes one notch feel like a continuous zoom
        # instead of a one-step window jump.
        self._zoom_target = self.scale
        self._zoom_start_scale = self.scale
        self._zoom_clock = QElapsedTimer()
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setInterval(16)
        self._zoom_timer.timeout.connect(self._zoom_tick)

        self.setWindowTitle(APP_NAME)
        # Desktop widget: sit at the BOTTOM of the z-order by default, so
        # normal windows cover it; "on top" floats it above everything instead.
        flags = Qt.FramelessWindowHint | Qt.Tool
        flags |= (Qt.WindowStaysOnTopHint if self.on_top
                  else Qt.WindowStaysOnBottomHint)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.gpu = GpuReader()
        self._last_net = psutil.net_io_counters()
        self._last_t = time.monotonic()
        psutil.cpu_percent(interval=None)  # prime the counter

        self._build_ui()
        self._apply_scale(self.scale)
        large = layout_metrics(SCALE_MAX)
        self.setMaximumSize(large["width"], large["height"])
        self._build_tray()
        self._restore_position()
        self._apply_cursor()

        # Hover moves must reach PulseWidget even over child rows, otherwise
        # the corner resize cursor would only appear on the bare card edges.
        for child in self.findChildren(QWidget):
            child.setMouseTracking(True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)
        self.refresh()

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        # We own the window geometry (it is frameless and scaled by hand). A
        # constrained layout would resize the top-level to the new minimum
        # height before our setGeometry runs, producing an extra native
        # configure per frame and visible jitter while zooming.
        root.setSizeConstraint(QLayout.SetNoConstraint)
        self.root_layout = root
        pad = SHADOW_PAD
        root.setContentsMargins(pad + CONTENT_PAD_X, pad + CONTENT_PAD_TOP,
                                pad + CONTENT_PAD_X, pad + CONTENT_PAD_BOTTOM)
        root.setSpacing(ROW_SPACING)

        header = QHBoxLayout()
        title = QLabel("PULSE")
        self._title = title
        self._title_spec = ("Segoe UI", 10, QFont.Bold)
        title.setStyleSheet(f"color:{TEXT_MAIN}; letter-spacing:4px;")
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.sub = QLabel(_("system monitor"))
        self._sub_spec = ("Segoe UI", 7, QFont.Normal)
        self.sub.setStyleSheet(f"color:{TEXT_DIM};")
        self.sub.setFont(QFont("Segoe UI", 7))

        self.pin_btn = QPushButton()
        self.pin_btn.clicked.connect(self.toggle_pin)
        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip(_("Hide to tray"))
        self.close_btn.clicked.connect(self.hide)
        self._buttons = (self.pin_btn, self.close_btn)
        for b in self._buttons:
            b.setFixedSize(HEADER_H, HEADER_H)
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
        self._bars = (self.cpu_bar, self.gpu_bar, self.ram_bar, self.disk_bar)
        for bar in self._bars:
            root.addWidget(bar)

        net_label = QLabel("NETWORK")
        self._net_label = net_label
        self._net_spec = ("Segoe UI", 7, QFont.DemiBold)
        net_label.setFont(QFont("Segoe UI", 7, QFont.DemiBold))
        net_label.setFixedHeight(NET_LABEL_H)
        net_label.setStyleSheet(
            f"color:{TEXT_DIM}; letter-spacing:2px; margin-top:4px;")
        root.addWidget(net_label)
        self.net_row = NetRow()
        root.addWidget(self.net_row)

        self._update_pin_icon()

    # ---------------- scaling ----------------
    def _size_for_scale(self, scale) -> QSize:
        """Window size for a scale; width and height grow proportionally."""
        m = layout_metrics(scale)
        return QSize(m["width"], m["height"])

    def _sync_meter_columns(self):
        """Give every meter row the same label and value columns.

        The value column is as wide as the widest current value, so the four
        tracks always have exactly the same length; the values stay right-
        aligned on the card edge. Both columns are measured at the capped font
        size, which is what keeps the bars filling the card at 2×–4×.
        """
        leading = round(max(bar.label_width() for bar in self._bars)
                        + METER_LABEL_GAP * capped_font_scale(self.scale))
        value_column = math.ceil(max(bar.value_width() for bar in self._bars))
        for bar in self._bars:
            bar.set_columns(leading, value_column)

    def _apply_scale(self, value):
        """Scale in place, keeping the current top-left."""
        self._stop_zoom()
        self._apply_scale_to(value, self.x(), self.y())
        self._zoom_target = self.scale

    def _apply_scale_to(self, value, x, y):
        """Resize the card and every row/font, moving it in the same step.

        Called on launch, on Ctrl+wheel and continuously while a corner is
        dragged. `setGeometry` sends one configure request (size + position)
        instead of the fixed-size-plus-move pair, which made dragging stutter
        and let the window manager race the requested position. It never
        persists by itself — the caller decides when the new scale is final.
        """
        s = clamp_scale(value)
        self.scale = s
        m = layout_metrics(s)
        self.root_layout.setContentsMargins(
            m["margin_left"], m["margin_top"],
            m["margin_right"], m["margin_bottom"])
        self.root_layout.setSpacing(m["spacing"])

        # The header is exactly as tall as its buttons; the labels are pinned
        # to that height too, so the layout height matches `m["height"]` even
        # after the font cap stops the text from growing.
        for label in (self._title, self.sub):
            label.setFixedHeight(m["header"])
        for bar in self._bars:
            bar.set_scale(s)
        self._sync_meter_columns()
        self._net_label.setFixedHeight(m["net_label"])
        self.net_row.set_scale(s)

        for b in self._buttons:
            b.setFixedSize(m["header"], m["header"])
            radius = max(1, round(m["header"] / 2))
            fs = capped_font_scale(s)
            b.setStyleSheet(
                "QPushButton{background:rgba(255,255,255,0.06); color:#9CA3AF;"
                f" border:none; border-radius:{radius}px;"
                f" font-size:{max(1, round(10 * fs))}px;}}"
                "QPushButton:hover{background:rgba(255,255,255,0.16);"
                " color:#fff;}")

        self._apply_fonts(s)
        self.setGeometry(int(x), int(y), m["width"], m["height"])
        self.update()

    def _apply_fonts(self, scale):
        s = clamp_scale(scale)
        fs = capped_font_scale(s)
        title_family, title_pt, title_weight = self._title_spec
        title_font = QFont(title_family)
        title_font.setPointSizeF(scaled_point_size(title_pt, fs))
        title_font.setWeight(title_weight)
        self._title.setFont(title_font)
        self._title.setStyleSheet(
            f"color:{TEXT_MAIN}; letter-spacing:{max(0, round(4 * fs))}px;")

        sub_family, sub_pt, sub_weight = self._sub_spec
        sub_font = QFont(sub_family)
        sub_font.setPointSizeF(scaled_point_size(sub_pt, fs))
        sub_font.setWeight(sub_weight)
        self.sub.setFont(sub_font)

        net_family, net_pt, net_weight = self._net_spec
        net_font = QFont(net_family)
        net_font.setPointSizeF(scaled_point_size(net_pt, fs))
        net_font.setWeight(net_weight)
        self._net_label.setFont(net_font)
        self._net_label.setStyleSheet(
            f"color:{TEXT_DIM}; letter-spacing:{max(0, round(2 * fs))}px;"
            f" margin-top:{round(4 * s)}px;")

    def paintEvent(self, _):
        """Card + hand-painted soft shadow.

        A QGraphicsDropShadowEffect on a top-level translucent window renders
        unreliably on Windows (clipping/artifacts), so the shadow is painted
        manually as fading rounded outlines inside the reserved margin.
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.scale
        pad = round(SHADOW_PAD * s)
        corner = CORNER * s
        shadow_pen = max(1, round(2 * s))
        shadow_dy = round(2 * s)
        card = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        # soft shadow: expanding translucent outlines. The layer count is
        # capped so a 4x card does not paint 48 full-size rounded rects every
        # frame; the outermost layers are a couple of pixels apart and the
        # gradient is visually unchanged.
        p.setBrush(Qt.NoBrush)
        steps = min(pad, SHADOW_MAX_STEPS)
        for step in range(steps, 0, -1):
            offset = step * pad / steps
            alpha = int(38 * (1 - offset / (pad + 1)) ** 2)
            p.setPen(QPen(QColor(0, 0, 0, alpha), shadow_pen))
            p.drawRoundedRect(
                card.adjusted(-offset, -offset + shadow_dy,
                              offset, offset + shadow_dy),
                corner + offset * 0.6, corner + offset * 0.6)
        # glass card
        path = QPainterPath()
        path.addRoundedRect(card, corner, corner)
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

        g, vram = self.gpu.percent, self.gpu.vram
        if g is None:
            gpu_txt = "  N/A"
        elif vram:
            gpu_txt = f"{g:3.0f}% {human_vram(vram[0], vram[1])}"
        else:
            gpu_txt = f"{g:4.0f}%"
        self.gpu_bar.set(g, gpu_txt)

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

        # Keep the shared value column wide enough for the new texts; this also
        # keeps all four tracks exactly the same length.
        self._sync_meter_columns()

        now = time.monotonic()
        net = psutil.net_io_counters()
        dt = max(now - self._last_t, 1e-6)
        down = max(0.0, (net.bytes_recv - self._last_net.bytes_recv) / dt)
        up = max(0.0, (net.bytes_sent - self._last_net.bytes_sent) / dt)
        self._last_net, self._last_t = net, now
        self.net_row.set(down, up)

        if g is None:
            gpu_tip = "GPU N/A"
        elif vram:
            gpu_tip = f"GPU {g:.0f}%   VRAM {human_vram(vram[0], vram[1])}"
        else:
            gpu_tip = f"GPU {g:.0f}%"
        self.tray.setToolTip(
            f"{APP_NAME}\nCPU {cpu:.0f}%   RAM {vm.percent:.0f}%\n"
            f"{gpu_tip}\n"
            f"▼ {human_speed(down).strip()}   ▲ {human_speed(up).strip()}")

    # ---------------- drag, resize & zoom ----------------
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            super().mousePressEvent(e)
            return
        self._stop_zoom()
        gp = e.globalPosition().toPoint()
        corner = resize_corner(self.mapFromGlobal(gp), self.width(),
                               self.height(), self.scale)
        if corner:
            # Pin locks moving, never resizing: corners work either way.
            self._begin_resize(corner, gp)
            e.accept()
            return
        if not self.pinned:
            self._drag_offset = gp - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        gp = e.globalPosition().toPoint()
        if self._resize is not None:
            self._resize_to(gp)
            e.accept()
            return
        if self._drag_offset is not None and not self.pinned:
            self.move(gp - self._drag_offset)
            e.accept()
            return
        self._update_hover_cursor(gp)

    def mouseReleaseEvent(self, e):
        if self._resize is not None:
            self._resize = None
            self._persist()
            self._update_hover_cursor(e.globalPosition().toPoint())
            e.accept()
            return
        if self._drag_offset is not None:
            self._drag_offset = None
            self._persist()

    def wheelEvent(self, e):
        """Ctrl + wheel: SCALE_STEP per notch, eased in place."""
        if self._resize is not None or self._drag_offset is not None:
            # A held drag owns the window geometry; never start a second mover.
            e.accept()
            return
        if e.modifiers() & Qt.ControlModifier:
            delta = e.angleDelta().y() or e.pixelDelta().y()
            if delta:
                target = zoomed_scale(self._zoom_target, delta / 120.0)
                self._zoom_to(target)
                e.accept()
                return
        super().wheelEvent(e)

    def _zoom_to(self, target):
        """Set a new zoom target; the timer eases the card towards it in place."""
        target = clamp_scale(target)
        if target == self._zoom_target and self._zoom_timer.isActive():
            return
        self._zoom_target = target
        if target == self.scale:
            self._stop_zoom()
            return
        if ZOOM_EASE_MS <= 0:
            # Zero duration (used by tests): apply the notch immediately in a
            # single geometry update.
            self._zoom_frame(target)
            self._zoom_target = self.scale
            self._persist()
            self._update_hover_cursor(QCursor.pos())
            return
        self._zoom_start_scale = self.scale
        self._zoom_clock.restart()
        if not self._zoom_timer.isActive():
            self._zoom_timer.start()

    def _zoom_frame(self, new_scale):
        """Apply one zoom frame without moving the card's top-left."""
        self._apply_scale_to(new_scale, self.x(), self.y())

    def _zoom_tick(self):
        """One smoothstep frame over ZOOM_EASE_MS milliseconds.

        Smoothstep is deliberate: a plain exponential ease-out puts most of a
        10 % step into the first frame, which still reads as a jump. This curve
        starts and ends slowly and spends its frames resizing the window.
        """
        elapsed = self._zoom_clock.elapsed()
        if ZOOM_EASE_MS <= 0 or elapsed >= ZOOM_EASE_MS:
            new_scale = self._zoom_target
            done = True
        else:
            t = max(0.0, min(elapsed / ZOOM_EASE_MS, 1.0))
            eased = t * t * (3.0 - 2.0 * t)     # smoothstep
            new_scale = (self._zoom_start_scale
                         + (self._zoom_target - self._zoom_start_scale) * eased)
            done = False

        self._zoom_frame(new_scale)

        if done:
            self._zoom_timer.stop()
            self._zoom_target = self.scale
            self._persist()
            self._update_hover_cursor(QCursor.pos())

    def _stop_zoom(self):
        """Abandon/finish an animation instantly (e.g. when a drag starts)."""
        self._zoom_timer.stop()
        self._zoom_target = self.scale

    def _begin_resize(self, corner: str, global_pos: QPoint):
        fg = self.frameGeometry()
        anchor = QPoint(
            fg.x() + fg.width() if "left" in corner else fg.x(),
            fg.y() + fg.height() if "top" in corner else fg.y())
        self._resize = {
            "corner": corner,
            "anchor": anchor,
            "press": QPoint(global_pos),
            "start_scale": self.scale,
        }
        self.setCursor(CORNER_CURSORS[corner])

    def _resize_to(self, global_pos: QPoint):
        r = self._resize
        if r is None:
            return
        dx = global_pos.x() - r["press"].x()
        dy = global_pos.y() - r["press"].y()
        scale = corner_drag_scale(
            r["corner"], dx, dy, self._base_size.width(),
            self._base_size.height(), r["start_scale"])
        if scale == self.scale:
            return
        target = layout_metrics(scale)
        pos = corner_resize_pos(r["corner"], r["anchor"],
                                target["width"], target["height"])
        self._apply_scale_to(scale, pos.x(), pos.y())

    def _update_hover_cursor(self, global_pos: QPoint):
        local = self.mapFromGlobal(global_pos)
        corner = resize_corner(local, self.width(), self.height(), self.scale)
        if corner:
            shape = CORNER_CURSORS[corner]
        elif self.pinned:
            shape = Qt.ArrowCursor
        else:
            shape = Qt.SizeAllCursor
        # setCursor on every mouse move means an X cursor round-trip per event.
        if self.cursor().shape() != shape:
            self.setCursor(shape)

    def _clamp_pos(self, x, y, width, height):
        """Clamp a target rect into the screen it is centred on."""
        app = QApplication.instance()
        center = QPoint(x + width // 2, y + height // 2)
        screen = app.screenAt(center) if app is not None else None
        screen = screen or QApplication.primaryScreen()
        if screen is None:
            return x, y
        avail = screen.availableGeometry()
        if width >= avail.width():
            x = avail.left()
        else:
            x = max(avail.left(), min(x, avail.right() - width + 1))
        if height >= avail.height():
            y = avail.top()
        else:
            y = max(avail.top(), min(y, avail.bottom() - height + 1))
        return x, y

    def toggle_pin(self):
        self.pinned = not self.pinned
        self._update_pin_icon()
        self._apply_cursor()
        self._persist()

    def toggle_on_top(self):
        self.on_top = not self.on_top
        # On X11, changing the window flags re-creates the native window and
        # drops _NET_WM_STATE, so ask the WM through EWMH instead. Windows and
        # other platforms use the Qt flag path.
        if not self._sync_stacking():
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowStaysOnBottomHint, not self.on_top)
            self.setWindowFlag(Qt.WindowStaysOnTopHint, self.on_top)
            if visible:
                self.show()
        self.act_top.setChecked(self.on_top)
        self._persist()

    def _sync_stacking(self) -> bool:
        """Apply the stacking state on X11 via EWMH; False elsewhere."""
        if QApplication.platformName() != "xcb":
            return False
        try:
            wid = int(self.winId())
        except (TypeError, ValueError):
            return False
        return _x11_set_stacking(wid, self.on_top)

    def showEvent(self, event):
        super().showEvent(event)
        # A hidden window re-shown after a toggle must get its state re-applied
        # once it is actually mapped; defer until the event loop runs again.
        QTimer.singleShot(0, self._sync_stacking)

    def toggle_autostart(self):
        self.autostart = not self.autostart
        ensure_autostart(self.autostart)
        self.act_auto.setChecked(self.autostart)   # keep tray menu in sync
        self._persist()

    def _apply_cursor(self):
        self._update_hover_cursor(QCursor.pos())

    def _update_pin_icon(self):
        self.pin_btn.setText("📌" if self.pinned else "📍")
        self.pin_btn.setToolTip(_("Unpin — allow dragging") if self.pinned
                                else _("Pin — lock position"))

    def _persist(self):
        self.settings.update({"x": self.x(), "y": self.y(),
                              "scale": self.scale,
                              "pinned": self.pinned,
                              "on_top": self.on_top,
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
        # A saved position from a larger-and-further-right window must not put
        # the restored (possibly bigger) card off-screen on this launch.
        x, y = self._clamp_pos(x, y, self.width(), self.height())
        self.setGeometry(x, y, self.width(), self.height())

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
        self.act_top.setText(_("Always on top / bottom"))
        self.act_pin.setText(_("Toggle Pin"))
        self.act_auto.setText(_("Start on login"))
        self.act_about.setText(_("About"))
        self.act_quit.setText(_("Exit"))
        self.tray_lang_menu.setTitle(_("Language"))
        for act, code in zip(self.tray_lang_menu.actions(), LANG_CODES):
            act.setChecked(code == _TR.lang)

    # ---------------- context menu ----------------
    def _show_context_menu(self, pos):
        menu = QMenu(self)
        act_pin = menu.addAction(_("Unpin") if self.pinned else _("Pin"))
        act_hide = menu.addAction(_("Hide to tray"))
        act_top = menu.addAction(_("Always on top / bottom"))
        act_top.setCheckable(True)
        act_top.setChecked(self.on_top)
        act_auto = menu.addAction(_("Start on login"))
        act_auto.setCheckable(True)
        act_auto.setChecked(self.autostart)
        menu.addMenu(self._make_language_menu(menu))
        menu.addSeparator()
        act_about = menu.addAction(_("About"))
        act_quit = menu.addAction(_("Exit"))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == act_pin:
            self.toggle_pin()
        elif chosen == act_hide:
            self.hide()
        elif chosen == act_top:
            self.toggle_on_top()
        elif chosen == act_auto:
            self.toggle_autostart()
        elif chosen == act_about:
            self._show_about()
        elif chosen == act_quit:
            self._quit()

    # ---------------- system tray ----------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._make_tray_icon(), self)
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        self.act_show = QAction(_("Show / Hide"), menu)
        self.act_show.triggered.connect(self._toggle_visible)
        self.act_top = QAction(_("Always on top / bottom"), menu)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(self.on_top)
        self.act_top.triggered.connect(self.toggle_on_top)
        self.act_pin = QAction(_("Toggle Pin"), menu)
        self.act_pin.triggered.connect(self.toggle_pin)
        self.act_auto = QAction(_("Start on login"), menu)
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(self.autostart)
        self.act_auto.triggered.connect(self.toggle_autostart)
        self.act_about = QAction(_("About"), menu)
        self.act_about.triggered.connect(self._show_about)
        self.act_quit = QAction(_("Exit"), menu)
        self.act_quit.triggered.connect(self._quit)
        self.tray_lang_menu = self._make_language_menu(menu)
        menu.addAction(self.act_show)
        menu.addAction(self.act_top)
        menu.addAction(self.act_pin)
        menu.addAction(self.act_auto)
        menu.addMenu(self.tray_lang_menu)
        menu.addSeparator()
        menu.addAction(self.act_about)
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

    def _show_about(self):
        AboutDialog(self).exec()

    def _toggle_visible(self):
        self.setVisible(not self.isVisible())

    def _quit(self):
        self._quitting = True
        self._stop_zoom()
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
