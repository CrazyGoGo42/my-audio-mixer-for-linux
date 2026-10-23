"""How big the window's layouts are allowed to get (no GTK here, so the size
tests can read it)."""

# The wide layout shrinks in steps as the window gets narrower or shorter,
# then hands over to the compact rows; nothing ever scrolls. Each step with the
# smallest window it's shown at — wider AND taller than this (sp: pixels at
# normal text size). tests/test_ui_sizes.py checks every step really fits.
WIDE_LAYOUTS = (("roomy", 1020, 640), ("snug", 840, 620), ("tight", 720, 580))
STRIP_SPACING = {"roomy": 8, "snug": 6, "tight": 4}
SMALLEST = (340, 380)  # the compact rows with something playing on every channel
