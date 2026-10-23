"""Run by test_ui_sizes on a private Xvfb display: the real mixer window with
fake audio, resized through a list of sizes the way a person drags its
corner. Logs one JSON line per size: the layout shown, the space the content
got, and the least space it needs (more needed than given = clipped). With
"shots", also saves a PNG per size."""
import json
import os
import subprocess
import sys

LOG, LIB, ROOT, TMP = sys.argv[1:5]
SIZES = json.loads(sys.argv[5])
SHOTS = len(sys.argv) > 6
sys.path[:0] = [LIB, ROOT]
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from audiomixer.live import AppRow  # noqa: E402
from audiomixer.ui import settings  # noqa: E402
from audiomixer.ui.controller import Controller  # noqa: E402
from audiomixer.ui.window import MixerWindow, save_png  # noqa: E402
from tests.test_ui import CHS, snapshot, status  # noqa: E402

settings.WINDOW_FILE = os.path.join(TMP, "window.json")
Adw.init()
snap = snapshot(Music_Audio=(25, False), Mic_In=(100, False))
# Something playing on every channel: the most the compact rows ever show.
snap.apps += [AppRow(("binary", b), b.title(), [300 + i], sink, True,
                     {"application.name": b.title(), "application.process.binary": b})
              for i, (b, sink) in enumerate((("discord", "Discord_Audio"), ("spotify", "Music_Audio")))]
controller = Controller(CHS, read_snapshot=lambda ch: snap, read_status=lambda ch: status(),
                        run=lambda argv: None, run_command=lambda argv: None,
                        load_hotkeys=dict, save_hotkeys=lambda k: None, apply_hotkeys=lambda k: None,
                        remove_hotkeys=lambda: None, hotkeys_suspended=lambda: False,
                        spawn=lambda argv, done=None: None)
win = MixerWindow(controller)
controller.refresh(status_too=True)
win.set_default_size(*SIZES[0])
win.present()
loop = GLib.MainLoop()


def steps():
    yield 1000
    xid = subprocess.run(["xdotool", "search", "--name", "^Audio Mixer$"],
                         capture_output=True, text=True).stdout.split()[0]
    for width, height in SIZES:
        subprocess.run(["xdotool", "windowsize", xid, str(width), str(height)], check=True)
        yield 350
        content = win.get_content()
        # The window's own room for it (the breakpoint bin it sits in): a
        # layout needing more is laid out bigger and cropped, never squeezed.
        room = content.get_parent()
        given = [room.get_width(), room.get_height()]
        need_w = content.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        need_h = content.measure(Gtk.Orientation.VERTICAL, given[0])[0]
        with open(LOG, "a") as f:
            f.write(json.dumps({"size": [width, height], "layout": win.layout, "room": type(room).__name__,
                                "given": given, "needs": [need_w, need_h]}) + "\n")
        if SHOTS:
            save_png(win, os.path.join(TMP, f"shot-{width}x{height}.png"))
    loop.quit()


def advance(it):
    """Run steps() one yield at a time: each yield is a wait in ms."""
    for delay in it:
        GLib.timeout_add(delay, advance, it)
        break
    return False


advance(steps())


GLib.timeout_add_seconds(60, loop.quit)
loop.run()
