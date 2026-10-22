"""
A snapshot of the live PipeWire graph, from `pw-dump`.

Only what the mixer needs: nodes by name, their ports, the links between ports
(as "node:port" name pairs, output first), and the default sink/source.
"""

import json
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Port:
    node: str
    name: str
    direction: str  # "in" or "out"
    channel: str    # audio.channel: FL, FR, MONO, ...
    monitor: bool


@dataclass
class Node:
    id: int
    name: str
    media_class: str
    props: dict


@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)   # name -> Node
    ports: dict = field(default_factory=dict)   # node name -> [Port]
    links: set = field(default_factory=set)     # {("node:port", "node:port")}
    default_sink: str | None = None
    default_source: str | None = None


def _props(obj):
    info = obj.get("info") if isinstance(obj.get("info"), dict) else {}
    return info.get("props") if isinstance(info.get("props"), dict) else {}


def parse_dump(dump):
    g = Graph()
    if not isinstance(dump, list):
        return g
    objects = [o for o in dump if isinstance(o, dict)]
    kind = lambda o: str(o.get("type", "")).rsplit(":", 1)[-1]  # noqa: E731

    node_names = {}  # id -> name
    for o in objects:
        p = _props(o)
        if kind(o) == "Node" and p.get("node.name") and isinstance(o.get("id"), int):
            node_names[o["id"]] = p["node.name"]
            g.nodes[p["node.name"]] = Node(o["id"], p["node.name"], p.get("media.class", ""), p)

    port_names = {}  # id -> "node:port"
    for o in objects:
        p = _props(o)
        if kind(o) != "Port" or p.get("node.id") not in node_names or "port.name" not in p:
            continue
        owner = node_names[p["node.id"]]
        port = Port(owner, p["port.name"], p.get("port.direction", ""),
                    p.get("audio.channel", ""), bool(p.get("port.monitor", False)))
        g.ports.setdefault(owner, []).append(port)
        port_names[o.get("id")] = f"{owner}:{port.name}"

    for o in objects:
        info = o.get("info") if isinstance(o.get("info"), dict) else {}
        if kind(o) == "Link":
            out = port_names.get(info.get("output-port-id"))
            inp = port_names.get(info.get("input-port-id"))
            if out and inp:
                g.links.add((out, inp))
        elif kind(o) == "Metadata" and (o.get("props") or {}).get("metadata.name") == "default":
            for entry in o.get("metadata") or []:
                value = entry.get("value") if isinstance(entry, dict) else None
                name = value.get("name") if isinstance(value, dict) else None
                if entry.get("key") == "default.audio.sink":
                    g.default_sink = name
                elif entry.get("key") == "default.audio.source":
                    g.default_source = name
    return g


def read_graph():
    """The live graph, or an empty one if pw-dump fails."""
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=10).stdout
        return parse_dump(json.loads(out))
    except (OSError, ValueError, subprocess.SubprocessError):
        return Graph()
