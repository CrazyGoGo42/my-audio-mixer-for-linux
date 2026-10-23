"""The window's look on top of libadwaita: how small the strips get at each
layout step, the knobs, and the theme picker in the menu."""

from gi.repository import Gdk, Gtk

CSS = """
.mixer-body { margin: 12px; }
.mixer-body.snug { margin: 10px; }
.mixer-body.tight { margin: 8px; }

.strip { min-width: 118px; }
.snug .strip { min-width: 100px; }
.tight .strip { min-width: 82px; font-size: 0.92em; }
.tight .strip button { min-height: 26px; padding-top: 2px; padding-bottom: 2px; }

.slots > button { padding-left: 8px; padding-right: 8px; }
.snug .slots > button { padding-left: 5px; padding-right: 5px; }
.tight .slots > button { padding-left: 3px; padding-right: 3px; min-width: 0; }

.compact-row button { min-height: 24px; padding-top: 2px; padding-bottom: 2px; }
.compact-row scale { padding-top: 5px; padding-bottom: 5px; }

/* The knob draws its lit arc in its own colour: the accent, like the faders. */
.knob { min-width: 52px; min-height: 52px; color: @accent_bg_color; }
.snug .knob { min-width: 44px; min-height: 44px; }
.tight .knob { min-width: 36px; min-height: 36px; }
.knob:focus-visible { outline: 2px solid alpha(@accent_color, 0.5); outline-offset: 1px;
                      border-radius: 9999px; }

/* The mic's Color Panel pad: lit in the accent colour like the knobs. */
.color-panel { min-width: 100px; min-height: 78px; color: @accent_bg_color; }
.snug .color-panel { min-width: 88px; min-height: 68px; }
.tight .color-panel { min-width: 74px; min-height: 58px; }
.color-panel:focus-visible { outline: 2px solid alpha(@accent_color, 0.5); outline-offset: 1px; border-radius: 8px; }

/* Follow system / light / dark: three round swatches, as in GNOME's own apps. */
.theme-switcher { margin: 6px 9px; }
.theme-switcher checkbutton {
  min-width: 44px; min-height: 44px; padding: 1px;
  background-clip: content-box; border-radius: 9999px;
  box-shadow: inset 0 0 0 1px @borders;
}
.theme-switcher checkbutton:checked { box-shadow: inset 0 0 0 2px @accent_bg_color; }
.theme-switcher checkbutton.system {
  background-image: linear-gradient(to bottom right, #fff 49.99%, #202020 50.01%);
}
.theme-switcher checkbutton.light { background-color: #fff; }
.theme-switcher checkbutton.dark { background-color: #202020; }
.theme-switcher checkbutton radio {
  -gtk-icon-source: none; border: none; background: none; box-shadow: none;
  min-width: 12px; min-height: 12px; padding: 2px;
  transform: translate(27px, 14px);
}
.theme-switcher checkbutton radio:checked {
  -gtk-icon-source: -gtk-icontheme("object-select-symbolic");
  background-color: @accent_bg_color; color: @accent_fg_color;
}
"""

_installed = []


def install():
    """Load the stylesheet once per process."""
    display = Gdk.Display.get_default()
    if display is None or display in _installed:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _installed.append(display)
