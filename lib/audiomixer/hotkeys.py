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

GNOME_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
OUR_COMMANDS = ("audio-channel-control", "audio-mixer out")

# With NumLock off the numpad sends different keysyms; bind those too.
NUMLOCK_OFF = {
    "KP_0": "KP_Insert", "KP_1": "KP_End", "KP_2": "KP_Down", "KP_3": "KP_Next",
    "KP_4": "KP_Left", "KP_5": "KP_Begin", "KP_6": "KP_Right", "KP_7": "KP_Home",
    "KP_8": "KP_Up", "KP_9": "KP_Prior", "KP_Decimal": "KP_Delete",
}
NUMLOCK_ON = {off: on for on, off in NUMLOCK_OFF.items()}
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
    """Safe to bind globally: has Ctrl/Alt/Super, or is an F- or media key.
    A plain letter (even with Shift) or a bare keypad key would break typing
    everywhere."""
    mods, key = _split(accel)
    if not key:
        return False
    return bool(mods & {MOD_ALIASES.get(m, m) for m in STRONG_MODS}) or bool(
        re.fullmatch(r"F\d{1,2}", key) or key.startswith("XF86"))


def canonical(accel):
    """The NumLock-on name for a keypad key pressed with NumLock off
    (<Ctrl>KP_Left -> <Ctrl>KP_4): its twin is bound for it anyway."""
    key = _split(accel)[1]
    return accel[: len(accel) - len(key)] + NUMLOCK_ON[key] if key in NUMLOCK_ON else accel


def _same(a, b):
    return _split(canonical(a)) == _split(canonical(b))


def assign(keys, action, accel):
    """keys with `action` set to accel (None clears it); a combination already
    used by another action moves here — one key, one action."""
    accel = canonical(accel) if accel else accel
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
    """audio-channel-control does volume, mute and A1–A4 toggles, and shows the OSD."""
    target, what = action.split(":", 1)
    return f"{bin_dir}/audio-channel-control {target} {what}"


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
# One `dconf dump` + one `dconf load` (plus a reset per leftover) instead of
# ~130 gsettings calls: applying takes milliseconds, so the window can suspend
# our shortcuts while you press a new combination.

DCONF_DIR = "/org/gnome/settings-daemon/plugins/media-keys/"


def _dconf(args, stdin=None):
    r = subprocess.run(["dconf", *args], input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"dconf {args[0]}: {r.stderr.strip() or 'failed'}")
    return r.stdout


def _gv(s):
    """A GVariant string literal."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _ungv(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        value = value[1:-1]
    return re.sub(r"\\(.)", r"\1", value)


def _read(dconf):
    """(listed paths, {path: {key: value}}) of the custom keybindings."""
    listed, entries, section = [], {}, None
    for line in dconf(["dump", DCONF_DIR]).splitlines():
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif "=" in line and section:
            key, _, value = line.partition("=")
            if section == "/" and key == "custom-keybindings":
                listed = [_ungv(v) for v in re.findall(r"'(?:[^'\\]|\\.)*'", value)]
            elif section != "/":
                entries.setdefault(DCONF_DIR + section + "/", {})[key] = _ungv(value)
    return listed, entries


def _ours(entry):
    return any(c in entry.get("command", "") for c in OUR_COMMANDS)


def apply_to_gnome(binding_list, dconf=_dconf):
    """Replace our GNOME shortcuts with binding_list; leave everyone else's."""
    listed, entries = _read(dconf)
    kept = [p for p in listed if not _ours(entries.get(p, {}))]
    old_ours = [p for p, e in entries.items() if _ours(e)]
    lines, ours, n = [], [], 100
    for name, command, accel in binding_list:
        while f"{GNOME_PATH}/custom{n}/" in kept:
            n += 1
        path = f"{GNOME_PATH}/custom{n}/"
        n += 1
        ours.append(path)
        lines += [f"[{path[len(DCONF_DIR):].rstrip('/')}]", f"binding={_gv(accel)}",
                  f"command={_gv(command)}", f"name={_gv(name)}", ""]
    paths = kept + ours
    head = ["[/]", "custom-keybindings=" + ("[" + ", ".join(_gv(p) for p in paths) + "]" if paths else "@as []"), ""]
    dconf(["load", DCONF_DIR], "\n".join(head + lines) + "\n")
    for path in old_ours:
        if path not in ours:
            dconf(["reset", "-f", path])
    return len(ours)


def remove_from_gnome(dconf=_dconf):
    apply_to_gnome([], dconf)


# While the window waits for you to press a new combination our shortcuts are
# out of GNOME (or GNOME would grab the keys first). A marker next to
# hotkeys.json records that, so a window that dies mid-capture can't leave you
# without hotkeys: the next window start, or the router daemon, puts them back.

def _marker(path=None):
    return os.path.join(os.path.dirname(path or HOTKEYS_FILE), ".hotkeys-suspended")


def suspended(path=None):
    return os.path.exists(_marker(path))


def suspend(dconf=_dconf, path=None):
    os.makedirs(os.path.dirname(_marker(path)), exist_ok=True)
    open(_marker(path), "w").close()
    remove_from_gnome(dconf)


def resume(binding_list, dconf=_dconf, path=None):
    """Bind binding_list and clear the suspended marker."""
    n = apply_to_gnome(binding_list, dconf)
    try:
        os.unlink(_marker(path))
    except FileNotFoundError:
        pass
    return n


def heal(channels, bin_dir, path=None, dconf=_dconf):
    """Put our shortcuts back if a capture never finished. False: nothing to do."""
    if not suspended(path):
        return False
    resume(bindings(load(channels, path), bin_dir, channels), dconf, path)
    return True


# -------------------------------------------------------------------- CLI

def cli(args, channels, bin_dir, path=None, gs=_dconf):
    """`audio-mixer hotkeys list | apply | set <action> <accel> | clear <action>`.
    Returns (exit code, text to print)."""
    keys = load(channels, path)
    known = dict(actions(channels))
    if args[:1] == ["list"]:
        width = max(len(a) for a in known)
        return 0, "\n".join(f"{a:{width}}  {keys.get(a, '-'):24}  {label}" for a, label in known.items())
    if args[:1] == ["apply"]:
        save(keys, path)
        try:
            n = resume(bindings(keys, bin_dir, channels), gs, path)
        except RuntimeError as e:
            return 1, f"could not update GNOME shortcuts ({e})"
        return 0, f"{n} keyboard shortcuts configured"
    if args[:1] in (["set"], ["clear"]) and len(args) == (3 if args[0] == "set" else 2):
        action = args[1]
        if action not in known:
            return 2, f"unknown action {action!r} (see `audio-mixer hotkeys list`)"
        accel = args[2] if args[0] == "set" else None
        if accel is not None and not acceptable(accel):
            return 2, f"{accel!r} needs Ctrl, Alt or Super (or an F- or media key)"
        keys = assign(keys, action, accel)
        save(keys, path)
        try:
            resume(bindings(keys, bin_dir, channels), gs, path)
        except RuntimeError as e:
            return 1, f"saved, but could not update GNOME shortcuts ({e})"
        return 0, ""
    return 2, "usage: audio-mixer hotkeys list | apply | set <action> <accel> | clear <action>"
