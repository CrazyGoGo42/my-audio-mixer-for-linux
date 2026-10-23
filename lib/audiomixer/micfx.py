"""
The Mic strip's VoiceMeeter controls — the Color Panel (Lo/Hi, brightness, fx
echo) and Audibility (Comp, Gate) — built from PipeWire's builtin filters only:
this PipeWire can't load LADSPA or LV2 plugins. Checked with real audio by
tests/spike/mic-spike.py.

    x -> level (x², 20 Hz lowpass, log10) -> gate + compressor gain, summed,
         10^gain -> × x -> Lo/Hi tilt -> brightness -> dry + 3 echo taps

PipeWire caps these controls at ±10, so levels are dB/10 (log10 of power) and
gains dB/20 (log10 of amplitude) rather than plain dB.
"""

GATE_DB = (-66.0, 3.6)        # threshold: -66 dBFS + 3.6 per knob step (10: -30)
COMP_DB = (-12.0, -2.8)       # threshold: -12 dBFS - 2.8 per step (10: -40)
COMP_RATIO = 0.3              # ratio 1 + 0.3 per step (10: 4:1)
SPEECH_DB = -18.0             # makeup keeps speech here about as loud as before
TILT_DB = 5.0                 # Lo/Hi: low shelf down / high shelf up, at most this
BRIGHT_DB = 7.0               # brightness shelf at the line (half way up)
ECHO_S = 0.22
ECHO_TAPS = (0.55, 0.30, 0.17)

# PipeWire's limits for each kind of control (from the filters' PropInfo).
RANGES = {"Mult": (-10.0, 10.0), "Add": (-10.0, 10.0), "Gain": (-120.0, 20.0),
          **{f"Gain {n}": (0.0, 10.0) for n in range(1, 9)}}

# (name, label, fixed controls, config). The controls micfx.controls() sets
# are added when rendering.
NODES = [
    ("split", "copy", {}, None),
    ("sq", "mult", {}, None),
    ("smooth", "bq_lowpass", {"Freq": 20.0, "Q": 0.5}, None),
    ("lg", "log", {"Base": 10.0}, None),
    ("floor", "clamp", {"Min": -10.0, "Max": 1.0}, None),
    ("g_lin", "linear", {}, None),
    ("g_clamp", "clamp", {"Min": -4.0, "Max": 0.0}, None),       # at most -80 dB
    ("c_lin", "linear", {"Mult": 1.0}, None),
    ("c_clamp", "clamp", {"Min": 0.0, "Max": 100.0}, None),
    ("c_slope", "linear", {}, None),
    ("sum", "mixer", {}, None),
    ("ex", "exp", {"Base": 10.0}, None),
    ("vca", "mult", {}, None),
    ("tilt_lo", "bq_lowshelf", {"Freq": 250.0, "Q": 0.7}, None),
    ("tilt_hi", "bq_highshelf", {"Freq": 2500.0, "Q": 0.7}, None),
    ("bright", "bq_highshelf", {"Freq": 6000.0, "Q": 0.7}, None),
    ("split2", "copy", {}, None),
    ("d1", "delay", {"Delay (s)": ECHO_S}, {"max-delay": 0.5}),
    ("d2", "delay", {"Delay (s)": ECHO_S}, {"max-delay": 0.5}),
    ("d3", "delay", {"Delay (s)": ECHO_S}, {"max-delay": 0.5}),
    ("mix", "mixer", {"Gain 1": 1.0}, None),
]
LINKS = [
    ("split:Out", "sq:In 1"), ("split:Out", "sq:In 2"), ("split:Out", "vca:In 1"),
    ("sq:Out", "smooth:In"), ("smooth:Out", "lg:In"), ("lg:Out", "floor:In"),
    ("floor:Out", "g_lin:In"), ("g_lin:Out", "g_clamp:In"), ("g_clamp:Out", "sum:In 1"),
    ("floor:Out", "c_lin:In"), ("c_lin:Out", "c_clamp:In"), ("c_clamp:Out", "c_slope:In"),
    ("c_slope:Out", "sum:In 2"), ("sum:Out", "ex:In"), ("ex:Out", "vca:In 2"),
    ("vca:Out", "tilt_lo:In"), ("tilt_lo:Out", "tilt_hi:In"), ("tilt_hi:Out", "bright:In"),
    ("bright:Out", "split2:In"), ("split2:Out", "mix:In 1"), ("split2:Out", "d1:In"),
    ("d1:Out", "mix:In 2"), ("d1:Out", "d2:In"), ("d2:Out", "mix:In 3"),
    ("d2:Out", "d3:In"), ("d3:Out", "mix:In 4"),
]
INPUT, OUTPUT = "split:In", "mix:Out"


def controls(fx):
    """{"node:Control": value} for these settings (config.MicFx)."""
    c = {}
    # Gate: below the threshold, 2 dB quieter per dB (a 1:3 expander).
    if fx.gate > 0:
        threshold = GATE_DB[0] + GATE_DB[1] * fx.gate
        c["g_lin:Mult"], c["g_lin:Add"] = 1.0, -threshold / 10
    else:
        c["g_lin:Mult"], c["g_lin:Add"] = 0.0, 0.0
    # Compressor: above the threshold, 1/ratio as much louder; plus makeup.
    threshold = COMP_DB[0] + COMP_DB[1] * fx.comp
    c["c_lin:Add"] = -threshold / 10
    if fx.comp > 0:
        reduce = 1 - 1 / (1 + COMP_RATIO * fx.comp)
        c["c_slope:Mult"] = -reduce / 2
        c["c_slope:Add"] = 0.7 * reduce * max(0.0, SPEECH_DB - threshold) / 20
    else:
        c["c_slope:Mult"], c["c_slope:Add"] = 0.0, 0.0
    # Color Panel: Lo..Hi tilts the tone; up brightens, past the line echoes.
    c["tilt_lo:Gain"] = -TILT_DB * fx.color_x
    c["tilt_hi:Gain"] = TILT_DB * fx.color_x
    c["bright:Gain"] = BRIGHT_DB * min(1.0, fx.color_y / 0.5)
    echo = max(0.0, (fx.color_y - 0.5) / 0.5)
    for n, tap in enumerate(ECHO_TAPS, start=2):
        c[f"mix:Gain {n}"] = echo * tap
    return {k: float(v) + 0.0 for k, v in c.items()}   # + 0.0: no "-0.0"


def props(fx):
    """The pw-cli Props that set them all live."""
    body = " ".join(f'"{k}" {v}' for k, v in controls(fx).items())
    return f"{{ params = [ {body} ] }}"
