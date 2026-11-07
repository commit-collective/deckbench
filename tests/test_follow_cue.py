# SPDX-License-Identifier: MIT OR Apache-2.0
"""Where a stopped older player waits and where its CUE-button cue is, followed from its status and beats."""
import unittest

from deckbench.protocols.monitor import follow_stop


class Player:
    """A player's statuses as the monitor keeps them, one at a time."""

    def __init__(self):
        self.d, self.previous, self.now = {"phase": None}, None, 100.0

    def status(self, state, beat, after=0.2, rbid=7):
        self.now += after
        st = {"state": state, "track_beat": beat, "source": 2, "slot": 3, "rbid": rbid, "seen": self.now}
        follow_stop(self.d, self.previous, st, self.now)
        self.previous = st
        return self

    def beat(self, pos, bpm=120.0):
        """A beat packet now: beat `pos` of the track (from 0) at this time."""
        self.d["phase"] = [self.now, pos, bpm]
        return self


class FollowCue(unittest.TestCase):
    def test_pause_while_playing_is_placed_from_its_beats(self):
        p = Player().status("playing", 10).beat(10.0)
        p.status("paused", 11, after=0.3)            # stopped between 0 and 0.3 s after beat 10, at 120 BPM
        self.assertAlmostEqual(p.d["held"], 10.3)
        self.assertIsNone(p.d["cue"])

    def test_cue_set_while_paused_lands_on_the_nearest_beat(self):
        p = Player().status("playing", 10).beat(10.0)
        p.status("paused", 11, after=0.3).status("cued", 10)       # quantized onto beat 10, reported as 10 (index 9)
        self.assertEqual(p.d["cue"], 10.0)
        self.assertEqual(p.d["held"], 10.0)

    def test_return_to_the_cue_and_cue_hold_keep_it(self):
        p = Player().status("playing", 10).beat(10.0).status("paused", 11, after=0.3).status("cued", 10)
        p.status("cue playing", 10).status("cue playing", 11).status("cued", 10)
        self.assertEqual(p.d["held"], 10.0)
        p.status("playing", 10).beat(10.0).status("playing", 11).status("playing", 12).status("cued", 10)
        self.assertEqual(p.d["held"], 10.0)
        self.assertEqual(p.d["cue"], 10.0)

    def test_what_the_bench_did_not_see_leaves_it_unknown(self):
        p = Player().status("playing", 10).beat(10.0).status("paused", 11, after=0.3).status("cued", 10)
        p.status("paused", 12)                                       # moved with the jog wheel
        self.assertIsNone(p.d["held"])
        p.status("cued", 12)                                         # a cue set there: where is not known
        self.assertIsNone(p.d["cue"])

    def test_a_return_that_disagrees_drops_the_cue(self):
        p = Player().status("playing", 10).beat(10.0).status("paused", 11, after=0.3).status("cued", 10)
        p.status("playing", 10).status("cued", 30)                    # a memory cue elsewhere, say
        self.assertIsNone(p.d["held"])
        self.assertIsNone(p.d["cue"])

    def test_a_gap_or_another_track_forgets(self):
        p = Player().status("playing", 10).beat(10.0).status("paused", 11, after=0.3).status("cued", 10)
        p.status("cued", 10, after=3.0)
        self.assertIsNone(p.d["cue"])
        p = Player().status("playing", 10).beat(10.0).status("paused", 11, after=0.3).status("cued", 10)
        p.status("cued", 10, rbid=8)
        self.assertIsNone(p.d["cue"])


if __name__ == "__main__":
    unittest.main()
