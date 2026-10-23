"""The 3-band EQ: a Mid knob between Bass and Treble on every channel."""

import json
import os
import tempfile
import unittest

from audiomixer import commands
from audiomixer.config import Channel, ChannelState, MixerState, load_state
from audiomixer.render import needs_restart, render_sinks

from tests.test_ui import UiTestBase

CHS = [Channel("default", "Default_Audio", "Desktop", ("-", "-", "-")),
       Channel("music", "Music_Audio", "Music", ("-", "-", "-"))]


def state(mid=0.0):
    s = MixerState({"A1": "@default", "A2": None, "A3": None, "A4": None},
                   {c.key: ChannelState() for c in CHS}, ["A1"], "@auto")
    s.channels["music"].mid = mid
    return s


class MidStateTest(unittest.TestCase):
    def test_mid_is_saved_flat_by_default_and_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mixer.json")
            self.assertEqual(load_state(CHS, path).channels["music"].mid, 0.0)
            with open(path, "w") as f:
                json.dump({"channels": {"music": {"mid": 40}}}, f)
            self.assertEqual(load_state(CHS, path).channels["music"].mid, 12.0)

    def test_eq_command_takes_mid(self):
        s = commands.apply_command(["eq", "music", "mid", "-4.5"], CHS, state())
        self.assertEqual(s.channels["music"].mid, -4.5)
        with self.assertRaises(ValueError):
            commands.apply_command(["eq", "music", "presence", "3"], CHS, state())


class MidRenderTest(unittest.TestCase):
    def test_mid_is_a_peaking_filter_between_bass_and_treble(self):
        out = render_sinks(CHS, state(mid=3.5))
        music = out.split('node.name = "Music_Audio"')[0].rsplit("libpipewire-module-filter-chain", 1)[1]
        self.assertIn('name = mid label = bq_peaking control = { "Freq" = 1000.0 "Q" = 0.7 "Gain" = 3.5 }', music)
        self.assertIn('{ output = "bass:Out" input = "mid:In" }', music)
        self.assertIn('{ output = "mid:Out" input = "treble:In" }', music)

    def test_turning_mid_needs_no_restart(self):
        self.assertFalse(needs_restart(render_sinks(CHS, state(0.0)), render_sinks(CHS, state(6.0))))


class MidKnobTest(UiTestBase):
    def test_three_knobs_treble_mid_bass(self):
        music = self.strip("Music_Audio")
        self.assertEqual([k.band for k in music.eq_knobs], ["treble", "mid", "bass"])
        self.assertIs(music.mid, music.eq_knobs[1])

    def test_mid_follows_the_saved_value(self):
        self.status["channels"][2]["mid"] = -2.0
        self.controller.refresh(status_too=True)
        self.assertEqual(self.strip("Music_Audio").mid.get_value(), -2.0)
