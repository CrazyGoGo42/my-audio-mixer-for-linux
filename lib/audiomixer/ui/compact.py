"""Compact layout for a narrow or short window (a tiny mixer in a corner): one
slim row per strip, and below them every app making sound, with its channel."""

from gi.repository import Gtk

from ..live import strip_targets
from .apps import AppsList
from .strip import StripWidget


class CompactView(Gtk.Box):
    def __init__(self, controller, title_of):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(10)
        self.strips = []
        for name, kind in strip_targets(controller.channels):
            row = StripWidget(controller, name, kind, title_of(name), compact=True)
            self.strips.append(row)
            self.append(row)
        # The rest of the window: "Playing now". It scrolls only when there
        # are more apps than room (never the rows above).
        self.apps = AppsList(controller, compact=True)
        self.apps.set_margin_top(10)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(60)
        scroll.set_child(self.apps)
        self.append(scroll)

    def update(self, snapshot, status=None):
        for row in self.strips:
            row.update(snapshot.strips.get(row.name), status)
        self.apps.update(snapshot, status)
