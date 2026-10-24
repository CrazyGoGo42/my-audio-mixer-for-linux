"""The window's sizes (it shrinks step by step, never scrolls), the Bass/Treble
knobs, and the settings menu (theme, restarts, quit)."""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import types
import unittest
from unittest import mock

from tests.test_ui import UiTestBase

HERE = os.path.dirname(os.path.abspath(__file__))


def Gtk():
    from gi.repository import Gtk as gtk
    return gtk


class LayoutTest(UiTestBase):
    """Which layout shows at which size, and that each one fits it, is checked
    on a real (hidden) screen by test_ui_sizes."""

    def test_layouts_never_scroll(self):
        for widget in (self.win.body, self.win.compact):
            self.assertIsNone(widget.get_ancestor(Gtk().ScrolledWindow))

    def test_layout_follows_the_window_size(self):
        self.win.set_layout("tight")
        self.assertEqual(self.win.stack.get_visible_child_name(), "wide")
        self.assertTrue(self.win.body.has_css_class("tight"))
        self.win.set_layout("compact")
        self.assertEqual(self.win.stack.get_visible_child_name(), "compact")
        self.win.set_layout("roomy")
        self.assertEqual(self.win.stack.get_visible_child_name(), "wide")
        self.assertFalse(self.win.body.has_css_class("tight"))


class KnobTest(UiTestBase):
    def knob(self):
        from audiomixer.ui.knob import Knob
        knob = Knob(-12, 12, 0.5)
        seen = []
        knob.connect("value-changed", lambda k: seen.append(k.get_value()))
        return knob, seen

    def test_bass_and_treble_are_knobs(self):
        from audiomixer.ui.knob import Knob
        music = self.strip("Music_Audio")
        self.assertIsInstance(music.bass, Knob)
        self.assertIsInstance(music.treble, Knob)

    def test_values_snap_to_half_a_db_and_stay_in_range(self):
        knob, seen = self.knob()
        knob.set_value(3.3)
        knob.set_value(3.5)   # same value again: nothing to report
        knob.set_value(40)
        self.assertEqual(seen, [3.5, 12])

    def test_dragging_up_turns_it_up_and_down_turns_it_down(self):
        knob, _ = self.knob()
        knob.drag_begin()
        knob.drag_update(0, -40)
        self.assertEqual(knob.get_value(), 6)
        knob.drag_update(0, 400)   # far past the end
        self.assertEqual(knob.get_value(), -12)

    def test_double_click_resets_to_flat(self):
        knob, seen = self.knob()
        knob.set_value(-4)
        knob.reset()
        self.assertEqual(seen, [-4, 0])

    def test_keys_and_wheel_move_half_a_db_per_step(self):
        knob, _ = self.knob()
        knob.step(2)
        knob.step(-1)
        self.assertEqual(knob.get_value(), 0.5)

    def test_a_clicked_knob_takes_the_wheel_with_the_window_in_the_background(self):
        music = self.strip("Music_Audio")
        music.get_root().set_focus(music.bass)             # what clicking it does
        self.assertFalse(music.bass.has_focus())           # the window isn't active
        self.assertTrue(music.bass._on_wheel(None, 0, -1))
        self.assertEqual(music.bass.get_value(), 0.5)
        self.assertFalse(music.treble._on_wheel(None, 0, -1))   # not clicked: scrolls past
        self.assertEqual(music.treble.get_value(), 0)

    def test_a_knob_shows_its_value_itself_and_its_tooltip_stays_its_name(self):
        from audiomixer.ui.knob import value_text
        music = self.strip("Music_Audio")
        music.treble.set_value(-3)
        self.assertEqual(value_text(music.treble.get_value()), "-3")
        from audiomixer.ui.tips import tip_text
        self.assertEqual(tip_text(music.treble), "Treble")


class RefreshCostTest(UiTestBase):
    """Lightweight: setting a tooltip costs ~10 ms here (even unchanged), so a
    refresh that changes nothing must not rewrite any."""

    def test_a_refresh_with_nothing_new_writes_no_tooltips(self):
        from gi.repository import Gtk as gtk
        writes = []
        original = gtk.Widget.set_tooltip_text

        def counting(widget, text):
            writes.append(text)
            return original(widget, text)
        gtk.Widget.set_tooltip_text = counting
        self.addCleanup(setattr, gtk.Widget, "set_tooltip_text", original)
        self.controller.refresh(status_too=True)
        self.assertEqual(writes, [])

    def test_building_a_window_writes_no_tooltips_the_slow_way(self):
        from gi.repository import Gtk as gtk
        from audiomixer.ui.window import MixerWindow
        writes = []
        original = gtk.Widget.set_tooltip_text
        gtk.Widget.set_tooltip_text = lambda w, t: writes.append(t) or original(w, t)
        self.addCleanup(setattr, gtk.Widget, "set_tooltip_text", original)
        win = MixerWindow(self.controller)
        self.addCleanup(win.destroy)
        self.controller.refresh(status_too=True)
        self.assertEqual(writes, [])

    def test_tips_are_handed_to_gtk_only_on_hover(self):
        from audiomixer.ui.tips import tip, tip_text
        button = Gtk().Button()
        tip(button, "Hello")
        self.assertTrue(button.get_has_tooltip())
        self.assertEqual(tip_text(button), "Hello")
        tip(button, "Bye")
        self.assertEqual(tip_text(button), "Bye")

    def test_turning_a_knob_writes_no_tooltips(self):
        from gi.repository import Gtk as gtk
        writes = []
        original = gtk.Widget.set_tooltip_text
        gtk.Widget.set_tooltip_text = lambda w, t: writes.append(t) or original(w, t)
        self.addCleanup(setattr, gtk.Widget, "set_tooltip_text", original)
        knob = self.strip("Music_Audio").bass
        knob.drag_begin()
        for dy in range(0, -60, -5):
            knob.drag_update(0, dy)
        self.assertEqual(writes, [])


class SettingsMenuTest(UiTestBase):
    def setUp(self):
        super().setUp()
        self.toasts = []
        self.win.show_toast = lambda text, **_: self.toasts.append(text)

    def menu_labels(self):
        labels = []

        def walk(model):
            for i in range(model.get_n_items()):
                label = model.get_item_attribute_value(i, "label", None)
                if label:
                    labels.append(label.get_string())
                for link in ("section", "submenu"):
                    sub = model.get_item_link(i, link)
                    if sub:
                        walk(sub)
        walk(self.win.menu_button.get_menu_model())
        return labels

    def test_menu_has_theme_easyeffects_restarts_and_quit(self):
        self.assertEqual(self.menu_labels(),
                         ["Open EasyEffects", "Restart EasyEffects", "Restart Audio Engine", "Quit"])
        self.assertEqual(sorted(self.win.theme_switcher.buttons), ["dark", "light", "system"])

    def test_restart_runs_in_the_background_and_says_when_done(self):
        self.win.restart("engine")
        argv, done = self.spawned[-1]
        self.assertTrue(argv[0].endswith("audio-mixer"))
        self.assertEqual(argv[1:], ["restart", "engine"])
        self.assertEqual(self.toasts, ["Restarting the audio engine…"])
        # One at a time: a second restart can't start mid-way.
        self.assertFalse(self.win.lookup_action("restart-engine").get_enabled())
        self.assertFalse(self.win.lookup_action("restart-easyeffects").get_enabled())
        done(0, "")
        self.assertTrue(self.win.lookup_action("restart-engine").get_enabled())
        self.assertEqual(self.toasts[-1], "Audio engine restarted")

    def test_a_failed_restart_says_why(self):
        self.win.restart("easyeffects")
        argv, done = self.spawned[-1]
        self.assertEqual(argv[1:], ["restart", "easyeffects"])
        done(1, "flatpak: command not found\n")
        self.assertEqual(self.toasts[-1], "Couldn't restart EasyEffects: flatpak: command not found")
        self.assertTrue(self.win.lookup_action("restart-easyeffects").get_enabled())

    def test_engine_restart_asks_first(self):
        dialog = self.win.engine_restart_dialog()
        dialog.emit("response", "cancel")
        self.assertEqual(self.spawned, [])
        dialog = self.win.engine_restart_dialog()
        dialog.emit("response", "restart")
        self.assertEqual(self.spawned[-1][0][1:], ["restart", "engine"])

    def test_open_easyeffects_shows_its_window(self):
        self.win.activate_action("win.open-easyeffects", None)
        self.assertEqual(self.spawned[-1][0], ["flatpak", "run", "com.github.wwmm.easyeffects"])

    def test_quit_closes_the_window(self):
        closed = []
        self.win.close = lambda: closed.append(True)   # closing runs the usual size save + meter stop
        self.win.activate_action("win.quit", None)
        self.assertEqual(closed, [True])


class ThemeTest(UiTestBase):
    def scheme(self):
        from gi.repository import Adw
        return Adw.StyleManager.get_default().get_color_scheme()

    def test_picking_a_theme_applies_and_remembers_it(self):
        from gi.repository import Adw
        from audiomixer.ui import settings
        self.win.theme_switcher.buttons["dark"].set_active(True)
        self.assertEqual(self.scheme(), Adw.ColorScheme.FORCE_DARK)
        self.assertEqual(settings.load_theme(), "dark")
        self.win.theme_switcher.buttons["system"].set_active(True)
        self.assertEqual(self.scheme(), Adw.ColorScheme.DEFAULT)
        self.assertEqual(settings.load_theme(), "system")

    def test_the_window_starts_with_the_saved_theme(self):
        from gi.repository import Adw
        from audiomixer.ui import settings
        from audiomixer.ui.window import MixerWindow
        settings.save_theme("light")
        win = MixerWindow(self.controller)
        self.addCleanup(win.destroy)
        self.assertEqual(self.scheme(), Adw.ColorScheme.FORCE_LIGHT)
        self.assertTrue(win.theme_switcher.buttons["light"].get_active())


class ThemeSettingTest(unittest.TestCase):
    def test_theme_and_size_are_kept_side_by_side(self):
        from audiomixer.ui.settings import load_size, load_theme, save_size, save_theme
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "window.json")
            self.assertEqual(load_theme(path), "system")
            save_size(900, 500, path)
            save_theme("dark", path)
            save_size(800, 600, path)
            self.assertEqual((load_size(path), load_theme(path)), ((800, 600), "dark"))

    def test_an_unknown_theme_follows_the_system(self):
        from audiomixer.ui.settings import load_theme
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "window.json")
            with open(path, "w") as f:
                json.dump({"theme": "purple"}, f)
            self.assertEqual(load_theme(path), "system")


def load_cli():
    path = os.path.join(HERE, "..", "bin", "audio-mixer")
    loader = importlib.machinery.SourceFileLoader("audio_mixer_cli", path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class RestartCliTest(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()

    def test_restart_easyeffects_quits_it_then_starts_it_again(self):
        calls = []
        self.cli.easyeffects = types.SimpleNamespace(stop=lambda: calls.append("stop"),
                                                     launch=lambda: calls.append("launch"))
        self.assertEqual(self.cli.main(["restart", "easyeffects"]), 0)
        self.assertEqual(calls, ["stop", "launch"])

    def test_restart_engine_is_the_safe_pipewire_restart(self):
        with mock.patch("os.execv") as execv:
            self.cli.main(["restart", "engine"])
        path, args = execv.call_args[0]
        self.assertEqual(os.path.basename(path), "audio-routes-apply")
        self.assertEqual(args[1:], ["--restart-pipewire"])

    def test_restart_needs_to_know_what(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(self.cli.main(["restart", "everything"]), 2)


if __name__ == "__main__":
    unittest.main()
