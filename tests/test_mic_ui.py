"""The Mic strip's VoiceMeeter controls in the window: the Color Panel pad and
the Comp / Gate knobs."""

import unittest

from audiomixer.config import ChannelState, MixerState

from tests.test_ui import CHS, UiTestBase


class ColorPanelTest(UiTestBase):
    def panel(self):
        from audiomixer.ui.colorpanel import ColorPanel
        panel = ColorPanel()
        seen = []
        panel.connect("changed", lambda p: seen.append(p.get_value()))
        return panel, seen

    def test_values_stay_in_the_pad_and_changes_are_reported_once(self):
        panel, seen = self.panel()
        panel.set_value(0.5, 0.25)
        panel.set_value(0.5, 0.25)
        panel.set_value(-3, 2)
        self.assertEqual(seen, [(0.5, 0.25), (-1.0, 1.0)])

    def test_where_you_click_is_where_the_square_goes(self):
        from audiomixer.ui.colorpanel import value_at
        self.assertEqual(value_at(50, 100, 100, 100), (0.0, 0.0))     # bottom middle: flat
        self.assertEqual(value_at(0, 0, 100, 100), (-1.0, 1.0))       # top left
        self.assertEqual(value_at(100, 50, 100, 100), (1.0, 0.5))
        self.assertEqual(value_at(150, -20, 100, 100), (1.0, 1.0))    # dragged past the edge

    def test_double_click_and_keys(self):
        panel, _ = self.panel()
        panel.set_value(0.6, 0.9)
        panel.reset()
        self.assertEqual(panel.get_value(), (0.0, 0.0))
        panel.nudge(1, 2)          # arrow right once, up twice
        self.assertEqual(panel.get_value(), (0.05, 0.1))


class UnsignedKnobTest(UiTestBase):
    def test_comp_and_gate_knobs_count_from_zero(self):
        from audiomixer.ui.knob import Knob
        knob = Knob(0, 10, 0.1)
        knob.set_value(1.43)
        self.assertEqual(knob.get_value(), 1.4)
        self.assertEqual(knob.text(), "1.4")
        knob.reset()
        self.assertEqual(knob.get_value(), 0)
        eq = Knob(-12, 12, 0.5)
        eq.set_value(3)
        self.assertEqual(eq.text(), "+3")


class MicStripTest(UiTestBase):
    def setUp(self):
        super().setUp()
        self.saved = []

        def update(change):
            st = change(MixerState({"A1": "@default"}, {c.key: ChannelState() for c in CHS}, ["A1"], "@auto"))
            self.saved.append(st.mic_fx)
            return st
        self.controller._update_state = update
        self.mic = self.strip("Mic_In")

    def test_mic_strip_has_the_color_panel_and_comp_gate(self):
        self.assertEqual(self.mic.color.get_value(), (0.0, 0.0))
        self.assertEqual((self.mic.comp.get_value(), self.mic.gate.get_value()), (0, 0))

    def test_it_follows_the_saved_settings(self):
        self.status["mic_fx"] = {"color_x": -0.5, "color_y": 0.7, "comp": 3.0, "gate": 1.5}
        self.controller.refresh(status_too=True)
        self.assertEqual(self.mic.color.get_value(), (-0.5, 0.7))
        self.assertEqual((self.mic.comp.get_value(), self.mic.gate.get_value()), (3.0, 1.5))
        self.assertEqual(self.calls, [])          # showing it never writes

    def test_moving_the_square_saves_and_sets_the_mic_filter_live(self):
        self.mic.color.set_value(0.4, 0.6)
        self.mic.comp.set_value(5)
        self.mic.flush_fx()                       # one write for everything changed
        self.assertEqual(self.saved[-1].color_x, 0.4)
        self.assertEqual((self.saved[-1].color_y, self.saved[-1].comp), (0.6, 5.0))
        (call,) = self.calls
        self.assertEqual(call[:4], ["pw-cli", "set-param", "77", "Props"])
        self.assertIn('"tilt_hi:Gain" 2.0', call[4])
        self.assertEqual(self.commands, [])       # no rewiring pass while dragging


if __name__ == "__main__":
    unittest.main()
