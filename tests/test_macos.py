# SPDX-License-Identifier: MIT OR Apache-2.0
"""Mac adapter fixtures and native unicast checks, without loopback aliases or broadcasts."""
import io
import json
import socket
import subprocess
import unittest
from unittest.mock import patch

from _ports import fresh
from deckbench import phone
from deckbench.core import Deck, World
from deckbench.metadata import read_track_metadata
from deckbench.net import interface_macs, parse_macos_interfaces, share
from deckbench.protocols.prolink import Prolink


IFCONFIG = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
    inet 127.0.0.1 netmask 0xff000000
en7: flags=8b63<UP,BROADCAST,SMART,RUNNING,PROMISC,SIMPLEX,MULTICAST> mtu 1500
    ether 02:10:20:30:40:50
    inet6 fe80::1%en7 prefixlen 64 secured scopeid 0xe
    inet 169.254.20.30 netmask 0xffff0000 broadcast 169.254.255.255
    inet 169.254.20.31 netmask 0xffff0000 broadcast 169.254.255.255
    status: active
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
    ether 02:60:70:80:90:a0
    inet 192.168.1.20 netmask 0xffffff00 broadcast 192.168.1.255
    status: active
en8: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
    ether 02:aa:bb:cc:dd:ee
    inet 169.254.99.99 netmask 0xffff0000 broadcast 169.254.255.255
    status: inactive
utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
    inet 10.0.0.2 --> 10.0.0.1 netmask 255.255.255.255
en9: flags=8822<BROADCAST,SMART,SIMPLEX,MULTICAST> mtu 1500
    inet 169.254.88.88 netmask 0xffff0000
"""


class MacAdapters(unittest.TestCase):
    def test_addresses_masks_aliases_and_inactive_interfaces(self):
        rows = parse_macos_interfaces(IFCONFIG)
        self.assertEqual([(name, str(ip)) for name, ip, _ in rows], [
            ("lo0", "127.0.0.1/8"), ("en7", "169.254.20.30/16"),
            ("en7", "169.254.20.31/16"), ("en0", "192.168.1.20/24"), ("utun0", "10.0.0.2/32")])
        self.assertIsNone(rows[-1][2])

    def test_selection_and_mac_lookup_use_the_same_read_only_records(self):
        result = subprocess.CompletedProcess([], 0, IFCONFIG, "")
        with patch("sys.platform", "darwin"), patch("deckbench.net.subprocess.run", return_value=result) as run:
            addresses = phone.dj_interface("en7", 2)
            self.assertEqual([str(ip.ip) for ip in addresses], ["169.254.20.30", "169.254.20.31"])
            macs = interface_macs()
            self.assertEqual(macs["169.254.20.31"], bytes.fromhex("021020304050"))
            self.assertNotIn("10.0.0.2", macs)
            with patch("deckbench.phone.route_address", return_value="192.168.1.20"):
                output = io.StringIO()
                self.assertEqual(phone.network_info(output), 0)
            self.assertIn("en7: 169.254.20.30/16", output.getvalue())
            for call in run.call_args_list:
                self.assertEqual(call.args[0], ["/sbin/ifconfig", "-a"])

    def test_invalid_masks_and_command_failure_are_not_hidden(self):
        with self.assertRaises(ValueError):
            parse_macos_interfaces(IFCONFIG.replace("0xffff0000", "0xff00ff00"))
        result = subprocess.CompletedProcess([], 1, "", "permission denied")
        with patch("sys.platform", "darwin"), patch("deckbench.net.subprocess.run", return_value=result):
            with self.assertRaisesRegex(ValueError, "permission denied"):
                interface_macs()

    def test_a_linux_adapter_without_a_mac_is_left_out(self):
        listing = json.dumps([
            {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1"}]},
            {"ifname": "loopback0", "address": "00:11:22:33:44:55", "addr_info": [{"family": "inet", "local": "10.0.0.1"}]},
            {"ifname": "eth1", "address": "02:10:20:30:40:50", "addr_info": [{"family": "inet", "local": "169.254.10.5"}]}])
        result = subprocess.CompletedProcess([], 0, listing, "")
        with patch("sys.platform", "linux"), patch("deckbench.net.subprocess.run", return_value=result):
            macs = interface_macs()
        self.assertEqual(macs, {"10.0.0.1": bytes.fromhex("001122334455"), "169.254.10.5": bytes.fromhex("021020304050")})

    def test_port_reuse_options_on_macos(self):
        from unittest.mock import Mock
        sock = Mock()
        with patch("sys.platform", "darwin"), patch.object(socket, "SO_REUSEPORT", 0x200, create=True):
            share(sock)
        sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt.assert_any_call(socket.SOL_SOCKET, 0x200, 1)


class NativeUnicast(unittest.TestCase):
    def test_database_and_worker_restart_on_localhost(self):
        world = World()
        world.decks[3] = Deck(world, 3, 126, "bench")
        net = Prolink(world, ports=fresh(), addresses={3: "127.0.0.1"}, mixer_address="127.0.0.1",
                      titles={3: {(3, 103): "Native unicast fixture"}})
        self.addCleanup(net.stop)
        world.decks[3].enabled = True
        # Exercise actual TCP sockets, but do not pretend to validate loopback broadcasts.
        with patch.object(net.decks[3], "send"):
            for _ in range(2):
                net.start()
                metadata = read_track_metadata("127.0.0.1", "127.0.0.1", 4, 3, 103, net.ports.query)
                self.assertEqual(metadata["title"], "Native unicast fixture")
                self.assertTrue(net.stop())
                self.assertFalse(any(thread.is_alive() for thread in net.runtime.threads))


if __name__ == "__main__":
    unittest.main()
