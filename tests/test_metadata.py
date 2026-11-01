# SPDX-License-Identifier: MIT OR Apache-2.0
"""Metadata client and bounded dbserver parsing against synthetic servers."""
import unittest
from unittest.mock import patch

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.metadata import read_track_metadata
from deckbench.protocols.prolink import Prolink, read_exact


class Metadata(unittest.TestCase):
    def test_unanalyzed_track_is_not_queried(self):
        net = Prolink(World())
        self.addCleanup(net.stop)
        with patch("socket.create_connection", side_effect=AssertionError("unanalyzed track opened a connection")):
            code, result = net.refresh_metadata({"status": {"rbid": 123, "track_type": 2}})
        self.assertEqual(code, 400)
        self.assertIn("analyzed", result["error"])

    def test_client_reads_a_synthetic_network_database(self):
        world = World()
        world.decks[2] = Deck(world, 2, 126, "source")
        world.decks[2].enabled = True
        net = Prolink(world, ports=fresh(), titles={2: {(3, 102): "Synthetic title"}})
        self.addCleanup(net.stop)
        net.start()
        result = read_track_metadata("127.0.0.2", "127.0.0.9", 3, 3, 102, net.ports.query)
        self.assertEqual(result["title"], "Synthetic title")
        self.assertEqual(result["artist"], "")
        self.assertEqual(result["bpm"], 126)
        self.assertEqual(result["duration_s"], 0)

    def test_invalid_requests_open_no_connection(self):
        with patch("socket.create_connection", side_effect=AssertionError("invalid request opened a connection")):
            for number, slot, track in ((7, 3, 10), (3, 99, 10), (3, 3, -1)):
                with self.assertRaises(ValueError):
                    read_track_metadata("127.0.0.2", "127.0.0.9", number, slot, track)

    def test_protocol_lengths_are_bounded(self):
        with self.assertRaises(ValueError):
            read_exact(None, 1024 * 1024 + 1)

    def test_client_refuses_a_failed_metadata_response(self):
        world = World()
        world.decks[2] = Deck(world, 2, 126, "source")
        world.decks[2].enabled = True
        net = Prolink(world, ports=fresh(), refuse_db=True)
        self.addCleanup(net.stop)
        net.start()
        with self.assertRaisesRegex(ValueError, "rejected"):
            read_track_metadata("127.0.0.2", "127.0.0.9", 3, 3, 102, net.ports.query)


if __name__ == "__main__":
    unittest.main()
