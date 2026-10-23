import array
import os
import stat
import tempfile
import threading
import unittest

from audiomixer.meters import MeterReader, meter_args, peak, post_fader


class PeakTest(unittest.TestCase):
    def test_peak_of_known_samples(self):
        self.assertEqual(peak(array.array("h", [0, 16384, -32768, 0]).tobytes()), 1.0)
        self.assertEqual(peak(array.array("h", [0, 16384, -100, 0]).tobytes()), 0.5)

    def test_silence_is_zero(self):
        self.assertEqual(peak(bytes(800)), 0.0)
        self.assertEqual(peak(b""), 0.0)

    def test_odd_trailing_byte_is_ignored(self):
        self.assertEqual(peak(array.array("h", [16384]).tobytes() + b"\x7f"), 0.5)

    def test_post_fader_is_cubic(self):
        self.assertEqual(post_fader(1.0, 50), 0.125)
        self.assertEqual(post_fader(0.5, 100), 0.5)
        self.assertEqual(post_fader(1.0, 150), 1.0)  # clamped
        self.assertEqual(post_fader(1.0, 0), 0.0)

    def test_meter_args(self):
        self.assertEqual(meter_args("Music_Audio", "sink"), ["--device=Music_Audio.monitor"])
        self.assertEqual(meter_args("Mic_In", "source"), ["--device=Mic_In"])


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        fake = os.path.join(self.dir.name, "parec")
        with open(fake, "w") as f:  # streams loud samples forever, like a live monitor
            f.write("#!/bin/sh\nexec python3 -c \"import sys\nwhile True: sys.stdout.buffer.write(b'\\\\x00\\\\x40' * 400)\"\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        old = os.environ["PATH"]
        os.environ["PATH"] = self.dir.name + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))

    def test_reader_reports_levels_and_stop_kills_process(self):
        got = threading.Event()
        levels = []

        def on_level(level):
            levels.append(level)
            got.set()
        reader = MeterReader(["--device=X.monitor"], on_level)
        reader.start()
        self.assertTrue(got.wait(3))
        self.assertEqual(levels[0], 0.5)  # 0x4000 = 16384
        pid = reader.process.pid
        reader.stop()
        self.assertFalse(reader.is_alive())
        self.assertIsNotNone(reader.process.poll())
        with self.assertRaises(OSError):
            os.kill(pid, 0)

    def test_idle_meter_process_dies_with_a_killed_window(self):
        # Seen live: a meter whose stream had vanished never wrote, so no broken
        # pipe ever killed it — it outlived its window at 16% CPU.
        import signal
        import subprocess
        import sys
        import time
        fake = os.path.join(self.dir.name, "parec")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\nexec sleep 60\n")
        lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
        child = subprocess.Popen([sys.executable, "-c", (
            f"import sys, time; sys.path.insert(0, {lib!r}); sys.dont_write_bytecode = True\n"
            "from audiomixer.meters import MeterReader\n"
            "r = MeterReader(['--device=X.monitor'], lambda level: None); r.start()\n"
            "time.sleep(1); print(r.process.pid, flush=True); time.sleep(60)")],
            stdout=subprocess.PIPE, text=True)
        parec_pid = int(child.stdout.readline())
        os.kill(child.pid, signal.SIGKILL)
        child.wait()
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                os.kill(parec_pid, 0)
            except OSError:
                break
            time.sleep(0.05)
        alive = True
        try:
            os.kill(parec_pid, 0)
        except OSError:
            alive = False
        if alive:
            os.kill(parec_pid, signal.SIGKILL)
        self.assertFalse(alive, "meter outlived its window")

    def test_reader_reports_silence_when_parec_exits(self):
        # A meter whose parec died (pulse restarted) must drop to 0, not freeze.
        fake = os.path.join(self.dir.name, "parec")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\nprintf '\\000\\100\\000\\100'\n")
        levels = []
        reader = MeterReader(["--device=X.monitor"], levels.append)
        reader.start()
        reader.join(3)
        self.assertEqual(levels[-1], 0.0)

    def test_stop_before_start_leaves_nothing_running(self):
        reader = MeterReader(["--device=X.monitor"], lambda level: None)
        reader.stop()
        reader.start()
        reader.join(3)
        self.assertFalse(reader.is_alive())
        self.assertTrue(reader.process is None or reader.process.poll() is not None)


    def test_meter_process_dies_with_a_killed_window(self):
        # A window that's killed (or crashes) can't stop its meters: they must
        # not live on as orphans reading monitors forever.
        import signal
        import subprocess
        import sys
        import time
        lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
        child = subprocess.Popen([sys.executable, "-c", (
            f"import sys, time; sys.path.insert(0, {lib!r}); sys.dont_write_bytecode = True\n"
            "from audiomixer.meters import MeterReader\n"
            "r = MeterReader(['--device=X.monitor'], lambda level: None); r.start()\n"
            "time.sleep(1); print(r.process.pid, flush=True); time.sleep(60)")],
            stdout=subprocess.PIPE, text=True)
        parec_pid = int(child.stdout.readline())
        os.kill(child.pid, signal.SIGKILL)
        child.wait()
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                os.kill(parec_pid, 0)
            except OSError:
                break
            time.sleep(0.05)
        with self.assertRaises(OSError):
            os.kill(parec_pid, 0)


if __name__ == "__main__":
    unittest.main()
