# SPDX-License-Identifier: MIT OR Apache-2.0
import socket
import struct
import unittest

import test_player_control as controls
from deckbench.protocols.remote import load_track_packet


class LoadPacket(unittest.TestCase):
    def test_documented_layout(self):
        packet = load_track_packet(b'deckbench', 3, 2, 1, 3, 0x12345678)
        self.assertEqual(len(packet), 0x58)
        self.assertEqual(packet[0x0A], 0x19)
        self.assertEqual(packet[0x1F:0x25], bytes((1, 0, 3, 0, 0x34, 3)))
        self.assertEqual(packet[0x28:0x30], bytes((1, 3, 1, 0, 0x12, 0x34, 0x56, 0x78)))
        self.assertEqual((packet[0x33], packet[0x34], packet[0x40]), (0x32, 0, 1))

    def test_invalid_track_and_slot_are_rejected(self):
        for slot, track in ((1, 10), (3, 0), (3, 0x100000000)):
            with self.assertRaises(ValueError):
                load_track_packet(b'bench', 3, 2, 2, slot, track)


class RemoteLoad(unittest.TestCase):
    setUp = controls.PlayerControl.setUp
    feed = controls.PlayerControl.feed
    call = controls.PlayerControl.call
    def load(self, source='2', slot='3', track='102'):
        return self.net.player_api(['player', self.ip, 'load', track],
                                   {'number': ['2'], 'source': [source], 'slot': [slot]})

    def test_load_is_armed_announced_and_unicast(self):
        self.assertEqual(self.load()[0], 403)
        self.call('arm', '1')
        self.assertEqual(self.load()[0], 400)
        self.world.decks[3].enabled = True
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.update))
            receiver.settimeout(1)
            status = dict(self.net.info()['devices'][0]['status'])
            self.assertEqual(self.load()[0], 202)
            packet, source = receiver.recvfrom(1024)
            self.assertEqual(source[0], '127.0.0.3')
            self.assertEqual(packet[0x0A], 0x19)
            self.assertEqual(struct.unpack_from('>I', packet, 0x2C)[0], 102)
            self.assertEqual(self.net.info()['devices'][0]['status'], status)

    def test_playing_and_missing_sources_are_rejected(self):
        self.call('arm', '1')
        self.world.decks[3].enabled = True
        self.assertTrue(self.net.info()['devices'][0]['load_allowed'])     # what the page enables its button by
        self.player.deck.playing = True
        self.feed()
        self.assertFalse(self.net.info()['devices'][0]['load_allowed'])
        self.assertEqual(self.load()[0], 409)
        self.player.deck.playing = False
        self.feed()
        self.assertEqual(self.load(source='6')[0], 400)

    def test_unknown_or_loading_state_is_not_treated_as_stopped(self):
        self.call('arm', '1')
        self.world.decks[3].enabled = True
        for state in ('loading', 'cue scratching', 'state 99'):
            with self.subTest(state=state):
                from unittest.mock import patch
                device = dict(self.net.info()['devices'][0])
                device['status'] = dict(device['status'], state=state)
                with patch.object(self.net, 'control_devices', return_value=[device]):
                    self.assertEqual(self.load()[0], 409)

    def test_invalid_inputs_send_no_packets(self):
        from unittest.mock import patch
        self.call('arm', '1')
        self.world.decks[3].enabled = True
        with patch.object(self.net.decks[3], 'send') as send:
            for values in ({'track': '0'}, {'track': '4294967296'}, {'track': 'abc'},
                           {'slot': '1'}, {'source': 'nope'}):
                with self.subTest(values=values):
                    self.assertEqual(self.load(**values)[0], 400)
            send.assert_not_called()
