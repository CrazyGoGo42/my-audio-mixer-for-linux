""""Playing now": every app making sound, its level, and a button per channel."""

from gi.repository import Gtk

from .strip import MenuButton
from .tips import tip


class AppRowWidget(Gtk.Box):
    def __init__(self, controller, channels, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.controller, self.channels, self.app = controller, channels, app
        self._updating = False

        self.name = Gtk.Label(label=app.name, xalign=0)
        self.name.set_width_chars(16)
        self.name.set_max_width_chars(22)
        self.name.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.append(self.name)
        self.new = Gtk.Label(label="NEW")
        self.new.add_css_class("caption-heading")
        self.new.add_css_class("warning")
        tip(self.new, "Not routed yet — pick its channel and it starts there from now on")
        self.append(self.new)

        self.meter = Gtk.LevelBar()
        self.meter.set_min_value(0)
        self.meter.set_max_value(1)
        self.meter.set_hexpand(True)
        self.meter.set_valign(Gtk.Align.CENTER)
        self.append(self.meter)

        group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        group.add_css_class("linked")
        self.channel_toggles = []
        for ch in channels:
            t = Gtk.ToggleButton(label=ch.label)
            t.connect("toggled", self._on_toggled, ch.sink)
            group.append(t)
            self.channel_toggles.append(t)
        self.append(group)
        self.update(app)

    def update(self, app):
        self.app = app
        self._updating = True
        try:
            self.name.set_label(app.name)
            self.new.set_visible(not app.known)
            for ch, t in zip(self.channels, self.channel_toggles):
                if t.get_active() != (ch.sink == app.sink):
                    t.set_active(ch.sink == app.sink)
        finally:
            self._updating = False

    def set_level(self, level):
        self.meter.set_value(max(0.0, min(1.0, level)))

    def retitle(self, channels):
        self.channels = channels
        for ch, toggle in zip(channels, self.channel_toggles):
            toggle.set_label(ch.label)

    def _on_toggled(self, toggle, sink):
        if self._updating:
            return
        if not toggle.get_active():  # the user clicked the channel it's already on
            if not self.app.known:
                self.controller.confirm_app(self.app)   # NEW app: "yes, here" — remember it
            self.update(self.app)
            return
        self.controller.move_app(self.app, sink)


class CompactAppRow(Gtk.Box):
    """One app in the compact view: name, level, and a button with its channel
    — click it to pick another. Same behaviour as AppRowWidget's buttons."""

    def __init__(self, controller, channels, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.controller, self.channels, self.app = controller, channels, app
        self.name = Gtk.Label(xalign=0, width_chars=6, max_width_chars=16)
        self.name.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.append(self.name)
        self.new = Gtk.Label(label="NEW")
        self.new.add_css_class("caption-heading")
        self.new.add_css_class("warning")
        tip(self.new, "Not routed yet — pick its channel and it starts there from now on")
        self.append(self.new)
        self.meter = Gtk.LevelBar(min_value=0, max_value=1, hexpand=True, valign=Gtk.Align.CENTER)
        self.append(self.meter)
        self.channel = MenuButton()
        self.channel.add_css_class("flat")
        self.append(self.channel)
        self.update(app)

    def update(self, app):
        self.app = app
        self.name.set_label(app.name)
        self.new.set_visible(not app.known)
        self.retitle(self.channels)

    def retitle(self, channels):
        self.channels = channels
        self.channel.set_label(next((c.label for c in channels if c.sink == self.app.sink), self.app.sink))
        self.channel.set_items([(c.label, lambda s=c.sink: self.pick(s)) for c in channels])

    def pick(self, sink):
        if sink != self.app.sink:
            self.controller.move_app(self.app, sink)
        elif not self.app.known:
            self.controller.confirm_app(self.app)   # NEW app: "yes, here" — remember it

    def set_level(self, level):
        self.meter.set_value(max(0.0, min(1.0, level)))


class AppsList(Gtk.Box):
    def __init__(self, controller, compact=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.controller = controller
        self.row_type = CompactAppRow if compact else AppRowWidget
        heading = Gtk.Label(label="Playing now", xalign=0)
        heading.add_css_class("heading")
        self.append(heading)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.append(self.list)
        self.empty = Gtk.Label(label="Nothing is playing right now", xalign=0)
        self.empty.add_css_class("dim-label")
        self.append(self.empty)
        self.rows = []

    def retitle(self, channels):
        """A channel was renamed: relabel its button on every row."""
        for row in self.rows:
            row.retitle(channels)

    def update(self, snapshot, status=None):
        apps = snapshot.apps
        if [r.app.key for r in self.rows] != [a.key for a in apps]:
            for row in self.rows:
                self.list.remove(row.get_parent())
            self.rows = []
            for app in apps:
                row = self.row_type(self.controller, self.controller.channels, app)
                for side in ("top", "bottom", "start", "end"):
                    getattr(row, f"set_margin_{side}")(6)
                self.list.append(row)
                self.rows.append(row)
        else:
            for row, app in zip(self.rows, apps):
                row.update(app)
        self.list.set_visible(bool(self.rows))
        self.empty.set_visible(not self.rows)
