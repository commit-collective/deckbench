# SPDX-License-Identifier: MIT OR Apache-2.0
"""The bench announces itself on a real network while its decks are off, so players send it their status. While it
reads track info by itself, it takes a free number 1 to 4, which older players answer metadata queries from."""
import unittest
from unittest.mock import patch

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

    def hear(self, name, number, ip):
        packet = startup.keepalive(name, number, ip, bytes((2, 0, 0, 0, 0, number)), 3)
        self.net.monitor.feed(packet, ip, self.net.ports.announce)

    def test_only_on_a_real_network_with_every_deck_off(self):
        self.assertIsNone(self.net.presence_link())                     # loopback: tests and the demo stay as they were
        self.real()
        self.assertIs(self.net.presence_link(), self.net.decks[1])
        self.world.decks[2].enabled = True
        self.assertIsNone(self.net.presence_link())                     # a deck on announces itself and gets the status
        self.world.decks[2].enabled = False
        self.world.decks[1].unplugged = True
        self.assertIs(self.net.presence_link(), self.net.decks[2])
        self.net.observer = True
        self.assertIsNone(self.net.presence_link())

    def test_always_7_even_with_numbers_free(self):
        # a free number 1 to 4 was tried, and an XDJ-1000MK2 went into emergency loop at once
        self.hear(b"CDJ-2000NXS2", 1, "169.254.10.91")
        self.net.auto_info = self.net.auto_waves = True
        self.assertEqual(self.net.announced_number(), Prolink.PRESENCE)

    def test_its_keep_alives_are_the_benchs_own(self):
        self.real()
        link = self.net.decks[1]
        for number in (3, Prolink.PRESENCE):
            self.net.monitor.feed(startup.keepalive(b"deckbench", number, link.address, link.mac, 2), link.address,
                                  self.net.ports.announce)
        self.assertEqual([d for d in self.net.monitor.snapshot() if d["name"] == "deckbench"], [])

    def test_a_device_with_its_number_suspends_it(self):
        self.real()
        sent = []
        link = self.net.decks[1]
        link.send = lambda sock, packet, addr: sent.append(packet)
        link.presence(None, 100.0, 0.0)
        self.assertEqual(sent[-1][0x24], Prolink.PRESENCE)
        self.hear(b"CDJ-3000", Prolink.PRESENCE, "169.254.10.99")
        self.assertEqual(link.presence(None, 200.0, 100.0), 100.0)     # nothing sent
        self.assertEqual(len(sent), 1)

    def test_track_info_still_needs_a_bench_player_1_to_4(self):
        self.real()
        other = World()
        other.decks[3] = Deck(other, 3, 124, "external")
        status = Prolink(other, profile="cdj-2000nxs2").decks[3].status()
        self.net.monitor.feed(status, "169.254.10.93", self.net.ports.update)
        device = next(d for d in self.net.monitor.snapshot() if d["number"] == 3)
        link = self.net.decks[1]
        link.send = lambda sock, packet, addr: None
        link.presence(None, 100.0, 0.0)
        self.assertIn("1 to 4", self.net.metadata_context(device)[2])
        self.world.decks[1].enabled = True
        sender = self.net.metadata_context(device)[0]
        self.assertEqual((sender.address, sender.number), (link.address, 1))


if __name__ == "__main__":
    unittest.main()
