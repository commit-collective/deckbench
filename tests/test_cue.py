# SPDX-License-Identifier: MIT OR Apache-2.0
"""Play, pause and CUE as a CDJ has them."""
import time
import unittest

from deckbench.core import Deck, World


def bench():
    world = World()
    deck = world.decks[1] = Deck(world, 1, 120.0)
    deck.enabled = True
    return world, deck


class Pause(unittest.TestCase):
    def test_pause_keeps_the_place_and_play_goes_on_from_it(self):
        world, deck = bench()
        world.set_play(deck, True)
        deck.anchor_t -= 3.0                       # three seconds at 120 BPM: six beats
        world.set_play(deck, False)
        at = deck.position(time.time())
        self.assertAlmostEqual(at, 6.0, delta=0.1)
        world.set_play(deck, True)
        self.assertAlmostEqual(deck.position(time.time()), at, delta=0.1)

    def test_a_loaded_track_starts_from_its_first_beat(self):
        world, deck = bench()
        world.set_play(deck, True)
        deck.anchor_t -= 3.0
        world.set_play(deck, False)
        world.load_track(deck, 100)
        self.assertEqual(deck.position(time.time()), 0.0)


class Cue(unittest.TestCase):
    def test_cue_while_playing_goes_back_and_pauses(self):
        world, deck = bench()
        world.set_play(deck, True)
        deck.anchor_t -= 2.0
        world.set_cue(deck, True)
        world.set_cue(deck, False)
        self.assertFalse(deck.playing)
        self.assertTrue(deck.at_cue())

    def test_cue_held_on_the_cue_point_plays_until_let_go(self):
        world, deck = bench()
        world.set_cue(deck, True)
        self.assertTrue(deck.playing and deck.cueing)
        deck.anchor_t -= 1.0
        world.set_cue(deck, False)
        self.assertFalse(deck.playing)
        self.assertTrue(deck.at_cue())

    def test_cue_paused_elsewhere_sets_the_cue_point(self):
        world, deck = bench()
        world.set_play(deck, True)
        deck.anchor_t -= 2.0
        world.set_play(deck, False)
        at = deck.position(time.time())
        world.set_cue(deck, True)
        world.set_cue(deck, False)
        self.assertAlmostEqual(deck.cue, at, delta=0.05)
        self.assertTrue(deck.at_cue())
        world.set_play(deck, True)                  # play on, then CUE goes back to the new point
        deck.anchor_t -= 1.0
        world.set_cue(deck, True)
        world.set_cue(deck, False)
        self.assertAlmostEqual(deck.position(time.time()), at, delta=0.05)

    def test_play_while_cue_is_held_keeps_playing(self):
        world, deck = bench()
        world.set_cue(deck, True)
        world.set_play(deck, True)
        world.set_cue(deck, False)
        self.assertTrue(deck.playing)

    def test_the_snapshot_and_the_status_say_cued_and_cue_playing(self):
        world, deck = bench()
        self.assertTrue(world.snapshot()["decks"]["1"]["cue"])        # paused on it
        world.set_cue(deck, True)
        self.assertTrue(deck.cueing)


if __name__ == "__main__":
    unittest.main()
