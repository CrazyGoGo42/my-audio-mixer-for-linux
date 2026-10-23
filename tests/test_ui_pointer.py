"""Real pointer events on a private Xvfb display (never the user's screen).
Skipped when Xvfb, xdotool or dbus-run-session are missing."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
TOOLS = ("Xvfb", "xdotool")


@unittest.skipUnless(all(shutil.which(t) for t in TOOLS), "needs Xvfb and xdotool")
class RightClickTest(unittest.TestCase):
    def xvfb(self):
        """A private X server for this test; returns the environment to run on it."""
        read_fd, write_fd = os.pipe()
        xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "800x600x24",
                                 "-nolisten", "tcp"], pass_fds=(write_fd,),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (xvfb.kill(), xvfb.wait()))
        os.close(write_fd)
        display = ":" + os.read(read_fd, 16).decode().strip()
        os.close(read_fd)
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
        # No session bus: nothing reaches the user's desktop, and GTK doesn't
        # wait ~25 s for portals that a bare X server doesn't have.
        env.update(DISPLAY=display, GTK_A11Y="none", NO_AT_BRIDGE="1", GDK_DEBUG="no-portals",
                   DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent")
        return env

    def test_right_click_on_a_fader_opens_hotkeys_and_leaves_the_volume_alone(self):
        # Seen in review: the fader started a drag on the press, the popover's
        # grab swallowed the release, and the volume ran away on its own.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log = os.path.join(tmp.name, "log")
        env = self.xvfb()
        app = subprocess.Popen(["python3", "-I",
                                os.path.join(HERE, "rightclick_harness.py"), log, LIB, "5"],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: app.poll() is None and app.kill())

        def lines():
            try:
                with open(log) as f:
                    return f.read().splitlines()
            except FileNotFoundError:
                return []
        deadline = time.monotonic() + 15
        while not any(l.startswith("CLICK") for l in lines()) and time.monotonic() < deadline:
            time.sleep(0.1)
        _, x, y = next(l for l in lines() if l.startswith("CLICK")).split()
        subprocess.run(["xdotool", "mousemove", x, y, "click", "3"], env=env, check=True)
        time.sleep(1.5)
        subprocess.run(["xdotool", "key", "Escape"], env=env, check=True)
        app.wait(timeout=20)
        out = lines()
        self.assertIn("POPOVER fader", out)
        self.assertEqual([l for l in out if l.startswith("SET_VOLUME")], [])


    def test_double_click_puts_the_color_panel_and_a_knob_exactly_back(self):
        # Seen live: the second press of a double-click also started a drag and
        # moved the square to the pointer (x = -0.01, still lit as "on").
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log = os.path.join(tmp.name, "log")
        env = self.xvfb()
        app = subprocess.Popen(["python3", "-I", os.path.join(HERE, "doubleclick_harness.py"), log, LIB, "5"],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: app.poll() is None and app.kill())

        def lines():
            try:
                with open(log) as f:
                    return f.read().splitlines()
            except FileNotFoundError:
                return []
        deadline = time.monotonic() + 15
        while not any(l.startswith("KNOB") for l in lines()) and time.monotonic() < deadline:
            time.sleep(0.1)
        for target in ("PANEL", "KNOB"):
            _, x, y = next(l for l in lines() if l.startswith(target)).split()
            subprocess.run(["xdotool", "mousemove", x, y, "click", "--repeat", "2", "--delay", "90", "1"],
                           env=env, check=True)
            time.sleep(0.5)
        app.wait(timeout=20)
        _, x, y, k = next(l for l in lines() if l.startswith("VALUES")).split()
        self.assertEqual((float(x), float(y), float(k)), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
