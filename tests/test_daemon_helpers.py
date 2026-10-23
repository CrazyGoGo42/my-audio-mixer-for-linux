import importlib.machinery
import importlib.util
import json
import os
import stat
import tempfile
import unittest

from audiomixer.config import Channel
from audiomixer.routing import own_nodes

HERE = os.path.dirname(os.path.abspath(__file__))


def load_daemon():
    """The daemon script as a module (its main() only runs as __main__)."""
    path = os.path.join(HERE, "..", "bin", "audio-router-daemon")
    loader = importlib.machinery.SourceFileLoader("audio_router_daemon", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


CHS = [Channel("default", "Default_Audio", "Desktop", ("-", "-", "-")),
       Channel("music", "Music_Audio", "Music", ("-", "-", "-"))]


class DaemonHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = load_daemon()

    def test_never_asks_about_our_own_nodes(self):
        own = own_nodes(CHS)
        for name in ("Music_Audio_out", "Default_Audio_out", "EE_Return_out", "Mic_In_in",
                     "All_Audio_in", "Music_Audio", "EE_Return", "Mic_In", "All_Audio"):
            self.assertTrue(self.d.skip_stream(name, own), name)
        self.assertFalse(self.d.skip_stream("Zen", own))
        self.assertFalse(self.d.skip_stream("spotify", own))

    def test_no_prompt_while_window_runs(self):
        # The window lists new apps itself ("new" marker); a zenity popup on
        # top of it would ask the same question twice.
        self.assertFalse(self.d.should_prompt(window_is_running=True))
        self.assertTrue(self.d.should_prompt(window_is_running=False))

    def test_which_events_trigger_a_patchbay_pass(self):
        rewire = self.d.event_rewires
        self.assertTrue(rewire("Event 'new' on sink #400"))            # device / EasyEffects back
        self.assertTrue(rewire("Event 'remove' on source #401"))
        self.assertTrue(rewire("Event 'change' on server #-1"))        # default output changed
        self.assertFalse(rewire("Event 'new' on client #9"))           # every pactl run
        self.assertFalse(rewire("Event 'new' on source-output #9"))    # meters
        self.assertFalse(rewire("Event 'change' on sink #53"))         # just a volume
        self.assertFalse(rewire("Event 'new' on sink-input #77"))      # an app (prompted separately)

    def test_volume_targets_cover_channels_and_the_new_strips(self):
        self.assertEqual(self.d.volume_targets(CHS), [
            ("Default_Audio", "sink"), ("Music_Audio", "sink"), ("EE_Return", "sink"),
            ("Mic_In", "source"), ("All_Audio", "source")])

    def test_restore_uses_source_volume_for_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "calls")
            fake = os.path.join(tmp, "pactl")
            with open(fake, "w") as f:
                f.write(f'#!/bin/sh\necho "$*" >> {log}\n')
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
            vol_file = os.path.join(tmp, "volumes.json")
            with open(vol_file, "w") as f:
                json.dump({"Music_Audio": 9830, "Mic_In": 45000, "Stale_Audio": 1}, f)
            old_path = os.environ["PATH"]
            os.environ["PATH"] = tmp + os.pathsep + old_path
            try:
                self.d.restore_volumes(vol_file, self.d.volume_targets(CHS))
            finally:
                os.environ["PATH"] = old_path
            with open(log) as f:
                self.assertEqual(sorted(f.read().splitlines()),
                                 ["set-sink-volume Music_Audio 9830", "set-source-volume Mic_In 45000"])


class VolumeTickTest(unittest.TestCase):
    """A PipeWire restart recreates the nodes at 100%. The daemon must put the
    saved levels back, never save the 100%s over them (seen live 2026-10-23)."""

    SAVED = {"Default_Audio": 22937, "Music_Audio": 16384, "EE_Return": 65536,
             "Mic_In": 50000, "All_Audio": 65536}

    def setUp(self):
        self.d = load_daemon()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "calls")
        fake = os.path.join(self.tmp.name, "pactl")
        # Every node reports a fresh 100%, answering only the cheap JSON lists
        # (one call per kind instead of one per node).
        listing = json.dumps([{"name": n, "mute": n == "Mic_In",
                               "volume": {"front-left": {"value": 65536, "value_percent": "100%"}}}
                              for n in ("Default_Audio", "Music_Audio", "EE_Return", "Mic_In", "All_Audio")])
        with open(os.path.join(self.tmp.name, "listing.json"), "w") as f:
            f.write(listing)
        with open(fake, "w") as f:
            f.write(f'#!/bin/sh\ncase "$*" in "-f json list "*) cat {self.tmp.name}/listing.json; exit 0;; esac\n'
                    f'echo "$*" >> {self.log}\n')
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        old = os.environ["PATH"]
        os.environ["PATH"] = self.tmp.name + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        self.d.VOL_FILE = os.path.join(self.tmp.name, "volumes.json")
        self.write_saved()
        self.d.VOLUME_TARGETS = self.d.volume_targets(CHS)

    def write_saved(self):
        with open(self.d.VOL_FILE, "w") as f:
            json.dump(self.SAVED, f)

    def saved(self):
        with open(self.d.VOL_FILE) as f:
            return json.load(f)

    def calls(self):
        """Commands run since the last call (none ran = no log file yet)."""
        try:
            with open(self.log) as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            return []
        open(self.log, "w").close()
        return lines

    def graph(self, shift=0):
        from audiomixer.pwgraph import parse_dump
        from tests.pwfake import DumpBuilder
        b = DumpBuilder()
        for i in range(shift):
            b.add(f"filler{i}", "Audio/Sink")
        for name, _ in self.d.VOLUME_TARGETS:
            b.add(name, "Audio/Sink")
        return parse_dump(b.dump())

    def test_fresh_nodes_get_saved_volumes_twice_then_changes_are_saved(self):
        g = self.graph()
        self.d.volume_tick(g)
        self.assertIn("set-sink-volume Music_Audio 16384", self.calls())
        self.d.volume_tick(g)
        self.assertIn("set-source-volume Mic_In 50000", self.calls())
        self.assertEqual(self.saved(), self.SAVED)  # nothing saved while restoring
        self.d.volume_tick(g)                       # settled: now changes are saved
        self.assertEqual(self.saved()["Music_Audio"], 65536)

    def test_pipewire_restart_restores_instead_of_saving_100_percent(self):
        for _ in range(3):
            self.d.volume_tick(self.graph())
        self.write_saved()
        self.calls()
        self.d.volume_tick(self.graph(shift=3))     # same names, new node ids
        self.assertIn("set-sink-volume Default_Audio 22937", self.calls())
        self.assertEqual(self.saved(), self.SAVED)

    def test_saving_reads_all_volumes_in_two_pactl_calls(self):
        for _ in range(3):
            self.d.volume_tick(self.graph())
        saved = self.saved()
        self.assertEqual({k: v for k, v in saved.items() if k != "_mute"}, {n: 65536 for n in self.SAVED})
        self.assertEqual(saved["_mute"]["Mic_In"], True)   # the muted mic is remembered
        self.assertEqual(saved["_mute"]["Music_Audio"], False)
        self.assertEqual([c for c in self.calls() if "get-" in c], [])  # no per-node calls

    def test_mutes_restored_with_volumes_but_nothing_is_unmuted(self):
        # A muted mic must come back muted after a reboot or PipeWire restart;
        # restoring never unmutes (a late second pass would undo a fresh mute).
        with open(self.d.VOL_FILE, "w") as f:
            json.dump(dict(self.SAVED, _mute={"Mic_In": True, "Music_Audio": False}), f)
        self.d.volume_tick(self.graph())
        calls = self.calls()
        self.assertIn("set-source-volume Mic_In 50000", calls)
        self.assertIn("set-source-mute Mic_In 1", calls)
        self.assertNotIn("set-sink-mute Music_Audio 0", calls)

    def test_stopping_saves_the_latest_levels(self):
        # Mute the mic and reboot within the 10 s poll: it must stay muted.
        self.d.PID_FILE = os.path.join(self.tmp.name, "pid")
        for _ in range(3):
            self.d.volume_tick(self.graph())
        self.write_saved()                     # the last poll ran before the change
        with self.assertRaises(SystemExit):
            self.d.cleanup()
        self.assertEqual(self.saved()["Music_Audio"], 65536)
        self.assertTrue(self.saved()["_mute"]["Mic_In"])

    def test_stopping_mid_restore_saves_nothing(self):
        self.d.PID_FILE = os.path.join(self.tmp.name, "pid")
        self.d.volume_tick(self.graph())       # fresh 100% nodes, restore still pending
        with self.assertRaises(SystemExit):
            self.d.cleanup()
        self.assertEqual(self.saved(), self.SAVED)

    def test_old_volume_files_still_load(self):
        self.d.volume_tick(self.graph())       # SAVED has no "_mute" (files from before)
        calls = self.calls()
        self.assertIn("set-sink-volume Music_Audio 16384", calls)
        self.assertEqual([c for c in calls if "-mute" in c], [])

    def test_present_targets_are_restored_but_nothing_saved_until_all_exist(self):
        g = self.graph()
        del g.nodes["Mic_In"]
        self.d.volume_tick(g)
        calls = self.calls()
        self.assertIn("set-sink-volume Music_Audio 16384", calls)
        self.assertFalse([c for c in calls if "Mic_In" in c])
        for _ in range(3):
            self.d.volume_tick(g)
        self.assertEqual(self.saved(), self.SAVED)  # never a partial snapshot

    def test_late_target_gets_its_own_restore(self):
        g = self.graph()
        del g.nodes["Mic_In"]
        for _ in range(3):
            self.d.volume_tick(g)
        self.calls()
        self.d.volume_tick(self.graph())            # Mic_In appears later
        self.assertEqual(self.calls(), ["set-source-volume Mic_In 50000"])

    def test_restore_happens_before_any_linking_when_nodes_are_new(self):
        # An unplanned PipeWire restart: fresh nodes at 100%. Linking them before
        # the saved levels are back would play them at 100% (review C1).
        def fake_reconcile(graph):
            with open(self.log, "a") as f:
                f.write("LINK\n")
        self.d.reconcile_once = fake_reconcile
        self.d.apply_eq = lambda *a: None
        self.d.tick(self.graph(shift=5))
        calls = self.calls()
        self.assertIn("LINK", calls)
        first_link = calls.index("LINK")
        self.assertTrue(any(c.startswith("set-") for c in calls[:first_link]), calls)


if __name__ == "__main__":
    unittest.main()


class HotkeyHealDaemonTest(unittest.TestCase):
    """The window suspends our shortcuts while you press a new combination; if
    it dies before putting them back, the daemon does."""

    def setUp(self):
        import types
        self.d = load_daemon()
        self.healed, self.marker = [], True
        self.d.hotkeys = types.SimpleNamespace(suspended=lambda: self.marker,
                                               heal=lambda channels, bin_dir: self.healed.append(bin_dir))

    def test_heals_when_the_window_is_gone(self):
        self.d.window_running = lambda: False
        self.d.heal_hotkeys()
        self.assertEqual(len(self.healed), 1)

    def test_leaves_a_capture_in_progress_alone(self):
        self.d.window_running = lambda: True
        self.d.heal_hotkeys()
        self.assertEqual(self.healed, [])

    def test_no_marker_costs_no_dbus_call(self):
        self.marker = False
        self.d.window_running = lambda: self.fail("asked D-Bus without a reason")
        self.d.heal_hotkeys()
        self.assertEqual(self.healed, [])
