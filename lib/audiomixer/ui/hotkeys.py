"""Right-click a control to see and change its hotkey.

One row per action (a mute button has one; a fader has volume down and up):
the current combination, Change, Clear. Change listens for the next key
combination; meanwhile our GNOME shortcuts are suspended, or GNOME would grab
the keys before the window sees them. Esc or closing cancels and restores them.
"""

from gi.repository import Gdk, Gtk

from .. import hotkeys
from .tips import tip

MODIFIER_KEYS = {
    Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R,
    Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift, Gdk.KEY_Caps_Lock,
    Gdk.KEY_Num_Lock, Gdk.KEY_Hyper_L, Gdk.KEY_Hyper_R,
}


def pretty(accel):
    """Ctrl+KP 3 instead of <Ctrl>KP_3; "—" for none."""
    if not accel:
        return "—"
    ok, key, mods = Gtk.accelerator_parse(accel)
    return Gtk.accelerator_get_label(key, mods) if ok else accel


class HotkeyRow(Gtk.Box):
    def __init__(self, popover, action, label):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.action = action
        name = Gtk.Label(label=label, xalign=0)
        name.set_hexpand(True)
        self.append(name)
        self.keys_label = Gtk.Label(label="—")
        self.keys_label.add_css_class("monospace")
        self.append(self.keys_label)
        change = Gtk.Button(label="Change")
        change.connect("clicked", lambda _b: popover.start_capture(action))
        self.append(change)
        clear = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        tip(clear, "Remove this hotkey")
        clear.connect("clicked", lambda _b: popover.clear(action))
        self.append(clear)


class HotkeyPopover(Gtk.Popover):
    def __init__(self, controller, actions):
        super().__init__()
        self.controller = controller
        self.capturing = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(8)
        title = Gtk.Label(label="Hotkeys", xalign=0)
        title.add_css_class("heading")
        box.append(title)
        self.rows = [HotkeyRow(self, action, label) for action, label in actions]
        for row in self.rows:
            box.append(row)
        self.message = Gtk.Label(xalign=0, wrap=True, max_width_chars=36)
        self.message.add_css_class("dim-label")
        self.message.set_visible(False)
        box.append(self.message)
        self.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, keyval, _code, state: self.handle_key(keyval, state))
        self.add_controller(keys)
        self.connect("closed", self._on_closed)
        self.refresh()

    def refresh(self):
        current = self.controller.hotkey_map()
        for row in self.rows:
            if row.action == self.capturing:
                row.keys_label.set_label("Press keys…")
            else:
                row.keys_label.set_label(pretty(current.get(row.action)))

    def _say(self, text):
        self.message.set_label(text or "")
        self.message.set_visible(bool(text))

    def _gnome(self, fn, *args):
        """Run a controller call that writes GNOME's shortcuts; False (and say
        why) if dconf refused."""
        try:
            fn(*args)
            return True
        except RuntimeError as e:
            self._say(f"Couldn't change the GNOME shortcuts: {e}")
            return False

    def start_capture(self, action):
        if self.capturing is None and not self._gnome(self.controller.suspend_hotkeys):
            return
        self.capturing = action
        self._say("Press the new combination — Esc cancels.")
        self.refresh()

    def handle_key(self, keyval, state):
        if self.capturing is None:
            return False
        if keyval == Gdk.KEY_Escape:
            self.cancel()
            return True
        if keyval in MODIFIER_KEYS:
            return True  # wait for the real key
        accel = Gtk.accelerator_name(keyval, state & Gtk.accelerator_get_default_mod_mask())
        if not hotkeys.acceptable(accel):
            self._say(f"{pretty(accel)} would get in the way of typing — "
                      "add Ctrl, Alt or Super (F- and media keys work alone).")
            return True
        action, self.capturing = self.capturing, None
        if self._gnome(self.controller.set_hotkey, action, accel):  # saves and re-binds everything
            self._say("")
        self.refresh()
        return True

    def cancel(self):
        ok = True
        if self.capturing is not None:
            self.capturing = None
            ok = self._gnome(self.controller.resume_hotkeys)
        if ok:
            self._say("")
        self.refresh()

    def clear(self, action):
        self.capturing = None  # set_hotkey below re-binds what was suspended
        if self._gnome(self.controller.set_hotkey, action, None):
            self._say("")
        self.refresh()

    def _on_closed(self, _popover):
        self.cancel()
