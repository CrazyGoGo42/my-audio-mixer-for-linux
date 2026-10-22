"""The mixer window: Mic | channels | EasyEffects | All Audio."""

from gi.repository import Adw, Gtk

from ..config import ALL_AUDIO, EE_RETURN, MIC_IN
from ..live import strip_targets
from .strip import StripWidget


def strip_title(channels, name):
    titles = {MIC_IN: "Mic", EE_RETURN: "EasyEffects", ALL_AUDIO: "All Audio"}
    titles.update({c.sink: c.label for c in channels})
    return titles.get(name, name)


def save_png(widget, path):
    """Render a widget (e.g. the window) to a PNG — for screenshots and checks."""
    width, height = widget.get_width(), widget.get_height()
    paintable = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, width, height)
    node = snap.to_node()
    texture = widget.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(path)


class MixerWindow(Adw.ApplicationWindow):
    def __init__(self, controller, application=None):
        super().__init__(application=application, title="Audio Mixer")
        self.set_default_size(1040, 600)
        self.controller = controller

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.body, f"set_margin_{side}")(12)

        self.strips_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.strips = []
        channels = controller.channels
        for name, kind in strip_targets(channels):
            if name in (channels[0].sink, EE_RETURN):  # Mic | channels | EasyEffects + All Audio
                self.strips_row.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
            strip = StripWidget(controller, name, kind, strip_title(channels, name))
            self.strips.append(strip)
            self.strips_row.append(strip)
        self.body.append(self.strips_row)

        toolbar.set_content(self.body)
        self.set_content(toolbar)
        controller.subscribe(self)

    def update(self, snapshot, status):
        for strip in self.strips:
            strip.update(snapshot.strips.get(strip.name), status)
