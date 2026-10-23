import unittest

from audiomixer.pwgraph import Port, parse_dump

from tests.pwfake import defaults, link, node, port


class ParseDumpTest(unittest.TestCase):
    def setUp(self):
        self.dump = [
            node(47, "Music_Audio_out", "Stream/Output/Audio"),
            port(120, 47, "output_FL", "out", "FL"),
            port(121, 47, "output_FR", "out", "FR"),
            node(50, "easyeffects_sink", "Audio/Sink", {"node.description": "Easy Effects Sink"}),
            port(79, 50, "playback_FL", "in", "FL"),
            port(80, 50, "playback_FR", "in", "FR"),
            port(81, 50, "monitor_FL", "out", "FL", monitor=True),
            link(47, 120, 50, 79),
            link(47, 121, 50, 80),
            defaults("alsa_output.x", "easyeffects_source"),
        ]
        self.g = parse_dump(self.dump)

    def test_ports_grouped_by_node_name_with_channel_and_direction(self):
        self.assertEqual(self.g.ports["Music_Audio_out"], [
            Port("Music_Audio_out", "output_FL", "out", "FL", False),
            Port("Music_Audio_out", "output_FR", "out", "FR", False),
        ])

    def test_monitor_ports_are_marked(self):
        self.assertIn(Port("easyeffects_sink", "monitor_FL", "out", "FL", True),
                      self.g.ports["easyeffects_sink"])

    def test_links_resolved_to_port_names(self):
        self.assertEqual(self.g.links, {
            ("Music_Audio_out:output_FL", "easyeffects_sink:playback_FL"),
            ("Music_Audio_out:output_FR", "easyeffects_sink:playback_FR"),
        })

    def test_nodes_keep_id_class_and_props(self):
        n = self.g.nodes["easyeffects_sink"]
        self.assertEqual((n.id, n.media_class, n.props["node.description"]),
                         (50, "Audio/Sink", "Easy Effects Sink"))

    def test_default_sink_and_source_from_metadata(self):
        self.assertEqual((self.g.default_sink, self.g.default_source),
                         ("alsa_output.x", "easyeffects_source"))

    def test_dangling_link_to_unknown_port_is_ignored(self):
        g = parse_dump(self.dump + [link(47, 120, 777, 778)])
        self.assertEqual(len(g.links), 2)

    def test_empty_or_garbage_dump_gives_empty_graph(self):
        for dump in ([], [{"type": "nonsense"}], [{"id": 1}], None, "junk"):
            g = parse_dump(dump)
            self.assertEqual((g.nodes, g.ports, g.links, g.default_sink, g.default_source),
                             ({}, {}, set(), None, None))


class DumpDocumentsTest(unittest.TestCase):
    """While the graph changes, pw-dump appends update documents after the main
    array ({"id": N, "info": null} = removed). Seen live: 18 of 30 dumps."""

    def test_trailing_updates_are_applied_not_fatal(self):
        import json
        from audiomixer.pwgraph import merge_dump_documents
        main = [node(1, "Music_Audio", "Audio/Sink"), node(2, "gone", "Audio/Sink")]
        text = (json.dumps(main) + "\n" + json.dumps([{"id": 2, "info": None}]) + "\n"
                + json.dumps([node(3, "new_one", "Audio/Sink")]) + "\n"
                + json.dumps([node(1, "Music_Audio", "Audio/Sink", {"x": 1})]))
        merged = merge_dump_documents(text)
        self.assertEqual(sorted(o["id"] for o in merged), [1, 3])
        self.assertEqual(next(o for o in merged if o["id"] == 1)["info"]["props"]["x"], 1)

    def test_garbage_gives_nothing(self):
        from audiomixer.pwgraph import merge_dump_documents
        self.assertEqual(merge_dump_documents(""), [])
        self.assertEqual(merge_dump_documents("not json"), [])


if __name__ == "__main__":
    unittest.main()
