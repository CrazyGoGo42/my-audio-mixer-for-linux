import json
import os
import re
import tempfile
import unittest

from audiomixer.config import load_channels
from audiomixer.hotkeys import (
    acceptable, actions, apply_to_gnome, assign, bindings, heal, load, remove_from_gnome, save,
    suspend, suspended, _dconf,
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


class FakeDconf:
    """Just enough of `dconf dump/load/reset -f` for custom keybindings; also
    counts calls (applying must stay a couple of process runs, not ~130)."""

    BASE = "/org/gnome/settings-daemon/plugins/media-keys/"

    def __init__(self, paths=()):
        self.list = [p for p, _ in paths]
        self.entries = {p: dict(zip(("name", "command", "binding"), v)) for p, v in paths}
        self.calls = 0

    @staticmethod
    def _q(s):
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def __call__(self, args, stdin=None):
        self.calls += 1
        if args[0] == "dump":
            out = ["[/]", "custom-keybindings=[" + ", ".join(self._q(p) for p in self.list) + "]", ""]
            for p, e in self.entries.items():
                rel = p[len(self.BASE):].rstrip("/")
                out += [f"[{rel}]"] + [f"{k}={self._q(v)}" for k, v in sorted(e.items())] + [""]
            return "\n".join(out)
        if args[0] == "reset":
            self.entries.pop(args[-1], None)
            return ""
        section = None
        for line in stdin.splitlines():
            if line.startswith("["):
                section = line[1:-1]
            elif "=" in line:
                key, _, value = line.partition("=")
                if section == "/" and key == "custom-keybindings":
                    self.list = re.findall(r"'([^']*)'", value)
                else:
                    path = self.BASE + section + "/"
                    v = value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
                    self.entries.setdefault(path, {})[key] = v
        return ""

    def bound(self):
        return [tuple(self.entries.get(p, {}).get(k, "") for k in ("name", "command", "binding"))
                for p in self.list]


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
        self.assertIn(("Music A2", "/bin/audio-channel-control music A2", "<Super>F2"), b)
        self.assertIn(("Mic Mute", "/bin/audio-channel-control mic mute", "<Ctrl><Alt>m"), b)
        self.assertIn(("EasyEffects A1", "/bin/audio-channel-control fx A1", "<Ctrl>F1"), b)

    def test_setting_a_used_combination_moves_it(self):
        keys = assign({"default:mute": "<Ctrl>KP_1"}, "mic:mute", "<Control>KP_1")
        self.assertEqual(keys, {"mic:mute": "<Control>KP_1"})
        self.assertEqual(assign(keys, "mic:mute", None), {})

    def test_acceptable_rejects_plain_letters(self):
        for accel in ("<Ctrl>m", "<Alt>F4", "<Super>1", "F5", "<Ctrl>KP_1", "XF86AudioMute"):
            self.assertTrue(acceptable(accel), accel)
        for accel in ("a", "<Shift>a", "space", "", "<Shift>Return"):
            self.assertFalse(acceptable(accel), accel)

    def test_keypad_keys_need_a_modifier(self):
        # A bare keypad key bound globally would stop the numpad typing anywhere.
        for accel in ("KP_1", "KP_Add", "KP_End", "KP_Enter", "<Shift>KP_2"):
            self.assertFalse(acceptable(accel), accel)

    def test_numlock_off_capture_is_stored_as_the_numpad_key(self):
        # NumLock off, Ctrl+Num4 arrives as KP_Left: it's Desktop Vol Down's
        # key (via its twin), so it must move here, not end up bound twice.
        keys = assign({"default:down": "<Ctrl>KP_4"}, "music:up", "<Control>KP_Left")
        self.assertEqual(keys, {"music:up": "<Control>KP_4"})
        accels = sorted(a for _, _, a in bindings(keys, "/bin", self.chs))
        self.assertEqual(accels, ["<Control>KP_4", "<Control>KP_Left"])

    def test_a_failed_read_writes_nothing(self):
        # A failed dump must never be taken for "no shortcuts" and delist yours.
        runs = []

        def broken(args, stdin=None):
            runs.append(args[0])
            if args[0] == "dump":
                raise RuntimeError("dconf: cannot read")
            return ""
        with self.assertRaises(RuntimeError):
            apply_to_gnome(bindings(load(self.chs, self.file), "/bin", self.chs), broken)
        self.assertEqual(runs, ["dump"])

    def test_dconf_failures_are_raised(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "dconf"), "w") as f:
                f.write("#!/bin/sh\necho 'error: no session bus' >&2\nexit 1\n")
            os.chmod(os.path.join(d, "dconf"), 0o755)
            old = os.environ["PATH"]
            os.environ["PATH"] = d + os.pathsep + old
            try:
                with self.assertRaisesRegex(RuntimeError, "no session bus"):
                    _dconf(["dump", "/"])
            finally:
                os.environ["PATH"] = old

    def test_suspend_marks_and_heal_puts_them_back(self):
        # If the window dies mid-capture, the marker lets it (or the daemon)
        # restore the shortcuts later instead of leaving you without hotkeys.
        gs = FakeDconf()
        apply_to_gnome(bindings(load(self.chs, self.file), "/bin", self.chs), gs)
        suspend(gs, self.file)
        self.assertEqual(gs.bound(), [])
        self.assertTrue(suspended(self.file))
        self.assertTrue(heal(self.chs, "/bin", self.file, gs))
        self.assertEqual(len(gs.bound()), 21)
        self.assertFalse(suspended(self.file))
        runs = gs.calls
        self.assertFalse(heal(self.chs, "/bin", self.file, gs))  # nothing pending: no dconf runs
        self.assertEqual(gs.calls, runs)

    def test_apply_keeps_foreign_shortcuts(self):
        gs = FakeDconf([
            (f"{GPATH}/custom0/", ("Terminal", "gnome-terminal", "<Super>t")),
            (f"{GPATH}/custom100/", ("CH1 Mute (Games)", "/old/audio-channel-control games mute", "<Ctrl>KP_1")),
        ])
        apply_to_gnome(bindings({"mic:mute": "<Ctrl><Alt>m"}, "/bin", self.chs), gs)
        self.assertEqual(gs.bound(), [("Terminal", "gnome-terminal", "<Super>t"),
                                      ("Mic Mute", "/bin/audio-channel-control mic mute", "<Ctrl><Alt>m")])

    def test_remove_from_gnome_leaves_only_foreign(self):
        gs = FakeDconf([
            (f"{GPATH}/custom0/", ("Terminal", "gnome-terminal", "<Super>t")),
            (f"{GPATH}/custom101/", ("Music A2", "/bin/audio-mixer out music A2 toggle", "<Super>F2")),
        ])
        remove_from_gnome(gs)
        self.assertEqual(gs.bound(), [("Terminal", "gnome-terminal", "<Super>t")])

    def test_applying_is_a_handful_of_process_runs(self):
        gs = FakeDconf([(f"{GPATH}/custom100/", ("Old", "/b/audio-channel-control music up", "<Ctrl>KP_9"))])
        apply_to_gnome(bindings(load(self.chs, self.file), "/bin", self.chs), gs)
        self.assertEqual(len(gs.bound()), 21)
        self.assertLessEqual(gs.calls, 3)



class HotkeysCliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        path = os.path.join(self.dir.name, "channels.conf")
        with open(path, "w") as f:
            f.write(CHANNELS_CONF)
        self.chs = load_channels(path)
        self.file = os.path.join(self.dir.name, "hotkeys.json")
        self.gs = FakeDconf()

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

    def test_apply_reports_a_dconf_failure(self):
        def broken(args, stdin=None):
            raise RuntimeError("dconf: cannot read")
        from audiomixer.hotkeys import cli
        code, text = cli(["apply"], self.chs, "/bin", self.file, broken)
        self.assertNotEqual(code, 0)
        self.assertIn("cannot read", text)


if __name__ == "__main__":
    unittest.main()
