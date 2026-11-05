# SPDX-License-Identifier: MIT OR Apache-2.0
"""Synthetic public-protocol fixtures, no device captures."""
import socket
import struct
import time
import unittest
from unittest.mock import Mock, patch

from deckbench.capture import replay_packets
from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink, header
from deckbench.protocols.mixer import on_air_packet


def position_packet(position=12345):
    packet = bytearray(0x3C)
    packet[:0x1F] = header(0x0B, b"CDJ-3000")
    packet[0x21] = 2
    struct.pack_into(">IIi", packet, 0x24, 240, position, -326)
    struct.pack_into(">I", packet, 0x38, 1202)
    return packet


class Extensions(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.world.decks[3] = Deck(self.world, 3, 128, "follower")
        self.net = Prolink(self.world)
        self.addCleanup(self.net.stop)

    def feed_one_air_packet(self, source, name, number):
        packet = on_air_packet(name, number, {3: False})
        receiver = Mock()
        receiver.recvfrom.side_effect = [(packet, (source, self.net.ports.beat)), OSError("fixture finished")]
        with patch.object(self.net.runtime, "socket", return_value=receiver):
            with self.assertRaisesRegex(OSError, "fixture finished"):
                self.net.faders()

    def test_queued_own_mixer_packet_cannot_restore_state_after_switching_off(self):
        self.world.decks[3].on_air = None
        self.feed_one_air_packet(self.net.mixer.address, self.net.mixer.name, self.net.mixer.number)
        self.assertIsNone(self.world.decks[3].on_air)

    def test_physical_mixer_packets_still_apply_with_simulation_off(self):
        self.feed_one_air_packet("127.0.0.9", b"DJM-PHYSICAL", 33)
        self.assertFalse(self.world.decks[3].on_air)

    def test_standard_length_takeover_reply_explains_acceptance(self):
        for accepted in (0, 1):
            packet = header(0x27, b"CDJ-TEST") + bytes((1, 0, 2, 0, 8, 0, 0, 0, 2, 0, 0, 0, accepted))
            self.net.monitor.feed(packet, "127.0.0.9", self.net.ports.beat)
            self.assertIn("yes" if accepted else "no", self.net.monitor.since(0)["packets"][-1]["text"])

    def test_precise_position_is_decoded_without_inventing_a_beat_grid(self):
        self.net.monitor.feed(position_packet(), "127.0.0.9", self.net.ports.beat)
        device = self.net.monitor.snapshot()[0]
        at = device["precise"].pop("at")                    # when it came, on the bench's clock: the page's anchor
        self.assertLess(abs(at - time.time()), 5)
        self.assertEqual(device["precise"], {"position_ms": 12345, "length_s": 240, "pitch": -3.26, "bpm": 120.2})
        self.assertIsNone(device["phase"])

    def test_unknown_position_tempo_and_short_packets(self):
        packet = position_packet()
        packet[0x38:0x3C] = b"\xff" * 4
        self.net.monitor.feed(packet, "127.0.0.9", self.net.ports.beat)
        self.assertIsNone(self.net.monitor.snapshot()[0]["precise"]["bpm"])
        self.net.monitor.feed(packet[:30], "127.0.0.8", self.net.ports.beat)
        self.assertFalse(getattr(self.net.monitor, "complained", False))

    def test_mixer_status_supplies_external_master_tempo(self):
        packet = bytearray(0x38)
        packet[:0x1F] = header(0x29, b"DJM-TEST")
        packet[0x21], packet[0x27], packet[0x36] = 33, 0xF0, 0xFF
        struct.pack_into(">I", packet, 0x28, 0x100000)
        struct.pack_into(">H", packet, 0x2E, 12650)
        self.net.monitor.feed(packet, "127.0.0.9", self.net.ports.update)
        self.assertEqual(self.net.external_master_bpm(), 126.5)
        self.assertEqual(self.net.monitor.snapshot()[0]["kind"], "mixer")

    def test_unsolicited_handoff_requires_a_playing_synced_follower(self):
        other = World()
        other.decks[2] = Deck(other, 2, 124, "outgoing")
        peer = Prolink(other).decks[2]
        peer.deck.master = True
        peer.handing_to = 3
        self.world.decks[3].enabled = True
        self.net.monitor.feed(peer.status(), "127.0.0.9", self.net.ports.update)
        self.assertFalse(self.world.decks[3].master)
        self.world.decks[3].playing = self.world.decks[3].sync = True
        self.net.monitor.recent.clear()
        self.net.monitor.feed(peer.status(), "127.0.0.9", self.net.ports.update)
        self.assertTrue(self.world.decks[3].master)
        counter = self.net.decks[3].sync_number
        self.net.monitor.recent.clear()
        self.net.monitor.feed(peer.status(), "127.0.0.9", self.net.ports.update)
        self.assertEqual(self.net.decks[3].sync_number, counter)

    def test_stopped_master_names_successor_and_waits_for_confirmation(self):
        self.world.decks[2] = Deck(self.world, 2, 124, "master")
        # Rebuild the unstarted protocol with both decks.
        self.net.stop()
        self.world.protocols.clear()
        self.net = Prolink(self.world)
        self.addCleanup(self.net.stop)
        master, follower = self.world.decks[2], self.world.decks[3]
        master.enabled = master.playing = master.master = True
        follower.enabled = follower.playing = follower.sync = True
        self.world.set_play(master, False)
        self.assertEqual(self.net.decks[2].handing_to, 3)
        self.assertTrue(master.master)
        self.assertFalse(follower.master)
        # The outgoing status names the follower, which then confirms in its own status.
        self.net.monitor.feed(self.net.decks[2].status(), "127.0.0.2", self.net.ports.update)
        self.assertTrue(follower.master)
        self.net.monitor.feed(self.net.decks[3].status(), "127.0.0.3", self.net.ports.update)
        self.assertFalse(master.master)


class Capture(unittest.TestCase):
    def packets(self):
        return [{"t": i * 0.1, "port": 50001, "src": "127.0.0.9", "hex": bytes(position_packet(1000 + i)).hex(), "len": 0x3C}
                for i in range(10)]

    def test_replay_is_offline_and_deterministic(self):
        with patch.object(socket, "socket", side_effect=AssertionError("offline replay opened a socket")):
            first = replay_packets(self.packets(), seed=7, loss=20, jitter_ms=150)
            second = replay_packets(self.packets(), seed=7, loss=20, jitter_ms=150)
        self.assertEqual(first, second)
        self.assertTrue(first["offline"])
        self.assertGreater(first["received"], 0)
        self.assertGreater(first["dropped"], 0)

    def test_rejects_truncated_exports_and_invalid_packets(self):
        packets = self.packets()
        packets[0]["hex"] += "..."
        with self.assertRaises(ValueError):
            replay_packets(packets)
        with self.assertRaises(ValueError):
            replay_packets([{"t": float("nan"), "src": "127.0.0.9", "port": 50001, "hex": "00"}])

    def test_full_payloads_are_retained(self):
        net = Prolink(World())
        packet = b"synthetic" * 100
        net.monitor.feed(packet, "127.0.0.9", 50002)
        self.assertEqual(net.monitor.since(0)["packets"][0]["hex"], packet.hex())


if __name__ == "__main__":
    unittest.main()
