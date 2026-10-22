import json
import os
import tempfile
import unittest

from audiomixer.config import (
    ChannelState, MixerState, catch_all, load_channels, load_state, save_state,
)

CHANNELS_CONF = """\
# key     sink            mute        down        up           label
default   Default_Audio   KP_1        KP_4        KP_7         Desktop
discord   Discord_Audio   KP_2        KP_5        KP_8         Discord
music     Music_Audio     KP_3        KP_6        KP_9         Music   # trailing comment
too       Short_Line      KP_1
voice     Voice_Chat      -           KP_5        KP_8         Voice Chat  # note
"""


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.channels_path = os.path.join(self.dir.name, "channels.conf")
        with open(self.channels_path, "w") as f:
            f.write(CHANNELS_CONF)
        self.chs = load_channels(self.channels_path)
        self.state_path = os.path.join(self.dir.name, "mixer.json")

    def write_state(self, text):
        with open(self.state_path, "w") as f:
            f.write(text)

    # --- channels.conf -----------------------------------------------------

    def test_parses_channels_conf_with_multiword_label_and_comments(self):
        ch = self.chs[-1]
        self.assertEqual((ch.key, ch.sink, ch.label, ch.hotkeys),
                         ("voice", "Voice_Chat", "Voice Chat", ("-", "KP_5", "KP_8")))

    def test_short_lines_and_comments_are_skipped(self):
        self.assertEqual([c.key for c in self.chs], ["default", "discord", "music", "voice"])
        self.assertEqual(self.chs[2].label, "Music")

    def test_catch_all_is_key_default(self):
        self.assertEqual(catch_all(self.chs).sink, "Default_Audio")

    def test_catch_all_missing_is_an_error(self):
        with self.assertRaises(ValueError):
            catch_all(self.chs[1:])

    # --- mixer.json --------------------------------------------------------

    def test_missing_state_file_gives_todays_sound(self):
        s = load_state(self.chs, os.path.join(self.dir.name, "missing.json"))
        self.assertEqual(s.slots, {"A1": "@default", "A2": None, "A3": None, "A4": None})
        self.assertEqual(sorted(s.channels), ["default", "discord", "music", "voice"])
        self.assertTrue(all(c.fx and c.outputs == ["A1"] and c.bass == 0 and c.treble == 0
                            for c in s.channels.values()))
        self.assertEqual((s.fx_outputs, s.mic), (["A1"], "@auto"))

    def test_corrupt_state_loads_defaults(self):
        self.write_state("{not json")
        s = load_state(self.chs, self.state_path)
        self.assertEqual(s.fx_outputs, ["A1"])
        self.assertTrue(s.channels["music"].fx)
        with open(self.state_path) as f:
            self.assertEqual(f.read(), "{not json")  # never rewritten by a load

    def test_new_channel_gets_default_state(self):
        self.write_state(json.dumps({"channels": {"music": {"fx": False, "outputs": ["A2"]}}}))
        s = load_state(self.chs, self.state_path)
        self.assertFalse(s.channels["music"].fx)
        self.assertEqual(s.channels["music"].outputs, ["A2"])
        self.assertTrue(s.channels["discord"].fx)
        self.assertEqual(s.channels["discord"].outputs, ["A1"])

    def test_eq_values_are_clamped_on_load(self):
        self.write_state(json.dumps({"channels": {"music": {"bass": 40, "treble": -99}}}))
        s = load_state(self.chs, self.state_path)
        self.assertEqual((s.channels["music"].bass, s.channels["music"].treble), (12.0, -12.0))

    def test_unknown_slot_names_are_dropped(self):
        self.write_state(json.dumps({
            "slots": {"A1": "@default", "A2": "alsa_output.hdmi", "B7": "x"},
            "channels": {"music": {"outputs": ["A1", "B7", "A2"]}},
            "fx_outputs": ["Z9", "A2"],
        }))
        s = load_state(self.chs, self.state_path)
        self.assertEqual(s.channels["music"].outputs, ["A1", "A2"])
        self.assertEqual(s.fx_outputs, ["A2"])
        self.assertEqual(s.slots, {"A1": "@default", "A2": "alsa_output.hdmi", "A3": None, "A4": None})

    def test_missing_slot_key_keeps_its_default_but_null_turns_it_off(self):
        self.write_state(json.dumps({"slots": {"A2": "alsa_output.hdmi"}}))
        self.assertEqual(load_state(self.chs, self.state_path).slots["A1"], "@default")
        self.write_state(json.dumps({"slots": {"A1": None}}))
        self.assertIsNone(load_state(self.chs, self.state_path).slots["A1"])

    def test_wrong_types_fall_back_per_field(self):
        self.write_state(json.dumps({"mic": 5, "fx_outputs": "A1",
                                     "channels": {"music": {"fx": "yes", "bass": "loud"}}}))
        s = load_state(self.chs, self.state_path)
        self.assertEqual((s.mic, s.fx_outputs), ("@auto", ["A1"]))
        self.assertTrue(s.channels["music"].fx)
        self.assertEqual(s.channels["music"].bass, 0.0)

    def test_save_then_load_round_trips(self):
        s = load_state(self.chs, self.state_path)
        s.slots["A2"] = "alsa_output.usb-headset"
        s.channels["discord"] = ChannelState(fx=False, outputs=["A2"], bass=-3.5, treble=2.0)
        s.fx_outputs = ["A1", "A2"]
        s.mic = "alsa_input.usb-blue"
        save_state(s, self.state_path)
        again = load_state(self.chs, self.state_path)
        self.assertEqual(again, s)
        self.assertFalse(os.path.exists(self.state_path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
