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
        self.master = self.sync = self.on_air = False

    def packet(self):
        data = bytearray(self.link.status())
        data[0x7B] = STATES[self.state]
        flags = data[0x89] & ~0x78
        if self.on_air:
            flags |= 0x08
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
        data[0xA6] = (self.beat - 1) % 4 + 1 if self.beat else 0      # its place in the bar, the track starting on a bar
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
                if player.state == "playing":                    # counted in fractions, said in whole beats
                    pos = player.__dict__.get("pos")
                    if pos is None or int(pos) != player.beat:      # a test moved it: from there
                        pos = float(player.beat)
                    player.pos = pos + 0.2 * beats_per_second * (1 + player.pitch / 100)
                    player.beat = int(player.pos)
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
            (20.26, 2, "play-pause"),                               # half a bar early, to wait for its beat
            (23.2, 2, "master"),
            (24.2, 1, "cue")])
        starts = [x for x in scenario["steps"] if x.get("press") == "play-pause"]
        self.assertNotIn("on_beat", starts[0])                       # player 1 started with no master playing
        self.assertEqual(starts[1]["on_beat"]["player"], 1)           # player 2 on player 1's beat
        self.assertIn(starts[1]["on_beat"]["beat"], (1, 2, 3, 4))
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


class Limits(unittest.TestCase):
    def test_an_older_player_is_played_with_fader_start(self):
        s = Session()
        old = Player(3, b"CDJ-2000")
        old.track, old.state, old.beat = (3, 3, 41), "cued", 1
        s.hear(old)
        s.wait(1, old)
        old.state = "playing"
        s.wait(2, old)
        old.state = "paused"                                         # fader start cannot pause in place
        s.wait(1, old)
        old.state = "playing"
        s.wait(1, old)
        old.state = "cued"
        s.wait(1, old)
        scenario = s.recorder.stop()
        Scenario(scenario)
        self.assertEqual([x for _, _, x in actions(scenario)], ["load 41", "start", "stop", "start", "stop"])
        self.assertIn("goes back to its cue instead", " / ".join(scenario["notes"]))

    def test_a_player_that_takes_neither_is_left_to_do_by_hand(self):
        players = {2: {"name": "XDJ-XZ", "model": "XDJ-XZ", "first_t": 0.0,
                       "first": {"rbid": 0, "source": 0, "slot": 0, "state": "no track", "sync": False, "master": False}}}
        scenario = build(players, [(3.0, 2, "play", {"from": 1})], "xz")
        self.assertEqual(actions(scenario), [])
        self.assertIn("PLAY by hand", scenario["notes"][0])

    def test_a_track_from_a_computer_is_loaded_by_hand(self):
        s = Session()
        one = Player(1)
        one.track, one.state, one.beat = (17, 4, 3001), "cued", 1     # rekordbox on a laptop, player 17
        s.hear(one)
        s.wait(1, one)
        one.track = (1, 3, 12)
        s.wait(1, one)
        one.track = (18, 4, 3002)
        s.wait(1, one)
        scenario = s.recorder.stop()
        Scenario(scenario)
        self.assertEqual([x for _, _, x in actions(scenario)], ["load 12"])
        notes = " / ".join(scenario["notes"])
        self.assertIn("load track 3001 by hand", notes)
        self.assertIn("load track 3002 by hand", notes)
        check = next(x for x in scenario["steps"] if x["do"] == "expect_player" and x["match"] == {"rbid": 3001})
        self.assertTrue(check["required"])                           # the setup waits for it, by hand

    def test_a_setup_that_is_not_right_ends_the_replay(self):
        world = World()
        scenario = Scenario({"steps": [
            {"at": 0, "do": "expect_player", "player": 9, "match": {"online": True}, "within": 0.1, "required": True},
            {"at": 0, "do": "log", "text": "never"}]})
        results = scenario.run(world)
        self.assertEqual(len(results), 1)
        self.assertIn("required: the scenario ends here", results[0][2])
        with self.assertRaises(Exception):
            Scenario({"steps": [{"at": 0, "do": "log", "text": "x", "required": True}]})


class OnBeat(unittest.TestCase):
    def test_a_step_waits_for_the_beat_of_a_bench_deck(self):
        import time
        world = World()
        deck = world.decks[1] = Deck(world, 1, 240.0, "deck 1")       # a beat each 0.25 s
        deck.enabled = deck.playing = True
        deck.anchor_t, deck.anchor_pos = time.time(), 0.3
        for beat in (1, 3, None):
            with self.subTest(beat=beat):
                target = {"deck": 1} if beat is None else {"deck": 1, "beat": beat}
                (step, ok, message), = Scenario({"steps": [{"at": 0, "do": "log", "text": "x", "on_beat": target}]}).run(world)
                pos = deck.position(time.time())
                self.assertLess(pos - int(pos), 0.2, message)            # just after a beat
                if beat:
                    self.assertEqual(deck.bar_beat(pos), beat, message)
                self.assertIn("on ", message)

    def test_a_deck_that_does_not_play_is_not_waited_for(self):
        world = World()
        world.decks[1] = Deck(world, 1, 120.0, "deck 1")
        (step, ok, message), = Scenario({"steps": [{"at": 0, "do": "log", "text": "x", "on_beat": {"deck": 1}}]}).run(world)
        self.assertIn("no beat from deck 1: done at once", message)

    def test_a_real_players_next_beat_comes_from_its_last_beat_packet(self):
        import time
        net = Prolink(World())
        device = net.monitor.device("127.0.0.30", time.time(), False, "CDJ-2000NXS2", 3)
        device["kind"], device["number"] = "player", 3
        device["status"] = {"master": True, "seen": time.time()}
        now = time.time()
        device["bar_phase"] = [now - 0.1, 2.0, 120.0]                 # beat 3 of its bar 0.1 s ago, a beat each 0.5 s
        when = net.next_beat({"player": 3}, 1)
        self.assertAlmostEqual(when, now - 0.1 + 1.0, places=3)       # beat 4 at +0.5, beat 1 at +1.0
        self.assertAlmostEqual(net.next_beat({"master": True}), now + 0.4, places=3)
        device["bar_phase"] = [now - 5, 2.0, 120.0]                   # its beats stopped
        self.assertIsNone(net.next_beat({"player": 3}))

    def test_a_bad_on_beat_is_refused_when_it_is_read(self):
        for target in ({}, {"deck": 1, "player": 2}, {"deck": 1, "beat": 5}, "master"):
            with self.subTest(target=target), self.assertRaises(Exception):
                Scenario({"steps": [{"at": 0, "do": "log", "text": "x", "on_beat": target}]})


class Replay(unittest.TestCase):
    def test_titles_and_the_on_air_changes_go_with_the_recording(self):
        s = Session()
        s.recorder.titles = lambda source, slot, rbid: {"title": "Night Drive", "artist": "Someone"} if rbid == 205 else None
        one = Player(2)
        one.track, one.state, one.beat = (2, 3, 205), "cued", 1
        s.hear(one)
        s.wait(1, one)
        one.track = (2, 3, 206)
        s.wait(1, one)
        one.on_air = True                                            # a mixer brings it in
        s.wait(1, one)
        scenario = s.recorder.stop()
        Scenario(scenario)
        loads = {x["load"]: x for x in scenario["steps"] if x.get("load")}
        self.assertEqual(loads[205]["title"], "Night Drive (Someone)")
        self.assertNotIn("title", loads[206])
        self.assertTrue(any("player 2 on air" in n for n in scenario["notes"]), scenario.get("notes"))

    def test_a_play_on_a_beat_is_then_measured_against_it(self):
        s = Session()
        one, two = Player(1), Player(2)
        one.track, one.state, one.beat, one.master = (1, 3, 7), "playing", 1, True
        two.track, two.state, two.beat = (2, 3, 8), "cued", 1
        s.hear(one, two)
        s.wait(2, one, two)
        two.state = "playing"
        s.wait(1, one, two)
        scenario = s.recorder.stop()
        Scenario(scenario)
        check = next(x for x in scenario["steps"] if x["do"] == "expect_player" and x.get("phase_to"))
        self.assertEqual((check["player"], check["phase_to"]), (2, {"player": 1}))

    def test_the_offset_between_two_players_beats(self):
        import time
        net = Prolink(World())
        now = time.time()
        for number, at in ((1, now - 0.5), (2, now - 0.5 + 0.03)):  # player 2's beats 30 ms after player 1's
            d = net.monitor.device("127.0.0.%d" % (40 + number), now, False, "CDJ-2000NXS2", number)
            d["kind"], d["number"], d["status"] = "player", number, {"master": number == 1, "seen": now}
            d["bar_phase"] = [at, 0.0, 120.0]
        self.assertAlmostEqual(net.beat_offset(2, {"player": 1}), 30.0, places=3)
        self.assertAlmostEqual(net.beat_offset(2, {"master": True}), 30.0, places=3)
        self.assertIsNone(net.beat_offset(2, {"player": 1}, since=now))  # none of its beats since then

    def test_the_check_before_a_replay_says_what_is_missing(self):
        net = Prolink(World())
        steps = [{"at": 0, "do": "expect_player", "player": 3, "match": {"online": True, "model": "CDJ-3000"}},
                 {"at": 1, "do": "player", "player": 3, "press": "play-pause"}]
        self.assertEqual(net.check_steps(steps), [(False, "player 3 is not on the link")])
        self.assertEqual(net.check_steps([{"at": 0, "do": "log", "text": "x"}]), [])


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
