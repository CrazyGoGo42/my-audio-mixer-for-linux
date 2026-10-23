#!/usr/bin/env python3
"""
Mic spike: runs the REAL rendered Mic_In filter-chain (renamed Spike_Mic so it
can't touch the live one) as a short-lived standalone PipeWire client, plays
test signals through it and measures what comes out. Checks the Color Panel /
Comp / Gate maths (audiomixer.micfx) against real audio. Nothing it creates is
linked to speakers or mics; everything is gone when it ends.

Usage: python3 tests/spike/mic-spike.py
"""
import json
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "lib"))
from audiomixer import micfx  # noqa: E402
from audiomixer.config import MicFx  # noqa: E402
from audiomixer.render import _mic  # noqa: E402

RATE = 48000
HEADER = """context.properties = { log.level = 2 }
context.spa-libs = { audio.convert.* = audioconvert/libspa-audioconvert support.* = support/libspa-support }
context.modules = [
    { name = libpipewire-module-rt flags = [ ifexists nofail ] }
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-adapter }
"""


def db(d):
    return 10 ** (d / 20)


def write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples))


def tone(level_db, seconds):
    return [math.sin(2 * math.pi * 300 * n / RATE) * db(level_db) * math.sqrt(2) for n in range(int(RATE * seconds))]


def level(xs):
    ms = sum(x * x for x in xs) / max(1, len(xs))
    return 10 * math.log10(ms) if ms > 0 else -200.0


def run(tmp, fx):
    """Play the test signal through the spike with these settings; returns the
    output's left channel, aligned so index 0 = the start of the signal."""
    module = "\n".join(_mic(MicFx())).replace("Mic_In", "Spike_Mic").replace(
        'node.passive = true', 'node.passive = true media.class = "Audio/Sink"')
    conf = os.path.join(tmp, "spike.conf")
    with open(conf, "w") as f:
        f.write(HEADER + module + "\n]\n")
    pw = subprocess.Popen(["pipewire", "-c", conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        node = next(o["id"] for o in json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout)
                    if ((o.get("info") or {}).get("props") or {}).get("node.name") == "Spike_Mic_in")
        subprocess.run(["pw-cli", "set-param", str(node), "Props", micfx.props(fx)], capture_output=True)
        out = os.path.join(tmp, "out.wav")
        rec = subprocess.Popen(["pw-record", "--target", "Spike_Mic", "--format", "s16", "--rate", str(RATE),
                                "--channels", "2", out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        subprocess.run(["pw-play", "--target", "Spike_Mic_in", os.path.join(tmp, "test.wav")], capture_output=True)
        time.sleep(1.0)
        rec.terminate()
        rec.wait()
    finally:
        pw.terminate()
        pw.wait()
    with wave.open(out) as w:
        n, ch = w.getnframes(), w.getnchannels()
        data = struct.unpack(f"<{n * ch}h", w.readframes(n))
    left = [data[i] / 32768 for i in range(0, len(data), ch)]
    marker = next(i for i, v in enumerate(left) if abs(v) > 0.5)   # the -3 dB start beep
    return left[marker + int(0.3 * RATE):]


def main():
    random.seed(1)
    with tempfile.TemporaryDirectory() as tmp:
        # beep (alignment), 0.2 s gap, then 1 s each: noise -50, tone -20, tone -40, tone -8;
        # 1 s quiet (the tone's echoes die out), a click, 1 s quiet
        signal = tone(-3, 0.1) + [0.0] * int(0.2 * RATE)
        signal += [random.gauss(0, db(-50)) for _ in range(RATE)]
        signal += tone(-20, 1) + tone(-40, 1) + tone(-8, 1) + [0.0] * RATE + [0.5] + [0.0] * RATE
        write_wav(os.path.join(tmp, "test.wav"), signal)
        seg = {"noise -50": (0.2, 0.9), "tone -20": (1.2, 1.9), "tone -40": (2.2, 2.9), "tone -8": (3.2, 3.9)}
        fails = 0
        for name, fx, expect in (
            ("neutral", MicFx(), {"noise -50": -50, "tone -20": -20, "tone -40": -40, "tone -8": -8}),
            ("gate 8", MicFx(gate=8), {"noise -50": -75.6, "tone -20": -20, "tone -40": -45.6, "tone -8": -8}),
            ("comp 10", MicFx(comp=10), {"tone -20": -23.5, "tone -40": -28.5, "tone -8": -20.5}),
        ):
            out = run(tmp, fx)
            if any(v != v for v in out):
                print(f"FAIL  {name}: NaN in the output")
                fails += 1
                continue
            for part, (a, b) in seg.items():
                if part in expect:
                    got = level(out[int(a * RATE):int(b * RATE)])
                    ok = abs(got - expect[part]) < 1.5
                    fails += not ok
                    print(f"{'PASS' if ok else 'FAIL'}  {name}: {part} -> {got:6.1f} dB (expected {expect[part]})")
        out = run(tmp, MicFx(color_y=1.0))
        # The click is the loudest thing after the quiet second; its echoes follow
        # every ECHO_S at the tap levels (relative to the click).
        start = int(4.95 * RATE)
        click = max(range(start, start + RATE), key=lambda i: abs(out[i]))
        peaks = [max(abs(v) for v in out[click + int(n * micfx.ECHO_S * RATE) - 50:
                                          click + int(n * micfx.ECHO_S * RATE) + 50]) / abs(out[click])
                 for n in (1, 2, 3)]
        ok = all(abs(p - t) < 0.05 for p, t in zip(peaks, micfx.ECHO_TAPS))
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  echo: taps {', '.join(f'{p:.2f}' for p in peaks)} of the click"
              f" (expected {', '.join(f'{t:.2f}' for t in micfx.ECHO_TAPS)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
