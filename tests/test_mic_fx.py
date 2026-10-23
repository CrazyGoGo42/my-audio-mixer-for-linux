"""The Mic strip's VoiceMeeter controls — Color Panel (Lo/Hi, brightness, echo)
and Audibility (Comp, Gate) — as PipeWire builtin filters on Mic_In. The DSP
itself was checked with real audio by tests/spike/mic-spike.py."""

import json
import os
import re
import stat
import tempfile
import unittest

from audiomixer import commands, micfx
from audiomixer.config import Channel, ChannelState, MicFx, MixerState, load_state
from audiomixer.pwgraph import parse_dump
from audiomixer.reconcile import apply_mic_fx
from audiomixer.render import needs_restart, render_sinks

from tests.pwfake import DumpBuilder

CHS = [Channel("default", "Default_Audio", "Desktop", ("-", "-", "-"))]


def state(**fx):
    return MixerState({"A1": "@default", "A2": None, "A3": None, "A4": None},
                      {c.key: ChannelState() for c in CHS}, ["A1"], "@auto", MicFx(**fx))


class ControlsTest(unittest.TestCase):
    def test_neutral_changes_nothing(self):
        c = micfx.controls(MicFx())
        self.assertEqual((c["g_lin:Mult"], c["g_lin:Add"]), (0.0, 0.0))        # gate off: gain 1
        self.assertEqual((c["c_slope:Mult"], c["c_slope:Add"]), (0.0, 0.0))    # comp off: gain 1
        self.assertEqual((c["tilt_lo:Gain"], c["tilt_hi:Gain"], c["bright:Gain"]), (0.0, 0.0, 0.0))
        self.assertEqual((c["mix:Gain 2"], c["mix:Gain 3"], c["mix:Gain 4"]), (0.0, 0.0, 0.0))

    def test_gate_threshold_rises_with_the_knob(self):
        c = micfx.controls(MicFx(gate=8))          # threshold -37.2 dBFS, 1:3 expander
        self.assertEqual(c["g_lin:Mult"], 1.0)
        self.assertAlmostEqual(c["g_lin:Add"], 3.72)

    def test_full_comp_is_4_to_1_from_minus_40_with_makeup(self):
        c = micfx.controls(MicFx(comp=10))
        self.assertAlmostEqual(c["c_lin:Add"], 4.0)
        self.assertAlmostEqual(c["c_slope:Mult"], -0.375)
        self.assertAlmostEqual(c["c_slope:Add"], 0.7 * 0.75 * 22 / 20)

    def test_color_panel_lo_hi_brightness_and_echo(self):
        c = micfx.controls(MicFx(color_x=1.0, color_y=1.0))
        self.assertEqual((c["tilt_lo:Gain"], c["tilt_hi:Gain"]), (-5.0, 5.0))
        self.assertEqual(c["bright:Gain"], 7.0)
        self.assertEqual([round(c[f"mix:Gain {n}"], 3) for n in (2, 3, 4)], [0.55, 0.3, 0.17])
        lower = micfx.controls(MicFx(color_x=-0.5, color_y=0.25))   # below the line: no echo yet
        self.assertEqual((lower["tilt_lo:Gain"], lower["bright:Gain"], lower["mix:Gain 2"]), (2.5, 3.5, 0.0))

    def test_every_setting_stays_inside_pipewires_control_ranges(self):
        for x in (-1, 0, 1):
            for y in (0, 0.5, 1):
                for knob in (0, 0.1, 5, 10):
                    for name, value in micfx.controls(MicFx(x, y, knob, knob)).items():
                        low, high = micfx.RANGES[name.split(":")[1]]
                        self.assertTrue(low <= value <= high, (name, value))


class StateTest(unittest.TestCase):
    def test_saved_with_defaults_and_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mixer.json")
            self.assertEqual(load_state(CHS, path).mic_fx, MicFx())
            with open(path, "w") as f:
                json.dump({"mic_fx": {"color_x": -7, "color_y": 0.4, "comp": 99, "gate": "loud"}}, f)
            self.assertEqual(load_state(CHS, path).mic_fx, MicFx(-1.0, 0.4, 10.0, 0.0))

    def test_commands(self):
        s = commands.apply_command(["mic", "comp", "5"], CHS, state())
        s = commands.apply_command(["mic", "gate", "2.5"], CHS, s)
        s = commands.apply_command(["mic", "color", "-0.5", "0.8"], CHS, s)
        self.assertEqual(s.mic_fx, MicFx(-0.5, 0.8, 5.0, 2.5))
        self.assertEqual(commands.apply_command(["mic", "auto"], CHS, s).mic, "@auto")
        for bad in (["mic", "comp", "lots"], ["mic", "color", "1"], ["mic", "gate", "x"]):
            with self.assertRaises(ValueError, msg=bad):
                commands.apply_command(bad, CHS, state())

    def test_status_has_the_mic_fx(self):
        g = parse_dump(DumpBuilder().dump())
        st = commands.status_dict(CHS, state(comp=3.0), g)
        self.assertEqual(st["mic_fx"], {"color_x": 0.0, "color_y": 0.0, "comp": 3.0, "gate": 0.0})


class RenderTest(unittest.TestCase):
    def mic_module(self, s):
        text = render_sinks(CHS, s)
        return next(m for m in text.split("\n    {") if 'node.name = "Mic_In"' in m)

    def test_mic_in_is_a_builtin_filter_chain_with_the_same_node_names(self):
        m = self.mic_module(state())
        self.assertIn("libpipewire-module-filter-chain", m)
        self.assertIn("flags = [ nofail ]", m)
        self.assertIn('capture.props = { node.name = "Mic_In_in" node.autoconnect = false node.passive = true', m)
        self.assertIn('playback.props = { node.name = "Mic_In" media.class = "Audio/Source"', m)
        for label in ("log", "exp", "linear", "clamp", "mult", "mixer", "delay", "bq_lowpass", "bq_lowshelf"):
            self.assertIn(f"label = {label}", m)
        self.assertNotIn("ladspa", m)

    def test_starts_with_the_saved_settings(self):
        m = self.mic_module(state(comp=10))
        self.assertRegex(m, r'name = c_slope label = linear control = \{ "Mult" = -0\.375 "Add" = 0\.57')

    def test_every_link_joins_nodes_that_exist(self):
        m = self.mic_module(state())
        names = set(re.findall(r"name = (\w+) label", m))
        for out_node, in_node in re.findall(r'output = "(\w+):[^"]+" input = "(\w+):', m):
            self.assertIn(out_node, names)
            self.assertIn(in_node, names)

    def test_changing_mic_settings_needs_no_restart(self):
        self.assertFalse(needs_restart(render_sinks(CHS, state()),
                                       render_sinks(CHS, state(color_x=0.3, color_y=0.9, comp=4, gate=6))))


class ApplyLiveTest(unittest.TestCase):
    def test_sets_every_control_on_the_mic_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "calls")
            fake = os.path.join(tmp, "pw-cli")
            with open(fake, "w") as f:
                f.write('#!/bin/sh\nfor a in "$@"; do printf "%s|" "$a"; done >> ' + log + '\necho >> ' + log + '\n')
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
            old = os.environ["PATH"]
            os.environ["PATH"] = tmp + os.pathsep + old
            try:
                g = parse_dump(DumpBuilder().add("Mic_In_in", "Stream/Input/Audio").dump())
                apply_mic_fx(g, state(gate=8))
            finally:
                os.environ["PATH"] = old
            with open(log) as f:
                (call,) = f.read().splitlines()
        self.assertTrue(call.startswith(f"set-param|{g.nodes['Mic_In_in'].id}|Props|{{ params = [ "))
        self.assertIn('"g_lin:Add" 3.72', call)
        self.assertEqual(call.count('" '), len(micfx.controls(MicFx())))



class DaemonTest(unittest.TestCase):
    def test_reapplied_when_pipewire_brings_the_mic_back(self):
        from tests.test_daemon_helpers import load_daemon
        d = load_daemon()
        d.CHANNEL_LIST = CHS
        d.reconcile_once = lambda graph: None
        applied = []
        d.apply_eq = lambda graph, channels, st: None
        d.apply_mic_fx = lambda graph, st: applied.append(graph.nodes["Mic_In_in"].id)
        first = parse_dump(DumpBuilder().add("Mic_In_in", "Stream/Input/Audio").dump())
        d._patch(first)
        d._patch(first)                            # nothing new: not again
        again = parse_dump(DumpBuilder().add("x", "Audio/Sink").add("Mic_In_in", "Stream/Input/Audio").dump())
        d._patch(again)                            # PipeWire restarted: new node id
        self.assertEqual(len(applied), 2)
        self.assertNotEqual(applied[0], applied[1])


if __name__ == "__main__":
    unittest.main()
