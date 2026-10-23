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
                      "outputs": outputs.get(c.key, ["A1"]), "bass": 0.0, "mid": 0.0, "treble": 0.0} for c in CHS],
        "fx_outputs": ["A1"],
        "mic": {"value": "@auto", "device": "alsa_input.usb-blue"},
        "devices": [{"kind": "output", "name": SPEAKERS, "description": "Speakers"},
                    {"kind": "output", "name": HDMI, "description": "HDMI"},
                    {"kind": "mic", "name": "alsa_input.usb-blue", "description": "Blue mic"}],
        "ee_preset": "Bass Enhancing",
        "mic_fx": {"color_x": 0.0, "color_y": 0.0, "comp": 0.0, "gate": 0.0},
        "mic_fx_node": 77,
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
        import tempfile
        from audiomixer.ui import settings
        from audiomixer.ui.controller import Controller
        from audiomixer.ui.window import MixerWindow
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_file = settings.WINDOW_FILE
        settings.WINDOW_FILE = os.path.join(tmp.name, "window.json")
        self.addCleanup(setattr, settings, "WINDOW_FILE", old_file)
        self.spawned = []
        self.snap = snapshot(Music_Audio=(25, False))
        self.status = status()
        self.calls, self.commands = [], []
        self.moves = []
        self.keys = {"music:mute": "<Ctrl>KP_3", "music:down": "<Ctrl>KP_6", "music:up": "<Ctrl>KP_9"}
        self.hk_log = []
        self.hk_suspended = False

        def suspend_keys():
            self.hk_log.append(("suspend",))
            self.hk_suspended = True

        def apply_keys(keys):
            self.hk_log.append(("apply", dict(keys)))
            self.hk_suspended = False

        def save_keys(keys):
            self.hk_log.append(("save", dict(keys)))
            self.keys = dict(keys)
        self.controller = Controller(CHS, read_snapshot=lambda ch: self.snap,
                                     load_hotkeys=lambda: dict(self.keys), save_hotkeys=save_keys,
                                     apply_hotkeys=apply_keys, remove_hotkeys=suspend_keys,
                                     hotkeys_suspended=lambda: self.hk_suspended,
                                     read_status=lambda ch: self.status,
                                     run=self.calls.append, run_command=self.commands.append,
                                     remember=lambda props, sink: self.moves.append(("remember", props["application.process.binary"], sink)),
                                     route_now=lambda idx, sink: self.moves.append(("route", list(idx), sink)),
                                     spawn=lambda argv, done=None: self.spawned.append((argv, done)))
        self.win = MixerWindow(self.controller)
        self.controller.refresh(status_too=True)

    def tearDown(self):
        from gi.repository import Adw
        self.win.destroy()
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)

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

    def test_mute_button_sends_absolute_state(self):
        # Absolute, not "toggle": a click can't undo a hotkey mute that landed
        # just before the window refreshed.
        self.strip("Mic_In").mute.set_active(True)
        self.assertEqual(self.calls, [["pactl", "set-source-mute", "Mic_In", "1"]])

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

    def test_compact_has_a_row_per_strip(self):
        # Its apps are listed under the rows: tests/test_compact_apps.py.
        self.assertEqual([r.name for r in self.win.compact.strips], [n for n, _ in strip_targets(CHS)])

    def test_compact_rows_show_their_titles(self):
        row = self.compact_row("Music_Audio")
        self.assertIs(row.heading.get_parent(), row)
        self.assertEqual(row.heading.get_label(), "Music")


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

            def is_alive(self):
                return not self.stopped
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

    def test_compact_app_rows_show_levels_while_compact(self):
        self.win.set_layout("compact")
        self.meters.start()
        by_args = {r.args[0]: r for r in self.readers}
        by_args["--monitor-stream=141"].on_level(0.5)
        self.meters._frame()
        zen = next(r for r in self.win.compact.apps.rows if r.app.name == "Zen")
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


class EventFilterTest(unittest.TestCase):
    """Seen live: the window's own pactl calls are pulse *clients*; reacting to
    client events re-ran pactl ~23 times a second forever (54% CPU)."""

    def test_what_each_event_refreshes(self):
        from audiomixer.ui.controller import event_needs
        cases = {
            "Event 'new' on client #8812": None,
            "Event 'remove' on client #8812": None,
            "Event 'new' on source-output #9001": None,      # our own meters
            "Event 'remove' on source-output #9001": None,
            "Event 'change' on module #12": None,
            "Event 'change' on sink #53": "snapshot",         # volume / mute
            "Event 'change' on source #59": "snapshot",
            "Event 'new' on sink-input #10030": "snapshot",   # an app started
            "Event 'remove' on sink-input #10030": "snapshot",
            "Event 'change' on sink-input #10030": "snapshot",
            "Event 'new' on sink #400": "status",             # a device appeared
            "Event 'remove' on source #401": "status",
            "Event 'change' on server #-1": "status",          # default output changed
            "Event 'change' on card #66": "status",            # profile / plug
        }
        for line, want in cases.items():
            self.assertEqual(event_needs(line), want, line)


class ReviewFixesTest(UiTestBase):
    def setUp(self):
        super().setUp()
        self.saved_states = []

    def row(self, name):
        return next(r for r in self.win.apps.rows if r.app.name == name)

    def test_confirming_a_new_app_on_its_current_channel_remembers_it(self):
        # Review: a NEW game on Desktop could never be confirmed (clicking the
        # already-active button was a no-op), so it stayed NEW forever.
        audacity = self.row("Audacity")             # NEW, playing on Desktop
        audacity.channel_toggles[0].set_active(False)  # the user clicks "Desktop"
        self.assertEqual(self.moves, [("remember", "audacity", "Default_Audio")])
        self.assertTrue(audacity.channel_toggles[0].get_active())

    def test_wheel_over_a_fader_scrolls_instead_of_changing_volume(self):
        music = self.strip("Music_Audio")
        self.assertTrue(music.on_scroll(None, 0, 1))   # consumed, not passed to the fader
        self.assertEqual(music.scale.get_value(), 25)
        self.assertEqual(self.calls, [])

    def test_changing_the_mic_level_never_unmutes_it(self):
        mic = self.strip("Mic_In")
        mic.scale.set_value(60)
        mic.flush()
        self.assertEqual(self.calls, [["pactl", "set-source-volume", "Mic_In", "60%"]])

    def test_unplugged_slot_says_so_first(self):
        self.assertTrue(self.win.slot_buttons["A2"].get_label().startswith("A2 · not connected"))

    def test_eq_drag_touches_only_that_channel(self):
        # Lightweight: no full command (pw-dump, rewiring, all channels) per drag step.
        self.snap.strips["Music_Audio"].node_id = 50
        def fake_update(change):
            state = change(self.state_for_eq())
            self.saved_states.append(state)
            return state
        self.controller._update_state = fake_update
        music = self.strip("Music_Audio")
        music.bass.set_value(6)
        music.flush_eq()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.calls, [["pw-cli", "set-param", "50", "Props",
                                       '{ params = [ "bass:Gain" 6.0 "mid:Gain" 0.0 "treble:Gain" 0.0 ] }']])
        self.assertEqual(self.saved_states[0].channels["music"].bass, 6.0)

    def state_for_eq(self):
        from audiomixer.config import ChannelState, MixerState
        return MixerState({"A1": "@default", "A2": None, "A3": None, "A4": None},
                          {c.key: ChannelState() for c in CHS}, ["A1"], "@auto")

    def test_size_is_saved_when_resized_not_only_on_close(self):
        import tempfile
        from audiomixer.ui import settings
        with tempfile.TemporaryDirectory() as tmp:
            old = settings.WINDOW_FILE
            settings.WINDOW_FILE = os.path.join(tmp, "window.json")
            try:
                self.win.set_default_size(800, 600)
                self.win.save_size_now()
                self.assertEqual(settings.load_size(), (800, 600))
            finally:
                settings.WINDOW_FILE = old


class MeterRecoveryTest(UiTestBase):
    def setUp(self):
        super().setUp()
        from audiomixer.ui.levels import Meters
        test = self
        self.readers = []

        class FakeReader:
            def __init__(self, args, on_level):
                self.args, self.on_level, self.stopped, self.alive = args, on_level, False, True
                test.readers.append(self)

            def start(self):
                pass

            def stop(self):
                self.stopped = True

            def is_alive(self):
                return self.alive and not self.stopped
        self.meters = Meters(self.win, reader=FakeReader)

    def running(self, arg):
        return [r for r in self.readers if r.args[0] == arg and r.is_alive()]

    def test_dead_meters_restart_after_pipewire_comes_back(self):
        self.meters.start()
        old = self.running("--device=Music_Audio.monitor")[0]
        old.alive = False                      # parec exited: pulse restarted
        self.controller.refresh()              # the reconnect refresh
        self.assertEqual(len(self.running("--device=Music_Audio.monitor")), 1)
        self.assertIsNot(self.running("--device=Music_Audio.monitor")[0], old)

    def test_no_meter_for_a_missing_strip(self):
        self.snap = snapshot(Browser_Audio=(None, False))
        self.controller.refresh()
        self.meters.start()
        self.assertEqual(self.running("--device=Browser_Audio.monitor"), [])


class HotkeyEditorTest(UiTestBase):
    def popover(self, strip_name, control):
        pop = self.strip(strip_name).hotkey_popover(control)
        self.addCleanup(pop.unparent)
        return pop

    def test_right_click_targets(self):
        self.assertEqual(self.strip("Music_Audio").hotkey_actions("mute"), ["music:mute"])
        self.assertEqual(self.strip("Music_Audio").hotkey_actions("fader"), ["music:down", "music:up"])
        self.assertEqual(self.strip("Music_Audio").hotkey_actions("A2"), ["music:A2"])
        self.assertEqual(self.strip("EE_Return").hotkey_actions("A1"), ["fx:A1"])
        self.assertEqual(self.strip("Mic_In").hotkey_actions("mute"), ["mic:mute"])
        self.assertEqual(self.strip("All_Audio").hotkey_actions("fader"), ["all:down", "all:up"])

    def test_popover_lists_current_keys(self):
        pop = self.popover("Music_Audio", "fader")
        self.assertEqual([r.action for r in pop.rows], ["music:down", "music:up"])
        self.assertIn("6", pop.rows[0].keys_label.get_label())
        self.assertEqual(self.popover("Mic_In", "mute").rows[0].keys_label.get_label(), "—")

    def test_capture_suspends_and_escape_restores(self):
        from gi.repository import Gdk
        pop = self.popover("Music_Audio", "mute")
        pop.start_capture("music:mute")
        self.assertEqual(self.hk_log, [("suspend",)])
        self.assertTrue(pop.handle_key(Gdk.KEY_Escape, 0))
        self.assertIsNone(pop.capturing)
        self.assertEqual(self.hk_log[-1], ("apply", {"music:mute": "<Ctrl>KP_3", "music:down": "<Ctrl>KP_6",
                                                     "music:up": "<Ctrl>KP_9"}))

    def test_capture_saves_and_applies(self):
        from gi.repository import Gdk, Gtk
        mods = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
        pop = self.popover("Mic_In", "mute")
        pop.start_capture("mic:mute")
        pop.handle_key(Gdk.KEY_m, mods)
        self.assertEqual(self.keys["mic:mute"], Gtk.accelerator_name(Gdk.KEY_m, mods))
        self.assertEqual(self.hk_log[-1][0], "apply")
        self.assertIsNone(pop.capturing)
        self.assertIn("M", pop.rows[0].keys_label.get_label())

    def test_unacceptable_key_keeps_capturing(self):
        from gi.repository import Gdk
        pop = self.popover("Mic_In", "mute")
        pop.start_capture("mic:mute")
        pop.handle_key(Gdk.KEY_m, 0)
        self.assertEqual(pop.capturing, "mic:mute")
        self.assertTrue(pop.message.get_visible())
        self.assertNotIn("mic:mute", self.keys)

    def test_modifier_alone_waits_for_the_real_key(self):
        from gi.repository import Gdk
        pop = self.popover("Mic_In", "mute")
        pop.start_capture("mic:mute")
        pop.handle_key(Gdk.KEY_Control_L, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(pop.capturing, "mic:mute")

    def test_clear_removes_the_key(self):
        pop = self.popover("Music_Audio", "mute")
        pop.clear("music:mute")
        self.assertNotIn("music:mute", self.keys)
        self.assertEqual(pop.rows[0].keys_label.get_label(), "—")

    def test_closing_while_capturing_restores_shortcuts(self):
        pop = self.popover("Music_Audio", "mute")
        pop.start_capture("music:mute")
        pop.emit("closed")
        self.assertIsNone(pop.capturing)
        self.assertEqual(self.hk_log[-1][0], "apply")


class HotkeyHealTest(UiTestBase):
    def test_stopping_mid_capture_puts_shortcuts_back(self):
        pop = self.strip("Music_Audio").hotkey_popover("mute")
        self.addCleanup(pop.unparent)
        pop.start_capture("music:mute")
        self.controller.stop()       # window closed, logout, SIGTERM
        self.assertEqual(self.hk_log[-1][0], "apply")

    def test_heal_restores_a_capture_that_never_finished(self):
        self.hk_suspended = True     # the last window died while capturing
        self.controller.heal_hotkeys()
        self.assertEqual(self.hk_log, [("apply", self.keys)])

    def test_heal_does_nothing_normally(self):
        self.controller.heal_hotkeys()
        self.assertEqual(self.hk_log, [])
