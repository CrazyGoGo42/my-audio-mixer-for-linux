"""Widget tests for the mixer window. They build real GTK widgets (no main loop),
with the controller's reads and writes replaced by in-memory fakes."""

import os
import unittest

from audiomixer.config import Channel
from audiomixer.live import AppRow, Snapshot, StripLive, strip_targets

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

CHS = [Channel("default", "Default_Audio", "Desktop", ("-", "-", "-")),
       Channel("discord", "Discord_Audio", "Discord", ("-", "-", "-")),
       Channel("music", "Music_Audio", "Music", ("-", "-", "-")),
       Channel("browser", "Browser_Audio", "Browser", ("-", "-", "-"))]
SPEAKERS = "alsa_output.speakers"
HDMI = "alsa_output.hdmi"


def snapshot(**volumes):
    strips = {}
    for name, kind in strip_targets(CHS):
        vol, muted = volumes.get(name, (50, False))
        strips[name] = StripLive(name, kind, vol is not None, vol or 0, muted)
    zen = AppRow(("binary", "zen"), "Zen", [119, 141], "Browser_Audio", True,
                 {"application.name": "Zen", "application.process.binary": "zen"})
    new = AppRow(("binary", "audacity"), "Audacity", [200], "Default_Audio", False,
                 {"application.name": "Audacity", "application.process.binary": "audacity"})
    return Snapshot(strips, [new, zen])


def status(fx=None, outputs=None):
    fx = fx or {}
    outputs = outputs or {}
    return {
        "slots": {"A1": {"value": "@default", "device": SPEAKERS, "description": "Speakers"},
                  "A2": {"value": HDMI, "device": None, "description": None},
                  "A3": {"value": None, "device": None, "description": None},
                  "A4": {"value": None, "device": None, "description": None}},
        "channels": [{"key": c.key, "label": c.label, "sink": c.sink, "fx": fx.get(c.key, True),
                      "outputs": outputs.get(c.key, ["A1"]), "bass": 0.0, "treble": 0.0} for c in CHS],
        "fx_outputs": ["A1"],
        "mic": {"value": "@auto", "device": "alsa_input.usb-blue"},
        "devices": [{"kind": "output", "name": SPEAKERS, "description": "Speakers"},
                    {"kind": "output", "name": HDMI, "description": "HDMI"},
                    {"kind": "mic", "name": "alsa_input.usb-blue", "description": "Blue mic"}],
        "ee_preset": "Bass Enhancing",
    }


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class UiTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw
        Adw.init()

    def setUp(self):
        from audiomixer.ui.controller import Controller
        from audiomixer.ui.window import MixerWindow
        self.snap = snapshot(Music_Audio=(25, False))
        self.status = status()
        self.calls, self.commands = [], []
        self.controller = Controller(CHS, read_snapshot=lambda ch: self.snap,
                                     read_status=lambda ch: self.status,
                                     run=self.calls.append, run_command=self.commands.append)
        self.win = MixerWindow(self.controller)
        self.controller.refresh(status_too=True)

    def tearDown(self):
        self.win.destroy()

    def strip(self, name):
        return next(s for s in self.win.strips if s.name == name)


class StripTest(UiTestBase):
    def test_window_builds_one_strip_per_target(self):
        self.assertEqual([s.name for s in self.win.strips], [n for n, _ in strip_targets(CHS)])
        self.assertEqual([s.title for s in self.win.strips],
                         ["Mic", "Desktop", "Discord", "Music", "Browser", "EasyEffects", "All Audio"])

    def test_strip_follows_snapshot_without_writing_back(self):
        music = self.strip("Music_Audio")
        self.assertEqual((music.scale.get_value(), music.percent.get_label()), (25, "25%"))
        self.snap = snapshot(Music_Audio=(30, True))
        self.controller.refresh()
        self.assertEqual((music.scale.get_value(), music.mute.get_active()), (30, True))
        self.assertEqual(self.calls, [])

    def test_user_slider_writes_volume_and_unmutes(self):
        music = self.strip("Music_Audio")
        music.scale.set_value(40)
        music.flush()
        self.assertEqual(self.calls, [["pactl", "set-sink-volume", "Music_Audio", "40%"],
                                      ["pactl", "set-sink-mute", "Music_Audio", "0"]])

    def test_refresh_does_not_touch_a_slider_being_dragged(self):
        music = self.strip("Music_Audio")
        music.scale.set_value(40)          # the user's hand is on it
        self.controller.refresh()          # an event echo still says 25
        self.assertEqual(music.scale.get_value(), 40)
        music.touched_at = 0               # hands off for a while
        self.controller.refresh()
        self.assertEqual(music.scale.get_value(), 25)

    def test_mute_button_toggles_through_pactl(self):
        self.strip("Mic_In").mute.set_active(True)
        self.assertEqual(self.calls, [["pactl", "set-source-mute", "Mic_In", "toggle"]])

    def test_strip_shows_dash_when_absent(self):
        self.snap = snapshot(Browser_Audio=(None, False))
        self.controller.refresh()
        browser = self.strip("Browser_Audio")
        self.assertEqual(browser.percent.get_label(), "—")
        self.assertFalse(browser.scale.get_sensitive())


if __name__ == "__main__":
    unittest.main()
