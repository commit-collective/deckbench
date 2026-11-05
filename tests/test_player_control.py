# SPDX-License-Identifier: MIT OR Apache-2.0
"""Explicit hardware transport commands, independent of mixer simulation."""
import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink
from deckbench.web import serve


class PlayerControl(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.world.decks[3] = Deck(self.world, 3, 128, "bench")
        self.net = Prolink(self.world, ports=fresh())
        other = World()
        other.decks[2] = Deck(other, 2, 124, "external")
        self.player = Prolink(other, profile="cdj-2000nxs2").decks[2]
        self.ip = "127.0.0.9"
        self.feed()

    def feed(self):
        self.net.monitor.recent.clear()
        self.net.monitor.feed(self.player.status(), self.ip, self.net.ports.update)

    def call(self, action, value, number="2"):
        return self.net.player_api(["player", self.ip, action, value], {"number": [number]})

    def test_default_denies_commands_and_arm_sends_nothing(self):
        with patch.object(self.net.decks[3], "send") as send:
            self.assertEqual(self.call("command", "stop")[0], 403)
            self.assertEqual(self.call("arm", "1")[0], 200)
            send.assert_not_called()
        self.assertTrue(self.net.info()["devices"][0]["transport_armed"])
        self.assertFalse(self.net.mixer.on)

    def test_metadata_is_read_only_and_tracks_the_loaded_identity(self):
        self.world.decks[3].enabled = True
        with patch("deckbench.metadata.read_track_metadata", return_value={"title": "Synthetic track"}) as read:
            self.assertEqual(self.call("metadata", "refresh")[0], 200)
        self.assertEqual(read.call_args.args[:5], (self.ip, "127.0.0.3", 3, 3, 102))
        self.assertFalse(self.net.info()["devices"][0]["transport_armed"])
        self.assertEqual(self.net.info()["devices"][0]["metadata"]["title"], "Synthetic track")
        self.player.rbid = 103
        self.feed()
        self.assertIsNone(self.net.info()["devices"][0]["metadata"])

    def test_metadata_availability_follows_sender_switch(self):
        def state():
            return self.net.info()["devices"][0]
        self.assertFalse(state()["metadata_available"])
        self.assertIn("enable", state()["metadata_reason"])
        self.world.decks[3].enabled = True
        self.assertTrue(state()["metadata_available"])
        self.world.decks[3].enabled = False
        self.assertFalse(state()["metadata_available"])
        with patch("deckbench.metadata.read_track_metadata") as read:
            self.assertEqual(self.call("metadata", "refresh")[0], 400)
        read.assert_not_called()

    def test_metadata_requires_analyzed_track_and_unambiguous_source(self):
        self.world.decks[3].enabled = True
        device = self.net.info()["devices"][0]
        for changes, word in (({"track_type": 2}, "analyzed"), ({"source": 4}, "source")):
            candidate = dict(device, status=dict(device["status"], **changes))
            self.assertIn(word, self.net.metadata_context(candidate)[2])
        self.world.decks[3].unplugged = True
        self.assertFalse(self.net.info()["devices"][0]["metadata_available"])

    def test_unicast_targets_only_the_chosen_player(self):
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(1)
            for command, value in (("start", 0), ("stop", 1)):
                self.assertEqual(self.call("command", command)[0], 200)
                packet, source = receiver.recvfrom(1024)
                self.assertEqual(source[0], "127.0.0.3")
                self.assertEqual(packet[0x0A], 2)
                self.assertEqual(packet[0x21], 3)
                self.assertEqual(packet[0x24:0x28], bytes((2, value, 2, 2)))
        self.assertFalse(self.net.mixer.on)
        # Sending is not an acknowledgement and must not invent player state.
        self.assertFalse(self.net.info()["devices"][0]["status"]["play"])
        self.assertEqual(len([e for e in self.world.events.since(0) if e["kind"] == "player_transport"]), 2)

    def test_disarm_and_invalid_commands_send_nothing(self):
        self.call("arm", "1")
        self.call("arm", "0")
        with patch.object(self.net.decks[3], "send") as send:
            self.assertEqual(self.call("command", "start")[0], 403)
            self.assertEqual(self.call("command", "pause")[0], 400)
            self.assertEqual(self.call("arm", "yes")[0], 400)
            self.assertEqual(self.call("arm", "1", "1")[0], 409)
            send.assert_not_called()

    def test_expiry_disarms_player(self):
        self.call("arm", "1")
        with patch("deckbench.protocols.monitor.time.time", return_value=time.time() + 9):
            self.assertEqual(self.call("command", "stop")[0], 400)
        self.feed()
        self.assertEqual(self.call("command", "stop")[0], 403)

    def test_identity_change_disarms_player(self):
        self.call("arm", "1")
        next(iter(self.net.monitor.devices.values()))["mac"] = "02:00:00:00:00:99"
        self.assertEqual(self.call("command", "stop")[0], 403)

    def test_conflicting_number_disarms_player(self):
        self.call("arm", "1")
        self.player.name = b"XDJ-1000MK2"
        self.net.monitor.feed(self.player.status(), "127.0.0.8", self.net.ports.update)
        self.assertEqual(self.call("command", "stop")[0], 400)

    def test_unsupported_model_and_numbers_are_rejected(self):
        self.net.monitor.devices.clear()
        self.player.name = b"CDJ-3000"
        self.feed()
        self.assertEqual(self.call("arm", "1")[0], 200)
        self.assertEqual(self.call("command", "start")[0], 400)
        self.net.monitor.devices.clear()
        self.player.name = b"CDJ-2000NXS2"
        self.player.deck.number = 5
        self.feed()
        self.assertEqual(self.call("arm", "1", "5")[0], 400)

    def test_sync_commands_use_the_documented_packet_and_stay_opt_in(self):
        self.assertEqual(self.call("command", "master")[0], 403)
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(1)
            for command, value in (("sync-on", 0x10), ("sync-off", 0x20), ("master", 1)):
                self.assertEqual(self.call("command", command)[0], 200)
                packet, source = receiver.recvfrom(1024)
                self.assertEqual((packet[0x0A], packet[0x21], packet[0x2B]), (0x2A, 3, value))
                self.assertEqual(source[0], "127.0.0.3")
        self.assertFalse(self.net.info()["devices"][0]["status"]["master"])

    def test_missing_target_never_sends(self):
        self.ip = "127.0.0.99"
        self.assertEqual(self.call("arm", "1")[0], 400)

    def test_no_available_sender_never_sends(self):
        self.call("arm", "1")
        self.world.decks[3].unplugged = True
        self.assertEqual(self.call("command", "stop")[0], 400)

    def test_sender_number_must_be_unused(self):
        self.call("arm", "1")
        packet = bytearray(self.player.status())
        packet[0x21] = 3
        self.net.monitor.feed(packet, "127.0.0.8", self.net.ports.update)
        self.assertEqual(self.call("command", "stop")[0], 400)

    def test_http_route_requires_arming(self):
        server = serve(self.world, "127.0.0.1", 0)
        base = "http://127.0.0.1:%d/api/player/%s/" % (server.server_address[1], self.ip)
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base + "command/stop?number=2", method="POST"), timeout=2)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            with urllib.request.urlopen(urllib.request.Request(base + "arm/1?number=2", method="POST"), timeout=2) as response:
                state = json.load(response)
            self.assertTrue(state["protocols"]["prolink"]["devices"][0]["transport_armed"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
