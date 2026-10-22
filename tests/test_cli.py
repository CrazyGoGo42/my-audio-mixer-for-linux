import unittest

from audiomixer import commands as CLI
from audiomixer.config import Channel, ChannelState, MixerState
from audiomixer.pwgraph import parse_dump

from tests.pwfake import DumpBuilder

CHS = [Channel("default", "Default_Audio", "Desktop", ("KP_1", "KP_4", "KP_7")),
       Channel("discord", "Discord_Audio", "Discord", ("KP_2", "KP_5", "KP_8")),
       Channel("music", "Music_Audio", "Music", ("KP_3", "KP_6", "KP_9"))]
HDMI = "alsa_output.pci-0000_01_00.1.hdmi-stereo-extra1"


def fresh():
    return MixerState({"A1": "@default", "A2": None, "A3": None, "A4": None},
                      {c.key: ChannelState() for c in CHS}, ["A1"], "@auto")


def run(*argv, state=None):
    return CLI.apply_command(list(argv), CHS, state or fresh())


class ApplyCommandTest(unittest.TestCase):
    def test_fx_toggle_flips_only_that_channel(self):
        s = run("fx", "music", "toggle")
        self.assertEqual({k: c.fx for k, c in s.channels.items()},
                         {"default": True, "discord": True, "music": False})
        self.assertTrue(run("fx", "music", "toggle", state=s).channels["music"].fx)
        self.assertFalse(run("fx", "discord", "off").channels["discord"].fx)

    def test_channel_can_be_named_by_label(self):
        self.assertFalse(run("fx", "Desktop", "off").channels["default"].fx)

    def test_out_on_fx_channel_is_remembered_for_when_fx_turns_off(self):
        s = run("out", "music", "A2", "on")  # FX still on: plays via EasyEffects for now
        self.assertTrue(s.channels["music"].fx)
        self.assertEqual(s.channels["music"].outputs, ["A1", "A2"])
        s = run("out", "music", "A1", "off", state=s)
        self.assertEqual(s.channels["music"].outputs, ["A2"])
        self.assertEqual(run("out", "music", "A2", "toggle", state=s).channels["music"].outputs, [])

    def test_out_fx_sets_the_easyeffects_strip(self):
        s = run("out", "fx", "A2", "on")
        self.assertEqual(s.fx_outputs, ["A1", "A2"])

    def test_outputs_stay_in_slot_order(self):
        s = run("out", "music", "A3", "on", state=run("out", "music", "A1", "off"))
        s = run("out", "music", "A1", "on", state=s)
        self.assertEqual(s.channels["music"].outputs, ["A1", "A3"])

    def test_slot_default_device_and_none(self):
        s = run("slot", "A2", HDMI)
        self.assertEqual(s.slots["A2"], HDMI)
        self.assertIsNone(run("slot", "A1", "none").slots["A1"])
        self.assertEqual(run("slot", "A3", "default").slots["A3"], "@default")

    def test_eq_is_clamped_to_12_db(self):
        self.assertEqual(run("eq", "music", "bass", "30").channels["music"].bass, 12.0)
        self.assertEqual(run("eq", "music", "treble", "-3.5").channels["music"].treble, -3.5)

    def test_mic_auto_and_pinned(self):
        self.assertEqual(run("mic", "alsa_input.usb-blue").mic, "alsa_input.usb-blue")
        self.assertEqual(run("mic", "auto", state=run("mic", "x")).mic, "@auto")

    def test_input_is_not_mutated(self):
        s = fresh()
        run("fx", "music", "off", state=s)
        self.assertTrue(s.channels["music"].fx)

    def test_bad_input_is_a_clear_error(self):
        for argv in (["fx", "games", "on"], ["out", "music", "A9", "on"], ["slot", "B1", "none"],
                     ["eq", "music", "mid", "3"], ["eq", "music", "bass", "loud"],
                     ["fx", "music", "maybe"], ["teleport"], []):
            with self.assertRaises(ValueError, msg=argv):
                run(*argv)


class StatusTest(unittest.TestCase):
    def test_status_json_shape(self):
        g = parse_dump(DumpBuilder()
                       .add("alsa_output.speakers", "Audio/Sink", ins=("playback_FL",),
                            props={"node.description": "Speakers", "device.api": "alsa"})
                       .add("alsa_input.usb-blue", "Audio/Source", outs=("capture_MONO",),
                            props={"node.description": "Blue mic", "device.api": "alsa"})
                       .default(sink="alsa_output.speakers").dump())
        s = fresh()
        s.slots["A2"] = HDMI  # not plugged in
        s.channels["music"] = ChannelState(fx=False, outputs=["A2"], bass=3.0)
        out = CLI.status_dict(CHS, s, g)
        self.assertEqual(out["slots"]["A1"], {"value": "@default", "device": "alsa_output.speakers",
                                              "description": "Speakers"})
        self.assertEqual(out["slots"]["A2"], {"value": HDMI, "device": None, "description": None})
        self.assertEqual(out["channels"][2], {"key": "music", "label": "Music", "sink": "Music_Audio",
                                              "fx": False, "outputs": ["A2"], "bass": 3.0, "treble": 0.0})
        self.assertEqual(out["fx_outputs"], ["A1"])
        self.assertEqual(out["mic"], {"value": "@auto", "device": "alsa_input.usb-blue"})

    def test_devices_lists_real_outputs_and_mics_only(self):
        g = parse_dump(DumpBuilder()
                       .add("alsa_output.speakers", "Audio/Sink", props={"node.description": "Speakers",
                                                                         "device.api": "alsa"})
                       .add("alsa_input.usb-blue", "Audio/Source", props={"node.description": "Blue mic",
                                                                          "device.api": "alsa"})
                       .add("Music_Audio", "Audio/Sink")
                       .add("easyeffects_sink", "Audio/Sink", props={"node.virtual": True})
                       .add("easyeffects_source", "Audio/Source/Virtual").dump())
        self.assertEqual(CLI.devices_list(CHS, g), [
            {"kind": "output", "name": "alsa_output.speakers", "description": "Speakers"},
            {"kind": "mic", "name": "alsa_input.usb-blue", "description": "Blue mic"}])


if __name__ == "__main__":
    unittest.main()
