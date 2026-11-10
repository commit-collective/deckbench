# SPDX-License-Identifier: MIT OR Apache-2.0
"""Recording a mix of real players as a scenario that plays it again on them."""
import unittest

from deckbench.core import Deck, World
from deckbench.mixrecord import MixRecorder, build, from_capture
from deckbench.protocols.prolink import Ports, Prolink
from deckbench.scenario import Scenario

PITCH_NORMAL = 0x100000
STATES = {"no track": 0, "loading": 2, "playing": 3, "looping": 4, "paused": 5, "cued": 6, "cue playing": 7,
          "searching": 9}


def template(number):
    world = World()
    world.decks[number] = Deck(world, number, 128.0, "deck %d" % number)
    return Prolink(world).decks[number]


class Player:
    """A real player as the bench hears it: status packets, with what is in them set by hand."""

    def __init__(self, number, name=b"CDJ-2000NXS2"):
        self.link = template(number)
        self.link.name = name
        self.ip = "127.0.0.%d" % (20 + number)
        self.track = (0, 0, 0)
        self.state, self.beat, self.pitch = "no track", 0, 0.0
        self.master = self.sync = False

    def packet(self):
        data = bytearray(self.link.status())
        data[0x7B] = STATES[self.state]
        flags = data[0x89] & ~0x70
        if self.state in ("playing", "looping"):
            flags |= 0x40
        if self.master:
            flags |= 0x20
        if self.sync:
            flags |= 0x10
        data[0x89] = flags
        source, slot, rbid = self.track
        data[0x28], data[0x29] = source, slot
        data[0x2C:0x30] = rbid.to_bytes(4, "big")
        data[0xA0:0xA4] = self.beat.to_bytes(4, "big")
        data[0x8C:0x90] = int(PITCH_NORMAL * (1 + self.pitch / 100)).to_bytes(4, "big")
        data[0x92:0x94] = (12800 if rbid else 0).to_bytes(2, "big")
        return bytes(data)


class Session:
    """A bench that is not started, its monitor fed the players' statuses on a clock of its own, with a recording."""

    def __init__(self):
        world = World()
        self.net = Prolink(world)
        self.monitor = self.net.monitor
        self.now = 100.0
        self.recorder = MixRecorder(clock=lambda: self.now)
        self.monitor.mix = self.recorder
        self.recorder.start()

    def hear(self, *players):
        for player in players:
            device = self.monitor.device(player.ip, self.now, False, player.link.name.decode(), player.link.number)
            self.monitor.status(device, player.packet(), self.now)

    def wait(self, seconds, *players, beats_per_second=128 / 60):
        """`seconds` pass, the players saying how they are each 0.2 s. A playing one moves on in its track."""
        end = self.now + seconds
        while self.now < end - 1e-9:
            self.now = round(self.now + 0.2, 3)
            for player in players:
                if player.state == "playing":
                    player.beat = int(round(player.beat + 0.2 * beats_per_second * (1 + player.pitch / 100)))
            self.hear(*players)


def actions(scenario):
    return [(s["at"], s["player"], s.get("press") or "load %s" % s.get("load")) for s in scenario["steps"]
            if s["do"] == "player"]


class Recording(unittest.TestCase):
    def test_a_mix_becomes_steps_that_do_it_again_and_check_it(self):
        s = Session()
        one, two = Player(1, b"XDJ-1000MK2"), Player(2)
        one.track, one.state, one.beat, one.master = (1, 3, 2476), "cued", 1, True
        two.track, two.state = (0, 0, 0), "no track"
        s.hear(one, two)
        s.wait(1, one, two)
        one.state = "playing"                                        # 1.2 s in
        s.wait(4, one, two)
        two.track, two.state, two.beat = (1, 3, 205), "cued", 1      # 5.2 s: loads a track from player 1's USB
        s.wait(3, one, two)
        two.sync = True                                              # 8.2 s
        s.wait(1, one, two)
        two.state = "playing"                                        # 9.2 s
        s.wait(2, one, two)
        two.master, one.master = True, False                         # 11.2 s
        s.wait(1, one, two)
        one.state = "cued"                                           # 12.2 s
        s.wait(1, one, two)
        scenario = self.recorder_stop(s)
        Scenario(scenario)                                           # a scenario the bench takes
        self.assertEqual(actions(scenario), [
            (0.5, 1, "load 2476"),
            (11.0, 1, "master"),
            (13.2, 1, "play-pause"),
            (17.2, 2, "load 205"),
            (20.2, 2, "sync-on"),
            (21.2, 2, "play-pause"),
            (23.2, 2, "master"),
            (24.2, 1, "cue")])
        load = next(s for s in scenario["steps"] if s.get("load") == 205)
        self.assertEqual((load["source"], load["slot"]), (1, "usb"))
        setup = [s for s in scenario["steps"] if s["do"] == "expect_player" and s["at"] == 0]
        self.assertEqual([(x["player"], x["match"]) for x in setup], [
            (1, {"online": True, "play": False, "model": "XDJ-1000MK2"}),
            (2, {"online": True, "play": False, "model": "CDJ-2000NXS2"})])
        play = scenario["steps"].index(next(x for x in scenario["steps"] if x.get("press") == "play-pause" and x["player"] == 2))
        self.assertEqual(scenario["steps"][play + 1]["match"], {"play": True})
        self.assertLessEqual(scenario["steps"][play + 1]["within"], 1.9)       # no longer than the gap to the next step
        self.assertNotIn("notes", scenario)

    def recorder_stop(self, session):
        return session.recorder.stop("test")

    def test_what_the_network_cannot_do_is_noted_at_its_time(self):
        s = Session()
        one = Player(3)
        one.track, one.state, one.beat = (3, 3, 12), "cued", 1
        s.hear(one)
        s.wait(1, one)
        one.state = "playing"
        s.wait(2, one)
        for value in (0.5, 1.0, 1.5, 2.0):                           # the pitch fader moved in one go
            one.pitch = value
            s.wait(0.2, one)
        s.wait(2, one)
        one.beat += 64                                               # a hot cue, further on
        s.wait(1, one)
        one.state = "looping"
        s.wait(1, one)
        one.state = "playing"
        s.wait(1, one)
        one.track, one.state, one.beat = (0, 0, 0), "no track", 0
        s.wait(1, one)
        scenario = s.recorder.stop()
        Scenario(scenario)
        notes = scenario["notes"]
        self.assertEqual(len([n for n in notes if "pitch" in n]), 1)
        self.assertIn("+2.00 %", next(n for n in notes if "pitch" in n))
        self.assertTrue(any("jumped" in n for n in notes), notes)
        self.assertTrue(any("loop began" in n for n in notes) and any("loop ended" in n for n in notes), notes)
        self.assertTrue(any("ejected" in n for n in notes), notes)
        logs = [x for x in scenario["steps"] if x["do"] == "log"]
        self.assertEqual(len(logs), len(notes))

    def test_a_cue_held_and_a_player_playing_from_the_start(self):
        s = Session()
        one, two = Player(1), Player(2)
        one.track, one.state, one.beat, one.sync = (1, 3, 7), "playing", 40, True
        two.track, two.state, two.beat, two.pitch = (2, 2, 8), "cued", 1, 3.0
        s.hear(one, two)
        s.wait(1, one, two)
        two.state = "cue playing"
        s.wait(1.4, one, two)
        two.state = "cued"
        s.wait(1, one, two)
        scenario = s.recorder.stop()
        Scenario(scenario)
        held = next(x for x in scenario["steps"] if x.get("hold"))
        self.assertEqual((held["player"], held["press"]), (2, "cue"))
        self.assertAlmostEqual(held["hold"], 1.4, delta=0.25)
        self.assertTrue(any(x.get("press") == "sync-on" and x["player"] == 1 for x in scenario["steps"]))
        self.assertTrue(any(x["do"] == "player" and x.get("load") == 8 and x["slot"] == "sd" for x in scenario["steps"]))
        notes = " / ".join(scenario["notes"])
        self.assertIn("player 1 was playing when the recording began", notes)
        self.assertIn("player 2: set its pitch to +3.00 %", notes)

    def test_the_bench_decks_and_nothing_heard_are_left_out(self):
        s = Session()
        scenario = s.recorder.stop("empty")
        self.assertEqual(scenario, {"name": "empty", "steps": []})
        self.assertFalse(s.recorder.recording)
        s.recorder.observe(1, "CDJ", {"state": "cued"}, 101.0)       # not recording: nothing kept
        self.assertEqual(s.recorder.snapshot()["players"], [])

    def test_a_capture_gives_the_same_scenario(self):
        one = Player(2)
        one.ip = "169.254.1.2"
        packets, t = [], 0.0

        def keep():
            packets.append({"t": round(t, 3), "src": one.ip, "port": Ports().update, "hex": one.packet().hex()})
        one.track, one.state, one.beat = (2, 3, 99), "cued", 1
        for _ in range(5):
            t += 0.2
            keep()
        one.state = "playing"
        for _ in range(10):
            t += 0.2
            one.beat += 1
            keep()
        scenario = from_capture(packets, "from a capture")
        self.assertEqual(scenario["name"], "from a capture")
        self.assertEqual([(x["player"], x.get("press") or x.get("load")) for x in scenario["steps"] if x["do"] == "player"],
                         [(2, 99), (2, "play-pause")])


class Build(unittest.TestCase):
    def test_steps_come_in_time_order_and_a_player_heard_later_is_noted(self):
        players = {4: {"model": "CDJ-3000", "first": {"rbid": 5, "source": 4, "slot": 3, "state": "cued", "sync": False,
                                                       "master": False, "pitch": 0.0}, "first_t": 9.0}}
        scenario = build(players, [(9.0, 4, "joined", {"rbid": 5, "state": "cued"}), (12.0, 4, "play", {"from": 1})],
                         "late")
        Scenario(scenario)
        self.assertEqual([x["at"] for x in scenario["steps"]], sorted(x["at"] for x in scenario["steps"]))
        self.assertIn("came on the link", scenario["notes"][0])


if __name__ == "__main__":
    unittest.main()
