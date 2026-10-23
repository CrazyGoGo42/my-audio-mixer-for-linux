"""One mixer strip: title, volume slider + meter, %, mute."""

import time

from gi.repository import GLib, Gtk

def guard_wheel(scale, owner):
    """A mouse wheel over an unfocused fader scrolls the window instead of
    changing a level (scrolling the list must never move, or unmute, anything)."""
    wheel = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
    wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    wheel.connect("scroll", lambda c, dx, dy: owner.on_scroll(c, dx, dy, scale))
    scale.add_controller(wheel)


SPECIAL_TARGETS = {"Mic_In": "mic", "EE_Return": "fx", "All_Audio": "all"}


# After the user touches a slider, live refreshes leave it alone this long, so
# the echo of their own (or an older) value can't yank it back mid-drag.
TOUCH_HOLD = 0.6
WRITE_DELAY_MS = 60  # coalesce slider writes while dragging


class StripWidget(Gtk.Box):
    """A strip: tall card (wide layout) or one slim row (compact layout). Both
    share the same slider/mute logic, so the two layouts can't disagree."""

    def __init__(self, controller, name, kind, title, compact=False):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL if compact else Gtk.Orientation.VERTICAL,
                         spacing=6)
        self.controller, self.name, self.kind, self.title = controller, name, kind, title
        self.touched_at = 0.0
        self._updating = False
        self._pending = None
        self._write_id = None

        self.heading = Gtk.Label(label=title)
        self.heading.add_css_class("heading")
        self.header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        # Strip-specific controls go above the fader (FX, Bass/Treble) and
        # below it (outputs); the compact layout doesn't show them.
        self.top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL if compact else Gtk.Orientation.VERTICAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("value-changed", self._on_value_changed)
        guard_wheel(self.scale, self)
        # A Mic level change never unmutes it (a muted mic must not go live by itself).
        self.unmute_on_change = name != "Mic_In"
        self.meter = Gtk.LevelBar()
        self.meter.set_min_value(0)
        self.meter.set_max_value(1)
        self.percent = Gtk.Label(label="—")
        self.percent.add_css_class("numeric")
        self.mute = Gtk.ToggleButton(label="Mute")
        self.mute.connect("toggled", self._on_mute_toggled)
        # Right-click a control to set its hotkey.
        self.target = SPECIAL_TARGETS.get(name) or next(
            (c.key for c in controller.channels if c.sink == name), name)
        self.right_click(self.mute, "mute")
        self.right_click(self.scale, "fader")
        if compact:
            self._build_compact()
        else:
            self._build_wide()

    def _build_wide(self):
        self.add_css_class("card")
        self.set_size_request(118, -1)
        self.heading.set_margin_top(10)
        self.header.append(self.heading)
        self.append(self.header)
        self.top.set_margin_start(8)
        self.top.set_margin_end(8)
        self.append(self.top)
        fader = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        fader.set_halign(Gtk.Align.CENTER)
        fader.set_vexpand(True)
        self.scale.set_inverted(True)
        self.scale.set_size_request(-1, 170)
        self.scale.set_vexpand(True)
        self.meter.set_orientation(Gtk.Orientation.VERTICAL)
        self.meter.set_inverted(True)
        self.meter.set_size_request(8, -1)
        fader.append(self.scale)
        fader.append(self.meter)
        self.append(fader)
        self.append(self.percent)
        self.mute.set_halign(Gtk.Align.CENTER)
        self.append(self.mute)
        self.bottom.set_margin_bottom(10)
        self.bottom.set_halign(Gtk.Align.CENTER)
        self.append(self.bottom)

    def _build_compact(self):
        self.heading.set_xalign(0)
        self.heading.set_width_chars(10)
        self.append(self.heading)
        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        middle.set_hexpand(True)
        middle.set_valign(Gtk.Align.CENTER)
        self.scale.set_hexpand(True)
        self.meter.set_size_request(-1, 4)
        middle.append(self.scale)
        middle.append(self.meter)
        self.append(middle)
        self.percent.set_width_chars(5)
        self.append(self.percent)
        self.mute.set_valign(Gtk.Align.CENTER)
        self.append(self.mute)

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
            self.controller.set_volume(self.name, self.kind, value, unmute=self.unmute_on_change)

    # -------------------------------------------------------------- hotkeys
    def hotkey_actions(self, control):
        """The hotkey actions behind a control: mute, fader (down + up) or a slot."""
        if control == "fader":
            return [f"{self.target}:down", f"{self.target}:up"]
        return [f"{self.target}:{control}"]

    def hotkey_popover(self, control):
        from .. import hotkeys
        from .hotkeys import HotkeyPopover
        labels = dict(hotkeys.actions(self.controller.channels))
        widget = {"mute": self.mute, "fader": self.scale}.get(control)
        if widget is None:
            widget = self.slot_toggles[int(control[1]) - 1]
        popover = HotkeyPopover(self.controller, [(a, labels.get(a, a)) for a in self.hotkey_actions(control)])
        popover.set_parent(widget)
        popover.connect("closed", lambda p: GLib.idle_add(lambda: p.unparent() or False))
        return popover

    def right_click(self, widget, control):
        """Right-click opens the hotkey popover. It runs before the widget's own
        handling and claims the click: otherwise a fader starts a drag on the
        press, the popover's grab swallows the release, and the volume keeps
        running on its own (seen in review)."""
        click = Gtk.GestureClick(button=3)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def pressed(gesture, *_):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.hotkey_popover(control).popup()
        click.connect("pressed", pressed)
        widget.add_controller(click)

    def on_scroll(self, _controller, _dx, dy, scale=None):
        scale = scale or self.scale
        if scale.has_focus():
            return False  # the user clicked it first: the wheel adjusts it
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is not None:
            adj = scrolled.get_vadjustment()
            adj.set_value(adj.get_value() + dy * 40)
        return True

    def _on_mute_toggled(self, button):
        if not self._updating:
            self.controller.set_mute(self.name, self.kind, button.get_active())


# --------------------------------------------------------------------------- #
# Strip types
# --------------------------------------------------------------------------- #

SLOTS = ("A1", "A2", "A3", "A4")
EQ_DELAY_MS = 250  # coalesce Bass/Treble writes while dragging


class MenuButton(Gtk.MenuButton):
    """A button with a plain list of choices; `items` = [(text, callback)]."""

    def __init__(self, label=""):
        super().__init__()
        self.items = []
        self._popover = Gtk.Popover()
        self.set_popover(self._popover)
        content = Gtk.Box(spacing=4)
        self._label = Gtk.Label(label=label)
        self._label.set_ellipsize(3)  # Pango.EllipsizeMode.END — long device names
        self._label.set_max_width_chars(30)
        content.append(self._label)
        content.append(Gtk.Image.new_from_icon_name("pan-down-symbolic"))
        self.set_child(content)

    def set_label(self, label):
        self._label.set_label(label)
        self.set_tooltip_text(label)

    def get_label(self):
        return self._label.get_label()

    def set_items(self, items):
        if [t for t, _ in items] == [t for t, _ in self.items]:
            self.items = items
            return
        self.items = items
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for text, callback in items:
            button = Gtk.Button(label=text)
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, cb=callback: (self._popover.popdown(), cb()))
            box.append(button)
        self._popover.set_child(box)


def _set_toggle(toggle, active):
    if toggle.get_active() != active:
        toggle.set_active(active)


class _SlotToggles(Gtk.Box):
    """A1–A4 toggle buttons; on_toggle(slot, on)."""

    def __init__(self, on_toggle):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.add_css_class("linked")
        self.toggles = []
        self._updating = False
        for slot in SLOTS:
            t = Gtk.ToggleButton(label=slot)
            t.connect("toggled", lambda b, s=slot: None if self._updating else on_toggle(s, b.get_active()))
            self.append(t)
            self.toggles.append(t)

    def show_active(self, active_slots):
        self._updating = True
        try:
            for slot, t in zip(SLOTS, self.toggles):
                _set_toggle(t, slot in active_slots)
        finally:
            self._updating = False


class ChannelStrip(StripWidget):
    """A channel: FX switch, Bass/Treble, and where it plays (A1–A4 or EasyEffects)."""

    def __init__(self, controller, channel):
        super().__init__(controller, channel.sink, "sink", channel.label)
        self.key = channel.key
        self._eq_pending = {}
        self._eq_id = None
        self._eq_touched_at = 0.0

        self.fx = Gtk.ToggleButton(label="FX")
        self.fx.set_tooltip_text("On: through EasyEffects. Off: plays dry on its own outputs.")
        self.fx.connect("toggled", self._on_fx)
        self.top.append(self.fx)
        self.bass = self._eq_scale("Bass")
        self.treble = self._eq_scale("Treble")

        self.where = Gtk.Stack()
        fx_label = Gtk.Label(label="→ EasyEffects")
        fx_label.add_css_class("dim-label")
        self.where.add_named(fx_label, "fx")
        self.slots = _SlotToggles(lambda slot, on: controller.command(
            ["out", self.key, slot, "on" if on else "off"]))
        self.slot_toggles = self.slots.toggles
        for slot, toggle in zip(SLOTS, self.slot_toggles):
            self.right_click(toggle, slot)
        self.where.add_named(self.slots, "slots")
        self.bottom.append(self.where)

    def _eq_scale(self, label):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        name = Gtk.Label(label=label)
        name.add_css_class("caption")
        name.set_width_chars(6)
        name.set_xalign(0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -12, 12, 0.5)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.add_mark(0, Gtk.PositionType.BOTTOM, None)
        scale.set_tooltip_text(f"{label}: 0 dB")
        scale.connect("value-changed", self._on_eq, label.lower())
        guard_wheel(scale, self)
        row.append(name)
        row.append(scale)
        self.top.append(row)
        return scale

    def update(self, live, status=None):
        super().update(live, status)
        cs = next((c for c in (status or {}).get("channels", []) if c["key"] == self.key), None)
        if cs is None:
            return
        self._updating = True
        try:
            _set_toggle(self.fx, cs["fx"])
            self.fx.set_label("FX on" if cs["fx"] else "FX off")
            if time.monotonic() - self._eq_touched_at > TOUCH_HOLD:
                for scale, value, name in ((self.bass, cs["bass"], "Bass"), (self.treble, cs["treble"], "Treble")):
                    scale.set_value(value)
                    scale.set_tooltip_text(f"{name}: {value:+.1f} dB")
            self.where.set_visible_child_name("fx" if cs["fx"] else "slots")
        finally:
            self._updating = False
        self.slots.show_active(cs["outputs"])

    def _on_fx(self, button):
        if not self._updating:
            self.controller.command(["fx", self.key, "on" if button.get_active() else "off"])

    def _on_eq(self, scale, band):
        if self._updating:
            return
        self._eq_touched_at = time.monotonic()
        self._eq_pending[band] = scale.get_value()
        scale.set_tooltip_text(f"{band.title()}: {scale.get_value():+.1f} dB")
        if self._eq_id is None:
            self._eq_id = GLib.timeout_add(EQ_DELAY_MS, self._eq_timeout)

    def _eq_timeout(self):
        self._eq_id = None
        self.flush_eq()
        return False

    def flush_eq(self):
        """Apply pending Bass/Treble changes now."""
        if self._eq_id is not None:
            GLib.source_remove(self._eq_id)
            self._eq_id = None
        pending, self._eq_pending = self._eq_pending, {}
        for band, value in pending.items():
            self.controller.set_eq(self.key, band, float(value))


class EasyEffectsStrip(StripWidget):
    """The EasyEffects output: its preset name and where it plays (A1–A4)."""

    def __init__(self, controller, name):
        super().__init__(controller, name, "sink", "EasyEffects")
        self.preset = Gtk.Label(label="")
        self.preset.add_css_class("caption")
        self.preset.add_css_class("dim-label")
        self.preset.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.preset.set_max_width_chars(14)
        self.header.append(self.preset)
        self.slots = _SlotToggles(lambda slot, on: controller.command(
            ["out", "fx", slot, "on" if on else "off"]))
        self.slot_toggles = self.slots.toggles
        for slot, toggle in zip(SLOTS, self.slot_toggles):
            self.right_click(toggle, slot)
        self.bottom.append(self.slots)

    def update(self, live, status=None):
        super().update(live, status)
        if status:
            self.preset.set_label(status.get("ee_preset") or "")
            self.slots.show_active(status.get("fx_outputs", []))


class MicStrip(StripWidget):
    """The mic: its title is a menu of real microphones (or Automatic)."""

    def __init__(self, controller, name):
        super().__init__(controller, name, "source", "Mic")
        self.heading.set_visible(False)
        self.menu = MenuButton("Mic")
        self.menu.set_margin_top(6)
        self.menu.set_halign(Gtk.Align.CENTER)
        self.menu.add_css_class("flat")
        self.header.prepend(self.menu)
        self.device = Gtk.Label(label="")
        self.device.add_css_class("caption")
        self.device.add_css_class("dim-label")
        self.device.set_ellipsize(3)
        self.device.set_max_width_chars(14)
        self.header.append(self.device)

    def update(self, live, status=None):
        super().update(live, status)
        if not status:
            return
        mics = [d for d in status.get("devices", []) if d["kind"] == "mic"]
        names = {d["name"]: d["description"] or d["name"] for d in mics}
        mic = status.get("mic", {})
        picked = names.get(mic.get("device"), mic.get("device") or "none")
        self.device.set_label(("Auto · " if mic.get("value") == "@auto" else "") + picked)
        self.device.set_tooltip_text(picked)
        self.menu.set_items([("Automatic", lambda: self.controller.command(["mic", "auto"]))]
                            + [(names[d["name"]], lambda n=d["name"]: self.controller.command(["mic", n]))
                               for d in mics])
