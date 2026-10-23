"""
A live snapshot for the mixer window: each strip's volume and mute, and the
apps currently playing on a channel. Built from `pactl -f json` (one call per
list), so it's cheap enough to refresh on every pactl event.
"""

import json
import subprocess
from dataclasses import dataclass, field

from . import apps
from .config import ALL_AUDIO, EE_RETURN, MIC_IN
from .routing import own_nodes


@dataclass
class StripLive:
    name: str
    kind: str        # "sink" or "source"
    present: bool
    volume: int      # pactl % (0–150)
    muted: bool
    node_id: int | None = None  # PipeWire object id (Bass/Treble controls live on it)


@dataclass
class AppRow:
    key: tuple       # routes.json identity, e.g. ("binary", "zen")
    name: str
    indexes: list    # sink-input indexes of this app's streams
    sink: str        # the channel it plays on
    known: bool      # in routes.json (False = "new")
    props: dict = field(default_factory=dict)  # first stream's properties


@dataclass
class Snapshot:
    strips: dict = field(default_factory=dict)   # node name -> StripLive
    apps: list = field(default_factory=list)     # [AppRow], sorted by name


def strip_targets(channels):
    """[(node, kind)] in display order: Mic | channels | EasyEffects | All Audio."""
    return ([(MIC_IN, "source")] + [(c.sink, "sink") for c in channels]
            + [(EE_RETURN, "sink"), (ALL_AUDIO, "source")])


def _percent(entry):
    channels = list((entry.get("volume") or {}).values())
    try:
        return int(str(channels[0]["value_percent"]).rstrip("%"))
    except (IndexError, KeyError, ValueError):
        return 0


def _object_id(entry):
    try:
        return int((entry.get("properties") or {}).get("object.id"))
    except (TypeError, ValueError):
        return None


def build_snapshot(sinks, sources, inputs, channels, routes):
    by_name = {e.get("name"): e for e in list(sinks) + list(sources)}
    strips = {}
    for name, kind in strip_targets(channels):
        e = by_name.get(name)
        strips[name] = (StripLive(name, kind, True, _percent(e), bool(e.get("mute")), _object_id(e))
                        if e else StripLive(name, kind, False, 0, False))

    sink_names = {e.get("index"): e.get("name") for e in sinks}
    channel_sinks = {c.sink for c in channels}
    own = own_nodes(channels)
    rows = {}
    for s in inputs:
        props = s.get("properties") or {}
        target = sink_names.get(s.get("sink"))
        if target not in channel_sinks or props.get("node.name") in own:
            continue
        if (props.get("application.name") in apps.IGNORE_APPS
                or props.get("application.process.binary") in apps.IGNORE_APPS):
            continue
        key = apps.identity(props)
        if not key:
            continue
        if key in rows:
            rows[key].indexes.append(s.get("index"))
            continue
        name = (props.get("application.name") or props.get("application.process.binary")
                or props.get("node.name"))
        rows[key] = AppRow(key, name, [s.get("index")], target, apps.is_known(routes, props), dict(props))
    return Snapshot(strips, sorted(rows.values(), key=lambda r: r.name.lower()))


def _pactl_json(what):
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", what], capture_output=True,
                             text=True, timeout=5).stdout
        data = json.loads(out)
        return data if isinstance(data, list) else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def read_snapshot(channels):
    return build_snapshot(_pactl_json("sinks"), _pactl_json("sources"), _pactl_json("sink-inputs"),
                          channels, apps.load_routes())
