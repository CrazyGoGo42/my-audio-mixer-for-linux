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
        with open(fake, "w") as f:  # every node reports a fresh 100%
            f.write(f'#!/bin/sh\necho "$*" >> {self.log}\n'
                    'case "$1" in get-*) echo "Volume: front-left: 65536 / 100% / 0.00 dB";; esac\n')
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
