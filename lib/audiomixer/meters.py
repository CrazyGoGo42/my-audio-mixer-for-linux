"""
Level meters for the mixer window: one low-rate `parec` per meter, reporting
the peak of each 25 ms chunk.

A sink's monitor carries the signal *before* the sink's own volume, so a
strip meter shows `peak × (volume%/100)³` — what you actually hear from it.
Sources (Mic_In, All_Audio) are metered directly.
"""

import array
import subprocess
import threading

RATE = 8000
CHUNK = 800  # bytes: 200 stereo s16 frames = 25 ms at 8 kHz


def peak(chunk):
    """Peak of s16le samples as 0.0–1.0."""
    samples = array.array("h", chunk[:len(chunk) // 2 * 2])
    if not samples:
        return 0.0
    return min(1.0, max(max(samples), -min(samples)) / 32768)


def post_fader(level, volume_pct):
    """What a level becomes after a pactl-percent volume (cubic), 0.0–1.0."""
    return max(0.0, min(1.0, level * (volume_pct / 100) ** 3))


def meter_args(name, kind):
    return [f"--device={name}.monitor"] if kind == "sink" else [f"--device={name}"]


class MeterReader(threading.Thread):
    """Runs parec with `args` and calls on_level(peak) for every chunk until stop()."""

    def __init__(self, args, on_level):
        super().__init__(daemon=True)
        self.args = list(args)
        self.on_level = on_level
        self.process = None
        self._lock = threading.Lock()
        self._stopping = False

    def run(self):
        with self._lock:
            if self._stopping:
                return
            try:
                self.process = subprocess.Popen(
                    ["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=2",
                     "--latency-msec=50", *self.args],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                return
        while not self._stopping:
            data = self.process.stdout.read(CHUNK)
            if not data:
                break
            if not self._stopping:
                self.on_level(peak(data))

    def stop(self):
        with self._lock:
            self._stopping = True
            if self.process and self.process.poll() is None:
                self.process.kill()
        if self.process:
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        if self.is_alive():
            self.join(timeout=2)
