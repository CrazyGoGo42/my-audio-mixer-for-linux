"""
Where every mixer node should be linked, given the user's settings and the live
graph. Pure: no PipeWire calls here (see audiomixer.reconcile for applying it).

    channel  ──► All_Audio_in                     always (All Audio = every channel)
             ──► easyeffects_sink                 FX on
             ──► the devices of its A1–A4 slots   FX off
    EE_Return_out ──► the devices of the EasyEffects strip's slots
    a real mic    ──► Mic_In_in                   (EasyEffects listens to Mic_In)

Our own outputs are never linked into our own nodes or into easyeffects_sink
from the EasyEffects side, so the graph can't loop.
"""

from .config import ALL_AUDIO, AUTO_MIC, DEFAULT_OUTPUT, EE_RETURN, EE_SINK, MIC_IN

ALL_IN = ALL_AUDIO + "_in"
MIC_IN_IN = MIC_IN + "_in"
EE_RETURN_OUT = EE_RETURN + "_out"
HARDWARE_APIS = ("alsa", "bluez5")


def own_nodes(channels):
    """Every node this project creates."""
    names = {EE_RETURN, EE_RETURN_OUT, MIC_IN, MIC_IN_IN, ALL_AUDIO, ALL_IN}
    for ch in channels:
        names |= {ch.sink, ch.sink + "_out"}
    return names


def managed_nodes(channels):
    """The nodes whose links the daemon owns (WirePlumber never links them)."""
    return {ch.sink + "_out" for ch in channels} | {EE_RETURN_OUT, MIC_IN_IN, ALL_IN}


def _usable_sink(name, graph, own):
    node = graph.nodes.get(name) if name else None
    return (node is not None and node.media_class == "Audio/Sink"
            and name not in own and name != EE_SINK)


def resolve_slot(value, graph, own):
    """The output device a slot plays on right now, or None (silent).

    "@default" follows the default output — unless that is one of our own
    nodes or EasyEffects' sink (WirePlumber can pick those; linking into them
    would loop), or missing: then the best real output plays instead."""
    if value == DEFAULT_OUTPUT:
        if _usable_sink(graph.default_sink, graph, own):
            return graph.default_sink
        outputs = sorted(hardware_outputs(graph, own),
                         key=lambda n: (-int(graph.nodes[n].props.get("priority.session") or 0), n))
        return outputs[0] if outputs else None
    return value if _usable_sink(value, graph, own) else None


def _hardware(graph, media_class, own):
    return sorted(n.name for n in graph.nodes.values()
                  if n.media_class == media_class
                  and n.props.get("device.api") in HARDWARE_APIS
                  and not n.props.get("node.virtual")
                  and n.name not in own)


def hardware_outputs(graph, own=frozenset()):
    """Real output devices present (speakers, headset, HDMI, ...), by name."""
    return _hardware(graph, "Audio/Sink", own)


def hardware_mics(graph, own=frozenset()):
    """Real microphones present — never a monitor or a virtual source."""
    return _hardware(graph, "Audio/Source", own)


def pick_mic(state, graph, own=frozenset()):
    """The real microphone that feeds Mic_In, or None."""
    mics = hardware_mics(graph, own)
    if state.mic != AUTO_MIC:
        return state.mic if state.mic in mics else None
    usb = [m for m in mics if m.startswith("alsa_input.usb-")]
    return (usb or mics or [None])[0]


def port_pairs(out_node, in_node, graph):
    """Port links from out_node to in_node, matched by channel (MONO feeds all)."""
    outs = [p for p in graph.ports.get(out_node, []) if p.direction == "out" and not p.monitor]
    ins = [p for p in graph.ports.get(in_node, []) if p.direction == "in"]
    pairs = []
    for o in outs:
        for i in ins:
            if o.channel == "MONO" or o.channel == i.channel:
                pairs.append((f"{out_node}:{o.name}", f"{in_node}:{i.name}"))
    return pairs


def wanted_routes(channels, state, graph):
    """[(from node, to node)] that should be connected right now."""
    own = own_nodes(channels)
    routes = []

    def slots_to(out_node, slots):
        for slot in slots:
            device = resolve_slot(state.slots.get(slot), graph, own)
            if device:
                routes.append((out_node, device))

    for ch in channels:
        out = ch.sink + "_out"
        cs = state.channels.get(ch.key)
        routes.append((out, ALL_IN))
        if cs is None or cs.fx:
            if EE_SINK in graph.nodes:
                routes.append((out, EE_SINK))
        else:
            slots_to(out, cs.outputs)
    slots_to(EE_RETURN_OUT, state.fx_outputs)

    mic = pick_mic(state, graph, own)
    if mic:
        routes.append((mic, MIC_IN_IN))
    return [r for r in routes if r[0] in graph.nodes]


def desired_links(channels, state, graph):
    links = set()
    for out_node, in_node in wanted_routes(channels, state, graph):
        links.update(port_pairs(out_node, in_node, graph))
    return links


def unpairable_routes(channels, state, graph):
    """Wanted routes whose ports can't be paired (e.g. unknown channel names):
    they would silently carry no sound."""
    return [r for r in wanted_routes(channels, state, graph) if not port_pairs(*r, graph)]
