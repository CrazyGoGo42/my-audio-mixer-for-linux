"""One mixer strip: title, volume slider + meter, %, mute."""

import time

from gi.repository import GLib, Gtk

# After the user touches a slider, live refreshes leave it alone this long, so
# the echo of their own (or an older) value can't yank it back mid-drag.
TOUCH_HOLD = 0.6
WRITE_DELAY_MS = 60  # coalesce slider writes while dragging


class StripWidget(Gtk.Box):
    def __init__(self, controller, name, kind, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.controller, self.name, self.kind, self.title = controller, name, kind, title
        self.add_css_class("card")
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(0)
        self.set_size_request(118, -1)
        self.touched_at = 0.0
        self._updating = False
        self._pending = None
        self._write_id = None

        heading = Gtk.Label(label=title)
        heading.add_css_class("heading")
        heading.set_margin_top(10)
        self.header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.header.append(heading)
        self.heading = heading
        self.append(self.header)

        # Room for strip-specific controls above the fader (FX, Bass/Treble).
        self.top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.top.set_margin_start(8)
        self.top.set_margin_end(8)
        self.append(self.top)

        fader = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        fader.set_halign(Gtk.Align.CENTER)
        fader.set_vexpand(True)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1)
        self.scale.set_inverted(True)
        self.scale.set_draw_value(False)
        self.scale.set_size_request(-1, 170)
        self.scale.set_vexpand(True)
        self.scale.connect("value-changed", self._on_value_changed)
        self.meter = Gtk.LevelBar(orientation=Gtk.Orientation.VERTICAL)
        self.meter.set_inverted(True)
        self.meter.set_min_value(0)
        self.meter.set_max_value(1)
        self.meter.set_size_request(8, -1)
        fader.append(self.scale)
        fader.append(self.meter)
        self.append(fader)

        self.percent = Gtk.Label(label="—")
        self.percent.add_css_class("numeric")
        self.append(self.percent)

        self.mute = Gtk.ToggleButton(label="Mute")
        self.mute.set_halign(Gtk.Align.CENTER)
        self.mute.connect("toggled", self._on_mute_toggled)
        self.append(self.mute)

        # Room below (output slot toggles / where it plays).
        self.bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.bottom.set_margin_bottom(10)
        self.bottom.set_halign(Gtk.Align.CENTER)
        self.append(self.bottom)

    # ----------------------------------------------------------------- live
    def update(self, live, status=None):
        self._updating = True
        try:
            present = bool(live and live.present)
            for w in (self.scale, self.mute):
                w.set_sensitive(present)
            if not present:
                self.percent.set_label("—")
                return
            if time.monotonic() - self.touched_at > TOUCH_HOLD:
                self.scale.set_value(min(live.volume, 100))
                self.percent.set_label(f"{live.volume}%")
            self.mute.set_active(live.muted)
            self.mute.set_label("Muted" if live.muted else "Mute")
            if live.muted:
                self.mute.add_css_class("destructive-action")
            else:
                self.mute.remove_css_class("destructive-action")
        finally:
            self._updating = False

    def set_level(self, level):
        self.meter.set_value(max(0.0, min(1.0, level)))

    # ---------------------------------------------------------------- input
    def _on_value_changed(self, scale):
        if self._updating:
            return
        self.touched_at = time.monotonic()
        self._pending = scale.get_value()
        self.percent.set_label(f"{int(round(self._pending))}%")
        if self._write_id is None:
            self._write_id = GLib.timeout_add(WRITE_DELAY_MS, self._write_timeout)

    def _write_timeout(self):
        self._write_id = None
        self.flush()
        return False

    def flush(self):
        """Write the slider's pending value now."""
        if self._write_id is not None:
            GLib.source_remove(self._write_id)
            self._write_id = None
        if self._pending is not None:
            value, self._pending = self._pending, None
            self.controller.set_volume(self.name, self.kind, value)

    def _on_mute_toggled(self, button):
        if not self._updating:
            self.controller.toggle_mute(self.name, self.kind)
