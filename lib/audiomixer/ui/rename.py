"""Right-click a channel's name: a small box for its new name."""

from gi.repository import Gtk

from ..config import MAX_NAME


class RenamePopover(Gtk.Popover):
    """Enter renames, Esc cancels. A name that can't be used stays in the box
    with the reason; on_rename(text) raises ValueError for those."""

    def __init__(self, current, on_rename):
        super().__init__()
        self.on_rename = on_rename
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(6)
        title = Gtk.Label(label="Rename channel", xalign=0)
        title.add_css_class("heading")
        box.append(title)
        row = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry(text=current, max_length=MAX_NAME, width_chars=14)
        self.entry.connect("activate", lambda _e: self.apply())
        row.append(self.entry)
        button = Gtk.Button(label="Rename")
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b: self.apply())
        row.append(button)
        box.append(row)
        self.message = Gtk.Label(xalign=0, wrap=True, max_width_chars=28, visible=False)
        self.message.add_css_class("error")
        box.append(self.message)
        hint = Gtk.Label(label="Only the name changes —\nits apps and hotkeys stay.", xalign=0)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        box.append(hint)
        self.set_child(box)
        self.connect("show", lambda _p: self.entry.grab_focus())

    def apply(self):
        try:
            self.on_rename(self.entry.get_text())
        except ValueError as e:
            self.message.set_label(str(e))
            self.message.set_visible(True)
            return
        self.popdown()
