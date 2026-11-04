# SPDX-License-Identifier: MIT OR Apache-2.0
import ipaddress
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.network_setup import NetworkSetup
from deckbench.protocols.prolink import Prolink, PortError
from deckbench.web import serve


class NetworkSetupTests(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.world.decks[3] = Deck(self.world, 3, 128)
        self.link = Prolink(self.world, ports=fresh())
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.link.stop)
        self.setup = NetworkSetup(self.link, settings=os.path.join(self.folder.name, 'network.json'))

    def test_discovery_reports_server_addresses_and_route(self):
        entries = [('Ethernet 2', ipaddress.IPv4Interface('169.254.4.5/16'))]
        with patch('deckbench.phone.interfaces', return_value=entries), patch('deckbench.phone.route_address', return_value='169.254.4.5'):
            result = self.setup.snapshot()
        self.assertEqual(result['interfaces'], [{'name': 'Ethernet 2', 'addresses': ['169.254.4.5/16'], 'default_route': True}])
        self.assertEqual(result['current']['addresses'], {'3': '127.0.0.3'})

    def test_remember_is_a_suggestion_not_an_automatic_connection(self):
        with patch.object(self.link, 'reconnect') as reconnect, patch('deckbench.phone.dj_interface', return_value=[ipaddress.IPv4Interface('169.254.4.5/16')]), patch('deckbench.network_setup.interface_macs', return_value={'169.254.4.5': b'abcdef'}):
            self.setup.apply('Ethernet 2', True)
        reconnect.assert_called_once_with({3: '169.254.4.5'}, '169.254.255.255', {'169.254.4.5': b'abcdef'}, ipaddress.IPv4Network('169.254.0.0/16'))
        other = NetworkSetup(self.link, settings=self.setup.settings)
        with patch('deckbench.phone.interfaces', return_value=[]):
            self.assertEqual(other.snapshot()['remembered'], 'Ethernet 2')
        self.assertIsNone(other.interface)

    def test_reconnect_rejects_enabled_decks_and_mixer(self):
        self.world.decks[3].enabled = True
        with self.assertRaisesRegex(RuntimeError, 'Switch off'):
            self.setup.apply('')
        self.world.decks[3].enabled = False
        self.link.mixer.on = True
        with self.assertRaisesRegex(RuntimeError, 'Switch off'):
            self.setup.apply('')
        self.link.mixer.on = False

    def test_loopback_reconnect_releases_workers_and_resets_remote_state(self):
        self.link.monitor.record(os.path.join(self.folder.name, 'capture.jsonl'))
        capture = self.link.monitor.recording
        self.link.start()
        workers = list(self.link.runtime.threads)
        self.link.player_controls.add(('test',))
        self.link.unit['number'] = 2
        self.setup.apply('')
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertTrue(self.link.ready.is_set())
        self.assertFalse(self.link.player_controls)
        self.assertEqual(self.link.unit['number'], 0)
        self.assertFalse(self.world.decks[3].enabled)
        self.assertEqual(len(self.world.protocols), 1)
        self.assertTrue(self.link.accepts_source('127.0.0.9'))
        self.assertFalse(self.link.accepts_source('169.254.4.5'))
        self.assertIs(self.link.monitor.recording, capture)
        self.assertFalse(capture.closed)

    def test_failed_bind_restores_previous_network(self):
        self.link.start()
        start = self.link.start
        calls = []
        def fail_once():
            calls.append(True)
            if len(calls) == 1:
                raise PortError('port occupied')
            return start()
        with patch.object(self.link, 'start', side_effect=fail_once):
            with self.assertRaisesRegex(ValueError, 'previous network restored'):
                self.setup.apply('')
        self.assertTrue(self.link.ready.is_set())
        self.assertEqual(self.link.decks[3].address, '127.0.0.3')

    def test_missing_address_does_not_stop_existing_network(self):
        with patch('deckbench.phone.dj_interface', side_effect=ValueError('no preferred IPv4')), patch.object(self.link.runtime, 'close') as close:
            with self.assertRaisesRegex(ValueError, 'no preferred IPv4'):
                self.setup.apply('unplugged')
            close.assert_not_called()

    def test_network_api_requires_token_and_valid_body(self):
        server = serve(self.world, port=0, token='secret', network=self.setup)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:%d/api/network' % server.server_port
        with self.assertRaises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(url, timeout=5)
        self.assertEqual(failure.exception.code, 401)
        with patch('deckbench.phone.interfaces', return_value=[]):
            with urllib.request.urlopen(url + '?token=secret', timeout=5) as result:
                self.assertIn('current', json.load(result))
        request = urllib.request.Request(url + '?token=secret', data=b'{"interface":42}', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(failure.exception.code, 400)

    def test_network_api_refuses_an_enabled_deck_and_keeps_http_alive(self):
        server = serve(self.world, port=0, network=self.setup)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:%d/api/network' % server.server_port
        self.world.decks[3].enabled = True
        request = urllib.request.Request(url, data=b'{"interface":""}', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(failure.exception.code, 409)
        with patch('deckbench.phone.interfaces', return_value=[]):
            with urllib.request.urlopen(url, timeout=5) as result:
                self.assertEqual(json.load(result)['current']['addresses'], {'3': '127.0.0.3'})
