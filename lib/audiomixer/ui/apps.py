""""Playing now": every app making sound, its level, and a button per channel."""

from gi.repository import Gtk


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
        self.new.set_tooltip_text("Not routed yet — pick its channel and it starts there from now on")
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

    def _on_toggled(self, toggle, sink):
        if self._updating:
            return
        if not toggle.get_active():  # un-pressing the current channel changes nothing
            self.update(self.app)
            return
        self.controller.move_app(self.app, sink)


class AppsList(Gtk.Box):
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.controller = controller
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

    def update(self, snapshot, status=None):
        apps = snapshot.apps
        if [r.app.key for r in self.rows] != [a.key for a in apps]:
            for row in self.rows:
                self.list.remove(row.get_parent())
            self.rows = []
            for app in apps:
                row = AppRowWidget(self.controller, self.controller.channels, app)
                for side in ("top", "bottom", "start", "end"):
                    getattr(row, f"set_margin_{side}")(6)
                self.list.append(row)
                self.rows.append(row)
        else:
            for row, app in zip(self.rows, apps):
                row.update(app)
        self.list.set_visible(bool(self.rows))
        self.empty.set_visible(not self.rows)
