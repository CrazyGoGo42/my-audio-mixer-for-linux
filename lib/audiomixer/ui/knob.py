"""A round knob for Bass/Treble, VoiceMeeter style: drag up/down to turn it,
double-click for flat (0 dB), arrow keys or the wheel (once clicked) for
half-dB steps. Speaks Gtk.Range's language — get_value / set_value and a
"value-changed" signal — so the strip code didn't change."""

import math

import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import GObject, Gtk, PangoCairo  # noqa: E402
from gi.repository import Gdk  # noqa: E402  (after Gtk: the GTK 4 one)

DRAG_PIXELS = 160          # a drag this long sweeps the whole range
START, SWEEP = 0.75 * math.pi, 1.5 * math.pi   # 7:30 round to 4:30, like a real knob


def value_text(value):
    return "0" if value == 0 else f"{value:+g}"


class Knob(Gtk.DrawingArea):
    __gsignals__ = {"value-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, lower=-12.0, upper=12.0, step=0.5):
        super().__init__(accessible_role=Gtk.AccessibleRole.SLIDER, focusable=True)
        self.lower, self.upper, self.step_size = float(lower), float(upper), float(step)
        self._value = 0.0
        self._drag_from = 0.0
        self.add_css_class("knob")
        self.set_draw_func(self._draw)
        self.set_cursor_from_name("ns-resize")

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda *_: self.drag_begin())
        drag.connect("drag-update", lambda _g, dx, dy: self.drag_update(dx, dy))
        self.add_controller(drag)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, n, *_: self.reset() if n == 2 else None)
        self.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        wheel = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        wheel.connect("scroll", self._on_wheel)
        self.add_controller(wheel)
        self._update_accessible()

    # ----------------------------------------------------------------- value
    def get_value(self):
        return self._value

    def set_value(self, value):
        value = round(float(value) / self.step_size) * self.step_size
        value = max(self.lower, min(self.upper, value)) + 0.0   # no "-0"
        if value == self._value:
            return
        self._value = value
        self._update_accessible()
        self.queue_draw()
        self.emit("value-changed")

    def reset(self):
        self.set_value(0)

    def step(self, steps):
        self.set_value(self._value + steps * self.step_size)

    def drag_begin(self):
        self.grab_focus()
        self._drag_from = self._value

    def drag_update(self, dx, dy):
        span = self.upper - self.lower
        self.set_value(self._drag_from + (dx - dy) * span / DRAG_PIXELS)

    def _on_key(self, _ctl, keyval, _code, _state):
        steps = {Gdk.KEY_Up: 1, Gdk.KEY_Right: 1, Gdk.KEY_Down: -1, Gdk.KEY_Left: -1,
                 Gdk.KEY_Page_Up: 4, Gdk.KEY_Page_Down: -4}.get(keyval)
        if steps:
            self.step(steps)
        elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0, Gdk.KEY_Home):
            self.reset()
        else:
            return False
        return True

    def _on_wheel(self, _ctl, _dx, dy):
        # Like the faders: the wheel turns it only once it was clicked, so
        # scrolling past never changes the sound.
        if not self.has_focus():
            return False
        self.step(-1 if dy > 0 else 1)
        return True

    def _update_accessible(self):
        self.update_property(
            [Gtk.AccessibleProperty.VALUE_MIN, Gtk.AccessibleProperty.VALUE_MAX,
             Gtk.AccessibleProperty.VALUE_NOW, Gtk.AccessibleProperty.VALUE_TEXT],
            [self.lower, self.upper, self._value, f"{value_text(self._value)} dB"])

    # ------------------------------------------------------------------ draw
    def _draw(self, _area, cr, width, height):
        accent = self.get_color()                   # CSS: the accent colour
        parent = self.get_parent()
        fg = parent.get_color() if parent else accent
        size = min(width, height)
        line = max(2.5, size / 14)
        radius = size / 2 - line / 2 - 1
        cx, cy = width / 2, height / 2
        dim = 1.0 if self.is_sensitive() else 0.45

        def source(rgba, alpha):
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, alpha * dim)

        def arc(a0, a1, rgba, alpha):
            source(rgba, alpha)
            cr.arc(cx, cy, radius, a0, a1)
            cr.stroke()

        cr.set_line_width(line)
        cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
        arc(START, START + SWEEP, fg, 0.18)          # the whole range, faint
        # Lit from flat (12 o'clock) to the value: boost or cut at a glance.
        span = self.upper - self.lower
        angle = START + SWEEP * (self._value - self.lower) / span
        middle = START + SWEEP * (0 - self.lower) / span
        if self._value:
            arc(min(angle, middle), max(angle, middle), accent, 1.0)
        # The knob's marker: a dot just inside the ring, pointing at the value.
        dot = max(2.0, size / 18)
        reach = radius - line - dot - 1.5
        source(fg, 0.9)
        cr.arc(cx + reach * math.cos(angle), cy + reach * math.sin(angle), dot, 0, 2 * math.pi)
        cr.fill()

        layout = self.create_pango_layout(value_text(self._value))
        font = layout.get_context().get_font_description().copy()
        font.set_absolute_size(max(7.5, size * 0.24) * 1024)  # Pango.SCALE
        layout.set_font_description(font)
        text_w, text_h = layout.get_pixel_size()
        source(fg, 0.85)
        cr.move_to(cx - text_w / 2, cy - text_h / 2)
        PangoCairo.show_layout(cr, layout)
