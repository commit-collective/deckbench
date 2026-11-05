# SPDX-License-Identifier: MIT OR Apache-2.0
"""Player control and the reading of track info: global settings, on by default and off for an observer."""
import unittest
from unittest.mock import patch

import test_player_control as controls
from _ports import fresh
from deckbench.core import World
from deckbench.protocols.prolink import Prolink


class Settings(unittest.TestCase):
    setUp = controls.PlayerControl.setUp
    feed = controls.PlayerControl.feed
    call = controls.PlayerControl.call

    def test_on_by_default_and_control_off_for_an_observer(self):
        settings = Prolink(World(), ports=fresh()).settings()
        self.assertEqual((settings["player_control"], settings["auto_track_info"]), (True, True))
        settings = Prolink(World(), ports=fresh(), observer=True).settings()
        self.assertEqual((settings["player_control"], settings["auto_track_info"]), (False, True))

    def test_player_control_arms_every_eligible_player(self):
        device = lambda: self.net.info()["devices"][0]
        self.assertFalse(device()["transport_armed"])
        self.assertTrue(self.net.set_option("player_control", "1"))
        self.assertTrue(device()["transport_armed"])
        self.assertTrue(self.net.set_option("player_control", "0"))
        self.assertFalse(device()["transport_armed"])
        self.assertFalse(self.net.set_option("player_control", "maybe"))

    def test_commands_go_through_with_player_control_on(self):
        self.assertEqual(self.call("command", "stop")[0], 403)
        self.net.set_option("player_control", "1")
        with patch.object(self.net.decks[3], "send") as send:
            self.assertEqual(self.call("command", "stop")[0], 200)
        send.assert_called_once()

    def test_track_info_is_read_once_by_itself(self):
        self.world.decks[3].enabled = True
        self.net.set_option("auto_track_info", "1")
        reads = []
        stops = iter([False, False, True])
        with patch("deckbench.metadata.read_track_metadata", side_effect=lambda *a, **k: reads.append(a) or {"title": "T"}),              patch.object(self.net.runtime.stopping, "wait", lambda seconds: next(stops)):
            self.net.read_track_info()
        self.assertEqual(len(reads), 1)                     # the second round finds it in the cache
        self.assertEqual(self.net.info()["devices"][0]["metadata"]["title"], "T")


if __name__ == "__main__":
    unittest.main()
