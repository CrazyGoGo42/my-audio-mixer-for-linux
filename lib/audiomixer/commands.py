"""
The mixer's commands — what `audio-mixer` and the mixer window both do.

    apply_command(argv, channels, state)  the new state after one command (pure)
    run(argv)                             apply it for real: saved under a lock,
                                          wired at once, Bass/Treble set live
    status_dict / devices_list            what goes where, what can be picked
"""

import copy

from .config import (
    AUTO_MIC, DEFAULT_OUTPUT, EQ_BANDS, EQ_LIMIT_DB, SLOTS, load_channels, update_state,
)
from .pwgraph import read_graph
from .reconcile import apply_eq, reconcile_once
from .routing import hardware_mics, hardware_outputs, own_nodes, pick_mic, resolve_slot


def find_channel(channels, name):
    """A channel by its key or name, any case."""
    for ch in channels:
        if name.lower() in (ch.key.lower(), ch.label.lower()):
            return ch
    raise ValueError(f"unknown channel {name!r} (choose: {', '.join(c.label.lower() for c in channels)})")


def _slot(name):
    if name.upper() not in SLOTS:
        raise ValueError(f"unknown slot {name!r} (choose: {', '.join(SLOTS)})")
    return name.upper()


def _switch(current, word):
    if word not in ("on", "off", "toggle"):
        raise ValueError(f"expected on, off or toggle, not {word!r}")
    return (not current) if word == "toggle" else word == "on"


def _set_slot(slots, slot, on):
    chosen = set(slots) | {slot} if on else set(slots) - {slot}
    return [s for s in SLOTS if s in chosen]


def out_message(argv, channels, state):
    """What an `out <channel|fx> <slot> ...` command left behind, for the OSD:
    "Music A2 on"."""
    target, slot = argv[1], _slot(argv[2])
    if target.lower() == "fx":
        return f"EasyEffects {slot} {'on' if slot in state.fx_outputs else 'off'}"
    ch = find_channel(channels, target)
    return f"{ch.label} {slot} {'on' if slot in state.channels[ch.key].outputs else 'off'}"


def apply_command(argv, channels, state):
    """The new MixerState after one command (the given state is not changed)."""
    s = copy.deepcopy(state)
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "fx" and len(args) == 2:
        cs = s.channels[find_channel(channels, args[0]).key]
        cs.fx = _switch(cs.fx, args[1])
    elif cmd == "out" and len(args) == 3:
        slot = _slot(args[1])
        if args[0].lower() == "fx":
            s.fx_outputs = _set_slot(s.fx_outputs, slot, _switch(slot in s.fx_outputs, args[2]))
        else:
            cs = s.channels[find_channel(channels, args[0]).key]
            cs.outputs = _set_slot(cs.outputs, slot, _switch(slot in cs.outputs, args[2]))
    elif cmd == "slot" and len(args) == 2:
        s.slots[_slot(args[0])] = {"default": DEFAULT_OUTPUT, "none": None}.get(args[1], args[1])
    elif cmd == "eq" and len(args) == 3:
        cs = s.channels[find_channel(channels, args[0]).key]
        if args[1] not in EQ_BANDS:
            raise ValueError(f"expected bass, mid or treble, not {args[1]!r}")
        try:
            db = float(args[2])
        except ValueError:
            raise ValueError(f"expected a number of dB, not {args[2]!r}") from None
        setattr(cs, args[1], max(-EQ_LIMIT_DB, min(EQ_LIMIT_DB, db)))
    elif cmd == "mic" and len(args) == 1:
        s.mic = AUTO_MIC if args[0] == "auto" else args[0]
    else:
        raise ValueError("unknown command; run `audio-mixer --help`")
    return s


def _description(graph, name):
    node = graph.nodes.get(name) if name else None
    return node.props.get("node.description") if node else None


def status_dict(channels, state, graph):
    """Everything the window needs to draw the routing (its data contract)."""
    own = own_nodes(channels)
    slots = {}
    for slot in SLOTS:
        device = resolve_slot(state.slots.get(slot), graph, own)
        slots[slot] = {"value": state.slots.get(slot), "device": device,
                       "description": _description(graph, device)}
    return {
        "slots": slots,
        "channels": [{"key": c.key, "label": c.label, "sink": c.sink,
                      "fx": state.channels[c.key].fx, "outputs": state.channels[c.key].outputs,
                      **{band: getattr(state.channels[c.key], band) for band in EQ_BANDS}}
                     for c in channels],
        "fx_outputs": state.fx_outputs,
        "mic": {"value": state.mic, "device": pick_mic(state, graph, own)},
    }


def devices_list(channels, graph):
    own = own_nodes(channels)
    return ([{"kind": "output", "name": n, "description": _description(graph, n)}
             for n in hardware_outputs(graph, own)]
            + [{"kind": "mic", "name": n, "description": _description(graph, n)}
               for n in hardware_mics(graph, own)])


def run(argv):
    """Apply one command for real (raises ValueError on bad input)."""
    channels = load_channels()
    # Locked load -> change -> save: a hotkey and the window may run at once.
    state = update_state(channels, lambda current: apply_command(argv, channels, current))
    graph = read_graph()
    reconcile_once(graph)
    if argv and argv[0] == "eq":
        apply_eq(graph, channels, state)
    return state
