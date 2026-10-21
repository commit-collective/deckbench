# SPDX-License-Identifier: MIT OR Apache-2.0
"""The log of the link's packets, and the devices on it."""
import json
import socket
import struct
import time
import unittest
import urllib.request

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.net import share
from deckbench.protocols import mixer as mixer_module
from deckbench.protocols import startup
from deckbench.protocols.monitor import Monitor, classify
from deckbench.protocols.prolink import Prolink
from deckbench.testing import FakeUnit
from deckbench.web import serve


def world_of(*numbers):
    world = World()
    for n in numbers:
        world.decks[n] = Deck(world, n, 128.0, "deck %d" % n)
    return world


class Sender:
    """Another device on the link: its packets come from an address of its own, to the broadcast address."""

    def __init__(self, ports, address):
        self.ports, self.address = ports, address
        self.sock = share(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind((address, 0))

    def send(self, packet, port):
        self.sock.sendto(packet, ("127.255.255.255", port))

    def close(self):
        self.sock.close()


def wait(check, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(0.03)
    return check()


class Classify(unittest.TestCase):
    def test_a_packet_is_named_by_its_port_and_type(self):
        def packet(t):
            p = bytearray(0x30)
            p[:10], p[0x0A] = startup.MAGIC, t
            return bytes(p)
        for port, t, name in ((50000, 0x06, "keep-alive"), (50000, 0x0A, "hello"), (50000, 0x00, "claim 1"), (50000, 0x02, "claim 2"),
                              (50000, 0x04, "claim 3"), (50000, 0x08, "number in use"), (50001, 0x28, "beat"), (50001, 0x03, "on air"),
                              (50001, 0x02, "fader start"), (50001, 0x26, "takeover request"), (50001, 0x2A, "sync command"),
                              (50002, 0x0A, "status"), (50002, 0x27, "takeover reply"), (50002, 0x10, "other"), (50009, 0x06, "other")):
            self.assertEqual(classify(port, packet(t)), name, (port, t))
        self.assertEqual(classify(50000, b"junk"), "other")
        self.assertEqual(classify(50000, b""), "other")


class Heard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = world_of(2, 3)
        cls.ports = fresh()
        cls.net = Prolink(cls.world, ports=cls.ports)
        cls.net.start()
        cls.monitor = cls.net.monitor
        # a CDJ of its own: its packets are built by a bench that is not started, sent from another address
        cls.other_world = world_of(5)
        cls.other = Prolink(cls.other_world, ports=cls.ports, profile="cdj-2000nxs2")
        cls.player = Sender(cls.ports, "127.0.0.5")

    @classmethod
    def tearDownClass(cls):
        cls.player.close()
        for deck in cls.world.decks.values():
            cls.world.set_enabled(deck, False)

    def device(self, ip="127.0.0.5"):
        return next((d for d in self.monitor.snapshot() if d["ip"] == ip), None)

    def test_01_a_player_that_is_heard_is_a_device(self):
        deck = self.other_world.decks[5]
        deck.enabled = True
        link = self.other.decks[5]

        def heard():                                             # the listener may not be bound yet: say it again until it hears
            self.player.send(link.keepalive(), self.ports.announce)
            self.player.send(link.status(), self.ports.update)
            time.sleep(0.1)
            return (self.device() or {}).get("status") and self.device()
        found = wait(heard, 8.0)
        self.assertTrue(found, "the device was not found")
        self.assertEqual((found["number"], found["model"], found["name"], found["kind"], found["online"]),
                         (5, "CDJ-2000NXS2", "CDJ-2000NXS2", "player", True))
        self.assertEqual((found["mac"], found["peers"]), ("02:fa:4e:de:c0:05", 1))
        self.assertFalse(found["unit"])
        self.assertFalse(found["status"]["play"])
        self.assertEqual(found["status"]["state"], "paused")

    def test_02_what_it_says_of_itself(self):
        deck = self.other_world.decks[5]
        deck.playing, deck.master, deck.sync, deck.base_bpm, deck.anchor_pos, deck.anchor_t = True, True, True, 124.0, 6.0, time.time()
        link = self.other.decks[5]
        self.player.send(link.status(), self.ports.update)
        found = wait(lambda: (self.device() or {}).get("status", {}) and self.device()["status"]["play"] and self.device())
        st = found["status"]
        self.assertEqual((st["play"], st["master"], st["sync"], st["on_air"], st["state"]), (True, True, True, True, "playing"))
        self.assertEqual((st["bpm"], st["pitch"]), (124.0, 0.0))
        self.assertEqual((st["source"], st["slot"], st["rbid"]), (5, 3, 105))
        self.assertEqual(st["track_beat"], 7)                    # the beat of the track: the deck's place is 6.x
        self.assertIsNone(found["at"])                           # playing: no stopped place

    def test_03_its_beats_give_its_place(self):
        link = self.other.decks[5]
        deck = self.other_world.decks[5]
        deck.anchor_pos, deck.anchor_t = 6.0, time.time()
        self.player.send(link.status(), self.ports.update)
        wait(lambda: (self.device() or {}).get("status") and self.device()["status"]["track_beat"] == 7)
        self.player.send(link.beat(6.0), self.ports.beat)        # beat 3 of its bar, the 7th of its track
        found = wait(lambda: (self.device() or {}).get("phase") and self.device())
        t, pos, bpm = found["phase"]
        self.assertEqual((pos, bpm), (6.0, 124.0))
        self.assertLess(abs(t - time.time()), 2.0)
        # a loop sends the track's count back, and the place with it
        deck.anchor_pos, deck.anchor_t = 4.0, time.time()
        self.player.send(link.status(), self.ports.update)
        wait(lambda: (self.device() or {}).get("status") and self.device()["status"]["track_beat"] == 5)
        self.player.send(link.beat(4.0), self.ports.beat)
        found = wait(lambda: self.device()["phase"] and self.device()["phase"][1] == 4.0 and self.device())
        self.assertTrue(found, "the phase did not follow the track beat")

    def test_04_a_player_that_stops_has_a_place_and_no_phase(self):
        deck = self.other_world.decks[5]
        deck.playing, deck.master = False, False
        deck.anchor_pos = 9.0
        self.player.send(self.other.decks[5].status(), self.ports.update)
        found = wait(lambda: (self.device() or {}).get("at") is not None and self.device())
        self.assertEqual(found["at"], 9.0)
        self.assertIsNone(found["phase"])
        self.assertEqual(found["status"]["state"], "paused")

    def test_05_the_benchs_own_are_not_devices(self):
        for deck in self.world.decks.values():
            self.world.set_enabled(deck, True)
        wait(lambda: any(p["ours"] and p["kind"] == "keep-alive" for p in self.monitor.since(0)["packets"]))
        self.assertTrue(any(p["ours"] and p["kind"] == "status" for p in self.monitor.since(0)["packets"]) or
                        wait(lambda: any(p["ours"] and p["kind"] == "status" for p in self.monitor.since(0)["packets"])))
        self.assertEqual([d["ip"] for d in self.monitor.snapshot() if d["ip"] in ("127.0.0.2", "127.0.0.3", "127.0.0.33")], [])

    def test_06_a_mixer_and_what_it_says(self):
        mixer = Sender(self.ports, "127.0.0.8")
        try:
            mixer.send(startup.keepalive(b"DJM-900NXS2", 33, "127.0.0.8", bytes(6), 4, False, kind=startup.MIXER), self.ports.announce)
            mixer.send(mixer_module.on_air_packet(b"DJM-900NXS2", 33, {1: True, 2: False, 3: True, 4: False}), self.ports.beat)
            mixer.send(mixer_module.fader_start_packet(b"DJM-900NXS2", 33, {2: "start", 3: "stop"}), self.ports.beat)
            found = wait(lambda: (self.device("127.0.0.8") or {}).get("air") and (self.device("127.0.0.8") or {}).get("fader") and self.device("127.0.0.8"))
            self.assertTrue(found)
            self.assertEqual((found["kind"], found["number"], found["name"], found["peers"]), ("mixer", 33, "DJM-900NXS2", 4))
            self.assertEqual(found["air"], {"1": True, "2": False, "3": True, "4": False} if False else {1: True, 2: False, 3: True, 4: False})
            self.assertEqual(found["fader"], {2: "start", 3: "stop"})
        finally:
            mixer.close()

    def test_07_the_unit_under_test_is_one_of_them(self):
        unit = FakeUnit(self.ports, address="127.0.0.1")
        try:
            unit.announce()
            unit.status(master=True, playing=True, bpm=120.0)
            found = wait(lambda: self.device("127.0.0.1") and self.device("127.0.0.1")["status"] and self.device("127.0.0.1"))
            self.assertTrue(found)
            self.assertTrue(found["unit"])
            self.assertEqual((found["name"], found["number"], found["status"]["master"]), ("DJS-1000", 1, True))
        finally:
            unit.close()

    def test_08_the_log_says_what_was_heard(self):
        packets = self.monitor.since(0)["packets"]
        by = {p["kind"]: p for p in packets if p["src"] == "127.0.0.5" or (p["src"] == "127.0.0.8" and p["kind"] in ("on air", "fader start"))}
        self.assertIn("CDJ-2000NXS2 #5 at 127.0.0.5, player, knows 1 device", by["keep-alive"]["text"])
        self.assertTrue(by["status"]["text"].startswith("CDJ-2000NXS2 #5: "))
        self.assertIn("beat", by["beat"]["text"])
        self.assertIn("fader start by DJM-900NXS2: 2 start, 3 stop", by["fader start"]["text"])
        self.assertIn("on air 1 3", by["on air"]["text"])
        self.assertEqual((by["keep-alive"]["port"], by["keep-alive"]["src"], by["keep-alive"]["ours"]), (self.ports.announce, "127.0.0.5", False))
        self.assertTrue(by["status"]["hex"].startswith("5173707431576d4a4f4c0a"))
        numbers = [p["n"] for p in packets]
        self.assertEqual(numbers, sorted(numbers))
        later = self.monitor.since(numbers[-1])
        self.assertTrue(all(p["n"] > numbers[-1] for p in later["packets"]))
        self.assertEqual(self.monitor.since(0, noisy=False)["packets"][0]["kind"] not in ("status", "beat"), True)
        self.assertNotIn("status", {p["kind"] for p in self.monitor.since(0, noisy=False)["packets"]})
        self.assertGreater(self.monitor.counts["status"], 0)

    def test_09_a_packet_that_cannot_be_read_does_not_stop_it(self):
        for kind_port, t, size in ((self.ports.update, 0x0A, 0x40), (self.ports.beat, 0x28, 0x30), (self.ports.announce, 0x06, 0x28), (self.ports.beat, 0x03, 0x2D),
                                   (self.ports.beat, 0x02, 0x24)):
            p = bytearray(size)
            p[:10], p[0x0A] = startup.MAGIC, t
            self.player.send(bytes(p), kind_port)
        self.player.send(b"not a packet at all", self.ports.update)
        self.player.send(b"", self.ports.beat)
        self.monitor.feed(b"\x51" * 5, "127.0.0.77", self.ports.update)        # and straight to it
        found = wait(lambda: any(p["src"] == "127.0.0.77" for p in self.monitor.since(0)["packets"]))
        self.assertTrue(found)
        self.assertTrue(any(p["text"].startswith("type 0x0a, 64 bytes") for p in self.monitor.since(0)["packets"]))
        self.assertTrue(self.device(), "the device was lost")


class Identity(unittest.TestCase):
    """A device is who it says it is, not the address it sends from."""

    def test_one_device_that_sends_from_two_addresses_is_one_device(self):
        net = Prolink(world_of(2), ports=fresh())
        monitor = net.monitor
        unit = FakeUnit(net.ports, number=1, address="172.21.0.9")
        monitor.feed(startup.keepalive(b"DJS-1000", 1, "172.21.0.9", bytes(6), 1), "172.21.0.9", net.ports.announce)   # its keep-alive: from its address
        status = bytearray(net.decks[2].status().replace(b"CDJ-FAKE2", b"DJS-1000\x00"))
        status[0x21] = status[0x24] = 1                                                                                  # it is player 1
        monitor.feed(bytes(status), "127.0.0.1", net.ports.update)                                                       # a status of it: from the loopback
        found = [d for d in monitor.snapshot() if d["name"] == "DJS-1000"]
        self.assertEqual(len(found), 1, [(d["ip"], d["number"]) for d in monitor.snapshot()])
        self.assertEqual(found[0]["ip"], "172.21.0.9")
        self.assertIsNotNone(found[0]["status"])
        self.assertTrue(found[0]["unit"])
        unit.close()

    def test_a_unit_on_the_address_of_deck_1_is_not_the_deck(self):
        net = Prolink(world_of(1, 2), ports=fresh())              # deck 1 is at 127.0.0.1
        monitor = net.monitor
        monitor.feed(net.decks[1].keepalive(), "127.0.0.1", net.ports.announce)                       # the bench's own deck 1
        monitor.feed(startup.keepalive(b"DJS-1000", 1, "172.21.0.9", bytes(6), 1), "127.0.0.1", net.ports.announce)   # a unit, also from 127.0.0.1
        names = [d["name"] for d in monitor.snapshot()]
        self.assertEqual(names, ["DJS-1000"])
        ours = [p for p in monitor.since(0)["packets"] if p["ours"]]
        self.assertEqual([p["name"] for p in ours], ["CDJ-FAKE1"])

    def test_a_device_heard_before_it_said_who_it_was(self):
        net = Prolink(world_of(2), ports=fresh())
        monitor = net.monitor
        short = bytearray(0x24)
        short[:10], short[0x0A] = startup.MAGIC, 0x04                                   # a claim of an unknown number: names a device
        monitor.feed(bytes(short), "10.9.9.9", net.ports.announce)
        monitor.feed(startup.keepalive(b"CDJ-3000", 6, "10.9.9.9", bytes(6), 2), "10.9.9.9", net.ports.announce)
        self.assertEqual([(d["name"], d["number"], d["ip"]) for d in monitor.snapshot() if d["name"] == "CDJ-3000"], [("CDJ-3000", 6, "10.9.9.9")])


class Aligned(unittest.TestCase):
    """A synced deck of the bench goes to the grid of a master that is not on the bench, by the beats it tells of."""

    @classmethod
    def setUpClass(cls):
        cls.world = world_of(2, 3)
        cls.ports = fresh()
        cls.net = Prolink(cls.world, ports=cls.ports)
        cls.net.start()
        cls.other_world = world_of(5)
        cls.other = Prolink(cls.other_world, ports=cls.ports, profile="cdj-2000nxs2")
        cls.player = Sender(cls.ports, "127.0.0.5")

    @classmethod
    def tearDownClass(cls):
        cls.player.close()
        for deck in cls.world.decks.values():
            cls.world.set_enabled(deck, False)

    def tell(self, position):
        """The master says it is at `position` beats (a whole one: it tells at each beat)."""
        master = self.other_world.decks[5]
        master.anchor_pos, master.anchor_t = float(position), time.time()
        link = self.other.decks[5]
        self.player.send(link.status(), self.ports.update)
        time.sleep(0.1)
        self.player.send(link.beat(float(position)), self.ports.beat)

    def off_by(self, deck, master_position, at):
        """How far the deck is from the master's bar, in beats, whichever bar: -2 to 2."""
        d = deck.position(at) - (master_position + (time.time() - at) * 0)
        return (d + 2) % 4 - 2

    def test_a_synced_deck_goes_to_the_masters_beat(self):
        master = self.other_world.decks[5]
        master.enabled, master.playing, master.master, master.sync, master.base_bpm = True, True, True, False, 120.0
        deck = self.world.decks[2]
        self.world.set_enabled(deck, True)
        self.world.set_play(deck, True)
        self.world.set_sync(deck, True)
        deck.base_bpm = 120.0
        deck.anchor_pos, deck.anchor_t = 0.4, time.time()                  # 0.4 beats into its bar, the master on a beat
        self.tell(2)
        t = time.time()
        found = wait(lambda: abs(((deck.position(time.time()) - 2.0 - (time.time() - t) * 2.0) + 2) % 4 - 2) < 0.15)
        self.assertTrue(found, "the deck did not go to the master's beat: %.3f" % deck.position(time.time()))
        # and goes on being there, a beat at a time (the master at 120 BPM: 0.5 s a beat)
        self.tell(3)
        t = time.time()
        found = wait(lambda: abs(((deck.position(time.time()) - 3.0 - (time.time() - t) * 2.0) + 2) % 4 - 2) < 0.15)
        self.assertTrue(found)

    def test_not_a_deck_that_loops_nor_one_that_is_not_synced(self):
        deck3 = self.world.decks[3]
        self.world.set_enabled(deck3, True)
        self.world.set_play(deck3, True)                                   # playing, not synced
        deck3.anchor_pos, deck3.anchor_t, deck3.base_bpm = 1.3, time.time(), 120.0
        deck2 = self.world.decks[2]
        self.world.set_loop(deck2, 4)
        place = deck2.position(time.time())
        self.tell(0)
        time.sleep(0.4)
        self.assertLess(abs(deck3.position(time.time()) - (1.3 + (time.time() - deck3.anchor_t) * 2.0)), 0.01, "a deck that is not synced was moved")
        self.assertLess(abs(deck2.position(time.time()) - place - (time.time() - deck2.anchor_t) * 2.0 + (deck2.anchor_pos - place)), 1.0)
        self.assertEqual(deck2.loop[1], 4)
        self.world.set_loop(deck2, 0)

    def test_not_while_a_deck_of_the_bench_is_the_master(self):
        deck2, deck3 = self.world.decks[2], self.world.decks[3]
        deck3.base_bpm = 120.0
        self.world.set_play(deck3, True)
        self.world.set_master(deck3, True)
        self.world.set_play(deck2, True)
        self.world.set_sync(deck2, True)
        t0 = time.time()
        deck2.anchor_pos, deck2.anchor_t = 0.4, t0                       # put out of step by hand, after it synced
        self.tell(2)                                                      # the other device is on a beat and is not the master here
        time.sleep(0.4)
        expected = 0.4 + (time.time() - t0) * 2.0                         # the tempo of the bench's master, 2 beats a second
        self.assertLess(abs(deck2.position(time.time()) - expected), 0.05, "a device that is not the master moved a deck")
        self.world.set_master(deck3, False)


class Rings(unittest.TestCase):
    def test_the_many_statuses_do_not_push_out_the_rare_packets(self):
        net = Prolink(world_of(2), ports=fresh())
        monitor = net.monitor
        monitor.feed(startup.hello(b"CDJ-3000", 1), "10.0.0.9", net.ports.announce)
        deck = net.decks[2]
        for _ in range(3000):
            monitor.feed(deck.status(), "10.0.0.7", net.ports.update)
        everything = monitor.since(0, limit=5000)
        kinds = [p["kind"] for p in everything["packets"]]
        self.assertEqual(kinds.count("hello"), 1)
        self.assertEqual(kinds.count("status"), 1500)                       # the ring's length
        self.assertEqual(everything["counts"]["status"], 3000)               # and the count is of all
        self.assertEqual(monitor.since(0, noisy=False)["packets"][0]["kind"], "hello")
        self.assertEqual(len(monitor.since(0, limit=50)["packets"]), 50)
        monitor.clear()
        self.assertEqual(monitor.since(0)["packets"], [])


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = world_of(2)
        cls.ports = fresh()
        cls.net = Prolink(cls.world, ports=cls.ports)
        cls.net.start()
        cls.server = serve(cls.world, "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, method="GET"):
        with urllib.request.urlopen(urllib.request.Request(self.url + path, method=method), timeout=5) as r:
            return json.loads(r.read())

    def test_the_log_and_the_devices_through_the_api(self):
        self.world.set_enabled(self.world.decks[2], True)
        sender = Sender(self.ports, "127.0.0.6")
        try:
            sender.send(startup.hello(b"XDJ-1000MK2", 1), self.ports.announce)
            wait(lambda: any(p["kind"] == "hello" and p["src"] == "127.0.0.6" for p in self.call("api/packets")["packets"]))
            data = self.call("api/packets?since=0&noisy=0&limit=50")
            self.assertTrue(any(p["kind"] == "hello" and p["text"] == "XDJ-1000MK2 says hello (a player)" for p in data["packets"]))
            self.assertNotIn("status", {p["kind"] for p in data["packets"]})
            self.assertGreaterEqual(data["next"], 1)
            self.assertEqual(self.call("api/packets?since=%d" % data["next"] + "&limit=abc")["packets"] is not None, True)
            self.assertIn("devices", self.call("api/state")["protocols"]["prolink"])
            self.call("api/packets/clear", "POST")
            self.assertEqual(self.call("api/packets?noisy=0")["packets"], [])
        finally:
            sender.close()
            self.world.set_enabled(self.world.decks[2], False)


if __name__ == "__main__":
    unittest.main()
