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
from deckbench.cli import run_cli_scenarios


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

    def test_manual_bind_keeps_receivers_unfiltered(self):
        address = '169.254.10.5'
        for broadcast in ('169.254.10.255', '169.254.255.255'):
            with self.subTest(broadcast=broadcast), patch('deckbench.protocols.prolink.interface_macs', return_value={address: b'abcdef'}):
                world = World()
                world.decks[3] = Deck(world, 3, 128)
                link = Prolink(world, addresses={3: address}, broadcast=broadcast)
                setup = NetworkSetup(link)
                self.assertIsNone(setup.current()['subnet'])
                self.assertTrue(link.accepts_source('169.254.77.3'))
                link.stop()

    def test_named_interface_uses_its_configured_mask(self):
        self.link.decks[3].address = '169.254.10.5'
        setup = NetworkSetup(self.link, interface='DJ', netmask='255.255.0.0')
        self.assertEqual(setup.current()['subnet'], '169.254.0.0/16')
        self.assertTrue(self.link.accepts_source('169.254.77.3'))
        self.assertFalse(self.link.accepts_source('192.168.1.2'))

    def test_cli_scenario_guard_is_released_after_completion_and_failure(self):
        for fails in (False, True):
            self.world.info['cli_scenarios'] = True
            def run():
                self.assertTrue(self.world.info['cli_scenarios'])
                if fails:
                    raise ValueError('scenario failed')
            if fails:
                with self.assertRaisesRegex(ValueError, 'scenario failed'):
                    run_cli_scenarios(self.world, run)
            else:
                run_cli_scenarios(self.world, run)
            self.assertFalse(self.world.info['cli_scenarios'])

    def test_physical_reconnect_requires_a_distinct_mixer_address(self):
        address, mixer_address = '169.254.10.5', '169.254.10.6'
        for configured in (None, address, mixer_address):
            with self.subTest(configured=configured), patch.object(self.link, 'start'), patch.object(self.link.runtime, 'close', return_value=True):
                self.link.mixer_address = configured
                self.link.reconnect({3: address}, '169.254.255.255',
                                    {address: b'abcdef', mixer_address: b'abcdef'},
                                    ipaddress.IPv4Network('169.254.0.0/16'))
                if configured == mixer_address:
                    self.assertEqual(self.link.mixer.address, mixer_address)
                    self.assertFalse(self.link.mixer.unavailable)
                else:
                    self.assertNotEqual(self.link.mixer.address, address)
                    self.assertIn('--mixer-address', self.link.mixer.unavailable)
                    self.assertFalse(self.link.mixer.set_on(True))
                    ok, message = self.link.mixer_do({'on': True})
                    self.assertFalse(ok)
                    self.assertIn('--mixer-address', message)

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
