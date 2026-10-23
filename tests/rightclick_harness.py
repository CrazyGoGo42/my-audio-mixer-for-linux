"""Run by test_ui_pointer on a private Xvfb display: one real StripWidget with
a fake controller; logs where to click and every volume write / popover."""
import sys

sys.path.insert(0, sys.argv[2])
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from audiomixer.config import Channel  # noqa: E402
from audiomixer.ui import strip as strip_mod  # noqa: E402

LOG = sys.argv[1]


def log(*a):
    with open(LOG, "a") as f:
        f.write(" ".join(str(x) for x in a) + "\n")


class FakeController:
    channels = [Channel("music", "Music_Audio", "Music", ("KP_3", "KP_6", "KP_9"))]

    def set_volume(self, name, kind, value, unmute=True):
        log("SET_VOLUME", value)

    def set_mute(self, *a):
        log("SET_MUTE")

    def hotkey_map(self):
        return {}

    def suspend_hotkeys(self):
        pass

    def resume_hotkeys(self):
        pass


class Live:
    present, volume, muted = True, 50, False


opened = strip_mod.StripWidget.hotkey_popover
strip_mod.StripWidget.hotkey_popover = lambda self, control: (log("POPOVER", control), opened(self, control))[1]


loop = GLib.MainLoop()
win = Gtk.Window()
win.set_default_size(300, 400)
s = strip_mod.StripWidget(FakeController(), "Music_Audio", "sink", "Music")
s.update(Live())
win.set_child(s)
win.present()


def report():
    tx, ty = s.scale.get_native().get_surface_transform()
    _ok, b = s.scale.compute_bounds(win)
    log("CLICK", int(tx + b.origin.x + b.size.width / 2), int(ty + b.origin.y + b.size.height * 0.2))
    return False


GLib.timeout_add(800, report)
GLib.timeout_add(int(float(sys.argv[3]) * 1000), loop.quit)
loop.run()
