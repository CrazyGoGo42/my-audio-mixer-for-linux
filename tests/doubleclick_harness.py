"""Run by test_ui_pointer on a private Xvfb display: a Color Panel and a knob,
both turned away from flat; logs where to double-click and their values after."""
import sys

sys.path.insert(0, sys.argv[2])
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from audiomixer.ui.colorpanel import ColorPanel  # noqa: E402
from audiomixer.ui.knob import Knob  # noqa: E402

LOG = sys.argv[1]


def log(*a):
    with open(LOG, "a") as f:
        f.write(" ".join(str(x) for x in a) + "\n")


loop = GLib.MainLoop()
win = Gtk.Window()
win.set_default_size(300, 300)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
panel = ColorPanel()
panel.set_size_request(200, 120)
panel.set_value(0.6, 0.9)
knob = Knob(-12, 12, 0.5)
knob.set_size_request(60, 60)
knob.set_value(6)
box.append(panel)
box.append(knob)
win.set_child(box)
win.present()


def report():
    tx, ty = win.get_surface_transform()
    for name, widget, fx, fy in (("PANEL", panel, 0.52, 0.9), ("KNOB", knob, 0.5, 0.5)):
        _ok, b = widget.compute_bounds(win)
        log(name, int(tx + b.origin.x + b.size.width * fx), int(ty + b.origin.y + b.size.height * fy))
    return False


def values():
    log("VALUES", panel.get_value()[0], panel.get_value()[1], knob.get_value())
    loop.quit()
    return False


GLib.timeout_add(800, report)
GLib.timeout_add(int(float(sys.argv[3]) * 1000), values)
loop.run()
