"""The window's own small settings (its size and theme), kept with the mixer's
config so the daily backup covers them. GTK 4 can't place windows, so position
is left to GNOME."""

import json
import os

from ..config import MIXER_DIR

WINDOW_FILE = os.path.join(MIXER_DIR, "window.json")
THEMES = ("system", "light", "dark")


def _load(path):
    try:
        with open(path or WINDOW_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update(path, **values):
    path = path or WINDOW_FILE
    data = _load(path)
    data.update(values)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_size(path=None):
    data = _load(path)
    try:
        width, height = int(data["width"]), int(data["height"])
    except (ValueError, KeyError, TypeError):
        return None
    return (width, height) if width > 100 and height > 100 else None


def save_size(width, height, path=None):
    _update(path, width=int(width), height=int(height))


def load_theme(path=None):
    """"system" (follow GNOME's light/dark), "light" or "dark"."""
    theme = _load(path).get("theme")
    return theme if theme in THEMES else "system"


def save_theme(theme, path=None):
    _update(path, theme=theme)
