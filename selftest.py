"""Headless smoke test for onscreen_ruler.py (runs on Linux/Xvfb).

Simulates mouse drags / clicks for every mode and checks the read-out text.
Run:  xvfb-run -a python3 selftest.py
"""
import math
import sys
import tkinter as tk

sys.path.insert(0, ".")
from onscreen_ruler import OnscreenRuler, FakeEvent, dist, path_length  # noqa


def make():
    root = tk.Tk()
    root.geometry("1200x800+0+0")
    app = OnscreenRuler(root)
    app.px_per_mm = 96.0 / 25.4   # force a known scale
    app.set_unit("px")
    root.update()
    return root, app


def drag(app, a, b, shift=False):
    app.shift = shift
    app.on_press(FakeEvent(*a))
    app.on_drag(FakeEvent(*b))
    app.on_release(FakeEvent(*b))
    app.shift = False


def ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        raise SystemExit(1)


def main():
    root, app = make()
    print("window:", root.winfo_width(), "x", root.winfo_height())

    # ---- line -------------------------------------------------------------
    app.set_mode("line")
    drag(app, (100, 300), (400, 700))
    ok("LINE" in app.readout_text, "line mode produces a read-out: " + app.readout_text)
    ok("500" in app.readout_text, "3-4-5 triangle -> 500 px")
    ok(app.pinned_count == 1, "one pinned measurement")

    # ---- shift constraint -------------------------------------------------
    app.set_mode("line")
    drag(app, (200, 400), (430, 460), shift=True)
    ok("LINE" in app.readout_text, "shift-constrained line: " + app.readout_text)
    ok("0.0°" in app.readout_text, "shift snapped to horizontal")

    # ---- rect -------------------------------------------------------------
    app.set_mode("rect")
    drag(app, (100, 300), (300, 450))
    ok("RECT" in app.readout_text, "rect read-out: " + app.readout_text)
    ok("W 200 px" in app.readout_text and "H 150 px" in app.readout_text, "rect W/H")
    ok("30,000" in app.readout_text, "rect area 200x150 = 30000")
    ok("700 px" in app.readout_text, "rect perimeter 700")

    # ---- ellipse ----------------------------------------------------------
    app.set_mode("ellipse")
    drag(app, (600, 500), (700, 500))
    ok("CIRCLE" in app.readout_text, "circle read-out: " + app.readout_text)
    ok("R 100 px" in app.readout_text, "radius 100 px")
    ok("31,416" in app.readout_text, "area of r=100 circle")

    # ---- poly -------------------------------------------------------------
    app.set_mode("poly")
    for p in [(100, 600), (300, 600), (300, 700), (100, 700)]:
        app.on_press(FakeEvent(*p))
    app.on_right(FakeEvent(100, 700))
    ok("SHAPE" in app.readout_text, "poly read-out: " + app.readout_text)
    ok("600 px" in app.readout_text, "200x100 box perimeter 600")
    ok("20,000 px²" in app.readout_text, "box area 20000")

    # ---- angle ------------------------------------------------------------
    app.set_mode("angle")
    for p in [(500, 700), (500, 600), (600, 600)]:
        app.on_press(FakeEvent(*p))
    ok("ANGLE" in app.readout_text, "angle read-out: " + app.readout_text)
    ok("90.00" in app.readout_text, "right angle detected")

    # ---- calibration + units ---------------------------------------------
    app.set_mode("calibrate")
    app.on_press(FakeEvent(100, 100))
    app.on_drag(FakeEvent(100, 100 + int(round(96.0 / 25.4 * 50))))
    app.on_release(FakeEvent(100, 100 + int(round(96.0 / 25.4 * 50))))
    # ask_calibration opens a modal dialog, so patch it out:
    ok(app.mode == "calibrate", "calibration waiting for a dialog")

    app.px_per_mm = 96.0 / 25.4
    app.set_unit("mm")
    app.set_mode("line")
    drag(app, (0, 300), (int(round(96.0 / 25.4 * 100)), 300))
    ok("mm" in app.readout_text, "mm read-out: " + app.readout_text)
    ok("100" in app.readout_text, "96 dpi -> 100 mm")

    app.set_unit("cm")
    drag(app, (0, 300), (int(round(96.0 / 25.4 * 100)), 300))
    ok("10.0" in app.readout_text or "10.00" in app.readout_text,
       "cm read-out: " + app.readout_text)

    app.set_unit("in")
    drag(app, (0, 300), (96, 300))
    ok("1.000" in app.readout_text, "inch read-out: " + app.readout_text)

    # ---- nudge ------------------------------------------------------------
    app.set_unit("px")
    app.set_mode("line")
    app.on_press(FakeEvent(10, 400))
    app.on_drag(FakeEvent(20, 400))
    app.nudge("Right", 5)
    ok(app.cursor[0] == 25, "arrow nudge moved endpoint to x=25")
    app.on_release(FakeEvent(25, 400))
    ok("15 px" in app.readout_text, "nudged line measures 15 px: " + app.readout_text)

    # ---- keys -------------------------------------------------------------
    app.clear_all()
    ok(app.readout_text.startswith("Cleared"), "clear works")
    app.set_mode("poly")
    app.on_press(FakeEvent(0, 400))
    app.on_press(FakeEvent(10, 400))
    app.undo_point()
    ok(len(app.pts) == 1, "undo removes last vertex")

    # ---- toolbar hit test --------------------------------------------------
    app.canvas.update()
    ok(app.in_toolbar(30, 30), "toolbar hit test finds the toolbar")
    ok(not app.in_toolbar(600, 700), "toolbar hit test ignores empty space")

    root.destroy()
    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
