# SPDX-License-Identifier: MIT OR Apache-2.0
"""A bench deck that loads a real player's track: the grid, title and waveform read from that player, the deck on the
grid, and a load command from the network."""
import struct
import unittest
from unittest.mock import patch

import test_player_control as controls
from deckbench.protocols.prolink import PITCH_NORMAL
from deckbench.protocols.remote import load_track_packet

GRID = [[250, 3, 12550], [728, 4, 12550], [1206, 1, 12550], [1684, 2, 12550]]


class LinkedTrack(unittest.TestCase):
    feed = controls.PlayerControl.feed

    def setUp(self):
        controls.PlayerControl.setUp(self)              # player 2 at 127.0.0.9, a real CDJ-2000NXS2, and bench deck 3
        self.deck = self.world.decks[3]
        self.deck.enabled = True
        self.link = self.net.decks[3]

    def rounds(self, n, grid=GRID, meta=None):
        """n rounds of the reader, with the player's answers: (the waveform reads, the title reads)."""
        reads, titles = [], []
        stops = iter([False] * n + [True])

        def read(address, source, number, slot, rbid, **k):
            reads.append((address, number, slot, rbid))
            return {"overview": b"\0" * 12, "detail": b"\0" * 300, "grid": grid,
                    "style": {"overview": "rgb", "detail": "rgb"}}

        def title(address, source, number, slot, rbid, *a, **k):
            titles.append(rbid)
            return meta or {"title": "Real track", "artist": "Someone"}
        with patch("deckbench.waveforms.read_track_waveforms", read), \
             patch("deckbench.metadata.read_track_metadata", title), \
             patch.object(self.net.runtime.stopping, "wait", lambda seconds: next(stops)):
            self.net.read_waveforms()
        return reads, titles

    def test_a_real_track_is_read_and_the_deck_plays_on_its_grid(self):
        self.world.load_track(self.deck, 57, source=2, slot=3)
        reads, titles = self.rounds(2)
        self.assertEqual(reads, [(self.ip, 3, 3, 57)])        # asked as the deck itself, player 3, even with Read waveforms off
        self.assertEqual(titles, [57])
        self.assertEqual((self.deck.grid["bpm"], self.deck.grid["first"]), (125.5, 3))
        self.assertEqual(self.deck.base_bpm, 125.5)
        described = self.net.describe(self.deck)
        self.assertEqual((described["track"], described["linked"]["state"]), ("Real track", "ready"))
        status = self.link.status()
        self.assertEqual(status[0xA6], 3)                     # its first beat is beat 3 of a bar, as the grid says
        self.assertEqual(struct.unpack(">H", status[0x92:0x94])[0], 12550)
        self.assertEqual(struct.unpack(">I", status[0x8C:0x90])[0], PITCH_NORMAL)
        self.assertEqual(self.link.beat(1.0)[0x5C], 4)
        self.assertEqual(self.net.linked_waveform(3)[1]["grid"], GRID)
        self.assertEqual(self.world.events.since(0)[-1]["kind"], "linked_track_read")

    def test_a_track_read_for_its_player_gets_its_title(self):
        self.world.load_track(self.deck, 57, source=2, slot=3)
        key, _ = self.net.linked_key(self.link, [d for d in self.net.monitor.snapshot() if d["online"]])
        self.net.waves[key] = {"data": {"overview": b"\0" * 12, "detail": b"\0" * 300, "grid": GRID, "style": {}},
                               "used": 0, "meta": None}         # read for the player, with no title
        reads, titles = self.rounds(2)
        self.assertEqual((reads, titles), ([], [57]))
        self.assertEqual(self.net.describe(self.deck)["track"], "Real track")

    def test_the_pitch_is_what_it_plays_at_over_the_track_tempo(self):
        self.world.load_track(self.deck, 57, source=2, slot=3)
        self.rounds(2)
        self.world.set_tempo(self.deck, 128.0)
        status = self.link.status()
        self.assertEqual(struct.unpack(">H", status[0x92:0x94])[0], 12550)   # the track's tempo stays
        pitch = struct.unpack(">I", status[0x8C:0x90])[0]
        self.assertAlmostEqual(125.5 * pitch / PITCH_NORMAL, 128.0, places=2)

    def test_a_track_of_its_own_database_is_not_read(self):
        self.world.load_track(self.deck, 57)
        self.assertEqual(self.rounds(2), ([], []))
        self.assertIsNone(self.deck.grid)
        self.assertIsNone(self.net.describe(self.deck)["linked"])
        self.assertEqual(self.link.status()[0xA6], 1)

    def test_a_missing_player_is_said_and_a_new_load_drops_the_grid(self):
        self.world.load_track(self.deck, 57, source=4, slot=3)
        self.assertEqual(self.rounds(2), ([], []))
        linked = self.net.describe(self.deck)["linked"]
        self.assertEqual((linked["state"], linked["reason"]), ("failed", "player 4 is not on the network"))
        self.world.load_track(self.deck, 57, source=2, slot=3)
        self.rounds(2)
        self.assertIsNotNone(self.deck.grid)
        self.world.load_track(self.deck, 58, source=2, slot=3)
        self.assertIsNone(self.deck.grid)
        self.assertIsNone(self.net.describe(self.deck)["linked"])
        self.assertEqual(self.rounds(2)[0], [(self.ip, 3, 3, 58)])
        self.assertEqual(self.deck.grid["first"], 3)

    def test_a_grid_whose_tempo_changes_is_followed_at_its_first(self):
        self.world.load_track(self.deck, 57, source=2, slot=3)
        self.rounds(2, grid=[[0, 1, 12000], [500, 2, 12400]])
        self.assertEqual((self.deck.base_bpm, self.deck.grid["variable"]), (120.0, True))


class LoadCommand(unittest.TestCase):
    """A load-track command sent to a bench deck, as rekordbox or Beat Link sends one to a player."""
    feed = controls.PlayerControl.feed

    def setUp(self):
        controls.PlayerControl.setUp(self)
        self.deck = self.world.decks[3]
        self.deck.enabled = True

    def test_the_deck_loads_the_track_it_is_told(self):
        self.net.load_command("127.0.0.3", load_track_packet(b"rekordbox", 2, 3, 2, 3, 77))
        self.assertEqual(self.deck.track[0], 77)
        link = self.net.decks[3]
        self.assertEqual((link.source, link.slot, link.rbid), (2, 3, 77))
        event = self.world.events.since(0)[-1]
        self.assertEqual((event["kind"], event["sender"], event["rbid"]), ("load_command", 2, 77))

    def test_a_playing_deck_refuses_and_another_address_is_not_it(self):
        self.deck.playing = True
        self.net.load_command("127.0.0.3", load_track_packet(b"rekordbox", 2, 3, 2, 3, 77))
        self.assertNotEqual((self.deck.track or (None,))[0], 77)
        self.assertEqual(self.world.events.since(0)[-1]["reason"], "it plays")
        self.deck.playing = False
        self.net.load_command("127.0.0.4", load_track_packet(b"rekordbox", 2, 3, 2, 3, 77))
        self.assertNotEqual((self.deck.track or (None,))[0], 77)


if __name__ == "__main__":
    unittest.main()
