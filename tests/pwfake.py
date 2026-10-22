"""Build synthetic `pw-dump` output for tests, in the same shapes the real tool
emits on PipeWire 1.0 (checked against this machine on 2026-10-23)."""


def node(id, name, media_class, props=None):
    p = {"node.name": name, "media.class": media_class}
    p.update(props or {})
    return {"id": id, "type": "PipeWire:Interface:Node", "info": {"props": p}}


def port(id, node_id, name, direction, channel, monitor=False):
    p = {"port.name": name, "port.direction": direction, "node.id": node_id,
         "audio.channel": channel}
    if monitor:
        p["port.monitor"] = True
    return {"id": id, "type": "PipeWire:Interface:Port", "info": {"props": p}}


def link(out_node_id, out_port_id, in_node_id, in_port_id, id=None):
    return {"id": id if id is not None else 10000 + out_port_id * 100 + in_port_id,
            "type": "PipeWire:Interface:Link",
            "info": {"output-node-id": out_node_id, "output-port-id": out_port_id,
                     "input-node-id": in_node_id, "input-port-id": in_port_id,
                     "state": "active"}}


def defaults(sink=None, source=None):
    entries = []
    if sink:
        entries.append({"subject": 0, "key": "default.audio.sink",
                        "type": "Spa:String:JSON", "value": {"name": sink}})
    if source:
        entries.append({"subject": 0, "key": "default.audio.source",
                        "type": "Spa:String:JSON", "value": {"name": source}})
    return {"id": 99999, "type": "PipeWire:Interface:Metadata",
            "props": {"metadata.name": "default"}, "metadata": entries}


class DumpBuilder:
    """Small helper: add nodes with stereo ports by name, then link by name."""

    def __init__(self):
        self.objects = []
        self._next = 1
        self._ids = {}      # node name -> id
        self._ports = {}    # "node:port" -> (node id, port id)

    def _id(self):
        self._next += 1
        return self._next

    def add(self, name, media_class, ins=(), outs=(), monitors=(), props=None):
        nid = self._id()
        self._ids[name] = nid
        self.objects.append(node(nid, name, media_class, props))
        for direction, names, mon in (("in", ins, False), ("out", outs, False), ("out", monitors, True)):
            for pname in names:
                pid = self._id()
                channel = pname.rsplit("_", 1)[-1]
                self.objects.append(port(pid, nid, pname, direction, channel, mon))
                self._ports[f"{name}:{pname}"] = (nid, pid)
        return self

    def connect(self, out_port, in_port):
        on, op = self._ports[out_port]
        inn, ip = self._ports[in_port]
        self.objects.append(link(on, op, inn, ip))
        return self

    def default(self, sink=None, source=None):
        self.objects.append(defaults(sink, source))
        return self

    def dump(self):
        return list(self.objects)
