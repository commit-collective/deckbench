# SPDX-License-Identifier: MIT OR Apache-2.0
"""The things that make the bench look like a real network of players and a mixer: the mixer's on air and fader start,
a player coming online and defending its number."""
import json
import socket
import time
import unittest
import urllib.error
import urllib.request

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.net import share
from deckbench.protocols import mixer as mixer_module
from deckbench.protocols import startup
from deckbench.protocols.prolink import MAGIC, Prolink
from deckbench.scenario import Scenario
from deckbench.web import serve
from test_prolink import collect, listen


def world_of(*numbers):
    world = World()
    for n in numbers:
        world.decks[n] = Deck(world, n, 128.0, "deck %d" % n)
    return world


def types(packets):
    return [p[0x0A] for p in packets]


class Packets(unittest.TestCase):
    def test_the_startup_packets(self):
        mac = bytes([2, 0xFA, 0x4E, 0xDE, 0xC0, 3])
        name = b"CDJ-2000NXS2"
        for packet, kind, length in ((startup.hello(name), 0x0A, 0x25), (startup.stage1(name, mac, 2), 0x00, 0x2C),
                                     (startup.stage2(name, "10.0.0.3", mac, 3, 2), 0x02, 0x32),
                                     (startup.stage3(name, 3, 2), 0x04, 0x26), (startup.in_use(name, 3, "10.0.0.3"), 0x08, 0x29),
                                     (startup.keepalive(name, 3, "10.0.0.3", mac, 2, True), 0x06, 0x36)):
            self.assertEqual((len(packet), packet[0x0A], packet[:10]), (length, kind, MAGIC))
            self.assertEqual(int.from_bytes(packet[0x22:0x24], "big"), length)
            self.assertEqual(packet[0x0C:0x18], name)
        s2 = startup.stage2(name, "10.0.0.3", mac, 3, 2, auto=True)
        self.assertEqual((s2[0x24:0x28], s2[0x28:0x2E], s2[0x2E], s2[0x2F], s2[0x30], s2[0x31]),
                         (bytes([10, 0, 0, 3]), mac, 3, 2, 1, 1))
        ka = startup.keepalive(name, 3, "10.0.0.3", mac, peers=2, alone=True, kind=startup.MIXER)
        self.assertEqual((ka[0x24], ka[0x25], ka[0x2C:0x30], ka[0x30], ka[0x34]), (3, 2, bytes([10, 0, 0, 3]), 2, 2))
        self.assertEqual(startup.claimed_number(s2), 3)
        self.assertEqual(startup.claimed_number(startup.stage3(name, 4, 1)), 4)
        self.assertEqual(startup.claimed_number(startup.keepalive(name, 5, "10.0.0.5", mac)), 5)
        self.assertIsNone(startup.claimed_number(startup.hello(name)))
        self.assertIsNone(startup.claimed_number(b"junk"))

    def test_the_mixer_packets(self):
        name = b"DJM-900NXS2"
        air = mixer_module.on_air_packet(name, 33, {1: True, 2: False, 3: True, 4: False})
        self.assertEqual((len(air), air[0x0A], air[0x0B:0x16], air[0x1F], air[0x20], air[0x21], air[0x23]),
                         (0x2D, 0x03, name, 1, 0, 33, 9))
        self.assertEqual(air[0x24:0x28], bytes([1, 0, 1, 0]))
        self.assertEqual(mixer_module.parse_on_air(air), {1: True, 2: False, 3: True, 4: False})
        six = mixer_module.on_air_packet(b"DJM-V10", 33, {1: True, 5: True, 6: False}, six=True)
        self.assertEqual((len(six), six[0x20], six[0x23], six[0x24], six[0x2D], six[0x2E], six[0x30]), (0x35, 3, 0x11, 1, 1, 0, 0x30))
        self.assertEqual(mixer_module.parse_on_air(six), {1: True, 2: False, 3: False, 4: False, 5: True, 6: False})
        fader = mixer_module.fader_start_packet(name, 33, {2: "start", 3: "stop"})
        self.assertEqual((len(fader), fader[0x0A], fader[0x21], fader[0x23], fader[0x24:0x28]),
                         (0x28, 0x02, 33, 4, bytes([2, 0, 1, 2])))
        self.assertIsNone(mixer_module.parse_on_air(fader))
        self.assertIsNone(mixer_module.parse_on_air(b"short"))


class Mixer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = world_of(2, 3)
        cls.ports = fresh()
        cls.net = Prolink(cls.world, ports=cls.ports)
        cls.net.start()
        cls.mixer = cls.net.mixer
        cls.keepalives, cls.statuses, cls.beats = listen(cls.ports.announce), listen(cls.ports.update), listen(cls.ports.beat)
        for deck in cls.world.decks.values():
            cls.world.set_enabled(deck, True)
            cls.world.set_play(deck, True)

    @classmethod
    def tearDownClass(cls):
        cls.mixer.set_on(False)
        for deck in cls.world.decks.values():
            cls.world.set_enabled(deck, False)
        for s in (cls.keepalives, cls.statuses, cls.beats):
            s.close()

    def setUp(self):
        self.mixer.set_on(False)
        for n in self.mixer.channels:
            self.mixer.channels[n].update(fader=0, fader_start=False)
        self.mixer.set_master(True)

    def status_flags(self, number, seconds=0.8):
        packets = collect(self.statuses, seconds, lambda d: d[0x0A] == 0x0A and d[0x21] == number)
        self.assertTrue(packets, "no status from deck %d" % number)
        return packets[-1][0x89]

    def test_01_it_announces_itself_as_a_mixer(self):
        self.mixer.set_on(True)
        packets = collect(self.keepalives, 2.0, lambda d: d[0x0A] == 0x06 and d[0x24] == 33)
        self.assertTrue(packets, "no keep-alive from the mixer")
        p = packets[-1]
        self.assertEqual((p[0x0C:0x17], p[0x34], len(p)), (b"DJM-900NXS2", 2, 0x36))
        self.assertEqual(p[0x2C:0x30], bytes([127, 0, 0, 33]))
        self.assertGreaterEqual(p[0x30], 3)                     # itself and the two decks

    def test_02_it_tells_the_channels_that_are_on_the_air(self):
        self.mixer.set_on(True)
        self.mixer.set_fader(2, 80)
        packets = collect(self.beats, 1.0, lambda d: d[0x0A] == 0x03)
        self.assertTrue(packets, "no on-air packet")
        self.assertEqual(mixer_module.parse_on_air(packets[-1]), {1: False, 2: True, 3: False, 4: False})
        self.mixer.set_master(False)                            # the master level down: nothing is on the air
        packets = collect(self.beats, 1.0, lambda d: d[0x0A] == 0x03)
        self.assertEqual(mixer_module.parse_on_air(packets[-1]), {1: False, 2: False, 3: False, 4: False})

    def test_03_a_deck_is_on_air_when_the_mixer_says_so(self):
        self.assertTrue(self.status_flags(2) & 0x08)            # no mixer: on air while it plays
        self.mixer.set_on(True)                                 # all faders closed
        self.assertTrue(self.until(lambda: self.world.decks[2].on_air is False), "the deck was not told")
        self.assertFalse(self.status_flags(2) & 0x08, "told it is off the air, it still says on air")
        self.assertFalse(self.world.snapshot()["decks"]["2"]["on_air"])
        self.mixer.set_fader(2, 100)
        self.assertTrue(self.until(lambda: self.world.decks[2].on_air is True), "the deck was not told")
        self.assertTrue(self.status_flags(2) & 0x08)
        self.assertFalse(self.status_flags(3) & 0x08)
        self.assertTrue(self.world.events.find("on_air", deck=2, on=True, sender=33))
        self.mixer.set_on(False)                                # no mixer again: back to on air while it plays
        self.assertTrue(self.status_flags(3) & 0x08)

    def until(self, check, seconds=3.0):
        """True once check() is, within `seconds`: a packet takes a moment to reach a deck."""
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return True
            time.sleep(0.02)
        return check()

    def test_04_fader_start(self):
        deck = self.world.decks[2]
        self.mixer.set_on(True)
        self.mixer.set_fader_start(2, True)
        self.world.set_play(deck, False)
        # opened: deck 2 is told to start. Each step waits for its own packet before the next, since they take their time
        before = len(self.world.events.items)
        self.mixer.set_fader(2, 50)
        self.assertTrue(self.world.events.wait("fader_start", 3.0, before, deck=2, action="start", sender=33), "deck 2 was not told to start")
        self.assertTrue(self.until(lambda: deck.playing))
        # closed: told to stop
        before = len(self.world.events.items)
        self.mixer.set_fader(2, 0)
        self.assertTrue(self.world.events.wait("fader_start", 3.0, before, deck=2, action="stop", sender=33), "deck 2 was not told to stop")
        self.assertTrue(self.until(lambda: not deck.playing))
        self.world.set_play(deck, True)
        # with fader start off for the channel, the fader moves nothing
        self.mixer.set_fader_start(2, False)
        count = len(self.world.events.items)
        self.mixer.set_fader(2, 90)
        self.mixer.set_fader(2, 0)
        time.sleep(0.6)
        self.assertEqual([e for e in self.world.events.since(count) if e["kind"] == "fader_start"], [])
        self.assertTrue(deck.playing)

    def test_05_a_command_by_hand(self):
        self.assertFalse(self.mixer.send_fader_start({3: "stop"}))      # off: nothing is sent
        self.mixer.set_on(True)
        before = len(self.world.events.items)
        self.assertTrue(self.mixer.send_fader_start({3: "stop"}))
        self.assertTrue(self.world.events.wait("fader_start", 2.0, before, deck=3, action="stop"))
        self.world.set_play(self.world.decks[3], True)

    def test_06_what_another_mixer_says_counts_too(self):
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sender.sendto(mixer_module.on_air_packet(b"DJM-A9", 33, {2: False, 3: True}), ("127.255.255.255", self.ports.beat))
        sender.close()
        end = time.time() + 2
        while time.time() < end and self.world.decks[2].on_air is not False:
            time.sleep(0.05)
        self.assertEqual((self.world.decks[2].on_air, self.world.decks[3].on_air), (False, True))
        self.net.mixer_gone()
        self.assertEqual((self.world.decks[2].on_air, self.world.decks[3].on_air), (None, None))

    def test_07_scenario_steps(self):
        world = self.world
        self.assertEqual(Scenario.do(world, {"do": "mixer", "on": True}), (True, ""))
        self.assertEqual(Scenario.do(world, {"do": "mixer", "channel": 2, "fader": 70, "fader_start": True}), (True, ""))
        self.assertEqual(self.mixer.channels[2], {"fader": 70, "fader_start": True})
        self.assertEqual(Scenario.do(world, {"do": "mixer", "master": False}), (True, ""))
        self.assertFalse(self.mixer.on_air(2))
        self.assertEqual(Scenario.do(world, {"do": "mixer", "channel": 3, "command": "stop"}), (True, ""))
        for bad in ({"channel": 9, "fader": 1}, {"channel": 2, "command": "jump"}, {"channel": 2, "fader": "up"}):
            self.assertFalse(Scenario.do(world, dict(bad, do="mixer"))[0], bad)
        self.world.set_play(self.world.decks[3], True)
        self.assertFalse(Scenario.do(World(), {"do": "mixer", "on": True})[0])      # no protocol: nothing does it


class Online(unittest.TestCase):
    """A player coming online, and what it says on 50000."""

    def test_a_deck_claims_its_number_first_when_asked(self):
        world, ports = world_of(2), fresh()
        net = Prolink(world, ports=ports, claim=True)
        net.start()
        sock = listen(ports.announce)
        try:
            world.set_enabled(world.decks[2], True)
            seen = collect(sock, 6.0, lambda d: d[0x0A] in (0x0A, 0x00, 0x02, 0x04, 0x06) and (d[0x0A] != 0x06 or d[0x24] == 2))
            kinds = types(seen)
            self.assertEqual(kinds[:12], [0x0A] * 3 + [0x00] * 3 + [0x02] * 3 + [0x04] * 3)
            self.assertEqual(kinds[12], 0x06)
            self.assertEqual([p[0x24] for p in seen[3:6]], [1, 2, 3])                 # the packet counter of stage 1
            self.assertEqual({p[0x2E] for p in seen[6:9]}, {2})                        # the number claimed
            self.assertEqual({p[0x31] for p in seen[6:9]}, {2})                        # a specific number, not auto-assign
        finally:
            sock.close()
            world.set_enabled(world.decks[2], False)

    def test_a_deck_is_there_at_once_by_default(self):
        world, ports = world_of(2), fresh()
        net = Prolink(world, ports=ports)
        net.start()
        sock = listen(ports.announce)
        try:
            world.set_enabled(world.decks[2], True)
            seen = collect(sock, 1.0, lambda d: d[0x24] == 2 or d[0x0A] != 0x06)
            self.assertEqual(types(seen)[:1], [0x06])
            self.assertNotIn(0x0A, types(seen))
        finally:
            sock.close()
            world.set_enabled(world.decks[2], False)

    def test_the_keepalive_counts_the_peers(self):
        world, ports = world_of(2, 3), fresh()
        net = Prolink(world, ports=ports)
        net.start()
        sock = listen(ports.announce)
        try:
            world.set_enabled(world.decks[2], True)
            first = [p for p in collect(sock, 2.5, lambda d: d[0x0A] == 0x06 and d[0x24] == 2)][-1]
            self.assertEqual((first[0x30], first[0x25]), (1, 2))                       # alone, and it was the first there
            world.set_enabled(world.decks[3], True)
            both = collect(sock, 2.5, lambda d: d[0x0A] == 0x06)
            by = {p[0x24]: p for p in both}
            self.assertEqual((by[2][0x30], by[3][0x30]), (2, 2))
            self.assertEqual((by[2][0x25], by[3][0x25]), (2, 1))                       # latched: 3 found 2 there, 2 did not
        finally:
            sock.close()
            for deck in world.decks.values():
                world.set_enabled(deck, False)

    def test_a_deck_defends_its_number(self):
        world, ports = world_of(2, 3), fresh()
        net = Prolink(world, ports=ports)
        net.start()
        world.set_enabled(world.decks[2], True)
        claimer = share(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))   # a device at 127.0.0.9 claims number 2
        claimer.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        claimer.bind(("127.0.0.9", ports.announce))
        claimer.settimeout(0.3)
        mac = bytes(6)
        try:
            claimer.sendto(startup.stage2(b"NEWCOMER", "127.0.0.9", mac, 2, 1), ("127.255.255.255", ports.announce))
            told = collect(claimer, 2.0, lambda d: d[0x0A] == 0x08, fresh=False)
            self.assertTrue(told, "the deck did not say that its number is in use")
            self.assertEqual((told[0][0x24], told[0][0x25:0x29]), (2, bytes([127, 0, 0, 2])))
            self.assertTrue(world.events.find("number_defended", deck=2, claimer="127.0.0.9"))
            # a number nobody on the bench uses, and a deck that is off, are not defended
            claimer.sendto(startup.stage2(b"NEWCOMER", "127.0.0.9", mac, 3, 1), ("127.255.255.255", ports.announce))
            claimer.sendto(startup.stage3(b"NEWCOMER", 5, 1), ("127.255.255.255", ports.announce))
            self.assertEqual(collect(claimer, 1.0, lambda d: d[0x0A] == 0x08, fresh=False), [])
        finally:
            claimer.close()
            world.set_enabled(world.decks[2], False)


class Profiles(unittest.TestCase):
    def status_of(self, net, number=2):
        return net.decks[number].status()

    def test_a_profile_sets_the_name_the_length_and_the_nexus_byte(self):
        for profile, name, length, nexus in (("cdj-2000", b"CDJ-2000nexus", 0xD4, 0x0F), ("cdj-2000nxs2", b"CDJ-2000NXS2", 0x124, 0x0F),
                                             ("xdj-1000mk2", b"XDJ-1000MK2", 0x11B, 0x0F), ("cdj-3000", b"CDJ-3000", 0x200, 0x1F)):
            world = world_of(2)
            net = Prolink(world, ports=fresh(), profile=profile)
            p = self.status_of(net)
            self.assertEqual((len(p), p[0x0B:0x0B + len(name)], p[0xCC]), (length, name, nexus), profile)
            self.assertEqual(int.from_bytes(p[0x22:0x24], "big"), length - 0x24)
            self.assertEqual(net.decks[2].keepalive()[0x0C:0x0C + len(name)], name)

    def test_the_cdj_3000_does_not_count_its_syncs(self):
        world = world_of(2)
        net = Prolink(world, ports=fresh(), profile="cdj-3000")
        net.decks[2].sync_number = 7
        self.assertEqual(self.status_of(net)[0x84:0x88], bytes(4))
        net = Prolink(world_of(2), ports=fresh(), profile="cdj-2000nxs2")
        net.decks[2].sync_number = 7
        self.assertEqual(self.status_of(net)[0x84:0x88], bytes([0, 0, 0, 7]))

    def test_what_is_asked_for_by_hand_wins(self):
        net = Prolink(world_of(2), ports=fresh(), profile="cdj-3000", model="MY-DECK", status_length=0x150)
        p = self.status_of(net)
        self.assertEqual((len(p), p[0x0B:0x12], p[0xCC]), (0x150, b"MY-DECK", 0x1F))
        self.assertRaises(ValueError, Prolink, world_of(2), ports=fresh(), profile="cdj-9000")

    def test_it_is_a_setting(self):
        net = Prolink(world_of(2, 3), ports=fresh())
        self.assertEqual(net.settings()["profile"], "")
        self.assertTrue(net.set_option("profile", "cdj-3000"))
        self.assertEqual((net.settings()["profile"], net.settings()["model"], len(self.status_of(net, 3))), ("cdj-3000", "CDJ-3000", 0x200))
        self.assertFalse(net.set_option("profile", "cdj-9000"))
        self.assertTrue(net.set_option("profile", "default"))
        p = self.status_of(net, 3)
        self.assertEqual((net.settings()["profile"], len(p), p[0x0B:0x15], p[0xCC]), ("", 0x124, b"CDJ-FAKE3\x00", 0x0F))

    def test_the_command_line_takes_only_a_profile_there_is(self):
        import os
        import subprocess
        import sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-m", "deckbench", "--profile", "cdj-9000", "--http-port", "-1"],
                             capture_output=True, text=True, timeout=20, cwd=root)
        self.assertEqual(out.returncode, 2)
        self.assertIn("cdj-3000", out.stderr)

    def test_it_is_a_setting_of_the_api(self):
        world = world_of(2)
        ports = fresh()
        net = Prolink(world, ports=ports)
        server = serve(world, "127.0.0.1", 0)
        try:
            url = "http://127.0.0.1:%d/" % server.server_address[1]
            request = urllib.request.Request(url + "api/settings/profile/xdj-1000mk2", method="POST")
            state = json.loads(urllib.request.urlopen(request, timeout=5).read())
            self.assertEqual(state["decks"]["2"]["model"], "XDJ-1000MK2")
        finally:
            server.shutdown()
            server.server_close()


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = world_of(2, 3)
        cls.ports = fresh()
        cls.net = Prolink(cls.world, ports=cls.ports)
        cls.net.start()
        cls.server = serve(cls.world, "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.net.mixer.set_on(False)
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, path):
        request = urllib.request.Request(self.url + path, method="POST")
        with urllib.request.urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def test_the_mixer_through_the_api(self):
        state = self.post("api/mixer/on/1")
        mixer = state["protocols"]["prolink"]["mixer"]
        self.assertTrue(mixer["on"])
        self.assertEqual((mixer["name"], mixer["number"], sorted(mixer["channels"])), ("DJM-900NXS2", 33, ["1", "2", "3", "4"]))
        state = self.post("api/mixer/channel/3/fader/65")
        self.assertEqual(state["protocols"]["prolink"]["mixer"]["channels"]["3"], {"fader": 65, "fader_start": False, "on_air": True})
        state = self.post("api/mixer/channel/3/fader_start/1")
        self.assertTrue(state["protocols"]["prolink"]["mixer"]["channels"]["3"]["fader_start"])
        self.post("api/mixer/master/0")
        self.assertFalse(self.world.protocols[0].mixer.on_air(3))
        self.post("api/mixer/master/1")
        self.assertTrue(self.post("api/settings/mixer/0")["protocols"]["prolink"]["settings"]["mixer"] is False)
        for bad in ("api/mixer/channel/9/fader/1", "api/mixer/channel/2/command/jump", "api/mixer/nothing/1", "api/mixer/channel/1/fader/x"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post(bad)
            self.assertIn(error.exception.code, (400, 404), bad)

    def test_claim_is_a_setting(self):
        self.assertTrue(self.post("api/settings/claim/1")["protocols"]["prolink"]["settings"]["claim"])
        self.assertFalse(self.post("api/settings/claim/0")["protocols"]["prolink"]["settings"]["claim"])


if __name__ == "__main__":
    unittest.main()
