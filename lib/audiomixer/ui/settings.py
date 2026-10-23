"""The window's own small settings (its size), kept with the mixer's config so
the daily backup covers them. GTK 4 can't place windows, so position is left
to GNOME."""

import json
import os

from ..config import MIXER_DIR

WINDOW_FILE = os.path.join(MIXER_DIR, "window.json")


def load_size(path=None):
    path = path or WINDOW_FILE
    try:
        with open(path) as f:
            data = json.load(f)
        width, height = int(data["width"]), int(data["height"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (width, height) if width > 100 and height > 100 else None


def save_size(width, height, path=None):
    path = path or WINDOW_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"width": int(width), "height": int(height)}, f)
    os.replace(tmp, path)
