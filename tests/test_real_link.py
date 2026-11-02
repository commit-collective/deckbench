# SPDX-License-Identifier: MIT OR Apache-2.0
"""External player tempo and coordinated master handoff."""
import time
import struct
import unittest
import json
import subprocess
from unittest.mock import Mock, patch

from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink
from deckbench.net import interface_macs


class ExternalPlayers(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.world.decks[3] = Deck(self.world, 3, 128.0, 'deck 3')
        self.net = Prolink(self.world)
        self.addCleanup(self.net.stop)
        self.deck = self.world.decks[3]
        self.deck.enabled = True
        self.link = self.net.decks[3]
        other = World()
        other.decks[1] = Deck(other, 1, 124.0, 'physical player')
        self.other = Prolink(other, profile='cdj-2000nxs2')
        self.addCleanup(self.other.stop)
        self.player = self.other.decks[1]
        self.player.deck.master = self.player.deck.playing = True

    def feed(self, player=None, address='127.0.0.9'):
        player = player or self.player
        self.net.monitor.feed(player.status(), address, self.net.ports.update)

    def test_sync_follows_cdj_tempo_and_changes_without_jumping(self):
        self.feed()
        self.world.set_sync(self.deck, True)
        self.world.set_play(self.deck, True)
        self.assertEqual(self.deck.tempo(), 124.0)
        self.deck.anchor_t -= 2
        before = self.deck.position(time.time())
        self.player.deck.base_bpm = 140.0
        self.feed()
        self.assertEqual(self.deck.tempo(), 140.0)
        self.assertAlmostEqual(self.deck.position(time.time()), before, delta=0.05)

    def test_expired_master_does_not_control_tempo(self):
        self.feed()
        self.world.set_sync(self.deck, True)
        with patch('deckbench.protocols.prolink.time.time', return_value=time.time() + 3):
            self.assertIsNone(self.net.external_master_bpm())
            self.assertEqual(self.deck.tempo(), 128.0)

    def test_takeover_targets_cdj_and_waits_for_its_status(self):
        self.feed()
        with patch.object(self.link, 'send') as send:
            self.world.set_master(self.deck, True)
        packet, destination = send.call_args.args[1:]
        self.assertEqual(destination, ('127.0.0.9', self.net.ports.beat))
        self.assertEqual((packet[0x0A], packet[0x21]), (0x26, 3))
        self.assertFalse(self.deck.master)
        self.assertTrue(self.link.pending)
        self.player.handing_to = 3
        # A different address cannot grant this request.
        self.feed(address='127.0.0.8')
        self.assertFalse(self.deck.master)
        self.net.monitor.recent.clear()
        self.feed()
        self.assertTrue(self.deck.master)
        self.assertFalse(self.link.pending)

    def test_early_master_command_reconciles_the_senders_late_status(self):
        self.deck.playing = True
        self.player.deck.master = False
        self.feed()
        with patch.object(self.link, 'send') as send:
            self.net.command_master(self.deck, 1, '127.0.0.9')
            self.assertTrue(self.deck.master)  # genuine no-master operation stays immediate
            self.player.deck.master = True
            self.feed()  # the sender announces MASTER after its command
            self.assertTrue(self.link.pending)
            self.assertFalse(self.deck.master)
            packet, destination = send.call_args.args[1:]
            self.assertEqual(packet[0x0A], 0x26)
            self.assertEqual(destination, ('127.0.0.9', self.net.ports.beat))
            self.player.handing_to = 3
            self.feed()
            self.assertTrue(self.deck.master)
            self.assertFalse(self.link.pending)

    def test_early_master_hint_is_scoped_to_sender_and_expires(self):
        for address, sender, late in [('127.0.0.8', 1, False), ('127.0.0.9', 2, False), ('127.0.0.9', 1, True)]:
            with self.subTest(address=address, sender=sender, late=late):
                self.net.monitor.devices.clear()
                self.deck.master = False
                self.player.deck.master = False
                self.net.monitor.recent.clear()
                self.feed()
                with patch.object(self.link, 'send') as send:
                    self.net.command_master(self.deck, sender, address)
                    if late:
                        self.link.early_master = (address, sender, time.monotonic() - 1)
                    self.player.deck.master = True
                    self.feed()
                    self.assertTrue(self.deck.master)
                    self.assertFalse(self.link.pending)
                    send.assert_not_called()

    def test_release_and_disable_cancel_early_master_reconciliation(self):
        for disable in (False, True):
            with self.subTest(disable=disable):
                self.net.monitor.devices.clear()
                self.net.monitor.recent.clear()
                self.deck.enabled, self.deck.master = True, False
                self.net.command_master(self.deck, 1, '127.0.0.9')
                if disable:
                    self.world.set_enabled(self.deck, False)
                else:
                    self.world.set_master(self.deck, False)
                self.assertIsNone(self.link.early_master)
                with patch.object(self.link, 'send') as send:
                    self.feed()
                    send.assert_not_called()
                self.assertFalse(self.link.pending)

    def test_early_reconciliation_timeout_does_not_reclaim_without_a_grant(self):
        self.net.command_master(self.deck, 1, '127.0.0.9')
        with patch.object(self.link, 'send'):
            self.feed()
        self.assertTrue(self.link.pending)
        self.link.pending_since -= 4
        self.link.give_up()
        self.assertFalse(self.link.pending)
        self.assertFalse(self.deck.master)

    def test_no_master_command_does_not_wait_or_send_a_takeover(self):
        with patch.object(self.link, 'send') as send:
            self.net.command_master(self.deck, 1, '127.0.0.9')
        self.assertTrue(self.deck.master)
        self.assertFalse(self.link.pending)
        send.assert_not_called()

    def test_master_command_with_known_peer_uses_normal_handoff(self):
        self.feed()
        self.deck.master = True  # recover an already conflicting local role too
        with patch.object(self.link, 'send') as send:
            self.net.command_master(self.deck, 1, '127.0.0.9')
        self.assertIsNone(self.link.early_master)
        self.assertTrue(self.link.pending)
        self.assertFalse(self.deck.master)
        self.assertEqual(send.call_args.args[1][0x0A], 0x26)

    def test_network_command_remembers_its_actual_sender(self):
        from deckbench.protocols.prolink import header
        command = header(0x2A, b'CDJ-2000NXS2') + bytes([
            1, 0, 1, 0, 8, 0, 0, 0, 0, 0, 0, 0, 1])
        receiver = Mock()
        receiver.recvfrom.side_effect = [(command, ('127.0.0.9', self.net.ports.beat)), OSError('fixture finished')]
        with patch.object(self.net.runtime, 'socket', return_value=receiver):
            with self.assertRaisesRegex(OSError, 'fixture finished'):
                self.link.control()
        self.assertTrue(self.deck.master)
        self.assertEqual(self.link.early_master[:2], ('127.0.0.9', 1))

    def test_timeout_and_release_cancel_pending_takeover(self):
        self.feed()
        with patch.object(self.link, 'send'):
            self.world.set_master(self.deck, True)
        self.link.pending_since -= 4
        self.link.give_up()
        self.assertFalse(self.deck.master)
        self.assertFalse(self.link.pending)
        with patch.object(self.link, 'send'):
            self.world.set_master(self.deck, True)
        self.world.set_master(self.deck, False)
        self.player.handing_to = 3
        self.feed()
        self.assertFalse(self.deck.master)

    def test_external_master_confirmation_releases_virtual_master(self):
        self.deck.master = True
        self.link.handing_to = 1
        self.feed()
        self.assertFalse(self.deck.master)
        self.assertEqual(self.link.handing_to, 0xFF)

    def test_known_external_number_cannot_be_enabled(self):
        self.player.deck.number = 3
        self.feed()
        self.assertFalse(self.net.allow_enable(self.deck))

    def test_virtual_player_does_not_advertise_mountable_media(self):
        status = self.link.status()
        self.assertEqual((status[0x6F], status[0x73]), (4, 4))

    def test_broadcast_beats_are_visible_without_player_status(self):
        self.deck.enabled = False
        self.net.monitor.feed(self.player.beat(2.0), '127.0.0.9', self.net.ports.beat)
        device = self.net.monitor.snapshot()[0]
        self.assertIsNone(device['status'])
        self.assertEqual(device['phase'][1:], [2.0, 124.0])
        self.assertEqual(device['bar_phase'][1:], [2.0, 124.0])

    def test_reported_bar_is_independent_of_track_count(self):
        status = bytearray(self.player.status())
        status[0xA0:0xA4] = struct.pack('>I', 10)
        status[0xA6] = 1
        self.net.monitor.feed(status, '127.0.0.9', self.net.ports.update)
        self.net.monitor.feed(self.player.beat(0.0), '127.0.0.9', self.net.ports.beat)
        device = self.net.monitor.snapshot()[0]
        self.assertEqual(device['phase'][1], 9.0)
        self.assertEqual(device['bar_phase'][1], 0.0)

    def test_new_beats_override_a_cached_paused_status(self):
        self.deck.enabled = False
        self.player.deck.playing = False
        self.feed()
        self.assertIsNone(self.net.monitor.snapshot()[0]['phase'])
        self.net.monitor.feed(self.player.beat(0.0), '127.0.0.9', self.net.ports.beat)
        self.assertIsNotNone(self.net.monitor.snapshot()[0]['phase'])
        self.player.deck.anchor_pos = 1
        self.feed()
        self.assertIsNone(self.net.monitor.snapshot()[0]['phase'])

    def test_status_ahead_of_beat_does_not_jump_forward_a_bar(self):
        status = bytearray(self.player.status())
        status[0xA0:0xA4] = struct.pack('>I', 10)
        status[0xA6] = 2
        self.net.monitor.feed(status, '127.0.0.9', self.net.ports.update)
        self.net.monitor.feed(self.player.beat(0.0), '127.0.0.9', self.net.ports.beat)
        device = self.net.monitor.snapshot()[0]
        self.assertEqual(device['phase'][1], 8.0)
        self.assertEqual(device['bar_phase'][1], 0.0)

    def test_loop_status_after_beat_corrects_that_same_beat(self):
        status = bytearray(self.player.status())
        status[0x7B] = 4
        status[0xA0:0xA4] = struct.pack('>I', 24)
        status[0xA6] = 4
        self.net.monitor.feed(status, '127.0.0.9', self.net.ports.update)
        self.net.monitor.feed(self.player.beat(0.0), '127.0.0.9', self.net.ports.beat)
        before = self.net.monitor.snapshot()[0]
        self.assertEqual(before['phase'][1], 24.0)
        status[0xA0:0xA4] = struct.pack('>I', 17)
        status[0xA6] = 1
        self.net.monitor.feed(status, '127.0.0.9', self.net.ports.update)
        after = self.net.monitor.snapshot()[0]
        self.assertEqual(after['phase'], [before['phase'][0], 16.0, 124.0])
        self.assertEqual(after['bar_phase'], before['bar_phase'])

    def test_physical_status_is_unicast_to_live_peers(self):
        self.feed()
        self.link.address = '169.254.100.1'
        self.assertEqual(self.net.status_destinations(self.link), ['127.0.0.9'])

    def test_cancelled_outgoing_handoff_retains_master(self):
        self.deck.master = True
        self.link.handing_to = 1
        self.link.cancel_handoff(1)
        self.assertTrue(self.deck.master)
        self.assertEqual(self.link.handing_to, 0xFF)


class AdapterMacs(unittest.TestCase):
    def test_windows_adapter_addresses(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([
            {'ip': '169.254.107.150', 'mac': '10-20-30-40-50-60'},
            {'ip': '169.254.107.151', 'mac': '10-20-30-40-50-60'}]))
        with patch('deckbench.net.sys.platform', 'win32'), patch('deckbench.net.subprocess.run', return_value=result):
            self.assertEqual(interface_macs(), {
                '169.254.107.150': bytes.fromhex('102030405060'),
                '169.254.107.151': bytes.fromhex('102030405060')})

    def test_linux_adapter_addresses(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([
            {'address': '10:20:30:40:50:60', 'addr_info': [
                {'family': 'inet', 'local': '169.254.107.150'}]}]))
        with patch('deckbench.net.sys.platform', 'linux'), patch('deckbench.net.subprocess.run', return_value=result):
            self.assertEqual(interface_macs()['169.254.107.150'], bytes.fromhex('102030405060'))

    def test_real_deck_uses_adapter_mac(self):
        world = World()
        world.decks[3] = Deck(world, 3, 128.0, 'deck 3')
        with patch('deckbench.protocols.prolink.interface_macs', return_value={
                '169.254.100.1': bytes.fromhex('102030405060')}):
            net = Prolink(world, addresses={3: '169.254.100.1'})
        self.assertEqual(net.decks[3].keepalive()[0x26:0x2C], bytes.fromhex('102030405060'))


if __name__ == '__main__':
    unittest.main()
