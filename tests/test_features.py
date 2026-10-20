# SPDX-License-Identifier: MIT OR Apache-2.0
"""Events, scenarios, the pitch fader and track changes, faults, the strict decks and the decks' sound.

    python -m unittest discover -s tests

The first classes need no network. `Faults` and `Strict` start decks of their own (1 and 4, and 6) beside those of
test_prolink.py, which uses 2 and 3.
"""
import json
import socket
import struct
import threading
import time
import unittest
import urllib.request

from deckbench import audio
from deckbench.core import Deck, World
from deckbench.events import Events
from deckbench.protocols import prolink
from _ports import fresh
from deckbench.protocols.prolink import (MAGIC, Prolink, message, num,
                                         read_exact, read_message)
from deckbench.scenario import Scenario, ScenarioError
from deckbench.web import serve
from test_prolink import collect, listen


def world_of(*numbers):
    world = World()
    for i, n in enumerate(numbers):
        world.decks[n] = Deck(world, n, 128.0 - 2 * i, "deck %d" % n)
    return world


class EventsTests(unittest.TestCase):
    def test_add_find_and_since(self):
        events = Events()
        events.add("fader_start", deck=2, action="stop")
        events.add("sync_command", deck=3, command=0x10)
        self.assertEqual([e["n"] for e in events.since()], [0, 1])
        self.assertEqual(events.find("sync_command", deck=3)["command"], 0x10)
        self.assertIsNone(events.find("sync_command", deck=2))
        self.assertEqual([e["kind"] for e in events.since(1)], ["sync_command"])

    def test_wait_gives_a_later_event_and_none_on_time_out(self):
        events = Events()
        threading.Timer(0.2, events.add, args=("unit_seen",), kwargs={"number": 3}).start()
        found = events.wait("unit_seen", timeout=3, number=3)
        self.assertEqual(found["number"], 3)
        started = time.time()
        self.assertIsNone(events.wait("never", timeout=0.3))
        self.assertGreaterEqual(time.time() - started, 0.25)

    def test_the_start_argument_leaves_out_what_came_before(self):
        events = Events()
        events.add("x", n_of_it=1)
        self.assertIsNone(events.find("x", start=1))
        self.assertIsNotNone(events.find("x", start=0))


class Clock:
    """A clock that only moves when it is slept on."""
    def __init__(self):
        self.t = 100.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class ScenarioTests(unittest.TestCase):
    def test_steps_run_in_order_at_their_times(self):
        world = world_of(2, 3)
        clock = Clock()
        scenario = Scenario({"steps": [
            {"at": 2, "deck": 2, "do": "play"},
            {"at": 0, "deck": 2, "do": "on"},
            {"at": 1, "deck": 2, "do": "tempo", "bpm": 126},
            {"at": 3, "deck": 2, "do": "load", "id": 205, "title": "Another", "bpm": 124},
        ]})
        times = []
        results = scenario.run(world, clock.now, clock.sleep, log=lambda line: times.append(line))
        self.assertTrue(all(ok for _, ok, _ in results))
        self.assertEqual([s["do"] for s, _, _ in results], ["on", "tempo", "play", "load"])
        deck = world.decks[2]
        self.assertTrue(deck.enabled and deck.playing)
        self.assertEqual(deck.track, (205, "Another"))
        self.assertEqual(deck.base_bpm, 124.0)
        self.assertAlmostEqual(clock.t, 103.0, places=3)

    def test_a_bad_step_is_refused_when_it_is_read(self):
        with self.assertRaises(ScenarioError):
            Scenario({"steps": [{"at": 0, "do": "dance"}]})
        with self.assertRaises(ScenarioError):
            Scenario({"steps": [{"at": 0, "do": "play"}]})            # no deck
        with self.assertRaises(ScenarioError):
            Scenario({"steps": [{"at": 0, "deck": 2, "do": "loop"}]})  # no beats

    def test_expect_passes_on_an_event_and_fails_without_one(self):
        world = world_of(2)
        threading.Timer(0.05, world.events.add, args=("fader_start",), kwargs={"deck": 2, "action": "stop"}).start()
        scenario = Scenario({"steps": [
            {"at": 0, "do": "expect", "event": "fader_start", "within": 1.0, "match": {"deck": 2, "action": "stop"}},
            {"at": 0, "do": "expect", "event": "fader_start", "within": 0.2, "match": {"deck": 2, "action": "start"}},
        ]})
        results = scenario.run(world)
        self.assertEqual([ok for _, ok, _ in results], [True, False])

    def test_an_event_from_before_the_scenario_does_not_count(self):
        world = world_of(2)
        scenario = Scenario({"steps": [{"at": 0, "do": "expect", "event": "late", "within": 0.1}]})
        # only events added after run() begins count: this one was there before
        world.events.add("late")
        self.assertFalse(scenario.run(world)[0][1])


class CoreTests(unittest.TestCase):
    def test_pitch_load_and_loss(self):
        world = world_of(2)
        deck = world.decks[2]
        world.set_enabled(deck, True)
        world.set_play(deck, True)
        world.set_tempo(deck, 111)
        self.assertAlmostEqual(deck.tempo(), 111.0)
        time.sleep(0.2)
        self.assertGreater(deck.position(time.time()), 0.2)
        world.load_track(deck, 777, "Seven", 100)
        self.assertEqual(deck.track, (777, "Seven"))
        self.assertLess(deck.position(time.time()), 0.2)             # from its first beat again
        world.set_loss(30)
        self.assertEqual(world.snapshot()["loss"], 30.0)

    def test_silence_unplugs_for_a_while(self):
        world = world_of(2)
        deck = world.decks[2]
        world.silence(deck, 0.3)
        self.assertTrue(deck.unplugged)
        time.sleep(0.6)
        self.assertFalse(deck.unplugged)


def peaks(samples, floor):
    """How many times the loudness rises above `floor` from below, in the mono samples (the kicks of a loop)."""
    count, above = 0, False
    window = 441
    for i in range(0, len(samples) - window, window // 2):
        level = max(abs(x) for x in samples[i:i + window])
        if level > floor and not above:
            count += 1
        above = level > floor
    return count


class AudioTests(unittest.TestCase):
    def test_a_loop_has_a_kick_on_each_beat_and_follows_the_tempo(self):
        seconds = 4.0
        frames = int(seconds * audio.RATE)
        at120 = audio.voice(2, 0.0, 120.0, frames)
        at60 = audio.voice(2, 0.0, 60.0, frames)
        kicks120, kicks60 = peaks(at120, 0.5), peaks(at60, 0.5)
        self.assertAlmostEqual(kicks120, 8, delta=1)                 # 2 beats a second
        self.assertAlmostEqual(kicks60, 4, delta=1)
        self.assertGreater(max(abs(x) for x in at120[:2000]), 0.5)  # a kick at the very beginning

    def test_each_deck_has_a_pitch_of_its_own(self):
        a, b = audio.voice(1, 0.0, 120.0, 4000), audio.voice(4, 0.0, 120.0, 4000)
        self.assertNotEqual(a[:2000], b[:2000])

    def test_a_deck_that_does_not_play_is_silent(self):
        world = world_of(2, 3)
        mixer = audio.Mixer(world)
        self.assertEqual(set(mixer.block(4410)), {0})
        world.set_enabled(world.decks[2], True)
        self.assertEqual(set(mixer.block(4410)), {0})                # on, but not playing
        world.set_play(world.decks[2], True)
        self.assertNotEqual(set(mixer.block(4410, time.time() + 0.0)), {0})
        world.set_unplugged(world.decks[2], True)
        self.assertEqual(set(mixer.block(4410)), {0})                # the cable is pulled

    def test_the_server_streams_in_real_time(self):
        world = world_of(2)
        world.set_enabled(world.decks[2], True)
        world.set_play(world.decks[2], True)
        server = audio.AudioServer(world, "127.0.0.1", 0)
        try:
            with socket.create_connection(("127.0.0.1", server.port), timeout=3) as c:
                started = time.time()
                data = read_exact(c, int(0.5 * audio.RATE) * 4)       # half a second of stereo 16 bit
                took = time.time() - started
            self.assertGreater(took, 0.35)                           # paced, not as fast as it can go
            self.assertLess(took, 1.2)
            self.assertNotEqual(set(data), {0})
        finally:
            server.close()


class Faults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ports = fresh()
        cls.world = world_of(1, 4)
        cls.prolink = Prolink(cls.world, ports=cls.ports)
        cls.prolink.start()
        cls.server = serve(cls.world, "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]
        cls.statuses, cls.beats = listen(cls.ports.update), listen(cls.ports.beat)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for deck in cls.world.decks.values():
            cls.world.set_enabled(deck, False)
        cls.statuses.close()
        cls.beats.close()

    def api(self, path, post=True):
        request = urllib.request.Request(self.url + path, method="POST" if post else "GET")
        with urllib.request.urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def statuses_of(self, number, seconds=0.8):
        return collect(self.statuses, seconds, lambda d: d[0x0A] == 0x0A and d[0x21] == number)

    def setUp(self):
        self.api("api/loss/0")
        for n in (1, 4):
            self.api("api/deck/%d/plug" % n)
        self.api("api/deck/4/on/1")
        self.api("api/deck/4/play/0")
        time.sleep(0.3)

    def test_the_pitch_fader_and_a_loaded_track_show_in_the_status(self):
        self.api("api/deck/4/tempo/111")
        state = self.api("api/deck/4/load/777?title=Seven&bpm=110")
        self.assertEqual(state["decks"]["4"]["track"], "Seven")
        self.assertEqual(state["decks"]["4"]["bpm"], 110.0)
        packets = self.statuses_of(4)
        self.assertTrue(packets)
        self.assertEqual(struct.unpack(">I", packets[-1][0x2C:0x30])[0], 777)
        self.assertEqual(struct.unpack(">H", packets[-1][0x92:0x94])[0], 11000)

    def test_a_pulled_cable_stops_the_deck_saying_anything(self):
        self.assertTrue(self.statuses_of(4))
        self.api("api/deck/4/unplug")
        time.sleep(0.4)
        self.assertFalse(self.statuses_of(4, 0.8))
        self.api("api/deck/4/plug")
        self.assertTrue(self.statuses_of(4, 1.0))

    def test_silence_comes_back_by_itself(self):
        self.api("api/deck/4/silence/1.0")
        time.sleep(0.1)
        self.assertFalse(self.statuses_of(4, 0.4))                    # well inside the second of silence
        time.sleep(1.0)
        self.assertTrue(self.statuses_of(4, 0.8))

    def test_loss_drops_the_datagrams(self):
        self.api("api/loss/100")
        time.sleep(0.3)
        self.assertFalse(self.statuses_of(4, 0.8))
        self.api("api/loss/0")
        self.assertTrue(self.statuses_of(4, 0.8))

    def test_fader_start_packets_are_events(self):
        self.api("api/deck/1/on/1")
        self.api("api/deck/1/play/1")
        before = len(self.world.events.items)
        packet = bytearray(0x30)
        packet[0:10] = MAGIC
        packet[0x0A] = 0x02
        packet[0x0B:0x0B + 6] = b"DJM-X1"
        packet[0x21] = 33
        packet[0x24:0x28] = bytes([1, 2, 2, 2])                       # stop deck 1, leave the others
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(bytes(packet), ("127.255.255.255", self.ports.beat))
        s.close()
        event = self.world.events.wait("fader_start", timeout=3, start=before, deck=1, action="stop")
        self.assertIsNotNone(event)
        self.assertEqual(event["sender"], 33)
        self.assertFalse(self.world.decks[1].playing)
        listed = self.api("api/events?since=%d" % before, post=False)
        self.assertTrue(any(e["kind"] == "fader_start" for e in listed))
        self.api("api/events/clear")
        self.assertEqual(self.api("api/events", post=False), [])

    def test_the_state_says_how_the_bench_was_started(self):
        self.assertIn("bench", self.api("api/state", post=False))

    def post_json(self, path, body):
        request = urllib.request.Request(self.url + path, data=body.encode("utf-8"), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait_for_scenario(self, seconds=8.0):
        end = time.time() + seconds
        while time.time() < end:
            state = self.api("api/scenario", post=False)
            if not state["running"]:
                return state
            time.sleep(0.2)
        self.fail("the scenario is still playing")

    def test_a_scenario_is_played_from_the_page_and_reports(self):
        body = json.dumps({"name": "from the page", "steps": [
            {"at": 0, "deck": 4, "do": "tempo", "bpm": 120},
            {"at": 0.3, "deck": 4, "do": "load", "id": 55, "title": "Fifty-five"},
            {"at": 0.4, "do": "expect", "event": "never_happens", "within": 0.3},
        ]})
        code, state = self.post_json("api/scenario", body)
        self.assertEqual(code, 200)
        self.assertTrue(state["running"])
        code, again = self.post_json("api/scenario", body)
        self.assertEqual(code, 409)                                   # one plays at a time
        done = self.wait_for_scenario()
        self.assertEqual((done["name"], done["total"], done["failed"]), ("from the page", 3, 1))
        self.assertEqual([r["ok"] for r in done["results"]], [True, True, False])
        self.assertEqual(self.world.decks[4].track, (55, "Fifty-five"))

    def test_a_scenario_that_is_not_one_is_refused_and_one_can_be_stopped(self):
        self.assertEqual(self.post_json("api/scenario", "not json")[0], 400)
        code, error = self.post_json("api/scenario", json.dumps({"steps": [{"at": 0, "do": "dance"}]}))
        self.assertEqual(code, 400)
        self.assertIn("no such action", error["error"])
        self.post_json("api/scenario", json.dumps({"name": "long", "steps": [
            {"at": 0, "do": "log", "text": "begin"}, {"at": 30, "do": "log", "text": "end"}]}))
        time.sleep(0.4)
        self.api("api/scenario/stop")
        done = self.wait_for_scenario(3.0)
        self.assertTrue(done["stopped"])
        self.assertEqual(len(done["results"]), 1)

    def test_a_scenario_drives_the_bench_and_checks_an_event(self):
        scenario = Scenario({"steps": [
            {"at": 0, "deck": 4, "do": "play"},
            {"at": 0.3, "deck": 4, "do": "loop", "beats": 2},
            {"at": 0.4, "deck": 4, "do": "unplug"},
            {"at": 0.8, "deck": 4, "do": "plug"},
            {"at": 0.8, "do": "log", "text": "the scenario test"},
        ]})
        results = scenario.run(self.world)
        self.assertTrue(all(ok for _, ok, _ in results))
        self.assertTrue(self.world.decks[4].playing)
        self.assertEqual(self.world.decks[4].loop[1], 2.0)
        self.assertFalse(self.world.decks[4].unplugged)


class Strict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ports = fresh()
        cls.world = world_of(6)
        cls.prolink = Prolink(cls.world, strict=True, ports=cls.ports)
        cls.prolink.start()
        cls.world.set_enabled(cls.world.decks[6], True)
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.world.set_enabled(cls.world.decks[6], False)

    def connect(self, requester):
        c = socket.create_connection(("127.0.0.6", self.ports.db), timeout=3)
        c.sendall(num(1))
        read_exact(c, 5)
        c.sendall(message(0xFFFFFFFE, 0x0000, [("n", requester)]))
        return c

    def metadata(self, c, requester):
        dmst = requester << 24 | 1 << 16 | 3 << 8 | 1
        c.sendall(message(1, 0x2002, [("n", dmst), ("n", 106)]))
        return read_message(c)

    def test_a_fifth_device_gets_no_answer_at_all(self):
        c = self.connect(5)
        c.settimeout(2)
        try:
            self.assertEqual(c.recv(64), b"")                         # the deck closed the connection
        finally:
            c.close()
        self.assertIsNotNone(self.world.events.find("db_ignored", deck=6, requester=5))

    def test_the_announced_unit_is_answered(self):
        self.prolink.unit.update(number=3, ip="127.0.0.9")
        c = self.connect(3)
        try:
            _, mtype, _ = read_message(c)
            self.assertEqual(mtype, 0x4000)
            _, mtype, args = self.metadata(c, 3)
            self.assertEqual((mtype, args[1][1]), (0x4000, 11))
        finally:
            c.close()
            self.prolink.unit.update(number=0, ip=None)

    def test_a_unit_that_is_not_a_player_is_turned_down(self):
        self.prolink.unit.update(number=0, ip=None)                    # drum machine mode: no number on the link
        c = self.connect(3)
        try:
            read_message(c)
            _, mtype, _ = self.metadata(c, 3)
            self.assertEqual(mtype, 0x0100)
        finally:
            c.close()
        event = self.world.events.find("metadata_request", deck=6, requester=3, answered=False)
        self.assertIsNotNone(event)


if __name__ == "__main__":
    unittest.main()
