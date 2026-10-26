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


class AudioSource(unittest.TestCase):
    """The sound port plays the one deck the unit's input is (its INPUT SOURCE knob), or all of them."""

    def two_playing(self):
        from deckbench.audio import Mixer, voice
        world = World()
        for n in (1, 2):
            deck = world.decks[n] = Deck(world, n, 120.0)
            deck.enabled = deck.playing = True
        now = time.time()
        for deck in world.decks.values():
            deck.anchor_t = now
        return world, Mixer(world), now, voice

    def distance(self, block, voice, deck, now, world):
        import array
        a = array.array("h")
        a.frombytes(block)
        v = voice(deck.number, deck.position(now), deck.tempo(), 4096)
        return sum(abs(int(x * 32767) - y) for x, y in zip(v, a[0::2]))

    def test_only_the_chosen_deck_is_heard_and_all_again(self):
        world, mixer, now, voice = self.two_playing()
        both = mixer.block(4096, now)
        self.assertTrue(world.set_audio_source(2))
        only2 = mixer.block(4096, now)
        self.assertEqual(self.distance(only2, voice, world.decks[2], now, world), 0)          # exactly deck 2's voice
        self.assertNotEqual(both, only2)
        self.assertEqual(world.snapshot()["bench"]["audio_source"], 2)
        self.assertTrue(world.set_audio_source(None))
        self.assertEqual(mixer.block(4096, now), both)

    def test_no_such_deck(self):
        world, mixer, now, voice = self.two_playing()
        self.assertFalse(world.set_audio_source(9))
        self.assertIsNone(world.audio_decks)

    def test_a_bench_started_with_decks_keeps_them(self):
        from deckbench.audio import Mixer
        world, _, now, voice = self.two_playing()
        mixer = Mixer(world, {1})
        world.set_audio_source(2)
        self.assertEqual(self.distance(mixer.block(4096, now), voice, world.decks[1], now, world), 0)       # --audio-decks wins
