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
from .. import micfx
from ..config import MIC_IN, STATE_FILE, load_state, rename_channel, update_state
from ..meters import die_with_parent
from ..pwgraph import read_graph
from ..reconcile import eq_params


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
    mic_filter = graph.nodes.get(MIC_IN + "_in")   # where the mic's controls live
    st["mic_fx_node"] = mic_filter.id if mic_filter else None
    return st


def _run(argv):
    try:
        subprocess.run(argv, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def _spawn(argv, done=None):
    """Run a tool without waiting for it (restarts take seconds); done(code,
    stderr) is called on the main loop when it ends. Its own session, so
    closing the window doesn't cut a restart short."""
    def finish(code, err):
        if done:
            GLib.idle_add(lambda: done(code, err) and False)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as e:
        finish(127, str(e))
        return

    def wait():
        _, err = proc.communicate()
        finish(proc.returncode, err)
    threading.Thread(target=wait, daemon=True).start()


class Controller:
    def __init__(self, channels, read_snapshot=None, read_status=None, run=None, run_command=None,
                 remember=None, route_now=None, update_state=None,
                 load_hotkeys=None, save_hotkeys=None, apply_hotkeys=None, remove_hotkeys=None,
                 hotkeys_suspended=None, spawn=None, rename=None):
        self.channels = channels
        self._read_snapshot = read_snapshot or live.read_snapshot
        self._read_status = read_status or globals()["read_status"]
        self._run = run or _run
        self._run_command = run_command or commands.run
        self._remember = remember or apps.remember
        self._route_now = route_now or apps.route_now
        self._update_state = update_state or (lambda change: globals()["update_state"](self.channels, change))
        self._spawn = spawn or _spawn
        self._rename = rename or rename_channel
        self._bin_dir = bin_dir = os.path.expanduser("~/.local/bin")
        self._load_hotkeys = load_hotkeys or (lambda: hotkeys.load(self.channels))
        self._save_hotkeys = save_hotkeys or hotkeys.save
        self._apply_hotkeys = apply_hotkeys or (
            lambda keys: hotkeys.resume(hotkeys.bindings(keys, bin_dir, self.channels)))
        self._remove_hotkeys = remove_hotkeys or hotkeys.suspend
        self._hotkeys_suspended = hotkeys_suspended or hotkeys.suspended
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
        """Bass/Mid/Treble while dragging: save it and set just this channel's
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
            self._run(["pw-cli", "set-param", str(live.node_id), "Props", eq_params(cs)])

    def set_mic_fx(self, **changes):
        """The Mic strip's Color Panel and Comp/Gate while you move them: saved,
        and set live on the mic's filter (one pw-cli) — no rewiring, no pw-dump."""
        try:
            state = self._update_state(lambda current: commands.with_mic_fx(current, **changes))
        except (ValueError, OSError):
            return
        node = (self.status or {}).get("mic_fx_node")
        if node is not None:
            self._run(["pw-cli", "set-param", str(node), "Props", micfx.props(state.mic_fx)])

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

    def rename_channel(self, key, label):
        """Give a channel a new name (ValueError says why one can't be used).
        The views retitle, GNOME's shortcut names follow, and the device name
        other apps see is written for the next engine start. Returns the old name."""
        old = next(c.label for c in self.channels if c.key == key)
        self.channels = self._rename(key, label)
        self._try(self.resume_hotkeys)
        self._spawn([os.path.join(self._bin_dir, "audio-routes-apply"), "--no-restart"])
        for view in list(self.views):
            if hasattr(view, "retitle"):
                view.retitle()
        return old

    def restart(self, what, done):
        """Restart "easyeffects" or the whole audio "engine" in the background;
        done(code, stderr) when it's over. The live updates reconnect by
        themselves after PipeWire comes back."""
        self._spawn([os.path.join(self._bin_dir, "audio-mixer"), "restart", what], done)

    def open_easyeffects(self):
        """Show EasyEffects' own window (presets, effects)."""
        self._spawn(["flatpak", "run", easyeffects.APP])

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

    def heal_hotkeys(self):
        """Put our shortcuts back if a capture never finished (this window is
        stopping mid-capture, or an earlier one died)."""
        if self._hotkeys_suspended():
            self.resume_hotkeys()

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

    @staticmethod
    def _try(fn):
        try:
            fn()
        except RuntimeError:  # dconf unreachable: the daemon heals later
            pass

    # ---------------------------------------------------------- live updates
    def start(self):
        self._try(self.heal_hotkeys)
        threading.Thread(target=self._events, daemon=True).start()
        GLib.timeout_add_seconds(1, self._check_state_file)

    def stop(self):
        self._try(self.heal_hotkeys)
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
