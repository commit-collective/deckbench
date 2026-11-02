# SPDX-License-Identifier: MIT OR Apache-2.0
"""An observer announces its presence but never advertises playback or a database."""
import socket
import time
import unittest
from unittest.mock import Mock, patch

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink
from deckbench.testing import Bench


class Observer(unittest.TestCase):
    def test_conflict_warning_recovers_without_erasing_other_errors(self):
        world = World()
        world.decks[7] = Deck(world, 7, 128, 'observer')
        net = Prolink(world, observer=True)
        self.addCleanup(net.stop)
        link = net.decks[7]
        tick = [0]
        conflicted = (True, True, False, True, False)
        states = []
        net.runtime.errors.append('a real worker failure')
        stopping = Mock()
        stopping.is_set.side_effect = lambda: tick[0] >= len(conflicted)

        def wait(_):
            states.append(list(net.runtime.errors))
            tick[0] += 1

        stopping.wait.side_effect = wait
        peers = lambda: [{'online': True, 'number': 7}] if conflicted[tick[0]] else []
        with patch.object(net.runtime, 'stopping', stopping), patch.object(net.runtime, 'socket', return_value=Mock()), \
                patch.object(net.monitor, 'snapshot', side_effect=peers), patch.object(link, 'send') as send, \
                patch('deckbench.protocols.prolink.time.time', side_effect=lambda: 100 + tick[0] * 2):
            link.announce()
        self.assertEqual(send.call_count, 2)
        self.assertEqual([state.count('observer number conflict') for state in states], [1, 1, 0, 1, 0])
        self.assertTrue(all('a real worker failure' in state for state in states))
        self.assertEqual([e['on'] for e in world.events.since() if e['kind'] == 'observer_conflict'],
                         [True, False, True, False])

    def test_cli_exposes_no_playback_decks(self):
        with Bench(numbers=[7], args=["--observe"]) as bench:
            state = bench.state()
            self.assertEqual(state["decks"], {})
            self.assertTrue(state["protocols"]["prolink"]["settings"]["observer"])

    def test_only_keepalives_are_sent_and_database_ports_remain_free(self):
        world = World()
        world.decks[7] = Deck(world, 7, 128, "observer")
        net = Prolink(world, ports=fresh(), observer=True)
        world.decks.clear()
        self.addCleanup(net.stop)
        net.start()
        end = time.monotonic() + 2
        while not net.monitor.since(0)["packets"] and time.monotonic() < end:
            time.sleep(0.01)
        packets = net.monitor.since(0)["packets"]
        self.assertTrue(packets)
        self.assertEqual({p["kind"] for p in packets}, {"keep-alive"})
        self.assertTrue(all(p["name"] == "deckbench" for p in packets))
        for port in (net.ports.query, net.ports.db):
            with socket.socket() as probe:
                probe.bind(("127.0.0.7", port))
        self.assertEqual(net.mixer_do({"on": True})[0], False)
