"""Renaming a channel: only its name changes (key, sink, hotkeys, routes stay),
everywhere it shows — the file, the command line, the window, the popup."""

import os
import tempfile
import types
import unittest
from unittest import mock

from audiomixer.config import Channel, load_channels, rename_channel

from tests.test_daemon_helpers import load_daemon
from tests.test_ui import UiTestBase
from tests.test_ui_layout import load_cli

CONF = """\
# key     sink            mute        down        up           label
default   Default_Audio   KP_1        KP_4        KP_7         Desktop
music     Music_Audio     KP_3        KP_6        KP_9         Music   # tunes
browser   Browser_Audio   KP_Delete   KP_Add      KP_Subtract  Browser
"""


class RenameFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "channels.conf")
        with open(self.path, "w") as f:
            f.write(CONF)

    def text(self):
        with open(self.path) as f:
            return f.read()

    def test_only_the_name_changes(self):
        channels = rename_channel("music", "Podcasts", self.path)
        self.assertEqual([c.label for c in channels], ["Desktop", "Podcasts", "Browser"])
        self.assertEqual(load_channels(self.path)[1],
                         Channel("music", "Music_Audio", "Podcasts", ("KP_3", "KP_6", "KP_9")))
        self.assertEqual(self.text(), CONF.replace("Music   # tunes", "Podcasts   # tunes"))

    def test_names_can_have_spaces(self):
        rename_channel("browser", "  Voice chat ", self.path)
        self.assertEqual(load_channels(self.path)[2].label, "Voice chat")

    def test_unusable_names_are_refused_and_nothing_changes(self):
        for bad in ("", "   ", "Fun # stuff", "x" * 21, "desktop", "DEFAULT", "Browser",
                    "Mic", "EasyEffects", "all audio", "fx"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rename_channel("music", bad, self.path)
        self.assertEqual(self.text(), CONF)

    def test_a_new_spelling_of_its_own_name_is_fine(self):
        rename_channel("music", "MUSIC", self.path)
        self.assertEqual(load_channels(self.path)[1].label, "MUSIC")

    def test_unknown_channel(self):
        with self.assertRaises(ValueError):
            rename_channel("games", "Games", self.path)

    def test_the_reason_is_readable(self):
        with self.assertRaises(ValueError) as e:
            rename_channel("music", "Browser", self.path)
        self.assertEqual(str(e.exception), "There's already a channel called Browser")


class RenameCliTest(unittest.TestCase):
    def test_rename_by_name_then_refresh_hotkeys_and_device_name(self):
        cli = load_cli()
        chs = [Channel("music", "Music_Audio", "Music", ("-", "-", "-"))]
        renamed = [Channel("music", "Music_Audio", "Podcasts", ("-", "-", "-"))]
        calls = []
        cli.load_channels = lambda: chs
        cli.rename_channel = lambda key, label: calls.append(("rename", key, label)) or renamed
        cli.hotkeys = types.SimpleNamespace(cli=lambda argv, channels, bin_dir: calls.append(
            ("hotkeys", argv, [c.label for c in channels])) or (0, ""))
        with mock.patch("subprocess.run") as run, mock.patch("sys.stdout"):
            self.assertEqual(cli.main(["rename", "music", "Podcasts"]), 0)
        self.assertEqual(calls, [("rename", "music", "Podcasts"), ("hotkeys", ["apply"], ["Podcasts"])])
        self.assertEqual(os.path.basename(run.call_args[0][0][0]), "audio-routes-apply")
        self.assertEqual(run.call_args[0][0][1:], ["--no-restart"])

    def test_a_refused_name_says_why(self):
        cli = load_cli()
        cli.load_channels = lambda: [Channel("music", "Music_Audio", "Music", ("-", "-", "-"))]

        def refuse(key, label):
            raise ValueError("There's already a channel called Browser")
        cli.rename_channel = refuse
        with mock.patch("sys.stderr") as err:
            self.assertEqual(cli.main(["rename", "music", "Browser"]), 2)
        self.assertIn("There's already a channel called Browser", "".join(c.args[0] for c in err.write.call_args_list))


class RenameWindowTest(UiTestBase):
    def setUp(self):
        super().setUp()
        self.renames = []

        def rename(key, label):
            if label == "Browser":
                raise ValueError("There's already a channel called Browser")
            self.renames.append((key, label))
            return [Channel(c.key, c.sink, label if c.key == key else c.label, c.hotkeys)
                    for c in self.controller.channels]
        self.controller._rename = rename
        self.toasts = []
        self.win.show_toast = lambda text, **kw: self.toasts.append((text, kw.get("button")))

    def test_right_click_on_a_channel_name_offers_rename(self):
        music = self.strip("Music_Audio")
        pop = music.rename_popover()
        self.addCleanup(pop.unparent)
        self.assertEqual(pop.entry.get_text(), "Music")
        self.assertIsNone(self.strip("Mic_In").rename_popover())   # built-in strips keep their names

    def test_renaming_shows_everywhere_and_keeps_everything_else(self):
        pop = self.strip("Music_Audio").rename_popover()
        self.addCleanup(pop.unparent)
        pop.entry.set_text("Podcasts")
        pop.apply()
        self.assertEqual(self.renames, [("music", "Podcasts")])
        self.assertEqual(self.strip("Music_Audio").heading.get_label(), "Podcasts")
        compact = next(r for r in self.win.compact.strips if r.name == "Music_Audio")
        self.assertEqual(compact.heading.get_label(), "Podcasts")
        row = self.win.apps.rows[0]
        self.assertEqual([t.get_label() for t in row.channel_toggles], ["Desktop", "Discord", "Podcasts", "Browser"])
        self.assertEqual(self.controller.channels[2].key, "music")
        # GNOME's shortcut names carry it; other apps get it from the next engine start.
        self.assertEqual(self.hk_log[-1][0], "apply")
        self.assertEqual(self.spawned[-1][0][1:], ["--no-restart"])
        text, button = self.toasts[-1]
        self.assertIn("Podcasts", text)
        self.assertEqual(button[0], "Restart Now")

    def test_a_refused_name_stays_in_the_box_with_the_reason(self):
        pop = self.strip("Music_Audio").rename_popover()
        self.addCleanup(pop.unparent)
        pop.entry.set_text("Browser")
        pop.apply()
        self.assertEqual(pop.message.get_label(), "There's already a channel called Browser")
        self.assertEqual(self.strip("Music_Audio").heading.get_label(), "Music")
        self.assertEqual(self.renames, [])


class RenamePopupTest(unittest.TestCase):
    def test_the_which_channel_popup_reads_the_names_fresh(self):
        d = load_daemon()
        d.load_channels = lambda: [Channel("default", "Default_Audio", "Everything else", ("-", "-", "-")),
                                   Channel("music", "Music_Audio", "Podcasts", ("-", "-", "-"))]
        rows = d.popup_rows()
        self.assertEqual(rows[:2], ["Music_Audio", "Podcasts"])
        self.assertIn("Leave on Everything else (stop asking)", rows)


if __name__ == "__main__":
    unittest.main()
