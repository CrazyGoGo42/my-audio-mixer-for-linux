import os
import stat
import tempfile
import unittest

from audiomixer.pwgraph import parse_dump
from audiomixer.config import Channel, ChannelState, MixerState
from audiomixer.reconcile import apply_changes, apply_eq, plan_changes

from tests.pwfake import DumpBuilder

MANAGED = {"Music_Audio_out", "EE_Return_out", "Mic_In_in", "All_Audio_in"}
ST = ("output_FL", "output_FR")
IN = ("playback_FL", "playback_FR")


def live(connect=()):
    b = (DumpBuilder()
         .add("Zen", "Stream/Output/Audio", outs=ST)
         .add("Music_Audio", "Audio/Sink", ins=IN)
         .add("Music_Audio_out", "Stream/Output/Audio", outs=ST)
         .add("easyeffects_sink", "Audio/Sink", ins=IN)
         .add("ee_soe_output_level", "Stream/Output/Audio", outs=ST)
         .add("speakers", "Audio/Sink", ins=IN)
         .add("All_Audio_in", "Stream/Input/Audio", ins=("input_FL", "input_FR")))
    for out, inp in connect:
        b.connect(out, inp)
    return parse_dump(b.dump())


TO_EE = {("Music_Audio_out:output_FL", "easyeffects_sink:playback_FL"),
         ("Music_Audio_out:output_FR", "easyeffects_sink:playback_FR")}
TO_SPEAKERS = {("Music_Audio_out:output_FL", "speakers:playback_FL"),
               ("Music_Audio_out:output_FR", "speakers:playback_FR")}
APP = {("Zen:output_FL", "Music_Audio:playback_FL"), ("Zen:output_FR", "Music_Audio:playback_FR")}
EE_INTERNAL = {("ee_soe_output_level:output_FL", "speakers:playback_FL")}


class PlanChangesTest(unittest.TestCase):
    def test_adds_missing_and_removes_stale_managed_links(self):
        g = live(connect=TO_SPEAKERS)
        add, remove = plan_changes(TO_EE, g, MANAGED)
        self.assertEqual((add, remove), (TO_EE, TO_SPEAKERS))

    def test_never_removes_links_of_unmanaged_nodes(self):
        g = live(connect=APP | EE_INTERNAL)
        add, remove = plan_changes(TO_EE, g, MANAGED)
        self.assertEqual(remove, set())
        self.assertEqual(add, TO_EE)

    def test_removes_wireplumber_fallback_link_from_channel_out_to_hardware(self):
        g = live(connect=TO_EE | {("Music_Audio_out:output_FL", "speakers:playback_FL")})
        self.assertEqual(plan_changes(TO_EE, g, MANAGED),
                         (set(), {("Music_Audio_out:output_FL", "speakers:playback_FL")}))

    def test_removes_stale_links_into_managed_inputs(self):
        # e.g. a monitor link into All_Audio_in left over from the old config
        stale = {("Zen:output_FL", "All_Audio_in:input_FL")}
        self.assertEqual(plan_changes(set(), live(connect=stale), MANAGED), (set(), stale))

    def test_noop_when_graph_matches(self):
        g = live(connect=TO_EE | APP | EE_INTERNAL)
        self.assertEqual(plan_changes(TO_EE, g, MANAGED), (set(), set()))


class ApplyChangesTest(unittest.TestCase):
    """Runs the real code against a fake pw-link that records its arguments."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.log = os.path.join(self.dir.name, "calls")
        fake = os.path.join(self.dir.name, "pw-link")
        with open(fake, "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> {self.log}\n'
                    'case "$*" in *broken*) echo "failed to link ports: No such file" >&2; exit 1 ;; esac\n')
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = self.dir.name + os.pathsep + self.old_path
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self.old_path))

    def calls(self):
        with open(self.log) as f:
            return sorted(f.read().splitlines())

    def test_links_and_unlinks_with_pw_link(self):
        errors = apply_changes({("a:output_FL", "b:playback_FL")}, {("a:output_FR", "c:playback_FR")})
        self.assertEqual(errors, [])
        self.assertEqual(self.calls(), ["-d a:output_FR c:playback_FR", "a:output_FL b:playback_FL"])

    def test_failures_are_reported_not_raised(self):
        errors = apply_changes({("broken:output_FL", "b:playback_FL"), ("a:output_FL", "b:playback_FL")}, set())
        self.assertEqual(len(errors), 1)
        self.assertIn("broken:output_FL", errors[0])
        self.assertEqual(len(self.calls()), 2)  # one failure doesn't stop the rest


class ApplyEqTest(unittest.TestCase):
    """Real apply_eq against a fake pw-cli that records its arguments."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.log = os.path.join(self.dir.name, "calls")
        fake = os.path.join(self.dir.name, "pw-cli")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\nfor a in "$@"; do printf "%s|" "$a"; done >> ' + self.log + '\necho >> ' + self.log + '\n')
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        old = os.environ["PATH"]
        os.environ["PATH"] = self.dir.name + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))

    def test_sets_bass_and_treble_on_each_channel_sink_node(self):
        chs = [Channel("music", "Music_Audio", "Music", ("-", "-", "-")),
               Channel("gone", "Gone_Audio", "Gone", ("-", "-", "-"))]
        st = MixerState({"A1": "@default"}, {"music": ChannelState(bass=6.0, treble=-2.5),
                                             "gone": ChannelState()}, ["A1"], "@auto")
        g = parse_dump(DumpBuilder().add("Music_Audio", "Audio/Sink", ins=IN).dump())
        apply_eq(g, chs, st)
        nid = g.nodes["Music_Audio"].id
        with open(self.log) as f:
            self.assertEqual(f.read().splitlines(),
                             [f'set-param|{nid}|Props|{{ params = [ "bass:Gain" 6.0 "mid:Gain" 0.0 "treble:Gain" -2.5 ] }}|'])


if __name__ == "__main__":
    unittest.main()
