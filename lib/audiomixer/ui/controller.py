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

from .. import apps, commands, easyeffects, hotkeys, live
from ..config import STATE_FILE, load_state, update_state
from ..meters import die_with_parent
from ..pwgraph import read_graph


def event_needs(line):
    """What a `pactl subscribe` line requires: None, "snapshot" (volumes, mutes,
    apps) or "status" (devices / default output changed: re-read the routing).

    Client and source-output events are ignored: every pactl run (ours, the
    daemon's) is a client and every meter is a source-output, so reacting to
    them made the window refresh itself in a loop."""
    if " on sink-input" in line:
        return "snapshot"
    if " on server" in line or " on card" in line:
        return "status"
    if " on sink " in line + " " or " on source " in line + " ":
        return "status" if ("'new'" in line or "'remove'" in line) else "snapshot"
    return None


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
                 remember=None, route_now=None, update_state=None,
                 load_hotkeys=None, save_hotkeys=None, apply_hotkeys=None, remove_hotkeys=None):
        self.channels = channels
        self._read_snapshot = read_snapshot or live.read_snapshot
        self._read_status = read_status or globals()["read_status"]
        self._run = run or _run
        self._run_command = run_command or commands.run
        self._remember = remember or apps.remember
        self._route_now = route_now or apps.route_now
        self._update_state = update_state or (lambda change: globals()["update_state"](self.channels, change))
        bin_dir = os.path.expanduser("~/.local/bin")
        self._load_hotkeys = load_hotkeys or (lambda: hotkeys.load(self.channels))
        self._save_hotkeys = save_hotkeys or hotkeys.save
        self._apply_hotkeys = apply_hotkeys or (
            lambda keys: hotkeys.apply_to_gnome(hotkeys.bindings(keys, bin_dir, self.channels)))
        self._remove_hotkeys = remove_hotkeys or hotkeys.remove_from_gnome
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
    def set_volume(self, name, kind, pct, unmute=True):
        self._run(["pactl", f"set-{kind}-volume", name, f"{int(round(pct))}%"])
        if unmute:
            self._run(["pactl", f"set-{kind}-mute", name, "0"])

    def set_eq(self, key, band, value):
        """Bass/Treble while dragging: save it and set just this channel's
        filter (one pw-cli) — no rewiring pass, no pw-dump."""
        try:
            state = self._update_state(
                lambda current: commands.apply_command(["eq", key, band, str(value)], self.channels, current))
        except (ValueError, OSError):
            return
        channel = next(c for c in self.channels if c.key == key)
        live = self.snapshot.strips.get(channel.sink)
        cs = state.channels[key]
        if live and live.node_id is not None:
            self._run(["pw-cli", "set-param", str(live.node_id), "Props",
                       f'{{ params = [ "bass:Gain" {float(cs.bass)} "treble:Gain" {float(cs.treble)} ] }}'])

    def set_mute(self, name, kind, on):
        """Absolute (never "toggle"), so a click can't undo a hotkey mute that
        landed just before the window caught up."""
        self._run(["pactl", f"set-{kind}-mute", name, "1" if on else "0"])

    def command(self, argv):
        """A routing change (fx/out/slot/eq/mic); the view updates from the
        refresh that follows, never optimistically."""
        try:
            self._run_command(argv)
        except ValueError:
            pass
        self.refresh(status_too=True)

    # --------------------------------------------------------------- hotkeys
    def hotkey_map(self):
        return self._load_hotkeys()

    def set_hotkey(self, action, accel):
        """Give `action` this combination (None clears it): saved and live at once."""
        keys = hotkeys.assign(self._load_hotkeys(), action, accel)
        self._save_hotkeys(keys)
        self._apply_hotkeys(keys)
        return keys

    def suspend_hotkeys(self):
        """While the user presses a new combination, GNOME must not grab it."""
        self._remove_hotkeys()

    def resume_hotkeys(self):
        self._apply_hotkeys(self._load_hotkeys())

    def confirm_app(self, row):
        """A NEW app is fine where it is: remember that, move nothing."""
        self._remember(row.props, row.sink)
        self.refresh()

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
                                             stderr=subprocess.DEVNULL, text=True,
                                             preexec_fn=die_with_parent)
            except OSError:
                return
            # (Re)connected — e.g. after a PipeWire restart: catch up on everything.
            GLib.idle_add(self.schedule_refresh, True)
            for line in self._sub.stdout:
                need = event_needs(line)
                if need:
                    GLib.idle_add(self.schedule_refresh, need == "status")
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
