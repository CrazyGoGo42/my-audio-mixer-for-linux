"""
Which channel each app plays on: routes.json, shared by the router daemon's
popup and the mixer window's "Playing now" list.

routes.json maps an app to a channel sink, by `application.process.binary`
("binary", preferred) or `application.name` ("app"); "ignore" lists apps
never to ask about. audio-routes-apply compiles it into pipewire-pulse rules,
so a remembered app is born on its channel from then on.
"""

import json
import os
import subprocess
import tempfile

ROUTES_FILE = os.path.expanduser("~/.config/audio-mixer/routes.json")
APPLY_CMD = os.path.expanduser("~/.local/bin/audio-routes-apply")
IGNORE = "__ignore__"

# Streams that are plumbing or system noise: never asked about, never listed.
IGNORE_APPS = {
    "audio-osd", "speech-dispatcher-dummy", "libcanberra",
    "GNOME Volume Control Media Keys", "gnome-shell", "Mutter",
    "easyeffects", "xdg-desktop-portal", "gnome-control-center",
}


def load_routes(path=ROUTES_FILE):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("binary", {})
    data.setdefault("app", {})
    data.setdefault("ignore", [])
    return data


def save_routes(data, path=ROUTES_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".routes-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def identity(props):
    """(field, key) that names this app in routes.json — binary preferred."""
    if props.get("application.process.binary"):
        return "binary", props["application.process.binary"]
    if props.get("application.name"):
        return "app", props["application.name"]
    if props.get("node.name"):
        return "app", props["node.name"]
    return None


def is_known(routes, props):
    binary = props.get("application.process.binary")
    app = props.get("application.name")
    return bool((binary and binary in routes["binary"]) or (app and app in routes["app"])
                or (binary and binary in routes["ignore"]) or (app and app in routes["ignore"]))


def remember(props, sink, path=ROUTES_FILE):
    """Save which channel this app belongs on (or IGNORE: never ask again)."""
    ident = identity(props)
    if not ident:
        return
    field, key = ident
    routes = load_routes(path)
    if sink == IGNORE:
        if key not in routes["ignore"]:
            routes["ignore"].append(key)
    else:
        routes[field][key] = sink
    save_routes(routes, path)


def route_now(indexes, sink, apply_cmd=APPLY_CMD):
    """Move these live streams onto `sink` now, then recompile the rules so the
    app is born there next time. A stream that has vanished is skipped."""
    for index in indexes:
        subprocess.run(["pactl", "move-sink-input", str(index), sink], capture_output=True, text=True)
    subprocess.run([apply_cmd, "--no-restart"], capture_output=True, text=True)
