import os
import stat
import subprocess
import tempfile
import time
import unittest

from audiomixer import easyeffects
from audiomixer.easyeffects import launch, output_preset, point_at, point_at_mixer, set_devices

# The user's real easyeffectsrc on 2026-10-23 (EasyEffects 8.3.0).
REAL_RC = """\
[Presets]
lastLoadedInputPreset=Woman
lastLoadedOutputPreset=Bass Boosted

[Spectrum]
spectrumColorScheme=automatic
spectrumColorTheme=mixSeries
spectrumShape=lines

[StreamInputs]
inputDevice=alsa_output.pci-0000_00_1f.3.analog-surround-40
mostUsedPresets=Woman
plugins=pitch#0,equalizer#0,deesser#0,compressor#0,exciter#0
usedPresets=Woman:8
visiblePage=pluginsPage
visiblePlugin=pitch#0

[StreamOutputs]
mostUsedPresets=Bass Enhancing + Perfect EQ,Bass Boosted,Perfect EQ,Boosted,Laptop
outputDevice=alsa_output.pci-0000_00_1f.3.analog-surround-40
plugins=equalizer#0,convolver#0,bass_enhancer#0,crossfeed#0,maximizer#0
usedPresets=Bass Enhancing + Perfect EQ:40,Bass Boosted:26,Perfect EQ:3,Loudness+Autogain:1,Laptop:1,Boosted:1
visiblePage=pluginsPage
visiblePlugin=equalizer#0

[Window]
autostartOnLogin=true
height=779
lastLoadedOutputPreset=Bass Enhancing + Perfect EQ
width=1063
"""


def section(text, name):
    """{key: value} of one [section]."""
    out, inside = {}, False
    for line in text.splitlines():
        if line.startswith("["):
            inside = line == f"[{name}]"
        elif inside and "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


class SetDevicesTest(unittest.TestCase):
    def test_sets_both_devices_and_disables_follow_default(self):
        out = set_devices(REAL_RC, "Mic_In", "EE_Return")
        self.assertEqual(section(out, "StreamInputs")["inputDevice"], "Mic_In")
        self.assertEqual(section(out, "StreamInputs")["useDefaultInputDevice"], "false")
        self.assertEqual(section(out, "StreamOutputs")["outputDevice"], "EE_Return")
        self.assertEqual(section(out, "StreamOutputs")["useDefaultOutputDevice"], "false")

    def test_keeps_presets_and_plugin_order_untouched(self):
        out = set_devices(REAL_RC, "Mic_In", "EE_Return")
        changed = [l for l in out.splitlines() if l not in REAL_RC.splitlines()]
        self.assertEqual(sorted(changed), ["inputDevice=Mic_In", "outputDevice=EE_Return",
                                           "useDefaultInputDevice=false", "useDefaultOutputDevice=false"])
        for name in ("Presets", "Spectrum", "Window"):
            self.assertEqual(section(out, name), section(REAL_RC, name))
        self.assertEqual(section(out, "StreamOutputs")["plugins"],
                         "equalizer#0,convolver#0,bass_enhancer#0,crossfeed#0,maximizer#0")

    def test_adds_missing_keys_and_sections(self):
        out = set_devices("[Window]\nwidth=1\n", "Mic_In", "EE_Return")
        self.assertEqual(section(out, "Window"), {"width": "1"})
        self.assertEqual(section(out, "StreamInputs"), {"useDefaultInputDevice": "false", "inputDevice": "Mic_In"})
        self.assertEqual(section(out, "StreamOutputs"), {"useDefaultOutputDevice": "false", "outputDevice": "EE_Return"})

    def test_none_restores_follow_default(self):
        mixer = set_devices(REAL_RC, "Mic_In", "EE_Return")
        out = set_devices(mixer, None, None)
        self.assertEqual(section(out, "StreamInputs")["useDefaultInputDevice"], "true")
        self.assertEqual(section(out, "StreamOutputs")["useDefaultOutputDevice"], "true")

    def test_already_set_is_unchanged(self):
        once = set_devices(REAL_RC, "Mic_In", "EE_Return")
        self.assertEqual(set_devices(once, "Mic_In", "EE_Return"), once)


class OutputPresetTest(unittest.TestCase):
    def test_reads_last_loaded_output_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = os.path.join(tmp, "easyeffectsrc")
            with open(rc, "w") as f:
                f.write(REAL_RC)
            self.assertEqual(output_preset(rc), "Bass Boosted")
            self.assertIsNone(output_preset(os.path.join(tmp, "missing")))


class _FakeCommandsBase(unittest.TestCase):
    """Real code, fake flatpak/pgrep/pkill on PATH that record their arguments."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.log = os.path.join(self.dir.name, "calls")
        self.running_flag = os.path.join(self.dir.name, "running")
        bindir = os.path.join(self.dir.name, "bin")
        os.mkdir(bindir)
        scripts = {
            # -q makes the fake EasyEffects exit (pgrep stops finding it)
            "flatpak": f'echo "flatpak $*" >> {self.log}\ncase "$*" in *" -q"*) rm -f {self.running_flag};; esac\n',
            "pkill": f'echo "pkill $*" >> {self.log}\n',
            "pgrep": f'[ -e {self.running_flag} ]\n',
        }
        for name, body in scripts.items():
            path = os.path.join(bindir, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        old = os.environ["PATH"]
        os.environ["PATH"] = bindir + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        self.rc = os.path.join(self.dir.name, "easyeffectsrc")
        with open(self.rc, "w") as f:
            f.write(REAL_RC)
        self.lockdir = os.path.join(self.dir.name, "lock")
        os.mkdir(self.lockdir)

    def calls(self, expect=0):
        """Recorded calls; waits (up to 3 s) for `expect` of them — launch() detaches."""
        deadline = time.time() + 3
        while True:
            try:
                with open(self.log) as f:
                    lines = f.read().splitlines()
            except OSError:
                lines = []
            if len(lines) >= expect or time.time() > deadline:
                return lines
            time.sleep(0.05)

class FakeCommandsTest(_FakeCommandsBase):
    def test_launch_clears_stale_lock_and_starts_service_mode(self):
        for name in ("EasyEffectsServer", "easyeffects.lock"):
            open(os.path.join(self.lockdir, name), "w").close()
        launch(lockdir=self.lockdir)
        self.assertEqual(os.listdir(self.lockdir), [])
        self.assertEqual(self.calls(expect=1), ["flatpak run com.github.wwmm.easyeffects --service-mode --hide-window"])

    def test_point_at_mixer_rewrites_rc_once_when_not_running(self):
        self.assertTrue(point_at_mixer(rc_file=self.rc, lockdir=self.lockdir))
        with open(self.rc) as f:
            self.assertEqual(section(f.read(), "StreamInputs")["inputDevice"], "Mic_In")
        self.assertEqual(self.calls(), [])  # not running: no quit, no launch
        self.assertFalse(point_at_mixer(rc_file=self.rc, lockdir=self.lockdir))

    def test_point_at_mixer_quits_and_relaunches_a_running_easyeffects(self):
        open(self.running_flag, "w").close()
        self.assertTrue(point_at_mixer(rc_file=self.rc, lockdir=self.lockdir))
        self.assertEqual(self.calls(expect=2), ["flatpak run com.github.wwmm.easyeffects -q",
                                        "flatpak run com.github.wwmm.easyeffects --service-mode --hide-window"])


class StopBeforeWriteTest(_FakeCommandsBase):
    """A fake EasyEffects that, like the real one, takes a moment to exit after
    -q and writes its own settings back as it goes. Writing ours before it is
    really gone gets them overwritten (review I2)."""

    def setUp(self):
        super().setUp()
        bindir = os.path.join(self.dir.name, "bin")
        self.pidfile = os.path.join(self.dir.name, "ee.pid")
        snapshot = os.path.join(self.dir.name, "ee-memory")
        with open(snapshot, "w") as f:
            f.write(REAL_RC)   # what the running instance will write back on exit
        # Detached (not our child), so once killed it's really gone instead of
        # lingering as a zombie that `kill -0` still reports alive.
        subprocess.run(["sh", "-c", f"sleep 30 >/dev/null 2>&1 & echo $! > {self.pidfile}"])
        with open(self.pidfile) as f:
            ee_pid = int(f.read())
        self.addCleanup(lambda: subprocess.run(["kill", str(ee_pid)], capture_output=True))
        scripts = {
            "pgrep": f'kill -0 $(cat {self.pidfile}) 2>/dev/null\n',
            # -q: exit after exit_delay s, writing settings back first. The
            # helper stops early once the fake is gone (killed), so it never
            # outlives the test.
            "flatpak": (f'echo "flatpak $*" >> {self.log}\n'
                        f'case "$*" in *" -q"*)\n'
                        f'  ( i=0; while [ $i -lt {int(self.exit_delay * 10)} ]; do '
                        f'kill -0 $(cat {self.pidfile}) 2>/dev/null || exit 0; sleep 0.1; i=$((i+1)); done; '
                        f'cp {snapshot} {self.rc}; kill $(cat {self.pidfile}) ) >/dev/null 2>&1 &\n;; esac\n'),
            "pkill": (f'echo "pkill $*" >> {self.log}\n'
                      f'cp {snapshot} {self.rc}; kill $(cat {self.pidfile})\n'),
        }
        for name, body in scripts.items():
            path = os.path.join(bindir, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    exit_delay = 1.5

    def rc_input_device(self):
        """inputDevice once the fake EasyEffects has gone (and written back)."""
        with open(self.pidfile) as f:
            pid = int(f.read())
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)
        time.sleep(0.2)
        with open(self.rc) as f:
            return section(f.read(), "StreamInputs")["inputDevice"]

    def test_waits_for_easyeffects_to_exit_before_writing(self):
        self.assertTrue(point_at_mixer(rc_file=self.rc, lockdir=self.lockdir))
        self.assertEqual(self.rc_input_device(), "Mic_In")
        self.assertEqual(self.calls(expect=2), ["flatpak run com.github.wwmm.easyeffects -q",
                                                "flatpak run com.github.wwmm.easyeffects --service-mode --hide-window"])


class StubbornEasyEffectsTest(StopBeforeWriteTest):
    exit_delay = 1000  # -q never gets it to exit

    def test_waits_for_easyeffects_to_exit_before_writing(self):
        pass  # covered above

    def test_kills_easyeffects_that_will_not_quit(self):
        point_at(easyeffects.MIC_IN, easyeffects.EE_RETURN, rc_file=self.rc, lockdir=self.lockdir,
                 quit_timeout=0.5)
        self.assertIn("pkill -f easyeffects --service-mode", self.calls(expect=3))
        self.assertEqual(self.rc_input_device(), "Mic_In")


if __name__ == "__main__":
    unittest.main()
