# SPDX-License-Identifier: MIT OR Apache-2.0
"""The Pro DJ Link decks, checked from the outside by a small client.

    python -m unittest discover -s tests

Starts the bench in this process (decks 2 and 3, and the page) and listens on
UDP 50000-50002 on the loopback, so nothing else that uses those ports (an
emulator, another bench) may run. Needs a loopback with all of 127.0.0.0/8
(Linux has it; macOS needs aliases).
"""
import json
import socket
import struct
import threading
import time
import unittest
import urllib.request

from deckbench.core import Deck, World
from deckbench.protocols import prolink
from deckbench.protocols.prolink import (ANNOUNCE_PORT, BEAT_PORT, MAGIC, UPDATE_PORT, Prolink,
                                         message, num, read_exact, read_message)
from deckbench.web import serve


def listen(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.settimeout(0.3)
    return s


def drain(sock):
    """Throws away what waits in the socket (it keeps the datagrams that came
    while nobody read it)."""
    sock.settimeout(0)
    try:
        while True:
            sock.recvfrom(4096)
    except (BlockingIOError, socket.timeout):
        pass
    finally:
        sock.settimeout(0.3)


def collect(sock, seconds, keep=lambda data: True, fresh=True):
    """The datagrams that arrive in `seconds` (from now on, unless fresh is
    false: then those that wait too), that are Pro DJ Link ones."""
    if fresh:
        drain(sock)
    out = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue
        if data[:10] == MAGIC and keep(data):
            out.append(data)
    return out


class Bench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()
        for i, n in enumerate((2, 3)):
            cls.world.decks[n] = Deck(cls.world, n, 128.0 - 2 * i, "deck %d" % n)
        titles = {2: {(3, 202): "Café del Mar"}}
        cls.prolink = Prolink(cls.world, loaded={3: (2, 3, 202)}, titles=titles)
        cls.prolink.start()
        cls.server = serve(cls.world, "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]
        cls.keepalives, cls.statuses, cls.beats = listen(ANNOUNCE_PORT), listen(UPDATE_PORT), listen(BEAT_PORT)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for s in (cls.keepalives, cls.statuses, cls.beats):
            s.close()

    def api(self, path, post=False):
        request = urllib.request.Request(self.url + path, method="POST" if post else "GET")
        with urllib.request.urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def status_of(self, number, seconds=1.0):
        packets = [d for d in collect(self.statuses, seconds, lambda d: d[0x0A] == 0x0A and d[0x21] == number)]
        self.assertTrue(packets, "no status from deck %d" % number)
        return packets[-1]

    def switch(self, number, what, on):
        self.api("api/deck/%d/%s/%d" % (number, what, 1 if on else 0), post=True)

    def setUp(self):
        for n in self.world.decks:
            self.switch(n, "master", False)
            self.switch(n, "sync", False)
            self.switch(n, "play", False)
        time.sleep(0.3)

    # -- the page and the API --
    def test_page_and_state(self):
        with urllib.request.urlopen(self.url, timeout=5) as r:
            self.assertIn(b"deckbench", r.read())
        state = self.api("api/state")
        self.assertEqual(sorted(state["decks"]), ["2", "3"])
        self.assertEqual(state["decks"]["2"]["track"], "Track of deck 2")
        self.assertEqual(state["decks"]["3"]["track"], "Café del Mar")
        self.assertIsNone(state["protocols"]["prolink"]["unit"])

    def test_api_toggles_and_refuses(self):
        self.switch(2, "on", False)
        self.assertFalse(self.api("api/state")["decks"]["2"]["on"])
        self.api("api/deck/2/on", post=True)
        self.assertTrue(self.api("api/state")["decks"]["2"]["on"])
        with self.assertRaises(urllib.error.HTTPError):
            self.api("api/deck/2/volume", post=True)
        with self.assertRaises(urllib.error.HTTPError):
            self.api("api/deck/9/on", post=True)

    # -- what a deck sends --
    def test_off_deck_is_silent(self):
        self.switch(3, "on", False)
        time.sleep(0.5)
        collect(self.statuses, 0.4)
        self.assertEqual(collect(self.statuses, 1.0, lambda d: d[0x21] == 3), [])
        self.switch(3, "on", True)

    def test_keepalive(self):
        self.switch(2, "on", True)
        packets = collect(self.keepalives, 3.0, lambda d: d[0x0A] == 0x06)
        mine = [p for p in packets if p[0x24] == 2]
        self.assertTrue(mine, "no keep-alive from deck 2")
        p = mine[-1]
        self.assertEqual(len(p), 0x36)
        self.assertEqual(p[0x0C:0x14], b"CDJ-FAKE")
        self.assertEqual(socket.inet_ntoa(p[0x2C:0x30]), "127.0.0.2")

    def test_status_fields(self):
        self.switch(2, "on", True)
        p = self.status_of(2)
        self.assertEqual(len(p), 0x124)
        self.assertEqual((p[0x1F], p[0x20], p[0x21], p[0x24]), (1, 3, 2, 2))
        self.assertEqual(struct.unpack(">H", p[0x22:0x24])[0], len(p) - 0x24)   # lenr
        self.assertEqual(struct.unpack(">H", p[0x90:0x92])[0], 0x8000)          # Mv
        self.assertEqual(p[0x89] & 0x84, 0x84)                                  # bits 7 and 2
        self.assertEqual(struct.unpack(">H", p[0x92:0x94])[0], 12800)
        self.assertEqual(struct.unpack(">I", p[0x2C:0x30])[0], 102)             # rekordbox id
        for at in (0x8C, 0x98, 0xC0, 0xC4):
            self.assertEqual(struct.unpack(">I", p[at:at + 4])[0], 0x100000)
        self.assertEqual(p[0x9F], 0xFF)

    def test_play_sends_beats(self):
        self.switch(2, "on", True)
        collect(self.beats, 0.3)
        self.switch(2, "play", True)
        packets = collect(self.beats, 2.5, lambda d: d[0x0A] == 0x28 and d[0x5F] == 2)
        self.assertGreaterEqual(len(packets), 3, "a beat a 0.47 s at 128 BPM")
        beats = [p[0x5C] for p in packets]
        for a, b in zip(beats, beats[1:]):
            self.assertEqual(b, a % 4 + 1)
        self.assertEqual(struct.unpack(">H", packets[-1][0x5A:0x5C])[0], 12800)
        self.assertEqual(self.status_of(2)[0x89] & 0x40, 0x40)                  # playing

    def test_sync_follows_the_master(self):
        for n in (2, 3):
            self.switch(n, "on", True)
        self.switch(2, "master", True)
        self.switch(3, "sync", True)
        self.assertEqual(struct.unpack(">H", self.status_of(3)[0x92:0x94])[0], 12800)
        self.assertEqual(self.api("api/state")["decks"]["3"]["bpm"], 128.0)
        self.switch(3, "sync", False)
        self.assertEqual(struct.unpack(">H", self.status_of(3)[0x92:0x94])[0], 12600)

    def test_only_one_master(self):
        for n in (2, 3):
            self.switch(n, "on", True)
        self.switch(2, "master", True)
        self.assertEqual(self.status_of(2)[0x89] & 0x20, 0x20)
        self.switch(3, "master", True)
        time.sleep(1.5)
        decks = self.api("api/state")["decks"]
        self.assertEqual((decks["2"]["master"], decks["3"]["master"]), (False, True))
        self.assertEqual(self.status_of(2)[0x89] & 0x20, 0)
        self.assertEqual(self.status_of(3)[0x89] & 0x20, 0x20)

    def test_hand_off_to_a_player_that_asks(self):
        for n in (2, 3):
            self.switch(n, "on", True)
        self.switch(2, "master", True)
        collect(self.statuses, 0.3)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.9", 0))
        request = prolink.header(0x26, b"TEST") + bytes([0x01, 0x00, 9, 0x00, 0x04, 0, 0, 0, 9])
        s.sendto(bytes(request), ("127.0.0.2", BEAT_PORT))
        s.close()
        reply = collect(self.statuses, 2.0, lambda d: d[0x0A] == 0x27, fresh=False)
        self.assertTrue(reply, "no answer to the request")
        self.assertEqual((reply[0][0x21], reply[0][-1]), (2, 1))                # yields: 1
        self.assertEqual(self.status_of(2)[0x9F], 9)                            # Mh: to player 9
        time.sleep(4.5)                                                         # the time is up
        self.assertEqual(self.status_of(2)[0x9F], 0xFF)
        self.assertFalse(self.api("api/state")["decks"]["2"]["master"])

    def test_sync_commands(self):
        for n in (2, 3):
            self.switch(n, "on", True)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.9", 0))

        def command(code):
            p = bytearray(prolink.header(0x2A, b"TEST")) + bytes([0x01, 0, 9, 0, 0x08, 0, 0, 0, 9, 0, 0, 0, code])
            s.sendto(bytes(p), ("127.0.0.3", BEAT_PORT))
            time.sleep(0.5)
            return self.api("api/state")["decks"]["3"]

        try:
            self.assertTrue(command(0x10)["sync"])
            self.assertFalse(command(0x20)["sync"])
            self.assertTrue(command(0x01)["master"])
        finally:
            s.close()

    # -- the database --
    def test_database_gives_the_title(self):
        self.switch(2, "on", True)
        with socket.create_connection(("127.0.0.2", 12523), timeout=3) as c:
            c.sendall(struct.pack(">I", 15) + b"RemoteDBServer\0")
            port = struct.unpack(">H", read_exact(c, 2))[0]
        self.assertEqual(port, prolink.DB_PORT)
        with socket.create_connection(("127.0.0.2", port), timeout=3) as c:
            c.sendall(num(1))
            self.assertEqual(read_exact(c, 5), num(1))
            c.sendall(message(0xFFFFFFFE, 0x0000, [("n", 5)]))
            txid, mtype, _ = read_message(c)
            self.assertEqual((txid, mtype), (0xFFFFFFFE, 0x4000))
            dmst = 2 << 24 | 1 << 16 | 3 << 8 | 1
            c.sendall(message(1, 0x2002, [("n", dmst), ("n", 202)]))
            _, mtype, args = read_message(c)
            self.assertEqual((mtype, args[1][1]), (0x4000, 11))                  # eleven items
            c.sendall(message(2, 0x3000, [("n", dmst), ("n", 0), ("n", 11)]))
            titles = []
            while True:
                _, mtype, args = read_message(c)
                if mtype == 0x4201:
                    break
                if mtype == 0x4101 and args[6][1] == 0x04:
                    titles.append(args[3][1])
            self.assertEqual(titles, ["Café del Mar"])


class Addresses(unittest.TestCase):
    def test_broadcast_of(self):
        from deckbench.cli import broadcast_of
        self.assertEqual(broadcast_of("192.168.1.50", "255.255.255.0"), "192.168.1.255")
        self.assertEqual(broadcast_of("169.254.7.9", "255.255.0.0"), "169.254.255.255")
        self.assertEqual(broadcast_of("10.1.2.3", "255.255.255.128"), "10.1.2.127")


if __name__ == "__main__":
    unittest.main()
