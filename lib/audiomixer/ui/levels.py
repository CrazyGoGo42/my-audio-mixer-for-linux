"""
Live level meters for the window: one MeterReader per strip and per playing
app, running only while the window is shown (start/stop). Readers report from
their own threads; levels are applied to the widgets ~15 times a second on the
GTK main loop.
"""

import math

from gi.repository import GLib

from ..meters import MeterReader, meter_args, post_fader

FRAME_MS = 66
FLOOR_DB = -60.0


def meter_fraction(level):
    """Where a 0–1 peak sits on a meter scaled in decibels (-60 dB .. 0 dB), like
    a mixing desk: on a straight 0–1 bar, normal listening levels (often -40 dB
    and below after a channel's volume) would barely move it."""
    if level <= 0:
        return 0.0
    return max(0.0, min(1.0, (20 * math.log10(level) - FLOOR_DB) / -FLOOR_DB))


def strip_level(raw, live):
    """What a strip's meter shows: sinks after their volume, muted = 0."""
    if live is None or not live.present or live.muted:
        return 0.0
    return post_fader(raw, live.volume) if live.kind == "sink" else max(0.0, min(1.0, raw))


class Meters:
    def __init__(self, window, reader=MeterReader):
        self.window = window
        self.reader = reader
        self.readers = {}   # key -> reader; strips keyed by node name, apps by ("app", key)
        self.levels = {}    # key -> latest raw peak
        self.running = False
        self._frame_id = None
        window.controller.subscribe(self)

    def _want(self):
        want = {s.name: meter_args(s.name, s.kind) for s in self.window.strips}
        for app in self.window.controller.snapshot.apps:
            for index in app.indexes:  # every stream: often only one of them is playing
                want[("app", app.key, index)] = [f"--monitor-stream={index}"]
        return want

    def start(self):
        if self.running:
            return
        self.running = True
        self._sync()
        self._frame_id = GLib.timeout_add(FRAME_MS, self._frame)

    def stop(self):
        self.running = False
        if self._frame_id is not None:
            GLib.source_remove(self._frame_id)
            self._frame_id = None
        for reader in self.readers.values():
            reader.stop()
        self.readers, self.levels = {}, {}
        self._show({})

    def update(self, snapshot, status=None):
        """Called on every refresh: follow the app list (and changed stream ids)."""
        if self.running:
            self._sync()

    def _sync(self):
        want = self._want()
        for key in list(self.readers):
            if key not in want or self.readers[key].args != want[key]:
                self.readers.pop(key).stop()
                self.levels.pop(key, None)
        for key, args in want.items():
            if key not in self.readers:
                reader = self.reader(args, lambda level, k=key: self.levels.__setitem__(k, level))
                self.readers[key] = reader
                reader.start()

    def _frame(self):
        self._show(self.levels)
        return self.running

    def _show(self, levels):
        snapshot = self.window.controller.snapshot
        for strip in self.window.strips + getattr(self.window, "compact_strips", []):
            strip.set_level(meter_fraction(strip_level(levels.get(strip.name, 0.0),
                                                       snapshot.strips.get(strip.name))))
        for row in self.window.apps.rows:
            loudest = max((levels.get(("app", row.app.key, i), 0.0) for i in row.app.indexes), default=0.0)
            row.set_level(meter_fraction(loudest))
