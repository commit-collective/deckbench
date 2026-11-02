# SPDX-License-Identifier: MIT OR Apache-2.0
"""Reliable diagnostic clocks, targets and retained packet recording."""
import json
import collections
import os
import tempfile
import unittest
from unittest.mock import patch

from deckbench.core import Deck, World
from deckbench.events import Events
from deckbench.protocols.prolink import Prolink


class Diagnostics(unittest.TestCase):
    def bench(self, **options):
        world = World()
        world.decks[4] = Deck(world, 4, 128)
        return Prolink(world, **options)

    def test_clear_keeps_the_clock_and_session(self):
        with patch("deckbench.events.time.time", return_value=100):
            events = Events()
        with patch("deckbench.events.time.time", return_value=120):
            first = events.add("before")
            events.clear()
            second = events.add("after")
        self.assertEqual(second["t"], 20)
        self.assertEqual(first["session"], second["session"])
        self.assertEqual(second["generation"], first["generation"] + 1)
        self.assertNotEqual(events.session, Events().session)

    def test_monitor_and_events_share_an_origin(self):
        net = self.bench()
        self.assertEqual(net.monitor.began, net.world.events.began)
        self.assertEqual(net.monitor.since()["session"], net.world.events.session)

    def test_explicit_target_does_not_match_an_unrelated_djs(self):
        net = self.bench(target="2")
        self.assertFalse(net.matches_target("DJS-1000", 1, "169.254.0.1"))
        self.assertTrue(net.matches_target("CDJ-2000NXS2", 2, "169.254.0.2"))
        net.target = "169.254.0.3"
        self.assertTrue(net.matches_target("CDJ-2000NXS2", 3, "169.254.0.3"))
        net.target = None
        self.assertFalse(net.matches_target("DJS-1000", 1, "169.254.0.1"))

    def test_all_external_players_emit_changes_not_every_status(self):
        net, remote = self.bench(target=None), self.bench()
        remote.decks[4].name = b"CDJ-2000NXS2"
        packet = remote.decks[4].status()
        for at in (100, 101):
            with patch.object(net.monitor, "clock", return_value=at):
                net.monitor.feed(packet, "169.254.0.4", net.ports.update)
        events = net.world.events.since()
        changes = [e for e in events if e["kind"] == "player_state"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["number"], 4)
        self.assertFalse(changes[0]["changes"]["play"])
        self.assertFalse(any(e["kind"].startswith("unit_") for e in events))

    def test_recording_survives_clear_and_ring_eviction(self):
        net = self.bench()
        net.monitor.rings["rest"] = collections.deque(maxlen=2)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "capture.jsonl")
            net.monitor.record(path)
            for n in range(5):
                net.monitor.feed(bytes([n]), "169.254.0.2", net.ports.update)
                if n == 3:
                    self.assertEqual(len(net.monitor.rings["rest"]), 2)
                    net.monitor.clear()
            net.monitor.close()
            with open(path, encoding="utf-8") as stream:
                packets = [json.loads(line) for line in stream]
            self.assertEqual(len(packets), 5)
            self.assertEqual([p["n"] for p in packets], [1, 2, 3, 4, 5])
            self.assertEqual(packets[0]["session"], net.world.events.session)
            with self.assertRaises(FileExistsError):
                net.monitor.record(path)

    def test_strict_metadata_accepts_announced_players_without_a_target(self):
        net, remote = self.bench(target=None, strict=True), self.bench()
        remote.decks[4].name = b"CDJ-2000NXS2"
        self.assertTrue(net.decks[4].unknown_player(4))
        net.monitor.feed(remote.decks[4].keepalive(), "169.254.0.4", net.ports.announce)
        self.assertFalse(net.decks[4].unknown_player(4))
        self.assertTrue(net.decks[4].unknown_player(3))


if __name__ == "__main__":
    unittest.main()
