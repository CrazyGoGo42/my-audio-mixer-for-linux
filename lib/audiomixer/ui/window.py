"""The mixer window: Mic | channels | EasyEffects | All Audio."""

from gi.repository import Adw, Gdk, GLib, Gtk

from ..config import ALL_AUDIO, EE_RETURN, MIC_IN
from ..live import strip_targets
from .apps import AppsList
from .compact import CompactView
from .settings import load_size, save_size
from .strip import SLOTS, ChannelStrip, EasyEffectsStrip, MenuButton, MicStrip, StripWidget


def strip_title(channels, name):
    titles = {MIC_IN: "Mic", EE_RETURN: "EasyEffects", ALL_AUDIO: "All Audio"}
    titles.update({c.sink: c.label for c in channels})
    return titles.get(name, name)


def save_png(widget, path):
    """Render a widget (e.g. the window) to a PNG — for screenshots and checks.
    Returns False if nothing could be drawn right now (mid-relayout): retry."""
    width, height = widget.get_width(), widget.get_height()
    paintable = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, width, height)
    node = snap.to_node()
    if node is None:
        return False
    texture = widget.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(path)
    return True


class MixerWindow(Adw.ApplicationWindow):
    def __init__(self, controller, application=None):
        super().__init__(application=application, title="Audio Mixer")
        # First run: as wide as everything needs (-1); later: the size it last had.
        self.set_default_size(*(load_size() or (-1, 760)))
        self.controller = controller

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.body, f"set_margin_{side}")(12)

        # Output slots: which device A1–A4 are.
        slots_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        outputs = Gtk.Label(label="Outputs")
        outputs.add_css_class("heading")
        slots_row.append(outputs)
        self.slot_buttons = {}
        for slot in SLOTS:
            button = MenuButton(slot)
            self.slot_buttons[slot] = button
            slots_row.append(button)
        self.body.append(slots_row)

        self.strips_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.strips = []
        channels = controller.channels
        by_sink = {c.sink: c for c in channels}
        for name, kind in strip_targets(channels):
            if name in (channels[0].sink, EE_RETURN):  # Mic | channels | EasyEffects + All Audio
                self.strips_row.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
            if name == MIC_IN:
                strip = MicStrip(controller, name)
            elif name == EE_RETURN:
                strip = EasyEffectsStrip(controller, name)
            elif name in by_sink:
                strip = ChannelStrip(controller, by_sink[name])
            else:
                strip = StripWidget(controller, name, kind, strip_title(channels, name))
            self.strips.append(strip)
            self.strips_row.append(strip)
        self.body.append(self.strips_row)

        self.apps = AppsList(controller)
        apps_scroll = Gtk.ScrolledWindow()
        apps_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        apps_scroll.set_min_content_height(90)
        apps_scroll.set_propagate_natural_height(True)
        apps_scroll.set_max_content_height(260)
        apps_scroll.set_child(self.apps)
        self.body.append(apps_scroll)

        # Narrow window -> compact rows (a tiny mixer in a corner).
        self.compact = CompactView(controller, lambda name: strip_title(channels, name))
        self.compact_strips = self.compact.strips
        compact_scroll = Gtk.ScrolledWindow()
        compact_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        compact_scroll.set_child(self.compact)
        # Wider than the window? Scroll sideways until the compact breakpoint.
        self.wide_scroll = Gtk.ScrolledWindow()
        self.wide_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.wide_scroll.set_propagate_natural_width(True)
        self.wide_scroll.set_propagate_natural_height(True)
        self.wide_scroll.set_child(self.body)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.wide_scroll, "wide")
        self.stack.add_named(compact_scroll, "compact")
        self.stack.set_visible_child_name("wide")
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        breakpoint.add_setter(self.stack, "visible-child-name", "compact")
        self.add_breakpoint(breakpoint)
        self.set_size_request(320, 300)

        toolbar.set_content(self.stack)
        self.set_content(toolbar)
        controller.subscribe(self)
        # Remember the size whenever it changes: an always-open window usually
        # ends at logout, where close-request never fires.
        self._size_save_id = None
        self.connect("notify::default-width", self._size_changed)
        self.connect("notify::default-height", self._size_changed)

    def _size_changed(self, *_):
        if self._size_save_id is None:
            self._size_save_id = GLib.timeout_add(1000, self._size_timeout)

    def _size_timeout(self):
        self._size_save_id = None
        self.save_size_now()
        return False

    def save_size_now(self):
        width, height = self.get_default_size()
        if not self.is_maximized() and width > 100 and height > 100:
            save_size(width, height)

    def update(self, snapshot, status):
        for strip in self.strips:
            strip.update(snapshot.strips.get(strip.name), status)
        self.apps.update(snapshot, status)
        self.compact.update(snapshot, status)
        if status:
            self._update_slots(status)

    def _update_slots(self, status):
        outputs = [d for d in status.get("devices", []) if d["kind"] == "output"]
        names = {d["name"]: d["description"] or d["name"] for d in outputs}
        for slot, button in self.slot_buttons.items():
            info = status["slots"].get(slot, {})
            value, device = info.get("value"), info.get("device")
            if value is None:
                text = "off"
            elif value == "@default":
                text = "Default output" + (f" ({names.get(device, device)})" if device else "")
            elif device:
                text = names.get(value, value)
            else:
                text = "not connected · " + names.get(value, value)
            button.set_label(f"{slot} · {text}")
            run = self.controller.command
            button.set_items([("Default output", lambda s=slot: run(["slot", s, "default"]))]
                             + [(names[d["name"]], lambda s=slot, n=d["name"]: run(["slot", s, n]))
                                for d in outputs]
                             + [("Off", lambda s=slot: run(["slot", s, "none"]))])


def follow_visibility(window, meters):
    """Meters run only while the window is shown and not minimized; the size is
    remembered when it closes."""
    def on_state(surface, _pspec):
        if surface.get_state() & Gdk.ToplevelState.MINIMIZED:
            meters.stop()
        elif window.get_mapped():
            meters.start()

    def on_map(_w):
        window.get_surface().connect("notify::state", on_state)
        meters.start()

    def on_close(_w):
        window.save_size_now()
        meters.stop()
        return False

    window.connect("map", on_map)
    window.connect("unmap", lambda _w: meters.stop())
    window.connect("close-request", on_close)
