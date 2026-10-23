"""The mixer window: Mic | channels | EasyEffects | All Audio."""

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..config import ALL_AUDIO, EE_RETURN, MIC_IN
from ..live import strip_targets
from . import style
from .apps import AppsList
from .compact import CompactView
from .layout import SMALLEST, STRIP_SPACING, WIDE_LAYOUTS
from .menu import ThemeSwitcher, apply_theme, primary_menu
from .settings import load_size, load_theme, save_size, save_theme
from .strip import SLOTS, ChannelStrip, EasyEffectsStrip, MenuButton, MicStrip, StripWidget

RESTARTS = {"engine": ("the audio engine", "Audio engine"),
            "easyeffects": ("EasyEffects", "EasyEffects")}


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
        style.install()
        # First run: as wide as everything needs (-1); later: the size it last had.
        self.set_default_size(*(load_size() or (-1, 760)))
        self.controller = controller
        theme = load_theme()
        apply_theme(theme)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu", primary=True)
        self.menu_button.set_menu_model(primary_menu())
        self.theme_switcher = ThemeSwitcher(theme, self.set_theme)
        self.menu_button.get_popover().add_child(self.theme_switcher, "theme")
        header.pack_end(self.menu_button)
        toolbar.add_top_bar(header)
        self._add_actions()
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.body.add_css_class("mixer-body")

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
        apps_scroll.set_min_content_height(70)
        apps_scroll.set_propagate_natural_height(True)
        apps_scroll.set_max_content_height(260)
        apps_scroll.set_child(self.apps)
        self.body.append(apps_scroll)

        # Narrow (or short) window -> compact rows (a tiny mixer in a corner).
        self.compact = CompactView(controller, lambda name: strip_title(channels, name))
        self.compact_strips = self.compact.strips
        self.stack = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)  # sized by what's shown
        self.stack.add_named(self.body, "wide")
        self.stack.add_named(self.compact, "compact")
        self.layout = None
        self.set_layout("roomy")
        self._breakpoints = {}
        # A step takes over once the window is no bigger than the one above allows.
        for name, (_, width, height) in zip([n for n, *_ in WIDE_LAYOUTS[1:]] + ["compact"], WIDE_LAYOUTS):
            self._add_breakpoint(f"max-width: {width}sp or max-height: {height}sp", name)
        self.connect("notify::current-breakpoint", self._on_breakpoint)
        self.set_size_request(*SMALLEST)

        self.toast_overlay = Adw.ToastOverlay(child=self.stack)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)
        controller.subscribe(self)
        # Remember the size whenever it changes: an always-open window usually
        # ends at logout, where close-request never fires.
        self._size_save_id = None
        self.connect("notify::default-width", self._size_changed)
        self.connect("notify::default-height", self._size_changed)

    # --------------------------------------------------------------- layout
    def _add_breakpoint(self, condition, layout):
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(condition))
        self.add_breakpoint(breakpoint)   # added last = wins when several match
        self._breakpoints[breakpoint] = layout

    def _on_breakpoint(self, *_):
        self.set_layout(self._breakpoints.get(self.get_current_breakpoint(), "roomy"))

    def set_layout(self, name):
        """One of WIDE_LAYOUTS' steps, or "compact"."""
        self.layout = name
        self.stack.set_visible_child_name("compact" if name == "compact" else "wide")
        for step, *_ in WIDE_LAYOUTS:
            (self.body.add_css_class if step == name else self.body.remove_css_class)(step)
        if name in STRIP_SPACING:
            self.strips_row.set_spacing(STRIP_SPACING[name])

    # ----------------------------------------------------------------- menu
    def _add_actions(self):
        for name, callback in (("open-easyeffects", lambda: self.controller.open_easyeffects()),
                               ("restart-easyeffects", lambda: self.restart("easyeffects")),
                               ("restart-engine", lambda: self.engine_restart_dialog().present(self)),
                               ("quit", lambda: self.close())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            self.add_action(action)
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.quit", ["<Control>q"])

    def set_theme(self, theme):
        apply_theme(theme)
        save_theme(theme)

    def show_toast(self, text, lasting=False, button=None):
        """button: (label, callback) for an action right in the toast."""
        toast = Adw.Toast.new(text)
        if lasting:
            toast.set_timeout(0)   # until it's dismissed
        if button:
            toast.set_button_label(button[0])
            toast.connect("button-clicked", lambda _t, cb=button[1]: cb())
        self.toast_overlay.add_toast(toast)
        return toast

    def retitle(self):
        """A channel was renamed: every place its name shows."""
        labels = {c.sink: c.label for c in self.controller.channels}
        for strip in self.strips + self.compact.strips:
            if strip.name in labels:
                strip.set_title(labels[strip.name])
        self.apps.retitle(self.controller.channels)
        self.compact.apps.retitle(self.controller.channels)

    def app_rows(self):
        """The "Playing now" rows on screen (each layout has its own list)."""
        return (self.compact.apps if self.layout == "compact" else self.apps).rows

    def show_renamed(self, old, new):
        self.show_toast(f"{old} is now {new}. Other apps see it after an engine restart.",
                        button=("Restart Now", lambda: self.restart("engine")))

    def engine_restart_dialog(self):
        dialog = Adw.AlertDialog.new(
            "Restart the audio engine?",
            "All sound stops for a few seconds while PipeWire restarts. "
            "EasyEffects and your levels come back by themselves.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("restart", "Restart")
        dialog.set_response_appearance("restart", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: response == "restart" and self.restart("engine"))
        return dialog

    def restart(self, what):
        """Restart EasyEffects or the whole engine; one restart at a time."""
        thing, title = RESTARTS[what]
        actions = [self.lookup_action(n) for n in ("restart-engine", "restart-easyeffects")]
        for action in actions:
            action.set_enabled(False)
        pending = self.show_toast(f"Restarting {thing}…", lasting=True)

        def done(code, err):
            for action in actions:
                action.set_enabled(True)
            if pending:
                pending.dismiss()
            lines = [line.strip() for line in (err or "").splitlines() if line.strip()]
            if code != 0:
                self.show_toast(f"Couldn't restart {thing}: {lines[-1] if lines else f'error {code}'}")
            elif lines:   # audio-routes-apply: up, but something isn't wired yet
                self.show_toast(f"{title} restarted, but not everything is connected yet")
            else:
                self.show_toast(f"{title} restarted")
        self.controller.restart(what, done)

    # ------------------------------------------------------------------ size
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
