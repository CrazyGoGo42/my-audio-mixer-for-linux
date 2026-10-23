"""VoiceMeeter's Color Panel: drag the square. Left/right goes from Lo to Hi
(the voice's tone), up adds brightness and, past the line, echo. Click
anywhere to put it there, double-click to flatten, arrow keys for small steps.
What each position does to the sound: audiomixer.micfx."""

import math

import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import GObject, Gtk, PangoCairo  # noqa: E402
from gi.repository import Gdk  # noqa: E402  (after Gtk: the GTK 4 one)

from .tips import tip  # noqa: E402

STEP = 0.05
LINE = 0.5   # above this, the echo comes in (micfx)


def value_at(px, py, width, height):
    """The (x, y) a point on the pad means: x -1 (Lo) .. 1 (Hi), y 0 .. 1 up."""
    x = max(-1.0, min(1.0, px / width * 2 - 1))
    y = max(0.0, min(1.0, 1 - py / height))
    return round(x, 3) + 0.0, round(y, 3) + 0.0


class ColorPanel(Gtk.DrawingArea):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__(focusable=True)
        self.add_css_class("color-panel")
        self._x = self._y = 0.0
        self.set_draw_func(self._draw)
        tip(self, "Color Panel — Lo/Hi: the voice's tone; up: brightness, then echo. Double-click: flat")
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda _g, x, y: self.begin_drag(x, y, self.get_width(), self.get_height()))
        drag.connect("drag-update", lambda _g, dx, dy: self.drag_to(dx, dy, self.get_width(), self.get_height()))
        drag.connect("drag-end", lambda *_: self.end_drag())
        self.add_controller(drag)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, n, *_: self.double_click() if n == 2 else None)
        click.connect("released", lambda *_: self.end_drag())
        self.add_controller(click)
        self._resetting = False
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self._start = (0, 0)

    def get_value(self):
        return self._x, self._y

    def set_value(self, x, y):
        x = round(max(-1.0, min(1.0, float(x))), 3) + 0.0
        y = round(max(0.0, min(1.0, float(y))), 3) + 0.0
        if (x, y) == (self._x, self._y):
            return
        self._x, self._y = x, y
        self.queue_draw()
        self.emit("changed")

    def reset(self):
        self.set_value(0, 0)

    def nudge(self, dx, dy):
        self.set_value(self._x + dx * STEP, self._y + dy * STEP)

    # A double-click is two presses, and each press also starts a drag: the
    # reset must win whichever comes first, so after it the rest of that press
    # moves nothing (seen live: the second press left x at -0.01).
    def begin_drag(self, px, py, width, height):
        """A press: the square jumps to the pointer."""
        self._start = (px, py)
        if not self._resetting:
            self.grab_focus()
            self.set_value(*value_at(px, py, width, height))

    def drag_to(self, dx, dy, width, height):
        if not self._resetting:
            sx, sy = self._start
            self.set_value(*value_at(sx + dx, sy + dy, width, height))

    def end_drag(self):
        self._resetting = False

    def double_click(self):
        self._resetting = True
        self.reset()

    def _on_key(self, _ctl, keyval, _code, _state):
        moves = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, 1), Gdk.KEY_Down: (0, -1)}
        if keyval in moves:
            self.nudge(*moves[keyval])
        elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0, Gdk.KEY_Home):
            self.reset()
        else:
            return False
        return True

    # ------------------------------------------------------------------ draw
    def _draw(self, _area, cr, width, height):
        accent = self.get_color()                   # CSS: the accent colour
        parent = self.get_parent()
        fg = parent.get_color() if parent else accent
        dim = 1.0 if self.is_sensitive() else 0.45

        def source(rgba, alpha):
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, alpha * dim)

        def rounded(x, y, w, h, r):
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
            cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.close_path()

        rounded(0.5, 0.5, width - 1, height - 1, 8)
        source(fg, 0.06)
        cr.fill_preserve()
        source(fg, 0.14)
        cr.set_line_width(1)
        cr.stroke()
        # The middle (flat tone) and the line where the echo starts.
        source(fg, 0.18)
        cr.move_to(width / 2, 6)
        cr.line_to(width / 2, height - 6)
        line_y = height * (1 - LINE)
        cr.move_to(6, line_y)
        cr.line_to(width - 6, line_y)
        cr.stroke()

        def text(s, x, y, alpha, align=0.5):
            layout = self.create_pango_layout(s)
            font = layout.get_context().get_font_description().copy()
            font.set_absolute_size(max(7.0, min(width, height) * 0.13) * 1024)   # Pango.SCALE
            layout.set_font_description(font)
            w, h = layout.get_pixel_size()
            source(fg, alpha)
            cr.move_to(x - w * align, y - h / 2)
            PangoCairo.show_layout(cr, layout)

        text("fx echo", width / 2, line_y / 2, 0.55)
        text("brightness", width / 2, line_y + (height - line_y) * 0.35, 0.35)
        text("Lo", 6, height - 9, 0.45, align=0)
        text("Hi", width - 6, height - 9, 0.45, align=1)

        # The square: lit in the accent colour once it does something.
        size = max(10.0, min(width, height) * 0.16)
        cx = 4 + size / 2 + (self._x + 1) / 2 * (width - 8 - size)
        cy = height - 4 - size / 2 - self._y * (height - 8 - size)
        rounded(cx - size / 2, cy - size / 2, size, size, 3)
        if (self._x, self._y) == (0.0, 0.0):
            source(fg, 0.75)
        else:
            source(accent, 1.0)
        cr.fill()
