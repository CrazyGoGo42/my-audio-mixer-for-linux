"""The compact view's own "Playing now": every app making sound, its level,
and a button with its channel — click it to move the app."""

import unittest

from tests.test_ui import UiTestBase


class CompactAppsTest(UiTestBase):
    def rows(self):
        return {r.app.name: r for r in self.win.compact.apps.rows}

    def test_every_playing_app_with_its_channel(self):
        rows = self.rows()
        self.assertEqual(sorted(rows), ["Audacity", "Zen"])
        self.assertEqual(rows["Zen"].channel.get_label(), "Browser")
        self.assertEqual(rows["Audacity"].channel.get_label(), "Desktop")
        self.assertTrue(rows["Audacity"].new.get_visible())     # not routed yet
        self.assertFalse(rows["Zen"].new.get_visible())

    def test_picking_a_channel_moves_the_app_for_good(self):
        self.rows()["Zen"].pick("Music_Audio")
        self.assertEqual(self.moves, [("remember", "zen", "Music_Audio"), ("route", [119, 141], "Music_Audio")])

    def test_picking_its_own_channel_keeps_a_new_app_there(self):
        self.rows()["Audacity"].pick("Default_Audio")
        self.assertEqual(self.moves, [("remember", "audacity", "Default_Audio")])

    def test_the_menu_lists_every_channel(self):
        self.assertEqual([t for t, _ in self.rows()["Zen"].channel.items],
                         ["Desktop", "Discord", "Music", "Browser"])

    def test_nothing_playing_says_so(self):
        self.snap.apps = []
        self.controller.refresh()
        self.assertEqual(self.win.compact.apps.rows, [])
        self.assertTrue(self.win.compact.apps.empty.get_visible())

    def test_it_replaces_the_names_under_the_rows(self):
        self.assertFalse(hasattr(self.win.compact, "app_labels"))

    def test_a_renamed_channel_is_renamed_here_too(self):
        from audiomixer.config import Channel
        self.controller._rename = lambda key, label: [
            Channel(c.key, c.sink, label if c.key == key else c.label, c.hotkeys) for c in self.controller.channels]
        self.controller.rename_channel("browser", "Web")
        zen = self.rows()["Zen"]
        self.assertEqual(zen.channel.get_label(), "Web")
        self.assertIn("Web", [t for t, _ in zen.channel.items])


if __name__ == "__main__":
    unittest.main()
