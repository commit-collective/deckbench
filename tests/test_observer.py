# SPDX-License-Identifier: MIT OR Apache-2.0
"""An observer announces its presence but never advertises playback or a database."""
import socket
import time
import unittest

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink
from deckbench.testing import Bench


class Observer(unittest.TestCase):
    def test_cli_exposes_no_playback_decks(self):
        with Bench(numbers=[7], args=["--observe"]) as bench:
            state = bench.state()
            self.assertEqual(state["decks"], {})
            self.assertTrue(state["protocols"]["prolink"]["settings"]["observer"])

    def test_only_keepalives_are_sent_and_database_ports_remain_free(self):
        world = World()
        world.decks[7] = Deck(world, 7, 128, "observer")
        net = Prolink(world, ports=fresh(), observer=True)
        world.decks.clear()
        self.addCleanup(net.stop)
        net.start()
        end = time.monotonic() + 2
        while not net.monitor.since(0)["packets"] and time.monotonic() < end:
            time.sleep(0.01)
        packets = net.monitor.since(0)["packets"]
        self.assertTrue(packets)
        self.assertEqual({p["kind"] for p in packets}, {"keep-alive"})
        self.assertTrue(all(p["name"] == "deckbench" for p in packets))
        for port in (net.ports.query, net.ports.db):
            with socket.socket() as probe:
                probe.bind(("127.0.0.7", port))
        self.assertEqual(net.mixer_do({"on": True})[0], False)
