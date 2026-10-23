"""
The mixer's two config files and the names of the nodes it creates.

    channels.conf  the channel list (hand-edited; see config/channels.conf)
    mixer.json     what the user set: output slots, FX, Bass/Mid/Treble, mic and
                   its Color Panel / Comp / Gate

Both live in ~/.config/audio-mixer/, so audio-mixer-backup covers them.
Loading is forgiving: anything missing or malformed in mixer.json falls back to
the defaults field by field, which sound exactly like the setup before output
slots existed (every channel through EasyEffects to the default output).
"""

import fcntl
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field

MIXER_DIR = os.path.expanduser("~/.config/audio-mixer")
CHANNELS_FILE = os.path.join(MIXER_DIR, "channels.conf")
STATE_FILE = os.path.join(MIXER_DIR, "mixer.json")

SLOTS = ("A1", "A2", "A3", "A4")
DEFAULT_OUTPUT = "@default"  # slot value: follow GNOME's default output device
AUTO_MIC = "@auto"           # mic value: pick a real microphone automatically
EQ_LIMIT_DB = 12.0
EQ_BANDS = ("bass", "mid", "treble")   # each channel's filters, in signal order

# Nodes outside our control that we connect to.
EE_SINK = "easyeffects_sink"
EE_SOURCE = "easyeffects_source"
# Nodes we create (see audiomixer.render).
EE_RETURN = "EE_Return"   # EasyEffects plays into this; its output is the EasyEffects strip
MIC_IN = "Mic_In"         # EasyEffects listens to this; a real mic feeds it
ALL_AUDIO = "All_Audio"   # every channel mixed, offered to apps as an input


@dataclass(frozen=True)
class Channel:
    key: str
    sink: str
    label: str
    hotkeys: tuple[str, str, str]  # mute, down, up ("-" = none)


def load_channels(path=CHANNELS_FILE):
    """[Channel] from channels.conf: key, sink, 3 hotkeys, then the label."""
    channels = []
    with open(path) as f:
        for line in f:
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 6:
                channels.append(Channel(parts[0], parts[1], " ".join(parts[5:]),
                                        tuple(parts[2:5])))
    return channels


# Names the built-in strips (and the hotkeys' targets) already use.
RESERVED_NAMES = ("mic", "easyeffects", "all audio", "fx", "all")
MAX_NAME = 20
# A channel line: key, sink, three hotkeys, then the name (and maybe a comment).
_CHANNEL_LINE = re.compile(r"^(\s*(\S+)(?:\s+\S+){4}\s+)([^#\n]*?)(\s*(?:#.*)?)$")


def rename_channel(key, label, path=CHANNELS_FILE):
    """Give a channel a new name; key, sink and hotkeys stay. Raises
    ValueError with a reason a person can read. Returns the new channel list."""
    label = label.strip()
    channels = load_channels(path)
    if not any(c.key == key for c in channels):
        raise ValueError(f"No channel {key!r}")
    if not label:
        raise ValueError("The name can't be empty")
    if "#" in label or "\n" in label:
        raise ValueError("The name can't contain #")
    if len(label) > MAX_NAME:
        raise ValueError(f"Keep it to {MAX_NAME} characters")
    taken = {n.lower() for c in channels if c.key != key for n in (c.key, c.label)}
    if label.lower() in taken or label.lower() in RESERVED_NAMES:
        raise ValueError(f"There's already a channel called {label}")
    with open(path) as f:
        lines = f.read().split("\n")
    for i, line in enumerate(lines):
        m = _CHANNEL_LINE.match(line)
        if m and m.group(2) == key and m.group(3):
            lines[i] = m.group(1) + label + m.group(4)
            break
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".channels-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)
    return load_channels(path)


def catch_all(channels):
    """The channel every unrouted app starts on (key "default")."""
    for ch in channels:
        if ch.key == "default":
            return ch
    raise ValueError('channels.conf needs a channel with key "default"')


@dataclass
class ChannelState:
    fx: bool = True
    outputs: list[str] = field(default_factory=lambda: ["A1"])
    bass: float = 0.0
    mid: float = 0.0
    treble: float = 0.0


@dataclass
class MicFx:
    """The Mic strip's VoiceMeeter controls (see audiomixer.micfx)."""
    color_x: float = 0.0   # Color Panel: -1 Lo .. 1 Hi
    color_y: float = 0.0   # 0 (flat) .. 0.5 brightness .. 1 echo
    comp: float = 0.0      # Audibility knobs, 0 (off) .. 10
    gate: float = 0.0


@dataclass
class MixerState:
    slots: dict[str, str | None]
    channels: dict[str, ChannelState]
    fx_outputs: list[str]
    mic: str
    mic_fx: MicFx = field(default_factory=MicFx)


def _slot_list(value, default):
    if not isinstance(value, list):
        return list(default)
    return [s for s in value if s in SLOTS]


def _db(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(max(-EQ_LIMIT_DB, min(EQ_LIMIT_DB, value)))


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(max(low, min(high, value)))


MIC_FX_RANGES = {"color_x": (-1.0, 1.0), "color_y": (0.0, 1.0), "comp": (0.0, 10.0), "gate": (0.0, 10.0)}


def load_state(channels, path=STATE_FILE):
    """The user's mixer settings for these channels, defaults filling every gap."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    raw_slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    slots = {"A1": DEFAULT_OUTPUT, "A2": None, "A3": None, "A4": None}
    for s in SLOTS:
        if s in raw_slots:  # a missing key keeps its default; null turns the slot off
            slots[s] = raw_slots[s] if isinstance(raw_slots[s], str) else None

    raw_channels = data.get("channels") if isinstance(data.get("channels"), dict) else {}
    states = {}
    for ch in channels:
        raw = raw_channels.get(ch.key)
        raw = raw if isinstance(raw, dict) else {}
        states[ch.key] = ChannelState(
            fx=raw["fx"] if isinstance(raw.get("fx"), bool) else True,
            outputs=_slot_list(raw.get("outputs"), ["A1"]),
            bass=_db(raw.get("bass")),
            mid=_db(raw.get("mid")),
            treble=_db(raw.get("treble")),
        )

    mic = data.get("mic") if isinstance(data.get("mic"), str) else AUTO_MIC
    raw_fx = data.get("mic_fx") if isinstance(data.get("mic_fx"), dict) else {}
    mic_fx = MicFx(**{k: _number(raw_fx.get(k), *r) for k, r in MIC_FX_RANGES.items()})
    return MixerState(slots, states, _slot_list(data.get("fx_outputs"), ["A1"]), mic, mic_fx)


def update_state(channels, change, path=STATE_FILE):
    """load -> change(state) -> save, holding a lock so two writers at once
    (a hotkey and the window) can't lose each other's change."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = change(load_state(channels, path))
        save_state(state, path)
    return state


def save_state(state, path=STATE_FILE):
    """Write atomically via a unique temp file, so readers never see half a
    file and two writers never trip over each other's temp file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".mixer-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(state), f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
