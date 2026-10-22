import unittest

from audiomixer.config import Channel
from audiomixer.live import AppRow, StripLive, build_snapshot, strip_targets

CHS = [Channel("default", "Default_Audio", "Desktop", ("-", "-", "-")),
       Channel("music", "Music_Audio", "Music", ("-", "-", "-")),
       Channel("browser", "Browser_Audio", "Browser", ("-", "-", "-"))]
ROUTES = {"binary": {"zen": "Browser_Audio"}, "app": {}, "ignore": []}


def vol(pct):
    return {"front-left": {"value": int(65536 * pct / 100), "value_percent": f"{pct}%"},
            "front-right": {"value": int(65536 * pct / 100), "value_percent": f"{pct}%"}}


def sink(index, name, pct, mute=False):
    return {"index": index, "name": name, "description": name, "volume": vol(pct), "mute": mute}


def stream(index, sink_index, **props):
    return {"index": index, "sink": sink_index, "properties": props}


SINKS = [sink(43, "Default_Audio", 35), sink(48, "Music_Audio", 25, mute=True),
         sink(50, "Browser_Audio", 27), sink(121, "EE_Return", 100),
         sink(330, "easyeffects_sink", 100), sink(9, "alsa_output.speakers", 60)]
SOURCES = [sink(60, "Mic_In", 80), sink(61, "All_Audio", 100)]
INPUTS = [
    stream(45, 330, **{"node.name": "Default_Audio_out"}),           # our own loopback
    stream(56, 9, **{"node.name": "EE_Return_out"}),                 # our own
    stream(119, 50, **{"application.name": "Zen", "application.process.binary": "zen", "node.name": "Zen"}),
    stream(141, 50, **{"application.name": "Zen", "application.process.binary": "zen", "node.name": "Zen"}),
    stream(200, 43, **{"application.name": "Audacity", "application.process.binary": "audacity"}),
    stream(201, 43, **{"application.name": "speech-dispatcher-dummy", "application.process.binary": "sd_dummy"}),
    stream(300, 9, **{"application.name": "Raw App", "application.process.binary": "raw"}),  # straight to hardware
]


class LiveTest(unittest.TestCase):
    def setUp(self):
        self.snap = build_snapshot(SINKS, SOURCES, INPUTS, CHS, ROUTES)

    def test_strip_targets_in_display_order(self):
        self.assertEqual(strip_targets(CHS), [
            ("Mic_In", "source"), ("Default_Audio", "sink"), ("Music_Audio", "sink"),
            ("Browser_Audio", "sink"), ("EE_Return", "sink"), ("All_Audio", "source")])

    def test_volume_and_mute_from_pactl_json(self):
        self.assertEqual(self.snap.strips["Music_Audio"], StripLive("Music_Audio", "sink", True, 25, True))
        self.assertEqual(self.snap.strips["Mic_In"], StripLive("Mic_In", "source", True, 80, False))

    def test_missing_node_is_reported_absent(self):
        snap = build_snapshot([s for s in SINKS if s["name"] != "Browser_Audio"], SOURCES, INPUTS, CHS, ROUTES)
        self.assertEqual(snap.strips["Browser_Audio"], StripLive("Browser_Audio", "sink", False, 0, False))

    def test_own_streams_and_ignored_apps_are_not_listed(self):
        names = [a.name for a in self.snap.apps]
        self.assertNotIn("Default_Audio_out", names)
        self.assertNotIn("EE_Return_out", names)
        self.assertNotIn("speech-dispatcher-dummy", names)

    def test_apps_on_ee_or_hardware_are_not_listed(self):
        self.assertNotIn("Raw App", [a.name for a in self.snap.apps])

    def test_same_app_streams_are_one_row(self):
        self.assertEqual(self.snap.apps[1], AppRow(("binary", "zen"), "Zen", [119, 141], "Browser_Audio", True,
                                                   {"application.name": "Zen",
                                                    "application.process.binary": "zen", "node.name": "Zen"}))

    def test_unknown_app_is_marked_new(self):
        self.assertEqual([(a.name, a.known) for a in self.snap.apps], [("Audacity", False), ("Zen", True)])


if __name__ == "__main__":
    unittest.main()
