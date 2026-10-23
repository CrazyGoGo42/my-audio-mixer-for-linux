"""
Hotkeys: ~/.config/audio-mixer/hotkeys.json is the one source of truth,
{action: accelerator}, turned into GNOME custom shortcuts.

Actions are "<target>:<what>": target = a channel key, "mic", "fx" (the
EasyEffects strip) or "all" (All Audio); what = mute / down / up, or A1–A4
for channels and the EasyEffects strip. Volume/mute keys run the fast bash
audio-channel-control; slot keys run `audio-mixer out <target> <slot> toggle`.

The first load (no file yet) takes the numpad keys from channels.conf, so an
existing install keeps exactly the shortcuts it had.
"""

import json
import os
import re
import subprocess
import tempfile

from .config import MIXER_DIR

HOTKEYS_FILE = os.path.join(MIXER_DIR, "hotkeys.json")
SLOTS = ("A1", "A2", "A3", "A4")
WHAT = {"mute": "Mute", "down": "Vol Down", "up": "Vol Up"}

GNOME_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_SCHEMA = GNOME_KEYS + ".custom-keybinding"
GNOME_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
OUR_COMMANDS = ("audio-channel-control", "audio-mixer out")

# With NumLock off the numpad sends different keysyms; bind those too.
NUMLOCK_OFF = {
    "KP_0": "KP_Insert", "KP_1": "KP_End", "KP_2": "KP_Down", "KP_3": "KP_Next",
    "KP_4": "KP_Left", "KP_5": "KP_Begin", "KP_6": "KP_Right", "KP_7": "KP_Home",
    "KP_8": "KP_Up", "KP_9": "KP_Prior", "KP_Decimal": "KP_Delete",
}
STRONG_MODS = {"ctrl", "control", "primary", "alt", "mod1", "super", "meta", "hyper", "mod4"}
MOD_ALIASES = {"ctrl": "control", "primary": "control", "mod1": "alt", "mod4": "super"}


def _targets(channels):
    return ([("mic", "Mic", False)] + [(c.key, c.label, True) for c in channels]
            + [("fx", "EasyEffects", True), ("all", "All Audio", False)])


def actions(channels):
    """[(action, label)] in display order."""
    out = []
    for target, label, has_slots in _targets(channels):
        out += [(f"{target}:{what}", f"{label} {name}") for what, name in WHAT.items()]
        if has_slots:
            out += [(f"{target}:{slot}", f"{label} {slot}") for slot in SLOTS]
    return out


def _split(accel):
    mods = {MOD_ALIASES.get(m.lower(), m.lower()) for m in re.findall(r"<(\w+)>", accel or "")}
    return mods, re.sub(r"<\w+>", "", accel or "")


def acceptable(accel):
    """Safe to bind globally: has Ctrl/Alt/Super, or is an F-, keypad or media
    key. A plain letter (even with Shift) would break typing everywhere."""
    mods, key = _split(accel)
    if not key:
        return False
    return bool(mods & {MOD_ALIASES.get(m, m) for m in STRONG_MODS}) or bool(
        re.fullmatch(r"F\d{1,2}", key) or key.startswith(("KP_", "XF86")))


def _same(a, b):
    return _split(a) == _split(b)


def assign(keys, action, accel):
    """keys with `action` set to accel (None clears it); a combination already
    used by another action moves here — one key, one action."""
    new = {a: k for a, k in keys.items() if a != action and not (accel and _same(k, accel))}
    if accel:
        new[action] = accel
    return new


def load(channels, path=None):
    path = path or HOTKEYS_FILE
    known = {a for a, _ in actions(channels)}
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {a: k for a, k in data.items() if a in known and isinstance(k, str) and k}
    except (OSError, ValueError):
        pass
    keys = {}  # first run: today's numpad keys from channels.conf
    for ch in channels:
        for what, sym in zip(("mute", "down", "up"), ch.hotkeys):
            if sym != "-":
                keys[f"{ch.key}:{what}"] = f"<Ctrl>{sym}"
    return keys


def save(keys, path=None):
    path = path or HOTKEYS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".hotkeys-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(keys, f, indent=2)
    os.replace(tmp, path)


def command_for(action, bin_dir):
    target, what = action.split(":", 1)
    if what in WHAT:
        return f"{bin_dir}/audio-channel-control {target} {what}"
    return f"{bin_dir}/audio-mixer out {target} {what} toggle"


def bindings(keys, bin_dir, channels):
    """[(name, command, accel)] for GNOME, NumLock-off twins included."""
    out = []
    for action, label in actions(channels):
        accel = keys.get(action)
        if not accel:
            continue
        command = command_for(action, bin_dir)
        out.append((label, command, accel))
        mods_text = accel[: len(accel) - len(_split(accel)[1])]
        twin = NUMLOCK_OFF.get(_split(accel)[1])
        if twin:
            out.append((f"{label} (NumLock off)", command, mods_text + twin))
    return out


# ------------------------------------------------------------------ GNOME

def _gsettings(*args):
    return subprocess.run(["gsettings", *args], capture_output=True, text=True).stdout.strip()


def _gv(s):
    """A GVariant string literal."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _foreign_paths(gs):
    """The user's own custom shortcuts; ours (recognised by command) are reset."""
    kept = []
    for path in re.findall(r"'([^']*)'", gs("get", GNOME_KEYS, "custom-keybindings")):
        if any(c in gs("get", f"{GNOME_SCHEMA}:{path}", "command") for c in OUR_COMMANDS):
            for k in ("name", "command", "binding"):
                gs("reset", f"{GNOME_SCHEMA}:{path}", k)
        else:
            kept.append(path)
    return kept


def _set_list(gs, paths):
    gs("set", GNOME_KEYS, "custom-keybindings",
       "[" + ", ".join(_gv(p) for p in paths) + "]" if paths else "@as []")


def apply_to_gnome(binding_list, gs=_gsettings):
    """Replace our GNOME shortcuts with binding_list; leave everyone else's."""
    kept = _foreign_paths(gs)
    ours, n = [], 100
    for name, command, accel in binding_list:
        while f"{GNOME_PATH}/custom{n}/" in kept:
            n += 1
        path = f"{GNOME_PATH}/custom{n}/"
        n += 1
        for key, value in (("name", name), ("command", command), ("binding", accel)):
            gs("set", f"{GNOME_SCHEMA}:{path}", key, _gv(value))
        ours.append(path)
    _set_list(gs, kept + ours)
    return len(ours)


def remove_from_gnome(gs=_gsettings):
    _set_list(gs, _foreign_paths(gs))


# -------------------------------------------------------------------- CLI

def cli(args, channels, bin_dir, path=None, gs=_gsettings):
    """`audio-mixer hotkeys list | apply | set <action> <accel> | clear <action>`.
    Returns (exit code, text to print)."""
    keys = load(channels, path)
    known = dict(actions(channels))
    if args[:1] == ["list"]:
        width = max(len(a) for a in known)
        return 0, "\n".join(f"{a:{width}}  {keys.get(a, '-'):24}  {label}" for a, label in known.items())
    if args[:1] == ["apply"]:
        save(keys, path)
        n = apply_to_gnome(bindings(keys, bin_dir, channels), gs)
        return 0, f"{n} keyboard shortcuts configured"
    if args[:1] in (["set"], ["clear"]) and len(args) == (3 if args[0] == "set" else 2):
        action = args[1]
        if action not in known:
            return 2, f"unknown action {action!r} (see `audio-mixer hotkeys list`)"
        accel = args[2] if args[0] == "set" else None
        if accel is not None and not acceptable(accel):
            return 2, f"{accel!r} needs Ctrl, Alt or Super (or an F-, keypad or media key)"
        keys = assign(keys, action, accel)
        save(keys, path)
        apply_to_gnome(bindings(keys, bin_dir, channels), gs)
        return 0, ""
    return 2, "usage: audio-mixer hotkeys list | apply | set <action> <accel> | clear <action>"
