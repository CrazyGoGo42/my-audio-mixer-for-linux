"""No scroll bars: the real window on a private Xvfb display (never the user's
screen), resized from roomy down to the smallest it allows. At every size it
must show the right layout and that layout must fit. Skipped without Xvfb and
xdotool."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")

def switch_over_sizes():
    """Window sizes just either side of every switch-over, plus the extremes.
    +10: on a bare X server the window keeps a 5 px border around its content."""
    from audiomixer.ui.layout import WIDE_LAYOUTS
    sizes = [(1400, 900)]
    for _, width, height in WIDE_LAYOUTS:
        sizes += [(width + 11, 900), (width + 10, 900), (1400, height + 11), (1400, height + 10),
                  (width + 11, height + 11)]   # the smallest a step is ever shown at
    return sizes + [(500, 700), (340, 380)]


def expected_layout(width, height):
    from audiomixer.ui.layout import WIDE_LAYOUTS
    # WIDE_LAYOUTS goes roomy -> tight; a step shows while the window is both
    # wider and taller than its smallest size.
    return next((name for name, w, h in WIDE_LAYOUTS if width > w and height > h), "compact")


def run_harness(sizes, tmp, shots=False):
    """Run sizes_harness on a fresh Xvfb; returns its JSON lines."""
    log = os.path.join(tmp, "log")
    read_fd, write_fd = os.pipe()
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1600x1000x24",
                             "-nolisten", "tcp"], pass_fds=(write_fd,),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.close(write_fd)
        display = ":" + os.read(read_fd, 16).decode().strip()
        os.close(read_fd)
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
        # No session bus: nothing reaches the user's desktop, and GTK doesn't
        # wait ~25 s for portals that a bare X server doesn't have.
        env.update(DISPLAY=display, GTK_A11Y="none", NO_AT_BRIDGE="1", GDK_DEBUG="no-portals",
                   DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent")
        args = ["python3", "-I", os.path.join(HERE, "sizes_harness.py"), log, LIB, ROOT, tmp,
                json.dumps(sizes)] + (["shots"] if shots else [])
        subprocess.run(args, env=env, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        xvfb.kill()
        xvfb.wait()
    with open(log) as f:
        return [json.loads(line) for line in f]


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("xdotool"), "needs Xvfb and xdotool")
class WindowSizesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.sizes = switch_over_sizes()
        cls.results = run_harness(cls.sizes, cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_size_was_tried(self):
        self.assertEqual([tuple(r["size"]) for r in self.results], self.sizes)
        self.assertEqual({r["layout"] for r in self.results}, {"roomy", "snug", "tight", "compact"})

    def test_each_size_shows_the_layout_meant_for_it(self):
        for r in self.results:
            with self.subTest(size=r["size"]):
                # Breakpoints go by the space the content gets (on a bare X
                # server the window keeps a small border around it).
                self.assertEqual(r["layout"], expected_layout(*r["given"]))

    def test_nothing_is_ever_cut_off(self):
        # The layout never needs more room than the window gives it, so there
        # is nothing to scroll to.
        for r in self.results:
            with self.subTest(size=r["size"], layout=r["layout"]):
                self.assertLessEqual(r["needs"][0], r["given"][0])
                self.assertLessEqual(r["needs"][1], r["given"][1])

    def test_the_wide_layout_gets_smaller_step_by_step(self):
        needs = {}
        for r in self.results:
            needs.setdefault(r["layout"], r["needs"][0])
        self.assertGreater(needs["roomy"], needs["snug"])
        self.assertGreater(needs["snug"], needs["tight"])


if __name__ == "__main__":
    unittest.main()
