"""The window's menu (the ☰ button): theme, EasyEffects, restarts, quit."""

from gi.repository import Adw, Gio, GLib, Gtk

SCHEMES = {"system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT,
           "dark": Adw.ColorScheme.FORCE_DARK}
THEME_TIPS = (("system", "Follow system style"), ("light", "Light style"), ("dark", "Dark style"))


def apply_theme(theme):
    Adw.StyleManager.get_default().set_color_scheme(SCHEMES.get(theme, Adw.ColorScheme.DEFAULT))


class ThemeSwitcher(Gtk.Box):
    """Three round swatches; on_pick(theme) when one is chosen."""

    def __init__(self, current, on_pick):
        super().__init__(spacing=12, halign=Gtk.Align.CENTER)
        self.add_css_class("theme-switcher")
        self.buttons = {}
        group = None
        for theme, tip in THEME_TIPS:
            button = Gtk.CheckButton()
            button.add_css_class(theme)
            button.set_tooltip_text(tip)
            button.update_property([Gtk.AccessibleProperty.LABEL], [tip])
            if group:
                button.set_group(group)
            group = group or button
            button.set_active(theme == current)
            button.connect("toggled", lambda b, t=theme: b.get_active() and on_pick(t))
            self.append(button)
            self.buttons[theme] = button


def primary_menu():
    """The menu model; its first item is a slot for the ThemeSwitcher ("theme")."""
    menu = Gio.Menu()
    theme = Gio.MenuItem.new(None, None)
    theme.set_attribute_value("custom", GLib.Variant.new_string("theme"))
    section = Gio.Menu()
    section.append_item(theme)
    menu.append_section(None, section)
    tools = Gio.Menu()
    tools.append("Open EasyEffects", "win.open-easyeffects")
    tools.append("Restart EasyEffects", "win.restart-easyeffects")
    tools.append("Restart Audio Engine", "win.restart-engine")
    menu.append_section(None, tools)
    end = Gio.Menu()
    end.append("Quit", "win.quit")
    menu.append_section(None, end)
    return menu
