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

    def test_a_free_number_1_to_4_while_track_info_is_read(self):
        self.hear(b"CDJ-2000NXS2", 1, "169.254.10.91")
        self.assertEqual(self.net.announced_number(), 2)
        self.hear(b"CDJ-2000NXS2", 3, "169.254.10.93")
        self.assertEqual(self.net.announced_number(), 2)                # kept while it stays free
        self.hear(b"CDJ-2000NXS2", 2, "169.254.10.92")
        self.assertEqual(self.net.announced_number(), 4)                # taken: the next free one
        self.hear(b"CDJ-2000NXS2", 4, "169.254.10.94")
        self.assertEqual(self.net.announced_number(), Prolink.PRESENCE) # none free
        self.net.set_option("auto_track_info", "0")
        self.assertEqual(self.net.announced_number(), Prolink.PRESENCE)

    def test_its_keep_alives_are_the_benchs_own(self):
        self.real()
        link = self.net.decks[1]
        for number in (3, Prolink.PRESENCE):
            self.net.monitor.feed(startup.keepalive(b"deckbench", number, link.address, link.mac, 2), link.address,
                                  self.net.ports.announce)
        self.assertEqual([d for d in self.net.monitor.snapshot() if d["name"] == "deckbench"], [])

    def test_a_device_with_its_number_moves_it(self):
        self.real()
        sent = []
        link = self.net.decks[1]
        link.send = lambda sock, packet, addr: sent.append(packet)
        link.presence(None, 100.0, 0.0)
        self.assertEqual(sent[-1][0x24], 1)
        self.hear(b"CDJ-3000", 1, "169.254.10.99")
        link.presence(None, 200.0, 100.0)
        self.assertEqual(sent[-1][0x24], 2)

    def test_track_info_is_asked_as_the_presence(self):
        self.real()
        other = World()
        other.decks[3] = Deck(other, 3, 124, "external")
        status = Prolink(other, profile="cdj-2000nxs2").decks[3].status()
        self.net.monitor.feed(status, "169.254.10.93", self.net.ports.update)
        device = next(d for d in self.net.monitor.snapshot() if d["number"] == 3)
        self.assertIsNotNone(self.net.metadata_context(device)[2])     # no presence yet: no one to ask as
        link = self.net.decks[1]
        link.send = lambda sock, packet, addr: None
        link.presence(None, 100.0, 0.0)
        sender, source, reason = self.net.metadata_context(device)
        self.assertIsNone(reason)
        self.assertEqual((sender.address, sender.number), (link.address, 1))
        with patch("deckbench.metadata.read_track_metadata", return_value={"title": "T"}) as read:
            self.assertEqual(self.net.refresh_metadata(device)[0], 200)
        self.assertEqual(read.call_args.args[1:3], (link.address, 1))


if __name__ == "__main__":
    unittest.main()
