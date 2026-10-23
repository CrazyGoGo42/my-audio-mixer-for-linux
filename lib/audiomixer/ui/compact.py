"""Compact layout for a narrow window (a tiny mixer in a corner): one slim row
per strip, with the apps playing on each channel listed under it."""

from gi.repository import Gtk

from ..live import strip_targets
from .strip import StripWidget


class CompactView(Gtk.Box):
    def __init__(self, controller, title_of):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(10)
        self.strips = []
        self.app_labels = {}
        channel_sinks = {c.sink for c in controller.channels}
        for name, kind in strip_targets(controller.channels):
            row = StripWidget(controller, name, kind, title_of(name), compact=True)
            self.strips.append(row)
            self.append(row)
            if name in channel_sinks:
                apps = Gtk.Label(xalign=0)
                apps.add_css_class("caption")
                apps.add_css_class("dim-label")
                apps.set_margin_start(12)
                apps.set_ellipsize(3)  # Pango.EllipsizeMode.END
                apps.set_visible(False)
                self.app_labels[name] = apps
                self.append(apps)

    def update(self, snapshot, status=None):
        for row in self.strips:
            row.update(snapshot.strips.get(row.name), status)
        for sink, label in self.app_labels.items():
            names = [a.name for a in snapshot.apps if a.sink == sink]
            label.set_label(", ".join(names))
            label.set_visible(bool(names))
