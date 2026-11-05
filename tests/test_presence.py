# SPDX-License-Identifier: MIT OR Apache-2.0
"""The bench announces itself as observer 7 on a real network while its decks are off, so players send it their status."""
import unittest

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.protocols import startup
from deckbench.protocols.prolink import Prolink


class Presence(unittest.TestCase):
    def setUp(self):
        self.world = World()
        for n in (1, 2):
            self.world.decks[n] = Deck(self.world, n, 128, "bench")
            self.world.decks[n].enabled = False
        self.net = Prolink(self.world, ports=fresh())

    def real(self):
        for n, link in self.net.decks.items():
            link.address = "169.254.10.%d" % n

    def test_only_on_a_real_network_with_every_deck_off(self):
        self.assertIsNone(self.net.presence_link())                     # loopback: tests and the demo stay as they were
        self.real()
        self.assertIs(self.net.presence_link(), self.net.decks[1])
        self.world.decks[2].enabled = True
        self.assertIsNone(self.net.presence_link())                     # a deck on announces itself and gets the status
        self.world.decks[2].enabled = False
        self.world.decks[1].unplugged = True
        self.assertIs(self.net.presence_link(), self.net.decks[2])

    def test_not_in_observer_mode_nor_when_a_deck_is_number_7(self):
        self.real()
        self.net.observer = True
        self.assertIsNone(self.net.presence_link())
        self.net.observer = False
        world = World()
        world.decks[7] = Deck(world, 7, 128, "bench")
        world.decks[7].enabled = False
        net = Prolink(world, ports=fresh())
        net.decks[7].address = "169.254.10.7"
        self.assertIsNone(net.presence_link())

    def test_its_keep_alives_are_the_benchs_own(self):
        self.real()
        link = self.net.decks[1]
        packet = startup.keepalive(b"deckbench", Prolink.PRESENCE, link.address, link.mac, 2)
        self.net.monitor.feed(packet, link.address, self.net.ports.announce)
        self.assertEqual([d for d in self.net.monitor.snapshot() if d["number"] == Prolink.PRESENCE], [])

    def test_a_device_with_number_7_suspends_it(self):
        self.real()
        sent = []
        link = self.net.decks[1]
        link.send = lambda sock, packet, addr: sent.append(packet)
        self.assertNotEqual(link.presence(None, 100.0, 0.0), 0.0)
        self.assertEqual(sent[0][0x24], Prolink.PRESENCE)
        other = startup.keepalive(b"CDJ-3000", 7, "169.254.10.99", b"\x02\0\0\0\0\x63", 3)
        self.net.monitor.feed(other, "169.254.10.99", self.net.ports.announce)
        self.assertEqual(link.presence(None, 200.0, 100.0), 100.0)     # nothing sent
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
