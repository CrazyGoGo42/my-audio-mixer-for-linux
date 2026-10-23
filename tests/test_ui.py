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
        self.moves = []
        self.controller = Controller(CHS, read_snapshot=lambda ch: self.snap,
                                     read_status=lambda ch: self.status,
                                     run=self.calls.append, run_command=self.commands.append,
                                     remember=lambda props, sink: self.moves.append(("remember", props["application.process.binary"], sink)),
                                     route_now=lambda idx, sink: self.moves.append(("route", list(idx), sink)))
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


class RoutingControlsTest(UiTestBase):
    def refresh_with(self, **kw):
        self.status = status(**kw)
        self.controller.refresh(status_too=True)

    def test_fx_off_shows_slot_toggles(self):
        self.refresh_with(fx={"music": False}, outputs={"music": ["A1", "A2"]})
        music = self.strip("Music_Audio")
        self.assertEqual(music.where.get_visible_child_name(), "slots")
        self.assertEqual([t.get_active() for t in music.slot_toggles], [True, True, False, False])
        self.assertFalse(music.fx.get_active())

    def test_fx_on_shows_ee_label(self):
        music = self.strip("Music_Audio")
        self.assertTrue(music.fx.get_active())
        self.assertEqual(music.where.get_visible_child_name(), "fx")

    def test_refresh_never_echoes_commands(self):
        self.refresh_with(fx={"music": False}, outputs={"music": ["A2"]})
        self.assertEqual(self.commands, [])

    def test_clicking_fx_and_slots_runs_commands(self):
        music = self.strip("Music_Audio")
        music.fx.set_active(False)
        self.refresh_with(fx={"music": False})
        music.slot_toggles[2].set_active(True)
        self.assertEqual(self.commands, [["fx", "music", "off"], ["out", "music", "A3", "on"]])

    def test_ee_strip_toggles_its_outputs_and_shows_preset(self):
        ee = self.strip("EE_Return")
        self.assertEqual([t.get_active() for t in ee.slot_toggles], [True, False, False, False])
        self.assertIn("Bass Enhancing", ee.preset.get_label())
        ee.slot_toggles[1].set_active(True)
        self.assertEqual(self.commands, [["out", "fx", "A2", "on"]])

    def test_eq_change_runs_eq_command(self):
        music = self.strip("Music_Audio")
        music.bass.set_value(6)
        music.flush_eq()
        self.assertEqual(self.commands, [["eq", "music", "bass", "6.0"]])

    def test_slot_menu_lists_default_devices_and_none(self):
        a2 = self.win.slot_buttons["A2"]
        self.assertTrue(a2.get_label().startswith("A2"))
        self.assertEqual([text for text, _ in a2.items], ["Default output", "Speakers", "HDMI", "Off"])
        dict(a2.items)["HDMI"]()
        self.assertEqual(self.commands, [["slot", "A2", HDMI]])

    def test_mic_menu_lists_auto_and_real_mics(self):
        mic = self.strip("Mic_In")
        self.assertEqual([text for text, _ in mic.menu.items], ["Automatic", "Blue mic"])
        dict(mic.menu.items)["Automatic"]()
        self.assertEqual(self.commands, [["mic", "auto"]])


class PlayingNowTest(UiTestBase):
    def row(self, name):
        return next(r for r in self.win.apps.rows if r.app.name == name)

    def test_rows_follow_snapshot(self):
        self.assertEqual([r.app.name for r in self.win.apps.rows], ["Audacity", "Zen"])
        self.snap.apps = [a for a in self.snap.apps if a.name == "Zen"]
        self.controller.refresh()
        self.assertEqual([r.app.name for r in self.win.apps.rows], ["Zen"])

    def test_empty_list_says_so(self):
        self.snap.apps = []
        self.controller.refresh()
        self.assertEqual(self.win.apps.rows, [])
        self.assertTrue(self.win.apps.empty.get_visible())

    def test_new_app_has_marker(self):
        self.assertTrue(self.row("Audacity").new.get_visible())
        self.assertFalse(self.row("Zen").new.get_visible())

    def test_current_channel_is_active(self):
        self.assertEqual([t.get_active() for t in self.row("Zen").channel_toggles], [False, False, False, True])

    def test_clicking_a_channel_remembers_then_moves_every_stream(self):
        self.row("Zen").channel_toggles[2].set_active(True)   # Music
        self.assertEqual(self.moves, [("remember", "zen", "Music_Audio"),
                                      ("route", [119, 141], "Music_Audio")])

    def test_move_of_vanished_stream_still_saves_route(self):
        def gone(indexes, sink):
            raise OSError("stream vanished")
        self.controller._route_now = gone
        self.row("Audacity").channel_toggles[1].set_active(True)  # no exception escapes
        self.assertEqual(self.moves, [("remember", "audacity", "Discord_Audio")])

    def test_refresh_never_moves_apps(self):
        self.controller.refresh(status_too=True)
        self.assertEqual(self.moves, [])


def Gtk_HORIZONTAL():
    from gi.repository import Gtk
    return Gtk.Orientation.HORIZONTAL


class CompactTest(UiTestBase):
    def compact_row(self, name):
        return next(r for r in self.win.compact.strips if r.name == name)

    def test_compact_has_a_row_per_strip_with_its_apps(self):
        self.assertEqual([r.name for r in self.win.compact.strips], [n for n, _ in strip_targets(CHS)])
        self.assertEqual(self.win.compact.app_labels["Browser_Audio"].get_label(), "Zen")
        self.assertEqual(self.win.compact.app_labels["Default_Audio"].get_label(), "Audacity")
        self.assertFalse(self.win.compact.app_labels["Music_Audio"].get_visible())

    def test_compact_rows_show_their_titles(self):
        row = self.compact_row("Music_Audio")
        self.assertIs(row.heading.get_parent(), row)
        self.assertEqual(row.heading.get_label(), "Music")

    def test_wide_layout_can_shrink_below_its_natural_width(self):
        # Wider content than the window must scroll, not overflow (libadwaita
        # warns and clips otherwise) until the compact breakpoint takes over.
        minimum, natural, _, _ = self.win.wide_scroll.measure(Gtk_HORIZONTAL(), -1)
        self.assertLess(minimum, 720)

    def test_compact_and_wide_show_same_volume(self):
        self.snap = snapshot(Music_Audio=(30, True))
        self.controller.refresh()
        wide, compact = self.strip("Music_Audio"), self.compact_row("Music_Audio")
        self.assertEqual((wide.scale.get_value(), wide.mute.get_active()),
                         (compact.scale.get_value(), compact.mute.get_active()))
        self.assertEqual(compact.scale.get_value(), 30)

    def test_compact_slider_writes_like_the_wide_one(self):
        row = self.compact_row("Music_Audio")
        row.scale.set_value(42)
        row.flush()
        self.assertEqual(self.calls[0], ["pactl", "set-sink-volume", "Music_Audio", "42%"])

    def test_window_has_wide_and_compact_pages(self):
        self.assertEqual(self.win.stack.get_visible_child_name(), "wide")
        self.assertIsNotNone(self.win.stack.get_child_by_name("compact"))


class MeterLifecycleTest(UiTestBase):
    def setUp(self):
        super().setUp()
        from audiomixer.ui.levels import Meters

        test = self
        self.readers = []

        class FakeReader:
            def __init__(self, args, on_level):
                self.args, self.on_level, self.stopped = args, on_level, False
                test.readers.append(self)

            def start(self):
                pass

            def stop(self):
                self.stopped = True
        self.meters = Meters(self.win, reader=FakeReader)

    def running(self):
        return sorted(r.args[0] for r in self.readers if not r.stopped)

    def test_one_meter_per_strip_and_app_while_shown(self):
        self.meters.start()
        self.assertEqual(self.running(), sorted([
            "--device=Mic_In", "--device=Default_Audio.monitor", "--device=Discord_Audio.monitor",
            "--device=Music_Audio.monitor", "--device=Browser_Audio.monitor", "--device=EE_Return.monitor",
            "--device=All_Audio", "--monitor-stream=119", "--monitor-stream=141", "--monitor-stream=200"]))

    def test_meters_stop_when_hidden(self):
        self.meters.start()
        self.meters.stop()
        self.assertEqual(self.running(), [])

    def test_app_meters_follow_the_app_list(self):
        self.meters.start()
        self.snap.apps = [a for a in self.snap.apps if a.name == "Zen"]
        self.controller.refresh()
        self.assertNotIn("--monitor-stream=200", self.running())
        self.assertIn("--monitor-stream=119", self.running())

    def test_app_row_shows_its_loudest_stream(self):
        # Zen has several streams and only one may be playing (seen live: the
        # row metered an idle stream and stayed empty).
        self.meters.start()
        by_args = {r.args[0]: r for r in self.readers}
        by_args["--monitor-stream=119"].on_level(0.0)
        by_args["--monitor-stream=141"].on_level(0.5)
        self.meters._frame()
        zen = next(r for r in self.win.apps.rows if r.app.name == "Zen")
        self.assertGreater(zen.meter.get_value(), 0.8)

    def test_meters_use_a_decibel_scale(self):
        from audiomixer.ui.levels import meter_fraction
        self.assertEqual(meter_fraction(1.0), 1.0)
        self.assertEqual(meter_fraction(0.0), 0.0)
        self.assertEqual(meter_fraction(0.0005), 0.0)               # below -60 dB
        self.assertAlmostEqual(meter_fraction(10 ** (-30 / 20)), 0.5)  # -30 dB = half
        # Seen live: -51 dBFS through a 27% channel must still show something.
        self.assertGreater(meter_fraction(93 / 32768), 0.1)

    def test_meter_level_is_post_fader_and_zero_when_muted(self):
        from audiomixer.ui.levels import strip_level
        self.assertEqual(strip_level(1.0, StripLive("Music_Audio", "sink", True, 50, False)), 0.125)
        self.assertEqual(strip_level(1.0, StripLive("Music_Audio", "sink", True, 50, True)), 0.0)
        self.assertEqual(strip_level(0.5, StripLive("Mic_In", "source", True, 80, False)), 0.5)
        self.assertEqual(strip_level(0.5, None), 0.0)


class SizeTest(unittest.TestCase):
    def test_size_round_trips(self):
        import tempfile
        from audiomixer.ui.settings import load_size, save_size
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "window.json")
            self.assertIsNone(load_size(path))
            save_size(900, 500, path)
            self.assertEqual(load_size(path), (900, 500))
            with open(path, "w") as f:
                f.write("garbage")
            self.assertIsNone(load_size(path))


if __name__ == "__main__":
    unittest.main()
