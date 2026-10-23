import json
import os
import re
import tempfile
import unittest

from audiomixer.config import load_channels
from audiomixer.hotkeys import (
    acceptable, actions, apply_to_gnome, assign, bindings, load, remove_from_gnome, save,
)

CHANNELS_CONF = """\
default   Default_Audio   KP_1        KP_4        KP_7         Desktop
discord   Discord_Audio   KP_2        KP_5        KP_8         Discord
music     Music_Audio     KP_3        KP_6        KP_9         Music
browser   Browser_Audio   KP_Delete   KP_Add      KP_Subtract  Browser
"""
KEYS = "org.gnome.settings-daemon.plugins.media-keys"
SCHEMA = KEYS + ".custom-keybinding"
GPATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"


class FakeGsettings:
    """Just enough of gsettings get/set/reset for custom keybindings."""

    def __init__(self, paths=()):
        self.values = {}
        self.list = [p for p, _ in paths]
        for path, (name, command, binding) in paths:
            self.values[(path, "name")] = f"'{name}'"
            self.values[(path, "command")] = f"'{command}'"
            self.values[(path, "binding")] = f"'{binding}'"

    def __call__(self, *args):
        op, schema, key = args[0], args[1], args[2]
        if schema == KEYS:
            if op == "get":
                return "[" + ", ".join(f"'{p}'" for p in self.list) + "]" if self.list else "@as []"
            self.list = re.findall(r"'([^']*)'", args[3])
            return ""
        path = schema.split(":", 1)[1]
        if op == "get":
            return self.values.get((path, key), "''")
        if op == "reset":
            self.values.pop((path, key), None)
        else:
            self.values[(path, key)] = args[3]
        return ""

    def bound(self):
        """[(name, command, binding)] of the listed paths, unquoted."""
        out = []
        for p in self.list:
            out.append(tuple(self.values.get((p, k), "''")[1:-1] for k in ("name", "command", "binding")))
        return out


class HotkeysTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        path = os.path.join(self.dir.name, "channels.conf")
        with open(path, "w") as f:
            f.write(CHANNELS_CONF)
        self.chs = load_channels(path)
        self.file = os.path.join(self.dir.name, "hotkeys.json")

    def test_actions_cover_every_strip_and_slot(self):
        ids = [a for a, _ in actions(self.chs)]
        self.assertEqual(ids[:3], ["mic:mute", "mic:down", "mic:up"])
        self.assertIn("music:A3", ids)
        self.assertIn("fx:A1", ids)
        self.assertIn("all:mute", ids)
        self.assertNotIn("mic:A1", ids)
        self.assertEqual(dict(actions(self.chs))["browser:down"], "Browser Vol Down")

    def test_first_load_migrates_channels_conf_keys(self):
        keys = load(self.chs, self.file)
        self.assertEqual(keys["default:mute"], "<Ctrl>KP_1")
        self.assertEqual(keys["browser:up"], "<Ctrl>KP_Subtract")
        b = bindings(keys, "/bin", self.chs)
        self.assertEqual(len(b), 21)  # exactly the shortcuts install.sh made before
        self.assertIn(("Desktop Mute", "/bin/audio-channel-control default mute", "<Ctrl>KP_1"), b)
        self.assertIn(("Desktop Mute (NumLock off)", "/bin/audio-channel-control default mute", "<Ctrl>KP_End"), b)
        self.assertIn(("Browser Mute", "/bin/audio-channel-control browser mute", "<Ctrl>KP_Delete"), b)

    def test_saved_file_wins_over_channels_conf(self):
        save({"mic:mute": "<Ctrl><Alt>m"}, self.file)
        self.assertEqual(load(self.chs, self.file), {"mic:mute": "<Ctrl><Alt>m"})

    def test_unknown_actions_in_the_file_are_dropped(self):
        with open(self.file, "w") as f:
            json.dump({"mic:mute": "<Ctrl><Alt>m", "games:mute": "<Ctrl>KP_1", "mic:A1": "<Ctrl>F1"}, f)
        self.assertEqual(load(self.chs, self.file), {"mic:mute": "<Ctrl><Alt>m"})

    def test_slot_and_strip_commands(self):
        b = bindings({"music:A2": "<Super>F2", "mic:mute": "<Ctrl><Alt>m", "fx:A1": "<Ctrl>F1"}, "/bin", self.chs)
        self.assertIn(("Music A2", "/bin/audio-mixer out music A2 toggle", "<Super>F2"), b)
        self.assertIn(("Mic Mute", "/bin/audio-channel-control mic mute", "<Ctrl><Alt>m"), b)
        self.assertIn(("EasyEffects A1", "/bin/audio-mixer out fx A1 toggle", "<Ctrl>F1"), b)

    def test_setting_a_used_combination_moves_it(self):
        keys = assign({"default:mute": "<Ctrl>KP_1"}, "mic:mute", "<Control>KP_1")
        self.assertEqual(keys, {"mic:mute": "<Control>KP_1"})
        self.assertEqual(assign(keys, "mic:mute", None), {})

    def test_acceptable_rejects_plain_letters(self):
        for accel in ("<Ctrl>m", "<Alt>F4", "<Super>1", "F5", "KP_1", "<Ctrl>KP_1", "XF86AudioMute"):
            self.assertTrue(acceptable(accel), accel)
        for accel in ("a", "<Shift>a", "space", "", "<Shift>Return"):
            self.assertFalse(acceptable(accel), accel)

    def test_apply_keeps_foreign_shortcuts(self):
        gs = FakeGsettings([
            (f"{GPATH}/custom0/", ("Terminal", "gnome-terminal", "<Super>t")),
            (f"{GPATH}/custom100/", ("CH1 Mute (Games)", "/old/audio-channel-control games mute", "<Ctrl>KP_1")),
        ])
        apply_to_gnome(bindings({"mic:mute": "<Ctrl><Alt>m"}, "/bin", self.chs), gs)
        self.assertEqual(gs.bound(), [("Terminal", "gnome-terminal", "<Super>t"),
                                      ("Mic Mute", "/bin/audio-channel-control mic mute", "<Ctrl><Alt>m")])

    def test_remove_from_gnome_leaves_only_foreign(self):
        gs = FakeGsettings([
            (f"{GPATH}/custom0/", ("Terminal", "gnome-terminal", "<Super>t")),
            (f"{GPATH}/custom101/", ("Music A2", "/bin/audio-mixer out music A2 toggle", "<Super>F2")),
        ])
        remove_from_gnome(gs)
        self.assertEqual(gs.bound(), [("Terminal", "gnome-terminal", "<Super>t")])


if __name__ == "__main__":
    unittest.main()


class HotkeysCliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        path = os.path.join(self.dir.name, "channels.conf")
        with open(path, "w") as f:
            f.write(CHANNELS_CONF)
        self.chs = load_channels(path)
        self.file = os.path.join(self.dir.name, "hotkeys.json")
        self.gs = FakeGsettings()

    def run_cli(self, *args):
        from audiomixer.hotkeys import cli
        return cli(list(args), self.chs, "/bin", self.file, self.gs)

    def test_apply_saves_the_migrated_file_and_binds(self):
        code, _ = self.run_cli("apply")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.gs.bound()), 21)
        with open(self.file) as f:
            self.assertEqual(json.load(f)["music:mute"], "<Ctrl>KP_3")

    def test_set_and_clear(self):
        self.assertEqual(self.run_cli("set", "mic:mute", "<Ctrl><Alt>m")[0], 0)
        self.assertIn(("Mic Mute", "/bin/audio-channel-control mic mute", "<Ctrl><Alt>m"), self.gs.bound())
        self.assertEqual(self.run_cli("clear", "mic:mute")[0], 0)
        self.assertNotIn("Mic Mute", [b[0] for b in self.gs.bound()])

    def test_bad_input_is_refused(self):
        self.assertEqual(self.run_cli("set", "mic:mute", "m")[0], 2)          # plain letter
        self.assertEqual(self.run_cli("set", "games:mute", "<Ctrl>F1")[0], 2)  # no such action
        self.assertEqual(self.run_cli("frobnicate")[0], 2)

    def test_list_shows_every_action(self):
        code, text = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("music:mute", text)
        self.assertIn("<Ctrl>KP_3", text)
        self.assertIn("fx:A4", text)
