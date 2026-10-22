"""
Point EasyEffects at the mixer, and quit/relaunch it safely.

EasyEffects (8.x, Flatpak) keeps its devices in a KConfig file:

    [StreamInputs]   useDefaultInputDevice / inputDevice    (what it listens to)
    [StreamOutputs]  useDefaultOutputDevice / outputDevice  (where it plays)

"Use default input" can't work here: the default input *is* EasyEffects' own
processed mic, so it falls back to whatever it finds — on 2026-10-23 that was
the speaker monitor, which put the speakers into everyone's mic. Pinning input
to Mic_In (fed only by a real microphone) and output to EE_Return (the
EasyEffects strip) makes that impossible.

EasyEffects writes its settings when it quits, so the file is only edited while
it isn't running; a stale single-instance lock after an unclean exit makes the
next launch silently exit, so launch() clears it first.
"""

import os
import subprocess
import tempfile
import time

from .config import EE_RETURN, MIC_IN

APP = "com.github.wwmm.easyeffects"
RC_FILE = os.path.expanduser(f"~/.var/app/{APP}/config/easyeffects/db/easyeffectsrc")
LOCK_DIR = f"/run/user/{os.getuid()}/.flatpak/{APP}/tmp"


def _set_keys(text, section, values):
    """Set keys inside [section] (adding the section or keys if missing),
    leaving every other line exactly as it was."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    header = f"[{section}]"
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == header)
    except StopIteration:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(header + "\n")
        lines += [f"{k}={v}\n" for k, v in values.items()]
        return "".join(lines)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    todo = dict(values)
    for i in range(start + 1, end):
        key = lines[i].split("=", 1)[0]
        if "=" in lines[i] and key in todo:
            lines[i] = f"{key}={todo.pop(key)}\n"
    # Missing keys go after the section's last key line, before any blank gap.
    last = max((i for i in range(start, end) if lines[i].strip()), default=start)
    lines[last + 1:last + 1] = [f"{k}={v}\n" for k, v in todo.items()]
    return "".join(lines)


def set_devices(rc_text, input_device, output_device):
    """rc_text with EasyEffects pinned to these devices (None = follow default)."""
    for section, use_default, device_key, device in (
            ("StreamInputs", "useDefaultInputDevice", "inputDevice", input_device),
            ("StreamOutputs", "useDefaultOutputDevice", "outputDevice", output_device)):
        values = {use_default: "true"} if device is None else {use_default: "false", device_key: device}
        rc_text = _set_keys(rc_text, section, values)
    return rc_text


def is_running():
    return subprocess.run(["pgrep", "-f", "easyeffects --service-mode"],
                          capture_output=True).returncode == 0


def quit():
    """Quit EasyEffects cleanly (-q flushes its settings), or kill it."""
    try:
        subprocess.run(["flatpak", "run", APP, "-q"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        subprocess.run(["pkill", "-f", "easyeffects --service-mode"], capture_output=True)


def _wait_until_stopped(timeout):
    deadline = time.time() + timeout
    while is_running():
        if time.time() > deadline:
            return False
        time.sleep(0.2)
    return True


def stop(timeout=10):
    """Quit EasyEffects and wait until it's really gone — it writes its
    settings back as it exits — killing it if it won't go."""
    quit()
    if not _wait_until_stopped(timeout):
        subprocess.run(["pkill", "-f", "easyeffects --service-mode"], capture_output=True)
        _wait_until_stopped(timeout)


def launch(lockdir=LOCK_DIR):
    """Start EasyEffects in the background, clearing a stale lock first."""
    for name in ("EasyEffectsServer", "easyeffects.lock"):
        try:
            os.unlink(os.path.join(lockdir, name))
        except OSError:
            pass
    subprocess.Popen(["flatpak", "run", APP, "--service-mode", "--hide-window"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def point_at(input_device, output_device, rc_file=RC_FILE, lockdir=LOCK_DIR, quit_timeout=10):
    """Pin EasyEffects' devices; True if anything changed. A running
    EasyEffects is stopped first (it would overwrite the file) and relaunched."""
    if set_devices(_read(rc_file), input_device, output_device) == _read(rc_file):
        return False
    was_running = is_running()
    if was_running:
        stop(quit_timeout)
    _write(rc_file, set_devices(_read(rc_file), input_device, output_device))
    if was_running:
        launch(lockdir)
    return True


def point_at_mixer(rc_file=RC_FILE, lockdir=LOCK_DIR):
    """EasyEffects listens to Mic_In and plays into EE_Return."""
    return point_at(MIC_IN, EE_RETURN, rc_file, lockdir)
