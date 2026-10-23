"""
Generate the mixer's PipeWire config (written by audio-routes-apply).

virtual-sinks.conf (pipewire.conf.d) — the nodes the mixer is built from:

    <Channel>_Audio   a sink apps play into (its volume = the channel slider),
                      then Bass/Mid/Treble (builtin biquads), then <Channel>_Audio_out
    EE_Return         EasyEffects plays into it; EE_Return_out = the EasyEffects strip
    Mic_In            a source EasyEffects listens to; a real mic feeds Mic_In_in,
                      through the Mic strip's Color Panel and Comp/Gate
    All_Audio         a source carrying every channel; channels feed All_Audio_in

Every output above is created with node.autoconnect = false: WirePlumber never
links or relinks them — the daemon does (audiomixer.reconcile).

50-audio-mixer-routing.conf (pipewire-pulse.conf.d) — which channel each app
is born on, from routes.json.
"""

import re

from . import micfx
from .config import ALL_AUDIO, EE_RETURN, EQ_BANDS, MIC_IN

BASS_HZ = 100.0
MID_HZ = 1000.0
TREBLE_HZ = 8000.0
SHELF_Q = 0.7


def spa_quote(s):
    """Quote a string for a PipeWire SPA-JSON config value."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _loopback(description, capture, playback, comment):
    return [
        f"    # {comment}",
        "    {   name = libpipewire-module-loopback",
        "        flags = [ nofail ]",
        "        args = {",
        f"            node.description = {spa_quote(description)}",
        f"            capture.props = {{ {capture} }}",
        f"            playback.props = {{ {playback} }}",
        "        }",
        "    }",
    ]


def _channel(ch, cs):
    desc = spa_quote(ch.label + " Audio")
    bass, mid, treble = (float(getattr(cs, band)) if cs else 0.0 for band in EQ_BANDS)
    return [
        f"    # {ch.label}: sink (volume) -> Bass -> Mid -> Treble -> {ch.sink}_out",
        "    {   name = libpipewire-module-filter-chain",
        "        flags = [ nofail ]",
        "        args = {",
        f"            node.description = {desc}",
        f"            media.name = {desc}",
        "            filter.graph = {",
        "                nodes = [",
        f'                    {{ type = builtin name = bass label = bq_lowshelf control = {{ "Freq" = {BASS_HZ} "Q" = {SHELF_Q} "Gain" = {bass} }} }}',
        f'                    {{ type = builtin name = mid label = bq_peaking control = {{ "Freq" = {MID_HZ} "Q" = {SHELF_Q} "Gain" = {mid} }} }}',
        f'                    {{ type = builtin name = treble label = bq_highshelf control = {{ "Freq" = {TREBLE_HZ} "Q" = {SHELF_Q} "Gain" = {treble} }} }}',
        "                ]",
        '                links = [ { output = "bass:Out" input = "mid:In" } { output = "mid:Out" input = "treble:In" } ]',
        "            }",
        "            audio.channels = 2",
        "            audio.position = [ FL FR ]",
        f"            capture.props = {{ node.name = {spa_quote(ch.sink)} media.class = \"Audio/Sink\""
        " audio.position = [ FL FR ] priority.session = 1 }",
        f"            playback.props = {{ node.name = {spa_quote(ch.sink + '_out')}"
        " node.passive = true node.autoconnect = false }",
        "        }",
        "    }",
    ]


def _controls(values):
    return " ".join(f'"{k}" = {v}' for k, v in values.items())


def _mic(fx):
    """Mic_In: a real mic feeds Mic_In_in, EasyEffects listens to Mic_In; in
    between, the Mic strip's Color Panel and Comp/Gate (audiomixer.micfx)."""
    live = {}
    for key, value in micfx.controls(fx).items():
        node, control = key.split(":")
        live.setdefault(node, {})[control] = value
    nodes = []
    for name, label, fixed, config in micfx.NODES:
        values = {**fixed, **live.get(name, {})}
        line = f"                    {{ type = builtin name = {name} label = {label}"
        if config:
            line += f" config = {{ {_controls(config)} }}"
        if values:
            line += f" control = {{ {_controls(values)} }}"
        nodes.append(line + " }")
    links = [f'                    {{ output = "{o}" input = "{i}" }}' for o, i in micfx.LINKS]
    return [
        "    # Mic_In: real mic -> gate/comp -> Lo/Hi -> brightness -> echo -> EasyEffects",
        "    {   name = libpipewire-module-filter-chain",
        "        flags = [ nofail ]",
        "        args = {",
        '            node.description = "Mixer Mic"',
        '            media.name = "Mixer Mic"',
        "            filter.graph = {",
        "                nodes = [", *nodes, "                ]",
        "                links = [", *links, "                ]",
        f'                inputs = [ "{micfx.INPUT}" ]',
        f'                outputs = [ "{micfx.OUTPUT}" ]',
        "            }",
        "            audio.channels = 2",
        "            audio.position = [ FL FR ]",
        f'            capture.props = {{ node.name = "{MIC_IN}_in" node.autoconnect = false node.passive = true'
        " audio.position = [ FL FR ] }",
        f'            playback.props = {{ node.name = "{MIC_IN}" media.class = "Audio/Source" audio.position = [ FL FR ] }}',
        "        }",
        "    }",
    ]


def render_sinks(channels, state):
    lines = [
        "# Generated by audio-routes-apply from ~/.config/audio-mixer/channels.conf",
        "# and mixer.json — do not edit by hand.",
        "#",
        "# One filter-chain per channel (sink + Bass/Treble), plus EE_Return (the",
        "# EasyEffects strip), Mic_In (what EasyEffects listens to) and All_Audio.",
        "# Outputs are not autoconnected: audio-router-daemon links them.",
        "#",
        "# NOTE: each *.props block stays on a single line (the PipeWire 1.0.x",
        "# parser silently drops later modules otherwise), and every module is",
        "# nofail so a bad one can never take PipeWire down with it.",
        "",
        "context.modules = [",
    ]
    for ch in channels:
        lines += _channel(ch, state.channels.get(ch.key))
    lines += _loopback(
        "EasyEffects",
        f'node.name = "{EE_RETURN}" media.class = "Audio/Sink" audio.position = [ FL FR ] priority.session = 1',
        f'node.name = "{EE_RETURN}_out" node.passive = true node.autoconnect = false audio.position = [ FL FR ]',
        "EasyEffects plays into EE_Return; EE_Return_out is the EasyEffects strip")
    lines += _mic(state.mic_fx)
    lines += _loopback(
        "All Audio",
        f'node.name = "{ALL_AUDIO}_in" node.autoconnect = false node.passive = true audio.position = [ FL FR ]',
        f'node.name = "{ALL_AUDIO}" media.class = "Audio/Source" audio.position = [ FL FR ]',
        "All Audio — every channel mixed, as an input for recording/streaming")
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def needs_restart(old_text, new_text):
    """Whether going from old_text to new_text changes the node set, which only
    a PipeWire restart applies. The values people turn (EQ, the mic's controls)
    don't count: they're set live, the file just carries them into the next
    PipeWire start."""
    if old_text is None:
        return True
    values = re.compile(r'("(?:Gain|Gain \d|Mult|Add)") = -?[0-9.]+(?:e[-+]?\d+)?')
    return values.sub(r"\1", old_text) != values.sub(r"\1", new_text)


def render_routes(by_channel, default_sink):
    lines = [
        "# Generated by audio-routes-apply — do not edit by hand.",
        "# Edit ~/.config/audio-mixer/routes.json and rerun audio-routes-apply.",
        "#",
        "# How this works: the first rule is a catch-all that sends EVERY app to the",
        "# Default channel (attenuated and safe). Later rules are more specific and",
        "# override it, pulling known apps onto their own channel. Because the target",
        "# is set at stream creation, an app is born on the right sink every time --",
        "# no race, and nothing ever escapes to the hardware at full volume.",
        "",
        "pulse.rules = [",
        "    # Catch-all: anything with an app name or binary -> Default.",
        "    {",
        "        matches = [",
        '            { application.name = "~.+" }',
        '            { application.process.binary = "~.+" }',
        "        ]",
        f"        actions = {{ update-props = {{ target.object = {spa_quote(default_sink)} }} }}",
        "    }",
    ]
    for channel in sorted(by_channel):
        matches = by_channel[channel]
        lines.append("    {")
        lines.append("        matches = [")
        for prop, value in matches:
            lines.append(f"            {{ {prop} = {spa_quote(value)} }}")
        lines.append("        ]")
        lines.append(
            f"        actions = {{ update-props = {{ target.object = {spa_quote(channel)} }} }}"
        )
        lines.append("    }")
    lines.append("]")
    lines.append("")
    return "\n".join(lines)
