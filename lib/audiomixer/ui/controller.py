"""
The mixer window's controller: reads the live state, tells the views, and is
the only thing that writes. Views never cache values — every refresh shows
what PipeWire/pactl says now, and writes happen only on the user's action.

Live updates: a `pactl subscribe` thread turns events into a debounced
refresh (80 ms); "new"/"remove" events and mixer.json changes also re-read the
routing status (pw-dump), which plain volume changes don't need.
"""

import os
import subprocess
import threading
import time

from gi.repository import GLib

from .. import apps, commands, easyeffects, live
from ..config import STATE_FILE, load_state
from ..pwgraph import read_graph


def read_status(channels):
    """Routing status for the views: commands.status_dict plus the device
    menus and the EasyEffects output preset name."""
    graph = read_graph()
    st = commands.status_dict(channels, load_state(channels), graph)
    st["devices"] = commands.devices_list(channels, graph)
    st["ee_preset"] = easyeffects.output_preset()
    return st


def _run(argv):
    try:
        subprocess.run(argv, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


class Controller:
    def __init__(self, channels, read_snapshot=None, read_status=None, run=None, run_command=None,
                 remember=None, route_now=None):
        self.channels = channels
        self._read_snapshot = read_snapshot or live.read_snapshot
        self._read_status = read_status or globals()["read_status"]
        self._run = run or _run
        self._run_command = run_command or commands.run
        self._remember = remember or apps.remember
        self._route_now = route_now or apps.route_now
        self.snapshot = live.Snapshot()
        self.status = None
        self.views = []
        self._refresh_id = None
        self._status_due = False
        self._stopping = False
        self._sub = None
        self._state_mtime = None

    def subscribe(self, view):
        self.views.append(view)

    # ---------------------------------------------------------------- reads
    def refresh(self, status_too=False):
        try:
            self.snapshot = self._read_snapshot(self.channels)
        except Exception:  # noqa: BLE001 — keep the window alive through PipeWire restarts
            pass
        if status_too or self.status is None:
            try:
                self.status = self._read_status(self.channels)
            except Exception:  # noqa: BLE001
                pass
        for view in list(self.views):
            view.update(self.snapshot, self.status)

    # ---------------------------------------------------------------- writes
    def set_volume(self, name, kind, pct):
        self._run(["pactl", f"set-{kind}-volume", name, f"{int(round(pct))}%"])
        self._run(["pactl", f"set-{kind}-mute", name, "0"])

    def toggle_mute(self, name, kind):
        self._run(["pactl", f"set-{kind}-mute", name, "toggle"])

    def command(self, argv):
        """A routing change (fx/out/slot/eq/mic); the view updates from the
        refresh that follows, never optimistically."""
        try:
            self._run_command(argv)
        except ValueError:
            pass
        self.refresh(status_too=True)

    def move_app(self, row, sink):
        """Put an app on a channel: remember it first (so it's born there next
        time even if the stream is already gone), then move what's playing."""
        self._remember(row.props, sink)
        try:
            self._route_now(row.indexes, sink)
        except Exception:  # noqa: BLE001 — a vanished stream must not break the window
            pass
        self.refresh()

    # ---------------------------------------------------------- live updates
    def start(self):
        threading.Thread(target=self._events, daemon=True).start()
        GLib.timeout_add_seconds(1, self._check_state_file)

    def stop(self):
        self._stopping = True
        if self._sub and self._sub.poll() is None:
            self._sub.kill()

    def _events(self):
        while not self._stopping:
            try:
                self._sub = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, text=True)
            except OSError:
                return
            for line in self._sub.stdout:
                GLib.idle_add(self.schedule_refresh, "'new'" in line or "'remove'" in line)
            self._sub.wait()
            time.sleep(1)  # pulse restarted: reconnect

    def schedule_refresh(self, status_too=False):
        self._status_due = self._status_due or status_too
        if self._refresh_id is None:
            self._refresh_id = GLib.timeout_add(80, self._scheduled_refresh)
        return False

    def _scheduled_refresh(self):
        self._refresh_id = None
        status_too, self._status_due = self._status_due, False
        self.refresh(status_too=status_too)
        return False

    def _check_state_file(self):
        try:
            mtime = os.path.getmtime(STATE_FILE)
        except OSError:
            mtime = None
        if self._state_mtime is not None and mtime != self._state_mtime:
            self.schedule_refresh(status_too=True)
        self._state_mtime = mtime
        return not self._stopping
