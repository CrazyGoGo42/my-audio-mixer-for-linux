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


def resolve_slot(value, graph, own):
    """The output device a slot plays on right now, or None (silent)."""
    name = graph.default_sink if value == DEFAULT_OUTPUT else value
    node = graph.nodes.get(name) if name else None
    if node is None or node.media_class != "Audio/Sink" or name in own or name == EE_SINK:
        return None
    return name


def _is_hardware_mic(node, own):
    return (node.media_class == "Audio/Source"
            and node.props.get("device.api") in HARDWARE_APIS
            and not node.props.get("node.virtual")
            and node.name not in own)


def pick_mic(state, graph, own=frozenset()):
    """The real microphone that feeds Mic_In, or None."""
    mics = sorted(n.name for n in graph.nodes.values() if _is_hardware_mic(n, own))
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


def desired_links(channels, state, graph):
    own = own_nodes(channels)
    links = set()

    def slots_to(out_node, slots):
        for slot in slots:
            device = resolve_slot(state.slots.get(slot), graph, own)
            if device:
                links.update(port_pairs(out_node, device, graph))

    for ch in channels:
        out = ch.sink + "_out"
        cs = state.channels.get(ch.key)
        links.update(port_pairs(out, ALL_IN, graph))
        if cs is None or cs.fx:
            links.update(port_pairs(out, EE_SINK, graph))
        else:
            slots_to(out, cs.outputs)
    slots_to(EE_RETURN_OUT, state.fx_outputs)

    mic = pick_mic(state, graph, own)
    if mic:
        links.update(port_pairs(mic, MIC_IN_IN, graph))
    return links
