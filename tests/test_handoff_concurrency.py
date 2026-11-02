# SPDX-License-Identifier: MIT OR Apache-2.0
"""Automatic handoffs serialize with explicit requests, without timing sleeps."""
import threading
import unittest
from unittest.mock import patch

from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink


class AutomaticHandoff(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.world.decks[3] = Deck(self.world, 3, 128)
        self.net = Prolink(self.world)
        self.addCleanup(self.net.stop)
        self.link = self.net.decks[3]
        self.link.deck.enabled = self.link.deck.master = True

    def test_explicit_target_is_not_overwritten_by_automatic_handoff(self):
        real_lock = self.world.lock
        reached, attempted, finished = threading.Event(), threading.Event(), threading.Event()
        failures = []

        class ObservedLock:
            def __enter__(self):
                attempted.set()
                reached.set()
                real_lock.acquire()

            def __exit__(self, *args):
                real_lock.release()

        self.world.lock = ObservedLock()
        peers = [{"online": True, "kind": "player", "number": 1, "status": {"play": True, "sync": True}}]

        def automatic():
            try:
                self.net.play_changed(None, False)
            except BaseException as error:
                failures.append(error)
            finally:
                finished.set()
                reached.set()

        with patch.object(self.net.monitor, 'snapshot', return_value=peers), patch.object(self.net.runtime, 'later') as later:
            with real_lock:
                worker = threading.Thread(target=automatic, daemon=True)
                worker.start()
                saw_progress = reached.wait(2)
                serialized = attempted.is_set() and not finished.is_set()
                self.link.handing_to = 2  # an explicit request wins while it owns the world lock
            worker.join(2)
            self.assertTrue(saw_progress)
            self.assertTrue(serialized, 'automatic handoff must acquire the world lock before making a decision')
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(self.link.handing_to, 2)
            later.assert_not_called()
        self.assertFalse(self.world.events.find('automatic_handoff'))

    def test_playing_master_does_not_build_a_device_snapshot(self):
        self.link.deck.playing = True
        with patch.object(self.net.monitor, 'snapshot') as snapshot:
            self.net.play_changed(None, False)
        snapshot.assert_not_called()

    def test_repeated_status_checks_schedule_one_handoff(self):
        peers = [{"online": True, "kind": "player", "number": 1, "status": {"play": True, "sync": True}}]
        with patch.object(self.net.monitor, 'snapshot', return_value=peers) as snapshot, \
                patch.object(self.net.runtime, 'later') as later:
            for _ in range(10):
                self.net.play_changed(None, False)
        self.assertEqual(self.link.handing_to, 1)
        later.assert_called_once_with(4.0, self.link.cancel_handoff, 1)
        snapshot.assert_called_once_with()
        events = [e for e in self.world.events.since() if e['kind'] == 'automatic_handoff']
        self.assertEqual(len(events), 1)
