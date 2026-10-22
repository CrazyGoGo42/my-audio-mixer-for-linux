import json
import os
import stat
import tempfile
import unittest

from audiomixer.apps import identity, is_known, load_routes, remember, route_now

ZEN = {"application.name": "Zen", "application.process.binary": "zen", "node.name": "Zen"}


class AppsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.routes = os.path.join(self.dir.name, "routes.json")
        with open(self.routes, "w") as f:
            json.dump({"_comment": "keep me", "binary": {"spotify": "Music_Audio"},
                       "app": {"WEBRTC VoiceEngine": "Discord_Audio"}, "ignore": ["sd_dummy"]}, f)

    def test_identity_prefers_binary_then_app_then_node(self):
        self.assertEqual(identity(ZEN), ("binary", "zen"))
        self.assertEqual(identity({"application.name": "Zen", "node.name": "x"}), ("app", "Zen"))
        self.assertEqual(identity({"node.name": "Some Node"}), ("app", "Some Node"))
        self.assertIsNone(identity({}))

    def test_is_known_counts_routes_and_ignore_list(self):
        routes = load_routes(self.routes)
        self.assertTrue(is_known(routes, {"application.process.binary": "spotify"}))
        self.assertTrue(is_known(routes, {"application.name": "WEBRTC VoiceEngine"}))
        self.assertTrue(is_known(routes, {"application.process.binary": "sd_dummy"}))
        self.assertFalse(is_known(routes, ZEN))

    def test_remember_writes_route_and_keeps_other_entries(self):
        remember(ZEN, "Browser_Audio", self.routes)
        with open(self.routes) as f:
            data = json.load(f)
        self.assertEqual(data["binary"], {"spotify": "Music_Audio", "zen": "Browser_Audio"})
        self.assertEqual(data["_comment"], "keep me")
        self.assertEqual(data["app"], {"WEBRTC VoiceEngine": "Discord_Audio"})

    def test_remember_ignore_adds_to_ignore_list_once(self):
        remember(ZEN, "__ignore__", self.routes)
        remember(ZEN, "__ignore__", self.routes)
        self.assertEqual(load_routes(self.routes)["ignore"], ["sd_dummy", "zen"])

    def test_route_now_moves_every_stream_then_recompiles(self):
        log = os.path.join(self.dir.name, "calls")
        bindir = os.path.join(self.dir.name, "bin")
        os.mkdir(bindir)
        for name, body in (("pactl", f'echo "pactl $*" >> {log}\ncase "$*" in *77*) exit 1;; esac\n'),
                           ("audio-routes-apply", f'echo "apply $*" >> {log}\n')):
            path = os.path.join(bindir, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        old = os.environ["PATH"]
        os.environ["PATH"] = bindir + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        route_now([12, 77, 13], "Browser_Audio", apply_cmd="audio-routes-apply")  # 77 has vanished
        with open(log) as f:
            self.assertEqual(f.read().splitlines(), [
                "pactl move-sink-input 12 Browser_Audio", "pactl move-sink-input 77 Browser_Audio",
                "pactl move-sink-input 13 Browser_Audio", "apply --no-restart"])


if __name__ == "__main__":
    unittest.main()
