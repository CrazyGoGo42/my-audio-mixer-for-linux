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


if __name__ == "__main__":
    unittest.main()
