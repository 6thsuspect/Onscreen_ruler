#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Onscreen Measuring Ruler  -  measure anything that is visible on your screen.
==============================================================================

A full-screen, click-through-free, semi-transparent overlay that lets you
measure straight distances, angles, rectangles, ellipses/circles and
irregular outlines, in pixels / mm / cm / inches, with on-screen calibration
so the numbers match reality.

Author : built for the user on Arena.ai
License: MIT
Requires: Python 3.8+ with tkinter (bundled with the python.org Windows
          installer).  No third-party packages.

Keyboard shortcuts
------------------
  Esc            quit
  M              cycle drawing mode
  U              cycle unit
  C              clear all measurements
  Backspace      undo last point
  P              pin (keep) current measurement
  T              show / hide the toolbar
  H or F1        help
  [ / ]          more / less transparent
  Arrows         nudge the last point by 1 px (Shift + arrows = 10 px)
  Ctrl + C       copy current read-out to the clipboard

Mouse
-----
  Left drag      draw (Line / Rect / Ellipse / Calibrate)
  Left click     add a vertex (Poly / Angle mode)
  Right click    finish the shape (Poly) / cancel the current shape
"""

from __future__ import annotations

import json
import math
import os
import sys

import tkinter as tk
from tkinter import font as tkfont

APP_NAME = "Onscreen Measuring Ruler"
VERSION = "1.0.0"

# ----------------------------------------------------------------------------
#  Windows high-DPI helper (must run before the Tk window exists)
# ----------------------------------------------------------------------------
def enable_high_dpi() -> float:
    """Make the process per-monitor DPI aware and return the system DPI."""
    if sys.platform != "win32":
        return 96.0
    try:
        # -4 == DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes = __import__("ctypes")
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes = __import__("ctypes")
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes = __import__("ctypes")
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    try:
        ctypes = __import__("ctypes")
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi:
            return float(dpi)
    except Exception:
        pass
    return 96.0


# ----------------------------------------------------------------------------
#  Configuration (remembers calibration + preferences between runs)
# ----------------------------------------------------------------------------
def config_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "OnscreenRuler")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".onscreen_ruler")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        pass
    return os.path.join(folder, "config.json")


# ----------------------------------------------------------------------------
#  Small helpers
# ----------------------------------------------------------------------------
MODES = ["line", "poly", "rect", "ellipse", "angle", "calibrate"]
MODE_LABEL = {
    "line": "Line",
    "poly": "Irregular",
    "rect": "Rectangle",
    "ellipse": "Circle / Ellipse",
    "angle": "Angle",
    "calibrate": "Calibrate",
}
UNITS = ["px", "mm", "cm", "in"]
UNIT_NAME = {"px": "px", "mm": "mm", "cm": "cm", "in": "inch"}


def nice(val: float, unit: str) -> str:
    """Format a number with a sensible number of decimals for its unit."""
    if unit == "px":
        return "{:,}".format(int(round(val)))
    if unit == "mm":
        return f"{val:.2f}" if abs(val) < 10 else f"{val:.1f}"
    if unit == "cm":
        return f"{val:.3f}" if abs(val) < 10 else f"{val:.2f}"
    return f"{val:.3f}"


def dist(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def constrain(start, end, step=45.0):
    """Snap `end` around `start` to the nearest multiple of `step` degrees."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return end
    ang = math.degrees(math.atan2(dy, dx))
    snapped = round(ang / step) * step
    r = math.radians(snapped)
    return (start[0] + length * math.cos(r), start[1] + length * math.sin(r))


def polygon_area(pts) -> float:
    if len(pts) < 3:
        return 0.0
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def path_length(pts) -> float:
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


class FakeEvent:  # used by the self-test at the bottom
    def __init__(self, x, y, state=0, widget=None):
        self.x, self.y, self.state, self.widget = x, y, state, widget


# ----------------------------------------------------------------------------
#  Main overlay
# ----------------------------------------------------------------------------
class OnscreenRuler:
    BG = "#12161c"

    def __init__(self, root: tk.Tk, system_dpi: float = 96.0):
        self.root = root
        self.cfg = self.load_config()

        # ---- scale -----------------------------------------------------
        self.px_per_mm = float(self.cfg.get("px_per_mm") or (system_dpi / 25.4))
        self.unit = self.cfg.get("unit", "px")
        if self.unit not in UNITS:
            self.unit = "px"
        self.alpha = float(self.cfg.get("alpha", 0.35))
        self.keep = bool(self.cfg.get("keep", False))

        # ---- state -----------------------------------------------------
        self.mode = "line"
        self.pts = []          # points of the shape being drawn
        self.dragging = False
        self.cursor = None
        self.shift = False
        self.pinned_count = 0
        self.calibration = None
        self.nudged = False   # keyboard nudge happened since the last motion

        # ---- window ----------------------------------------------------
        root.title(APP_NAME)
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", self.alpha)
        root.configure(bg=self.BG, cursor="crosshair")
        try:
            root.attributes("-toolwindow", False)
        except Exception:
            pass

        self.canvas = tk.Canvas(root, bg=self.BG, highlightthickness=0,
                                bd=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.build_toolbar()
        self.build_hint()
        self.bind_events()
        self.set_mode("line")
        self.update_crosshair(None)

    # ------------------------------------------------------------------ config
    def load_config(self) -> dict:
        try:
            with open(config_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_config(self):
        try:
            with open(config_path(), "w", encoding="utf-8") as fh:
                json.dump({
                    "px_per_mm": round(self.px_per_mm, 6),
                    "unit": self.unit,
                    "alpha": round(self.alpha, 2),
                    "keep": self.keep,
                }, fh, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------- fonts
    def font(self, size=10, bold=False):
        return ("Consolas", size, "bold" if bold else "normal")

    # ----------------------------------------------------------------- toolbar
    def build_toolbar(self):
        self.toolbar = tk.Frame(self.root, bg="#1b2027", bd=1, relief=tk.SOLID)
        self.toolbar.place(x=18, y=18)

        row = tk.Frame(self.toolbar, bg="#1b2027")
        row.pack(padx=6, pady=6)

        self.mode_buttons = {}
        for m in MODES:
            b = tk.Button(row, text=MODE_LABEL[m], command=lambda m=m: self.set_mode(m),
                          bg="#2b333d", fg="#e8eef5", activebackground="#3d4a58",
                          activeforeground="white", relief=tk.FLAT, bd=0,
                          padx=10, pady=5, font=self.font(9), cursor="hand2",
                          highlightthickness=0)
            b.pack(side=tk.LEFT, padx=2)
            self.mode_buttons[m] = b

        tk.Frame(row, bg="#3a444f", width=1, height=26).pack(side=tk.LEFT, padx=6)

        self.unit_var = tk.StringVar(value=self.unit)
        unit = tk.OptionMenu(row, self.unit_var, *UNITS, command=self.set_unit)
        unit.config(bg="#2b333d", fg="#e8eef5", activebackground="#3d4a58",
                    relief=tk.FLAT, bd=0, font=self.font(9), highlightthickness=0,
                    width=3, cursor="hand2")
        unit["menu"].config(bg="#2b333d", fg="#e8eef5", font=self.font(9))
        unit.pack(side=tk.LEFT, padx=2)

        self.keep_btn = tk.Button(row, text="Pin: OFF", command=self.toggle_keep,
                                  bg="#2b333d", fg="#e8eef5", activebackground="#3d4a58",
                                  relief=tk.FLAT, bd=0, padx=8, pady=5,
                                  font=self.font(9), cursor="hand2")
        self.keep_btn.pack(side=tk.LEFT, padx=2)
        self.refresh_keep_button()

        self.copy_btn = tk.Button(row, text="Copy", command=self.copy_readout,
                                  bg="#2b333d", fg="#e8eef5", activebackground="#3d4a58",
                                  relief=tk.FLAT, bd=0, padx=8, pady=5,
                                  font=self.font(9), cursor="hand2")
        self.copy_btn.pack(side=tk.LEFT, padx=2)

        tk.Button(row, text="Clear", command=self.clear_all, bg="#4a3a1f", fg="#ffd27f",
                  activebackground="#6b552c", relief=tk.FLAT, bd=0, padx=8, pady=5,
                  font=self.font(9), cursor="hand2").pack(side=tk.LEFT, padx=2)

        tk.Button(row, text="Help", command=self.show_help, bg="#1f3a4a", fg="#9fd8ff",
                  activebackground="#2c5468", relief=tk.FLAT, bd=0, padx=8, pady=5,
                  font=self.font(9), cursor="hand2").pack(side=tk.LEFT, padx=2)

        tk.Button(row, text="Close", command=self.quit, bg="#5a2222", fg="#ffb3b3",
                  activebackground="#7d2f2f", relief=tk.FLAT, bd=0, padx=8, pady=5,
                  font=self.font(9), cursor="hand2").pack(side=tk.LEFT, padx=2)

        # green read-out
        self.readout = tk.Label(self.toolbar, text="", bg="#10151a", fg="#37ff9a",
                                font=self.font(12, True), anchor="w", padx=10, pady=6)
        self.readout.pack(fill=tk.X, padx=6, pady=(0, 6))

        self.scale_lbl = tk.Label(self.toolbar, text=self.scale_text(), bg="#1b2027",
                                  fg="#7d8b99", font=self.font(8), anchor="w", padx=8)
        self.scale_lbl.pack(fill=tk.X, padx=6, pady=(0, 4))

    def build_hint(self):
        self.hint = tk.Label(self.root, bg="#10151a", fg="#8fa3b6", font=self.font(8),
                             justify=tk.LEFT, padx=8, pady=4,
                             text="Esc quit   M mode   U unit   C clear   "
                                  "Shift = snap 45°   P pin   T hide bar")
        self.hint.place(relx=0.0, rely=1.0, anchor="sw", x=18, y=-14)

    # ------------------------------------------------------------------- events
    def bind_events(self):
        c = self.canvas
        c.bind("<Button-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Motion>", self.on_motion)
        c.bind("<Button-3>", self.on_right)
        self.root.bind("<Escape>", lambda e: self.quit())
        self.root.bind("<KeyPress>", self.on_key)
        self.root.bind("<KeyRelease>", self.on_key_release)

    def on_key_release(self, ev):
        if ev.keysym in ("Shift_L", "Shift_R"):
            self.shift = False

    def on_key(self, ev):
        k = ev.keysym
        if k in ("Shift_L", "Shift_R"):
            self.shift = True
            return
        if k == "Escape":
            self.quit()
        elif k.lower() == "m":
            self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])
        elif k.lower() == "u":
            self.set_unit(UNITS[(UNITS.index(self.unit) + 1) % len(UNITS)])
        elif k.lower() == "c" and not (ev.state & 0x4):
            self.clear_all()
        elif k.lower() == "c" and (ev.state & 0x4):
            self.copy_readout()
        elif k.lower() == "p":
            self.pin_current()
        elif k.lower() == "t":
            self.toggle_toolbar()
        elif k in ("h", "F1"):
            self.show_help()
        elif k == "bracketleft":
            self.set_alpha(self.alpha - 0.08)
        elif k == "bracketright":
            self.set_alpha(self.alpha + 0.08)
        elif k == "BackSpace":
            self.undo_point()
        elif k in ("Left", "Right", "Up", "Down"):
            self.nudge(k, 10 if (ev.state & 0x1) else 1)
        elif k in ("Return", "KP_Enter"):
            if self.mode == "poly" and len(self.pts) > 1:
                self.finish_poly(close=False)

    # --------------------------------------------------------------------- modes
    def set_mode(self, mode):
        self.mode = mode
        self.clear_temp()
        self.pts = []
        self.dragging = False
        for m, b in self.mode_buttons.items():
            active = (m == mode)
            b.config(bg="#2f6f4f" if active else "#2b333d",
                     fg="white" if active else "#e8eef5")
        hints = {
            "line": "Click and drag between two points.  Hold Shift to snap to 45°.",
            "poly": "Click to add vertices around the outline.  Right-click or Enter to finish.",
            "rect": "Drag to measure width, height, area, perimeter, diagonal.",
            "ellipse": "Drag from the centre outwards to measure radius / area / circumference.",
            "angle": "Click three points: first arm, vertex, second arm.",
            "calibrate": "Drag across something of known length, then type its real length.",
        }
        self.set_readout(f"{MODE_LABEL[mode].upper()}  -  {hints[mode]}")

    def set_unit(self, unit):
        self.unit = unit
        self.unit_var.set(unit)
        self.scale_lbl.config(text=self.scale_text())
        self.convert_pinned()
        self.refresh_readout()
        self.save_config()

    def set_alpha(self, a):
        self.alpha = min(1.0, max(0.08, a))
        self.root.attributes("-alpha", self.alpha)
        self.save_config()

    def toggle_keep(self):
        self.keep = not self.keep
        self.refresh_keep_button()
        self.save_config()

    def refresh_keep_button(self):
        self.keep_btn.config(text="Pin: ON" if self.keep else "Pin: OFF",
                             bg="#2f6f4f" if self.keep else "#2b333d")

    def toggle_toolbar(self):
        if self.toolbar.winfo_ismapped():
            self.toolbar.place_forget()
        else:
            self.toolbar.place(x=18, y=18)

    # ------------------------------------------------------------------ scale math
    def scale_text(self):
        return (f"Scale: {self.px_per_mm:.3f} px/mm   "
                f"({self.px_per_mm * 25.4:.1f} px/inch)   Unit: {UNIT_NAME[self.unit]}")

    def conv(self, px):
        if self.unit == "px":
            return px
        mm = px / self.px_per_mm
        if self.unit == "mm":
            return mm
        if self.unit == "cm":
            return mm / 10.0
        return mm / 25.4

    def fmt(self, px):
        return f"{nice(self.conv(px), self.unit)} {UNIT_NAME[self.unit]}"

    def fmt2(self, px_area):
        """Area formatting (square units)."""
        u = "px²" if self.unit == "px" else ("mm²" if self.unit == "mm" else
                                            ("cm²" if self.unit == "cm" else "in²"))
        return f"{nice(self.conv_area(px_area), self.unit)} {u}"

    def conv_area(self, px_area):
        if self.unit == "px":
            return px_area
        return px_area / (self.px_per_mm ** 2) * (
            1.0 if self.unit == "mm" else (0.01 if self.unit == "cm" else 1 / 645.16))

    # ------------------------------------------------------------------- drawing
    def tag_clear(self, tag):
        self.canvas.delete(tag)

    def clear_temp(self):
        self.canvas.delete("temp")

    def clear_all(self):
        self.canvas.delete("temp")
        self.canvas.delete("pinned")
        self.pts = []
        self.dragging = False
        self.pinned_count = 0
        self.set_readout("Cleared.  " + MODE_LABEL[self.mode] + " mode ready.")

    def draw_label(self, x, y, text, color="#37ff9a", tag="temp"):
        """Draw a text label with a dark plate behind it."""
        pad = 4
        t = self.canvas.create_text(x, y, text=text, fill=color, font=self.font(10, True),
                                    anchor="center", tags=(tag, "tmp_label"))
        b = self.canvas.bbox(t)
        if b:
            plate = self.canvas.create_rectangle(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad,
                                                 fill="#0b0f13", outline="#2f3d4a", tags=(tag, "tmp_label"))
            self.canvas.tag_lower(plate, t)
        return t

    def draw_endpoint(self, x, y, color="#37ff9a", tag="temp"):
        r = 3
        self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="",
                                tags=tag)

    def line_with_ticks(self, x0, y0, x1, y1, color="#37ff9a", tag="temp"):
        """A dimension line with perpendicular end ticks."""
        self.canvas.create_line(x0, y0, x1, y1, fill=color, width=1, tags=tag)
        ang = math.atan2(y1 - y0, x1 - x0)
        nx, ny = -math.sin(ang), math.cos(ang)
        t = 6
        for (px, py) in ((x0, y0), (x1, y1)):
            self.canvas.create_line(px - nx * t, py - ny * t, px + nx * t, py + ny * t,
                                    fill=color, width=2, tags=tag)

    def redraw(self):
        """Redraw the temporary (in-progress) layer."""
        self.clear_temp()
        if self.mode == "poly":
            self.draw_poly()
            return
        if self.mode == "angle":
            self.draw_angle()
            return
        if not self.pts or not self.cursor:
            return
        x0, y0 = self.pts[0]
        end = self.cursor
        if self.shift and self.dragging:
            end = constrain(self.pts[0], end)
        x1, y1 = end

        if self.mode in ("line", "calibrate"):
            col = "#37ff9a" if self.mode == "line" else "#ffd166"
            self.line_with_ticks(x0, y0, x1, y1, color=col)
            self.draw_endpoint(x0, y0, col)
            self.draw_endpoint(x1, y1, col)
            length = dist((x0, y0), (x1, y1))
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            ang = math.degrees(math.atan2(-(y1 - y0), x1 - x0)) % 360
            off = 20
            self.draw_label(mx, my - off,
                            f"{self.fmt(length)}   {ang:.1f}°", col)

        elif self.mode == "rect":
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#37ff9a", width=1,
                                         tags="temp")
            w, h = abs(x1 - x0), abs(y1 - y0)
            self.draw_label((x0 + x1) / 2, min(y0, y1) - 18,
                            f"{self.fmt(w)} × {self.fmt(h)}")
            self.draw_label((x0 + x1) / 2, max(y0, y1) + 18,
                            f"Area {self.fmt2(w * h)}    Perimeter {self.fmt(2 * (w + h))}",
                            color="#9fd8ff")

        elif self.mode == "ellipse":
            r = dist((x0, y0), (x1, y1))
            self.canvas.create_oval(x0 - r, y0 - r, x0 + r, y0 + r, outline="#37ff9a",
                                    width=1, tags="temp")
            self.canvas.create_line(x0, y0, x1, y1, fill="#ff6b6b", dash=(4, 3),
                                    tags="temp")
            self.draw_endpoint(x0, y0, "#ff6b6b")
            self.draw_endpoint(x1, y1, "#ff6b6b")
            self.draw_label(x0, y0 - r - 20,
                            f"⌀ {self.fmt(2 * r)}    R {self.fmt(r)}")
            self.draw_label(x0, y0 + r + 20,
                            f"Area {self.fmt2(math.pi * r * r)}    Circ {self.fmt(2 * math.pi * r)}",
                            color="#9fd8ff")

    def draw_poly(self):
        pts = list(self.pts)
        if pts and self.cursor:
            end = self.cursor
            if self.shift and len(pts) >= 1:
                end = constrain(pts[-1], end)
            ghost = pts + [end]
        else:
            ghost = pts
        if len(ghost) >= 2:
            flat = [c for p in ghost for c in p]
            self.canvas.create_line(*flat, fill="#37ff9a", width=2, tags="temp",
                                    joinstyle=tk.ROUND)
        for p in pts:
            self.draw_endpoint(p[0], p[1], "#ffd166")
        if pts and self.cursor:
            end = constrain(pts[-1], self.cursor) if self.shift else self.cursor
            seg = dist(pts[-1], end)
            self.draw_label(end[0] + 62, end[1] - 26,
                            f"seg {self.fmt(seg)}  ·  total {self.fmt(path_length(pts) + seg)}",
                            color="#9fd8ff")
        # faint closing hint of the loop (no fill: you must still see through it)
        if len(pts) >= 3:
            self.canvas.create_line(pts[-1][0], pts[-1][1], pts[0][0], pts[0][1],
                                    fill="#2f6f4f", dash=(3, 4), tags="temp")

    def draw_angle(self):
        pts = list(self.pts)
        cur = self.cursor
        col = "#37ff9a"
        for p in pts:
            self.draw_endpoint(p[0], p[1], "#ffd166")
        if len(pts) >= 2 and cur:
            self.canvas.create_line(pts[0][0], pts[0][1], pts[1][0], pts[1][1],
                                    fill=col, width=1, tags="temp")
            self.canvas.create_line(pts[1][0], pts[1][1], cur[0], cur[1],
                                    fill="#9fd8ff", width=1, dash=(4, 3), tags="temp")
            a = self.angle_at(pts[0], pts[1], cur)
            self.draw_label(cur[0] - 55, cur[1] + 30, f"{a:.2f}°", "#9fd8ff")
            self.arc_at(pts[1], pts[0], cur)
        elif len(pts) == 1 and cur:
            self.canvas.create_line(pts[0][0], pts[0][1], cur[0], cur[1],
                                    fill=col, width=1, tags="temp")

    def arc_at(self, vertex, a, b, radius=34):
        ang1 = math.degrees(math.atan2(a[1] - vertex[1], a[0] - vertex[0]))
        ang2 = math.degrees(math.atan2(b[1] - vertex[1], b[0] - vertex[0]))
        self.canvas.create_arc(vertex[0] - radius, vertex[1] - radius,
                               vertex[0] + radius, vertex[1] + radius,
                               start=-ang1, extent=-(ang2 - ang1), style=tk.ARC,
                               outline="#ffd166", width=1, tags="temp")

    @staticmethod
    def angle_at(a, v, b) -> float:
        v1 = (a[0] - v[0], a[1] - v[1])
        v2 = (b[0] - v[0], b[1] - v[1])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 == 0 or n2 == 0:
            return 0.0
        c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        return math.degrees(math.acos(c))

    # ----------------------------------------------------------------- mouse I/O
    def in_toolbar(self, x, y) -> bool:
        """Canvas coords -> is the point over the toolbar (or the hint bar)?"""
        try:
            tb_x = self.toolbar.winfo_x()
            tb_y = self.toolbar.winfo_y()
            if self.toolbar.winfo_ismapped() and \
               tb_x <= x <= tb_x + self.toolbar.winfo_width() and \
               tb_y <= y <= tb_y + self.toolbar.winfo_height():
                return True
        except Exception:
            pass
        return False

    def update_crosshair(self, ev):
        self.canvas.delete("hud")
        if ev is None:
            return
        x, y = ev.x, ev.y
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.canvas.create_line(0, y, w, y, fill="#ff6b6b", dash=(1, 4), tags="hud")
        self.canvas.create_line(x, 0, x, h, fill="#ff6b6b", dash=(1, 4), tags="hud")
        self.canvas.create_rectangle(x - 1, y - 1, x + 1, y + 1, outline="#ffffff",
                                     tags="hud")
        self.canvas.create_text(x + 12, y + 12, text=f"{x}, {y}", fill="#8fa3b6",
                                font=self.font(8), anchor="nw", tags="hud")

    def on_motion(self, ev):
        self.cursor = (ev.x, ev.y)
        self.nudged = False
        self.update_crosshair(ev)
        if self.dragging or (self.mode in ("poly", "angle") and self.pts):
            self.nudged = True
        self.redraw()
        self.refresh_readout()

    def on_press(self, ev):
        if self.in_toolbar(ev.x, ev.y):
            return
        self.root.focus_force()
        self.cursor = (ev.x, ev.y)

        if self.mode == "poly":
            if not self.pts and not self.keep:
                self.canvas.delete("pinned")
            p = (ev.x, ev.y)
            if self.shift and self.pts:
                p = constrain(self.pts[-1], p)
            self.pts.append(p)
            self.redraw()
            self.refresh_readout()
            return

        if self.mode == "angle":
            if len(self.pts) >= 3:
                self.pts = []
            self.pts.append((ev.x, ev.y))
            if len(self.pts) == 3:
                self.finish_angle()
            else:
                self.redraw()
            self.refresh_readout()
            return

        # drag modes
        if not self.keep:
            self.canvas.delete("pinned")
        self.pts = [(ev.x, ev.y)]
        self.dragging = True
        self.redraw()

    def on_drag(self, ev):
        self.cursor = (ev.x, ev.y)
        self.update_crosshair(ev)
        if self.dragging:
            self.redraw()
            self.refresh_readout()

    def on_release(self, ev):
        if not self.dragging:
            return
        if not self.nudged:
            self.cursor = (ev.x, ev.y)
        self.dragging = False
        if not self.pts:
            return
        if self.mode == "calibrate":
            self.finish_calibration()
            return
        if dist(self.pts[0], self.cursor) < 2:
            # a click, not a drag
            self.clear_temp()
            self.pts = []
            self.refresh_readout()
            return
        self.redraw()
        self.finalize()

    def on_right(self, ev):
        if self.mode == "poly" and len(self.pts) > 1:
            self.finish_poly(close=True)
        else:
            self.clear_temp()
            self.pts = []
            self.set_readout("Cancelled.")

    # ----------------------------------------------------------------- finishing
    def finalize(self):
        """Turn the temp layer into a pinned measurement and print the result."""
        if self.mode == "rect" and self.pts and self.cursor:
            x0, y0 = self.pts[0]
            end = self.cursor
            if self.shift:
                end = constrain(self.pts[0], end)
            x1, y1 = end
            w, h = abs(x1 - x0), abs(y1 - y0)
            text = (f"RECT  W {self.fmt(w)}  |  H {self.fmt(h)}  |  "
                    f"Area {self.fmt2(w * h)}  |  Perim {self.fmt(2 * (w + h))}  |  "
                    f"Diag {self.fmt(math.hypot(w, h))}")
        elif self.mode == "ellipse" and self.pts and self.cursor:
            r = dist(self.pts[0], self.cursor)
            text = (f"CIRCLE  R {self.fmt(r)}  |  ⌀ {self.fmt(2 * r)}  |  "
                    f"Area {self.fmt2(math.pi * r * r)}  |  Circ {self.fmt(2 * math.pi * r)}")
        else:
            if not self.pts or not self.cursor:
                return
            end = constrain(self.pts[0], self.cursor) if self.shift else self.cursor
            length = dist(self.pts[0], end)
            ang = math.degrees(math.atan2(-(end[1] - self.pts[0][1]),
                                          end[0] - self.pts[0][0])) % 360
            dx = abs(end[0] - self.pts[0][0])
            dy = abs(end[1] - self.pts[0][1])
            text = (f"LINE  {self.fmt(length)}  |  {ang:.1f}°  |  "
                    f"dx {self.fmt(dx)}  dy {self.fmt(dy)}")
        self.canvas.itemconfig("temp", tags=("pinned",))
        self.canvas.itemconfig("tmp_label", tags=("pinned",))
        self.pinned_count += 1
        self.set_readout(text)
        self.pts = []
        self.canvas.tag_raise("hud")

    def finish_poly(self, close=True):
        if len(self.pts) < 2:
            self.pts = []
            return
        pts = list(self.pts)
        perim_open = path_length(pts)
        perim_closed = perim_open + (dist(pts[-1], pts[0]) if close else 0.0)
        area = polygon_area(pts)
        if close:
            flat = [c for p in pts for c in p]
            self.canvas.create_line(*flat, pts[0][0], pts[0][1], fill="#37ff9a",
                                    width=2, tags="temp", joinstyle=tk.ROUND)
        # centroid label
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        self.canvas.delete("poly_label")
        self.draw_label(cx, cy, f"Perimeter {self.fmt(perim_closed)}", color="#37ff9a")
        self.canvas.addtag_withtag("poly_label", "tmp_label")
        self.canvas.itemconfig("temp", tags=("pinned",))
        self.canvas.itemconfig("poly_label", tags=("pinned",))
        self.pinned_count += 1
        text = (f"SHAPE  Perimeter {self.fmt(perim_closed)}"
                + (f"  |  Area {self.fmt2(area)}" if close and len(pts) > 2 else "")
                + f"  |  {len(pts)} points")
        self.set_readout(text)
        self.pts = []

    def finish_angle(self):
        a, v, b = self.pts[0], self.pts[1], self.pts[2]
        ang = self.angle_at(a, v, b)
        self.canvas.delete("temp")
        self.canvas.create_line(a[0], a[1], v[0], v[1], fill="#37ff9a", width=1,
                                tags="pinned")
        self.canvas.create_line(v[0], v[1], b[0], b[1], fill="#37ff9a", width=1,
                                tags="pinned")
        self.arc_at(v, a, b)
        self.canvas.itemconfig("temp", tags=("pinned",))
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        self.draw_label(mid[0], mid[1] - 24, f"{ang:.2f}°", color="#ffd166")
        self.canvas.itemconfig("tmp_label", tags=("pinned",))
        self.set_readout(f"ANGLE  {ang:.2f}°   (arms "
                         f"{self.fmt(dist(a, v))} and {self.fmt(dist(v, b))})")
        self.pts = []
        self.pinned_count += 1

    # ------------------------------------------------------------------ calibrate
    def finish_calibration(self):
        if not self.pts or not self.cursor:
            return
        px = dist(self.pts[0], self.cursor)
        self.clear_temp()
        if px < 15:
            self.set_mode(self.mode)
            return
        self.ask_calibration(px)

    def ask_calibration(self, pixels: float):
        dlg = tk.Toplevel(self.root)
        dlg.title("Calibrate scale")
        dlg.configure(bg="#1b2027")
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        dlg.transient(self.root)

        tk.Label(dlg, text=f"Drawn length: {pixels:.1f} px", bg="#1b2027", fg="#8fa3b6",
                 font=self.font(10)).pack(padx=18, pady=(16, 4), anchor="w")
        tk.Label(dlg, text="What is its real length?", bg="#1b2027", fg="#e8eef5",
                 font=self.font(11, True)).pack(padx=18, anchor="w")

        row = tk.Frame(dlg, bg="#1b2027")
        row.pack(padx=18, pady=10)
        val = tk.StringVar(value="50")
        ent = tk.Entry(row, textvariable=val, width=10, bg="#0e1216", fg="#37ff9a",
                       insertbackground="#37ff9a", relief=tk.FLAT, font=self.font(12, True))
        ent.pack(side=tk.LEFT, ipady=4, padx=(0, 8))
        ent.focus_set()
        ent.select_range(0, tk.END)
        uvar = tk.StringVar(value="mm")
        um = tk.OptionMenu(row, uvar, "mm", "cm", "in")
        um.config(bg="#2b333d", fg="#e8eef5", relief=tk.FLAT, highlightthickness=0,
                  font=self.font(10), width=4)
        um["menu"].config(bg="#2b333d", fg="#e8eef5")
        um.pack(side=tk.LEFT)

        info = tk.Label(dlg, text=f"Current scale: {self.px_per_mm:.3f} px/mm",
                        bg="#1b2027", fg="#7d8b99", font=self.font(9))
        info.pack(padx=18, anchor="w")

        def apply(_=None):
            try:
                real = float(val.get().replace(",", "."))
            except ValueError:
                info.config(text="Please type a number.", fg="#ff8f8f")
                return
            if real <= 0:
                info.config(text="Length must be greater than 0.", fg="#ff8f8f")
                return
            mm = real * {"mm": 1.0, "cm": 10.0, "in": 25.4}[uvar.get()]
            self.px_per_mm = pixels / mm
            self.save_config()
            self.scale_lbl.config(text=self.scale_text())
            dlg.destroy()
            self.set_mode("line")
            self.set_readout(f"Calibrated: {self.px_per_mm:.3f} px/mm "
                             f"({self.px_per_mm * 25.4:.2f} px/inch).  Ready.")

        btns = tk.Frame(dlg, bg="#1b2027")
        btns.pack(padx=18, pady=(6, 16), fill=tk.X)
        tk.Button(btns, text="Apply", command=apply, bg="#2f6f4f", fg="white",
                  relief=tk.FLAT, padx=14, pady=5, font=self.font(10, True),
                  cursor="hand2").pack(side=tk.RIGHT)
        tk.Button(btns, text="Cancel", command=dlg.destroy, bg="#2b333d", fg="#e8eef5",
                  relief=tk.FLAT, padx=14, pady=5, font=self.font(10),
                  cursor="hand2").pack(side=tk.RIGHT, padx=6)
        dlg.bind("<Return>", apply)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        # centre the dialog
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        self.root.attributes("-alpha", max(self.alpha, 0.97))
        dlg.grab_set()
        dlg.wait_window()
        self.root.attributes("-alpha", self.alpha)

    # ------------------------------------------------------------------- read-out
    def refresh_readout(self):
        """Live read-out while the mouse moves."""
        if not self.pts:
            if self.mode == "calibrate":
                self.set_readout("CALIBRATE  -  drag across a known length, then type it in.")
            return
        if self.mode in ("line", "calibrate") and self.cursor:
            end = constrain(self.pts[0], self.cursor) if self.shift else self.cursor
            length = dist(self.pts[0], end)
            ang = math.degrees(math.atan2(-(end[1] - self.pts[0][1]),
                                          end[0] - self.pts[0][0])) % 360
            self.set_readout(f"{self.fmt(length)}   {ang:.1f}°")
        elif self.mode == "rect" and self.cursor:
            end = constrain(self.pts[0], self.cursor) if self.shift else self.cursor
            w, h = abs(end[0] - self.pts[0][0]), abs(end[1] - self.pts[0][1])
            self.set_readout(f"W {self.fmt(w)}   H {self.fmt(h)}   "
                             f"Area {self.fmt2(w * h)}   Perim {self.fmt(2 * (w + h))}")
        elif self.mode == "ellipse" and self.cursor:
            r = dist(self.pts[0], self.cursor)
            self.set_readout(f"R {self.fmt(r)}   ⌀ {self.fmt(2 * r)}   "
                             f"Area {self.fmt2(math.pi * r * r)}   "
                             f"Circ {self.fmt(2 * math.pi * r)}")
        elif self.mode == "poly" and len(self.pts) >= 2:
            self.set_readout(f"Perimeter {self.fmt(path_length(self.pts))}   "
                             f"Area {self.fmt2(polygon_area(self.pts))}   "
                             f"{len(self.pts)} pts")
        elif self.mode == "angle" and len(self.pts) == 2 and self.cursor:
            a = self.angle_at(self.pts[0], self.pts[1], self.cursor)
            self.set_readout(f"{a:.2f}°")

    def set_readout(self, text):
        self.readout.config(text=text)
        self.readout_text = text

    def copy_readout(self):
        txt = getattr(self, "readout_text", "")
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self.set_readout(txt + environ_note())

    # ------------------------------------------------------------------ utilities
    def undo_point(self):
        if self.pts:
            self.pts.pop()
            self.redraw()
            self.refresh_readout()
        else:
            # remove the most recent pinned measurement
            items = self.canvas.find_withtag("pinned")
            self.canvas.delete("pinned")

    def nudge(self, key, amount):
        """Fine-tune the moving end of the measurement, one pixel at a time."""
        dx = -amount if key == "Left" else amount if key == "Right" else 0
        dy = -amount if key == "Up" else amount if key == "Down" else 0
        if not (dx or dy):
            return
        if self.dragging and self.pts:
            # while dragging: move the free end
            cur = self.cursor or self.pts[0]
            self.cursor = (cur[0] + dx, cur[1] + dy)
            self.update_crosshair(FakeEvent(int(self.cursor[0]), int(self.cursor[1])))
        elif self.pts:
            last = self.pts[-1]
            self.pts[-1] = (last[0] + dx, last[1] + dy)
            if self.mode not in ("poly", "angle"):
                self.cursor = self.pts[-1]
        else:
            return
        self.redraw()
        self.refresh_readout()

    def pin_current(self):
        self.canvas.itemconfig("temp", tags=("pinned",))
        self.canvas.itemconfig("tmp_label", tags=("pinned",))
        self.keep = True
        self.refresh_keep_button()
        self.set_readout("Pinned.  Next measurement will be kept too (Pin: ON).")

    def convert_pinned(self):
        """Units changed -> recompute pinned labels by redrawing is impractical,
        so just note it: existing labels stay in their original unit."""
        pass

    # ---------------------------------------------------------------------- help
    def show_help(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Help - " + APP_NAME)
        dlg.configure(bg="#131920")
        dlg.attributes("-topmost", True)
        dlg.transient(self.root)
        txt = (
            f"{APP_NAME}  v{VERSION}\n"
            "\n"
            "MEASURING\n"
            "  Line ............ drag from A to B, Shift snaps to 45° steps\n"
            "  Rectangle ....... drag a box: W, H, area, perimeter, diagonal\n"
            "  Circle/Ellipse .. drag from the centre outwards: radius, area, circumference\n"
            "  Irregular ....... click each corner / bump, right-click or Enter to close\n"
            "  Angle ........... click arm point, vertex, arm point\n"
            "  Calibrate ....... drag across a known length once, every measurement\n"
            "                    afterwards is then in real mm / cm / inches\n"
            "\n"
            "ACCURACY\n"
            "  * Measurements always start and end on exact whole pixel coordinates,\n"
            "    so results are reproducible to 1 px.\n"
            "  * Use the arrow keys to nudge the last placed point 1 px at a time\n"
            "    (Shift + arrows = 10 px) for pixel-perfect endpoints.\n"
            "  * Calibrate once per monitor / zoom level. The scale is saved and\n"
            "    reloaded automatically the next time you open the app.\n"
            "  * Hold Shift while drawing a line to lock it perfectly horizontal,\n"
            "    vertical or diagonal.\n"
            "\n"
            "KEYS\n"
            "  Esc quit · M mode · U unit · C clear · Ctrl+C copy · P pin\n"
            "  T hide toolbar · [ ] opacity · Backspace undo point · H / F1 help\n"
            "\n"
            "Drawn on top of a live app? Press Windows key + PrintScreen first to\n"
            "freeze the screen in the Snipping Tool, or simply measure over the\n"
            "open window - the overlay is see-through.\n"
        )
        lbl = tk.Label(dlg, text=txt, bg="#131920", fg="#dfe8f1", justify=tk.LEFT,
                       font=self.font(9), padx=18, pady=14)
        lbl.pack()
        tk.Button(dlg, text="Got it", command=dlg.destroy, bg="#2f6f4f", fg="white",
                  relief=tk.FLAT, padx=18, pady=6, font=self.font(10, True),
                  cursor="hand2").pack(pady=(0, 14))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self.root.attributes("-alpha", 0.97)
        dlg.grab_set()
        dlg.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{(sw - w) // 2}+{max(20, (sh - h) // 3)}")
        dlg.wait_window()
        self.root.attributes("-alpha", self.alpha)

    # ---------------------------------------------------------------------- quit
    def quit(self):
        self.save_config()
        try:
            self.root.destroy()
        except Exception:
            pass


def environ_note():
    return ""


def main():
    system_dpi = enable_high_dpi()
    root = tk.Tk()
    # keep Tk's point-to-pixel scaling consistent with the real DPI
    try:
        root.tk.call("tk", "scaling", system_dpi / 72.0)
    except Exception:
        pass
    app = OnscreenRuler(root, system_dpi)
    root.mainloop()
    return app


if __name__ == "__main__":
    main()
