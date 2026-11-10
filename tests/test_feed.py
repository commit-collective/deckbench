# SPDX-License-Identifier: MIT OR Apache-2.0
"""Watching the link through a feed (--feed): another program forwards each packet it hears or sends, and the bench
reads them as if heard, binding and sending nothing on the link itself."""
import json
import socket
import time
import unittest

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Feed(unittest.TestCase):
    def setUp(self):
        self.ports = fresh()
        self.feed = ("127.0.0.1", free_port())
        world = World()
        world.decks[7] = Deck(world, 7, 120.0, "observer")
        self.net = Prolink(world, ports=self.ports, observer=True, feed=self.feed)
        self.net.start()
        self.addCleanup(self.net.stop)
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(self.out.close)

    def send(self, item):
        self.out.sendto(item if isinstance(item, bytes) else json.dumps(item).encode(), self.feed)

    def test_what_is_forwarded_is_heard_and_the_link_is_left_alone(self):
        player_world = World()
        player_world.decks[3] = Deck(player_world, 3, 124.0, "deck 3")
        status = Prolink(player_world, ports=self.ports).decks[3].status()
        self.send(b"not json")                                         # left out
        self.send({"src": "169.254.3.3", "port": 1234, "hex": status.hex()})   # not a Pro DJ Link port
        self.send({"src": "169.254.3.3", "port": self.ports.update, "hex": status.hex(), "to": "169.254.9.9"})
        end = time.time() + 3
        while time.time() < end and not any(d["ip"] == "169.254.3.3" for d in self.net.monitor.snapshot()):
            time.sleep(0.05)
        heard = [d for d in self.net.monitor.snapshot() if d["ip"] == "169.254.3.3"]
        self.assertEqual(len(heard), 1)
        self.assertEqual(heard[0]["number"], 3)
        for port in (self.ports.announce, self.ports.beat, self.ports.update):     # nothing of the link is held
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.bind(("0.0.0.0", port))

    def test_a_feed_port_in_use_says_so(self):
        world = World()
        world.decks[7] = Deck(world, 7, 120.0, "observer")
        with self.assertRaises(OSError):
            Prolink(world, ports=fresh(), observer=True, feed=self.feed).start()


if __name__ == "__main__":
    unittest.main()
