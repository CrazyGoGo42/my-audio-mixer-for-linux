"""audio-channel-control (the bash script the hotkeys run), against a fake pactl."""

import os
import stat
import subprocess
import tempfile
import time
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "audio-channel-control")
CHANNELS = """\
default   Default_Audio   KP_1   KP_4   KP_7   Desktop
music     Music_Audio     KP_3   KP_6   KP_9   Music
"""


class ChannelControlTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        home = os.path.join(self.dir.name, "home")
        os.makedirs(os.path.join(home, ".config", "audio-mixer"))
        with open(os.path.join(home, ".config", "audio-mixer", "channels.conf"), "w") as f:
            f.write(CHANNELS)
        self.log = os.path.join(self.dir.name, "calls")
        self.osd = os.path.join(self.dir.name, "osd")
        bindir = os.path.join(self.dir.name, "bin")
        os.mkdir(bindir)
        with open(os.path.join(bindir, "pactl"), "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> {self.log}\n'
                    'case "$1" in\n'
                    '  get-*-volume) echo "Volume: front-left: 32768 /  50% / -18.06 dB";;\n'
                    '  get-*-mute) echo "Mute: no";;\n'
                    'esac\n')
        os.chmod(os.path.join(bindir, "pactl"), 0o755)
        self.env = dict(os.environ, HOME=home, PATH=bindir + os.pathsep + os.environ["PATH"],
                        AUDIO_OSD_FIFO=self.osd)

    def run_ctl(self, *args):
        r = subprocess.run([SCRIPT, *args], env=self.env, capture_output=True, text=True, timeout=10)
        try:
            with open(self.log) as f:
                calls = [c for c in f.read().splitlines() if c.startswith("set-")]
        except FileNotFoundError:
            calls = []
        return r.returncode, calls

    def test_channel_volume_still_works(self):
        self.assertEqual(self.run_ctl("music", "up")[1],
                         ["set-sink-mute Music_Audio 0", "set-sink-volume Music_Audio 51%"])

    def test_mic_up_never_unmutes(self):
        self.assertEqual(self.run_ctl("mic", "up")[1], ["set-source-volume Mic_In 51%"])

    def test_fx_and_all_use_their_nodes(self):
        self.assertEqual(self.run_ctl("fx", "down")[1],
                         ["set-sink-mute EE_Return 0", "set-sink-volume EE_Return 49%"])
        os.remove(self.log)
        self.assertEqual(self.run_ctl("all", "mute")[1], ["set-source-mute All_Audio toggle"])

    def test_slot_hotkey_toggles_and_shows_the_osd(self):
        mixer = os.path.join(self.dir.name, "bin", "audio-mixer")
        with open(mixer, "w") as f:
            f.write(f'#!/bin/sh\necho "mixer $*" >> {self.log}\necho "Music A2 on"\n')
        os.chmod(mixer, 0o755)
        self.env["AUDIO_MIXER"] = mixer
        self.assertEqual(self.run_ctl("music", "A2")[0], 0)
        with open(self.log) as f:
            self.assertIn("mixer out music A2 toggle", f.read())
        for _ in range(40):          # the OSD write is backgrounded
            if os.path.exists(self.osd) and os.path.getsize(self.osd):
                break
            time.sleep(0.05)
        with open(self.osd) as f:
            self.assertEqual(f.read().strip(), "Music A2 on")

    def test_unknown_target_does_nothing(self):
        code, calls = self.run_ctl("games", "up")
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
