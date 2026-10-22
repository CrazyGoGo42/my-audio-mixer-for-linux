"""The mixer window: Mic | channels | EasyEffects | All Audio."""

from gi.repository import Adw, Gtk

from ..config import ALL_AUDIO, EE_RETURN, MIC_IN
from ..live import strip_targets
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
        self.set_default_size(1040, 600)
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

        toolbar.set_content(self.body)
        self.set_content(toolbar)
        controller.subscribe(self)

    def update(self, snapshot, status):
        for strip in self.strips:
            strip.update(snapshot.strips.get(strip.name), status)
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
            else:
                text = names.get(value, value) + ("" if device else " (not connected)")
            button.set_label(f"{slot} · {text}")
            run = self.controller.command
            button.set_items([("Default output", lambda s=slot: run(["slot", s, "default"]))]
                             + [(names[d["name"]], lambda s=slot, n=d["name"]: run(["slot", s, n]))
                                for d in outputs]
                             + [("Off", lambda s=slot: run(["slot", s, "none"]))])
