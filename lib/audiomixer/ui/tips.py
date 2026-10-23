"""Tooltips that cost nothing to set. GTK's set_tooltip_text asks the X server
where the pointer is, which on a composited desktop takes ~10 ms per call —
even unchanged, even for a widget not on screen — so a window refresh that
touched a dozen tooltips stuttered. tip() hands GTK the text only when the
pointer actually hovers; screen readers get it as the description."""

from gi.repository import Gtk


def _on_query(widget, _x, _y, _keyboard, tooltip):
    tooltip.set_text(widget._tip)
    return True


def tip(widget, text):
    if not hasattr(widget, "_tip"):
        widget.connect("query-tooltip", _on_query)
        widget.set_has_tooltip(True)
    elif widget._tip == text:
        return
    widget._tip = text
    widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [text])


def tip_text(widget):
    return getattr(widget, "_tip", None)
