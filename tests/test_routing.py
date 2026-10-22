import unittest

from audiomixer.config import Channel, ChannelState, MixerState
from audiomixer.pwgraph import parse_dump
from audiomixer.routing import (
    desired_links, managed_nodes, own_nodes, pick_mic, port_pairs, resolve_slot,
    unpairable_routes,
)

from tests.pwfake import DumpBuilder

ST = ("output_FL", "output_FR")
CHS = [Channel("default", "Default_Audio", "Desktop", ("KP_1", "KP_4", "KP_7")),
       Channel("discord", "Discord_Audio", "Discord", ("KP_2", "KP_5", "KP_8")),
       Channel("music", "Music_Audio", "Music", ("KP_3", "KP_6", "KP_9"))]
SPEAKERS = "alsa_output.pci-0000_00_1f.3.analog-surround-40"
HDMI = "alsa_output.pci-0000_01_00.1.hdmi-stereo-extra1"
HEADSET = "alsa_output.usb-Generic_Blue_Microphones-00.analog-stereo"
PCI_MIC = "alsa_input.pci-0000_00_1f.3.analog-stereo"
USB_MIC = "alsa_input.usb-Generic_Blue_Microphones-00.mono-fallback"


def graph(ee=True, usb_mic=True, default_sink=SPEAKERS, extra=None):
    b = DumpBuilder()
    for ch in CHS:
        b.add(ch.sink, "Audio/Sink", ins=("playback_FL", "playback_FR"))
        b.add(ch.sink + "_out", "Stream/Output/Audio", outs=ST)
    if ee:
        b.add("easyeffects_sink", "Audio/Sink", ins=("playback_FL", "playback_FR"),
              monitors=("monitor_FL", "monitor_FR"))
        b.add("easyeffects_source", "Audio/Source/Virtual", outs=("capture_FL", "capture_FR"),
              props={"node.virtual": True})
    b.add("EE_Return", "Audio/Sink", ins=("playback_FL", "playback_FR"))
    b.add("EE_Return_out", "Stream/Output/Audio", outs=ST)
    b.add("Mic_In_in", "Stream/Input/Audio", ins=("input_FL", "input_FR"))
    b.add("Mic_In", "Audio/Source", outs=("capture_FL", "capture_FR"), props={"node.virtual": True})
    b.add("All_Audio_in", "Stream/Input/Audio", ins=("input_FL", "input_FR"))
    b.add("All_Audio", "Audio/Source", outs=("capture_FL", "capture_FR"), props={"node.virtual": True})
    b.add(SPEAKERS, "Audio/Sink", ins=("playback_FL", "playback_FR", "playback_RL", "playback_RR"),
          monitors=("monitor_FL", "monitor_FR"), props={"device.api": "alsa", "priority.session": 1009})
    b.add(HDMI, "Audio/Sink", ins=("playback_FL", "playback_FR"),
          props={"device.api": "alsa", "priority.session": 704})
    b.add(PCI_MIC, "Audio/Source", outs=("capture_FL", "capture_FR"), props={"device.api": "alsa"})
    if usb_mic:
        b.add(HEADSET, "Audio/Sink", ins=("playback_FL", "playback_FR"),
              props={"device.api": "alsa", "priority.session": 1000})
        b.add(USB_MIC, "Audio/Source", outs=("capture_MONO",), props={"device.api": "alsa"})
    if extra:
        extra(b)
    b.default(sink=default_sink, source="easyeffects_source")
    return parse_dump(b.dump())


def state(**over):
    s = MixerState(slots={"A1": "@default", "A2": None, "A3": None, "A4": None},
                   channels={c.key: ChannelState() for c in CHS},
                   fx_outputs=["A1"], mic="@auto")
    for k, v in over.items():
        setattr(s, k, v)
    return s


def pair(out_node, in_node, out_prefix="output", in_prefix="playback"):
    return {(f"{out_node}:{out_prefix}_FL", f"{in_node}:{in_prefix}_FL"),
            (f"{out_node}:{out_prefix}_FR", f"{in_node}:{in_prefix}_FR")}


def from_node(links, name):
    return {l for l in links if l[0].startswith(name + ":")}


class RoutingTest(unittest.TestCase):
    def test_todays_defaults_route_all_channels_through_ee_and_ee_to_default_device(self):
        links = desired_links(CHS, state(), graph())
        for ch in CHS:
            self.assertEqual(from_node(links, ch.sink + "_out"),
                             pair(ch.sink + "_out", "easyeffects_sink")
                             | pair(ch.sink + "_out", "All_Audio_in", in_prefix="input"))
        self.assertEqual(from_node(links, "EE_Return_out"), pair("EE_Return_out", SPEAKERS))

    def test_fx_off_channel_goes_to_its_slots_not_ee(self):
        s = state(slots={"A1": "@default", "A2": HDMI, "A3": None, "A4": None})
        s.channels["discord"] = ChannelState(fx=False, outputs=["A1", "A2"])
        links = from_node(desired_links(CHS, s, graph()), "Discord_Audio_out")
        self.assertEqual(links, pair("Discord_Audio_out", SPEAKERS) | pair("Discord_Audio_out", HDMI)
                         | pair("Discord_Audio_out", "All_Audio_in", in_prefix="input"))

    def test_every_channel_feeds_all_audio_regardless_of_fx_and_slots(self):
        s = state()
        s.channels["music"] = ChannelState(fx=False, outputs=[])
        links = from_node(desired_links(CHS, s, graph()), "Music_Audio_out")
        self.assertEqual(links, pair("Music_Audio_out", "All_Audio_in", in_prefix="input"))

    def test_fx_channel_without_ee_sink_gets_no_links(self):
        links = desired_links(CHS, state(), graph(ee=False))
        for ch in CHS:  # only All Audio; never a fallback straight to hardware
            self.assertEqual(from_node(links, ch.sink + "_out"),
                             pair(ch.sink + "_out", "All_Audio_in", in_prefix="input"))

    def test_ee_strip_plays_on_every_fx_output(self):
        s = state(slots={"A1": "@default", "A2": HDMI, "A3": None, "A4": None}, fx_outputs=["A1", "A2"])
        self.assertEqual(from_node(desired_links(CHS, s, graph()), "EE_Return_out"),
                         pair("EE_Return_out", SPEAKERS) | pair("EE_Return_out", HDMI))

    def test_default_slot_follows_default_sink(self):
        self.assertEqual(from_node(desired_links(CHS, state(), graph(default_sink=HEADSET)), "EE_Return_out"),
                         pair("EE_Return_out", HEADSET))

    def test_missing_device_slot_is_silent(self):
        s = state(slots={"A1": HEADSET, "A2": None, "A3": None, "A4": None})
        self.assertEqual(from_node(desired_links(CHS, s, graph(usb_mic=False)), "EE_Return_out"), set())

    def test_default_pointing_at_our_own_node_falls_back_to_real_hardware(self):
        # WirePlumber can pick one of our sinks as the default output (it's in
        # its history on this machine). Linking into it would loop; going silent
        # isn't what anyone expects (review I1): use the best real output.
        own = own_nodes(CHS)
        for bad_default in ("Default_Audio", "EE_Return", "easyeffects_sink", "gone_device", None):
            self.assertEqual(resolve_slot("@default", graph(default_sink=bad_default), own), SPEAKERS,
                             bad_default)
        self.assertEqual(from_node(desired_links(CHS, state(), graph(default_sink="Music_Audio")),
                                   "EE_Return_out"), pair("EE_Return_out", SPEAKERS))

    def test_default_with_no_hardware_at_all_is_silent(self):
        g = graph(default_sink="Default_Audio")
        for name in (SPEAKERS, HDMI, HEADSET):
            g.nodes.pop(name, None)
        self.assertIsNone(resolve_slot("@default", g, own_nodes(CHS)))

    def test_slot_never_resolves_to_easyeffects_sink(self):
        # EasyEffects' output would come straight back into it: a feedback loop.
        self.assertIsNone(resolve_slot("easyeffects_sink", graph(), own_nodes(CHS)))

    def test_slot_must_name_a_sink(self):
        self.assertIsNone(resolve_slot(PCI_MIC, graph(), own_nodes(CHS)))
        self.assertEqual(resolve_slot(HDMI, graph(), own_nodes(CHS)), HDMI)
        self.assertIsNone(resolve_slot(None, graph(), own_nodes(CHS)))

    def test_mono_mic_feeds_both_channels(self):
        self.assertEqual(port_pairs(USB_MIC, "Mic_In_in", graph()),
                         [(f"{USB_MIC}:capture_MONO", "Mic_In_in:input_FL"),
                          (f"{USB_MIC}:capture_MONO", "Mic_In_in:input_FR")])

    def test_four_channel_device_gets_front_pair_only(self):
        self.assertEqual(set(port_pairs("EE_Return_out", SPEAKERS, graph())), pair("EE_Return_out", SPEAKERS))

    def test_auto_mic_prefers_usb_and_never_picks_a_monitor_or_ee_source(self):
        self.assertEqual(pick_mic(state(), graph()), USB_MIC)
        self.assertEqual(pick_mic(state(), graph(usb_mic=False)), PCI_MIC)
        only_virtual = graph(usb_mic=False, extra=lambda b: None)
        del only_virtual.nodes[PCI_MIC]
        self.assertIsNone(pick_mic(state(), only_virtual))  # Mic_In, All_Audio, easyeffects_source are never picked

    def test_auto_mic_feeds_mic_in(self):
        self.assertEqual(from_node(desired_links(CHS, state(), graph()), USB_MIC),
                         {(f"{USB_MIC}:capture_MONO", "Mic_In_in:input_FL"),
                          (f"{USB_MIC}:capture_MONO", "Mic_In_in:input_FR")})

    def test_pinned_mic_absent_means_no_mic(self):
        self.assertEqual(pick_mic(state(mic=PCI_MIC), graph()), PCI_MIC)
        self.assertIsNone(pick_mic(state(mic=USB_MIC), graph(usb_mic=False)))
        self.assertIsNone(pick_mic(state(mic="easyeffects_source"), graph()))

    def test_a_wanted_route_whose_ports_cannot_pair_is_reported(self):
        # EE_Return_out once had ports output_1/output_2 with channel UNK:
        # nothing paired, no link was wanted, and the strip went silent unnoticed.
        def unknown_channels(b):
            b.add("EE_Return_out_unk", "Stream/Output/Audio", outs=("output_1", "output_2"))
        g = graph(extra=unknown_channels)
        g.ports["EE_Return_out"] = g.ports.pop("EE_Return_out_unk")
        self.assertIn(("EE_Return_out", SPEAKERS), unpairable_routes(CHS, state(), g))
        self.assertEqual(unpairable_routes(CHS, state(), graph()), [])

    def test_managed_nodes_are_the_ones_whose_links_we_own(self):
        self.assertEqual(managed_nodes(CHS), {"Default_Audio_out", "Discord_Audio_out", "Music_Audio_out",
                                              "EE_Return_out", "Mic_In_in", "All_Audio_in"})
        self.assertLessEqual(managed_nodes(CHS), own_nodes(CHS))
        self.assertIn("Music_Audio", own_nodes(CHS))


if __name__ == "__main__":
    unittest.main()
