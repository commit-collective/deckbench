# SPDX-License-Identifier: MIT OR Apache-2.0
"""Network workers release their sockets and timers before a restart."""
import socket
import unittest

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink


class Lifecycle(unittest.TestCase):
    def test_stop_joins_workers_and_releases_all_ports(self):
        world = World()
        world.decks[2] = Deck(world, 2, 128, "deck 2")
        net = Prolink(world, ports=fresh())
        self.addCleanup(net.stop)
        net.start()
        # An idle database client must not prevent shutdown.
        client = socket.create_connection(("127.0.0.2", net.ports.db), timeout=1)
        self.addCleanup(client.close)
        net.runtime.later(60, lambda: self.fail("a cancelled timer fired"))
        self.assertTrue(net.stop())
        self.assertFalse(any(thread.is_alive() for thread in net.runtime.threads))
        for kind, port in ((socket.SOCK_DGRAM, net.ports.announce), (socket.SOCK_DGRAM, net.ports.beat),
                           (socket.SOCK_DGRAM, net.ports.update), (socket.SOCK_STREAM, net.ports.query),
                           (socket.SOCK_STREAM, net.ports.db)):
            with socket.socket(socket.AF_INET, kind) as probe:
                if kind == socket.SOCK_STREAM:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.2", port))
        net.start()
        self.assertTrue(net.ready.is_set())
        self.assertTrue(net.stop())
        self.assertEqual(net.runtime.errors, [])
