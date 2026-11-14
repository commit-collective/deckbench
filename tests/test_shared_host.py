# SPDX-License-Identifier: MIT OR Apache-2.0
"""A bench on a real network that shares its machine with another Pro DJ Link program (an emulated player, say): what
players send to that program's address must reach it, not the bench. On Linux, sockets bound to any address on one
port share what is sent to an address there: the last one bound gets it, or, when all of them let the port be
shared (SO_REUSEPORT), one of them for each sender. So on a real network the bench listens on its own and the broadcast
addresses only. Checked on the loopback, with the bench made to bind as on a real network."""
import socket
import sys
import time
import unittest
from unittest import mock

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.net import macos_interfaces
from deckbench.protocols.prolink import PortError, Prolink

SENDERS = 12            # players: each its own address and port, which is what the sharing of a port goes by


@unittest.skipUnless(sys.platform.startswith("linux"), "how a port is shared is Linux's")
class SharedHost(unittest.TestCase):
    def test_what_is_sent_to_another_programs_address_reaches_it_not_the_bench(self):
        ports = fresh()
        others = {}
        for port in (ports.beat, ports.update):                            # the other program, bound first
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.bind(("0.0.0.0", port))
            s.settimeout(0.3)
            self.addCleanup(s.close)
            others[port] = s
        world = World()
        world.decks[5] = Deck(world, 5, 128.0, "deck 5")
        with mock.patch.object(Prolink, "broadcast_addresses", lambda self: ["127.255.255.255", "255.255.255.255"]):
            net = Prolink(world, ports=ports, addresses={5: "127.0.0.25"}, broadcast="127.255.255.255")
            net.start()
            self.addCleanup(net.stop)
            self.assertTrue(net.ready.wait(10))
        player_world = World()
        player_world.decks[3] = Deck(player_world, 3, 124.0, "deck 3")
        status = Prolink(player_world, ports=ports).decks[3].status()      # a player's status, built not sent
        senders = []
        for i in range(SENDERS):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(("127.0.0.%d" % (40 + i), 0))
            self.addCleanup(s.close)
            senders.append(s)
        for port, other in others.items():
            for s in senders:
                s.sendto(status, ("127.0.0.1", port))                       # to the other program's address only
            got = 0
            try:
                while True:
                    other.recv(2048)
                    got += 1
            except socket.timeout:
                pass
            self.assertEqual(got, SENDERS, "port %d: the bench took some of what was sent to the other program" % port)
        heard = {d["ip"] for d in net.monitor.snapshot()}
        self.assertFalse(heard & {"127.0.0.%d" % (40 + i) for i in range(SENDERS)})
        senders[0].sendto(status, ("127.255.255.255", ports.update))       # to everyone: the bench hears it
        end = time.time() + 3
        while time.time() < end and not any(d["ip"] == "127.0.0.40" for d in net.monitor.snapshot()):
            time.sleep(0.05)
        self.assertTrue(any(d["ip"] == "127.0.0.40" for d in net.monitor.snapshot()), "a broadcast did not reach the bench")


class Binding(unittest.TestCase):
    def test_the_bench_binds_any_address_only_on_the_loopback(self):
        world = World()
        world.decks[2] = Deck(world, 2, 120.0)
        self.assertEqual(Prolink(world).broadcast_addresses(), ["0.0.0.0"])
        with mock.patch("deckbench.protocols.prolink.interface_macs", return_value={"169.254.4.5": bytes(6)}):
            net = Prolink(world, addresses={2: "169.254.4.5"}, broadcast="169.254.255.255")
        self.assertEqual(net.broadcast_addresses(), ["0.0.0.0"] if sys.platform == "win32" else
                         ["169.254.255.255"] if sys.platform == "darwin" else
                         ["169.254.255.255", "255.255.255.255"])

    @unittest.skipUnless(sys.platform == "darwin", "macOS only")
    def test_every_broadcast_address_can_be_bound_on_macos(self):
        world = World()
        world.decks[2] = Deck(world, 2, 120.0)
        with mock.patch("deckbench.protocols.prolink.interface_macs", return_value={"169.254.4.5": bytes(6)}):
            net = Prolink(world, addresses={2: "169.254.4.5"}, broadcast="169.254.255.255")
        for address in net.broadcast_addresses():
            self.assertNotEqual(address, "255.255.255.255", "macOS cannot bind it (EADDRNOTAVAIL)")

    @unittest.skipUnless(sys.platform == "darwin", "macOS only")
    def test_the_listeners_bind_on_a_real_interface_on_macos(self):
        found = [(name, a, mac) for name, a, mac in macos_interfaces()
                 if not a.ip.is_loopback and not a.ip.is_link_local and a.network.prefixlen < 31]
        if not found:
            self.skipTest("no interface with an IPv4 broadcast address")
        name, a, mac = found[0]
        world = World()
        world.decks[2] = Deck(world, 2, 120.0)
        with mock.patch("deckbench.protocols.prolink.interface_macs", return_value={str(a.ip): mac or bytes(6)}):
            net = Prolink(world, ports=fresh(), addresses={2: str(a.ip)}, broadcast=str(a.network.broadcast_address))
        self.assertEqual(net.broadcast_addresses(), [str(a.network.broadcast_address)])
        net.start()
        self.addCleanup(net.stop)
        self.assertTrue(net.ready.wait(10))
        self.assertEqual(net.runtime.errors, [], "a listener could not bind on " + name)

    def test_a_configured_255_255_255_255_is_refused_on_macos_before_any_listener_starts(self):
        world = World()
        world.decks[2] = Deck(world, 2, 120.0)
        with mock.patch("deckbench.protocols.prolink.interface_macs", return_value={"169.254.4.5": bytes(6)}):
            net = Prolink(world, ports=fresh(), addresses={2: "169.254.4.5"}, broadcast="255.255.255.255")
        with mock.patch("deckbench.protocols.prolink.sys.platform", "darwin"), \
                mock.patch.object(Prolink, "check_ports") as ports:
            with self.assertRaises(PortError) as caught:
                net.start()
        self.assertIn("255.255.255.255", str(caught.exception))
        ports.assert_not_called()
        self.assertEqual(net.runtime.threads, [])


if __name__ == "__main__":
    unittest.main()
