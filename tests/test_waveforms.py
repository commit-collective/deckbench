# SPDX-License-Identifier: MIT OR Apache-2.0
"""Real players' waveforms: the requests, the answers' checks and decoding, a session with a database server, and the
bench's cache. Synthetic data only: no player's answer is kept in the repository."""
import io
import socket
import struct
import threading
import unittest
from unittest.mock import patch

import test_player_control as controls
from deckbench import waveforms
from deckbench.protocols.prolink import num, read_message

MAGIC = 0x872349AE


def field(kind, value):
    if kind == "n":
        return num(value)
    return b"\x14" + struct.pack(">I", len(value)) + value


def answer(txid, kind, args, omit_empty=True):
    """A message as a server writes it, blobs included. With omit_empty, an empty blob after a zero is left out."""
    tags, body = bytearray(12), b""
    for i, (k, v) in enumerate(args):
        tags[i] = 6 if k == "n" else 3
        if k == "b" and not v and omit_empty and i and args[i - 1] == ("n", 0):
            continue
        body += field(k, v)
    return num(MAGIC) + num(txid) + num(kind, 2) + num(len(args), 1) + field("b", bytes(tags)) + body


def envelope(name, width, columns):
    # a four-byte prefix, then the analysis tag: its name and a 24-byte header (lengths, then four unknown bytes)
    return b"\0\0\0\0" + name + struct.pack(">IIII", 24, 24 + len(columns), width, len(columns) // width) + b"\0" * 4 + columns


def overview(count=1200):
    return envelope(b"PWV4", 6, bytes((0, 0, 0, i % 128, (2 * i) % 128, (3 * i) % 128)[j] for i in range(count) for j in range(6)))


def detail(seconds=4):
    return envelope(b"PWV5", 2, b"".join(struct.pack(">H", (i % 32) << 2) for i in range(seconds * waveforms.RATE)))


def grid(times, bpm=120.0):
    return b"\0" * 20 + b"".join(struct.pack("<HHI", i % 4 + 1, int(bpm * 100), ms) + b"\0" * 8 for i, ms in enumerate(times))


class Stream(io.BytesIO):
    def recv(self, size):
        return self.read(size)


class Decoding(unittest.TestCase):
    def test_tags_are_ascii_read_backwards(self):
        self.assertEqual(waveforms.tag("PWV4"), int.from_bytes(b"PWV4", "little"))
        self.assertEqual(waveforms.tag("EXT"), int.from_bytes(b"EXT\0", "little"))
        name, kind, args, reply = waveforms.requests(3, 3, 805)[0]
        self.assertEqual((kind, reply, args[0]), (0x2C04, 0x4F02, ("n", 3 << 24 | 1 << 16 | 3 << 8 | 1)))
        self.assertEqual(waveforms.requests(3, 2, 805)[2][2][0], ("n", 3 << 24 | 8 << 16 | 2 << 8 | 1))

    def test_an_empty_blob_after_a_zero_is_left_out(self):
        data = answer(5, 0x4F02, [("n", 0x2C04), ("n", 0), ("n", 0), ("b", b""), ("n", 0)])
        txid, kind, args = read_message(Stream(data))
        self.assertEqual((txid, kind, args[3], args[4]), (5, 0x4F02, ("b", b""), ("n", 0)))
        with self.assertRaises(waveforms.Unavailable):
            waveforms.blob("overview", 0x2C04, 0x4F02, kind, args)

    def test_both_shapes_of_the_beat_grid_answer(self):
        data = grid([100, 600, 1100])
        four = [("n", 0x2204), ("n", 0), ("n", len(data)), ("b", data)]
        self.assertEqual(waveforms.blob("grid", 0x2204, 0x4602, 0x4602, four), data)
        self.assertEqual(waveforms.blob("grid", 0x2204, 0x4602, 0x4602, four + [("n", 0)]), data)    # the NXS2's
        with self.assertRaises(ValueError):
            waveforms.blob("grid", 0x2204, 0x4602, 0x4602, four + [("n", 7)])
        self.assertEqual(waveforms.decode_grid(data), [[100, 1, 12000], [600, 2, 12000], [1100, 3, 12000]])

    def test_malformed_answers_are_refused(self):
        data = overview()
        good = [("n", 0x2C04), ("n", 0), ("n", len(data)), ("b", data), ("n", 0)]
        self.assertEqual(len(waveforms.decode_overview(waveforms.blob("overview", 0x2C04, 0x4F02, 0x4F02, good))), 7200)
        for bad in ([("n", 0x2C04), ("n", 0), ("n", len(data) + 1), ("b", data), ("n", 0)],      # length
                    [("n", 0x2204)] + good[1:],                                                  # another request's
                    good[:4]):                                                                   # one argument short
            with self.assertRaises(ValueError):
                waveforms.blob("overview", 0x2C04, 0x4F02, 0x4F02, bad)
        with self.assertRaises(waveforms.Unavailable):
            waveforms.blob("overview", 0x2C04, 0x4F02, 0x4000, good)
        for broken in (data[:-6], data[:20], data.replace(b"PWV4", b"PWV6")):                   # truncated, other tag
            with self.assertRaises(ValueError):
                waveforms.decode_overview(broken)
        with self.assertRaises(ValueError):
            waveforms.decode_grid(grid([100, 100]))                                              # not increasing
        with self.assertRaises(ValueError):
            waveforms.decode_grid(grid([100])[:-3])


class Server:
    """A database server on the loopback answering one session: the port query, the greeting, the requester, then
    the answers given, in order."""
    def __init__(self, answers, txids=None):
        self.answers, self.txids, self.requests = answers, txids, []
        self.query = socket.create_server(("127.0.0.1", 0))
        self.db = socket.create_server(("127.0.0.1", 0))
        self.port = self.query.getsockname()[1]
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        conn, _ = self.query.accept()
        conn.recv(64)
        conn.sendall(struct.pack(">H", self.db.getsockname()[1]))
        conn.close()
        conn, _ = self.db.accept()
        conn.recv(5)
        conn.sendall(num(1))
        stream = conn.makefile("rb")
        reader = type("R", (), {"recv": lambda self, n: stream.read(n)})()
        txid, kind, args = read_message(reader)
        conn.sendall(answer(txid, 0x4000, [("n", 0), ("n", args[0][1])]))
        try:
            for i, (kind, args) in enumerate(self.answers):
                txid, got, request = read_message(reader)
                self.requests.append((got, request))
                conn.sendall(answer(self.txids[i] if self.txids else txid, kind, args))
            read_message(reader)                                        # the end of the session
        except (EOFError, OSError, ValueError):                         # the client gave up first
            pass
        conn.close()

    def close(self):
        self.query.close()
        self.db.close()


def good_answers(times=(50, 550, 1050, 1550)):
    o, d, g = overview(), detail(), grid(list(times))
    return [(0x4F02, [("n", 0x2C04), ("n", 0), ("n", len(o)), ("b", o), ("n", 0)]),
            (0x4F02, [("n", 0x2C04), ("n", 0), ("n", len(d)), ("b", d), ("n", 0)]),
            (0x4602, [("n", 0x2204), ("n", 0), ("n", len(g)), ("b", g), ("n", 0)])]


class Session(unittest.TestCase):
    def read(self, server):
        try:
            return waveforms.read_track_waveforms("127.0.0.1", "127.0.0.1", 3, 3, 805, query_port=server.port, timeout=3)
        finally:
            server.close()

    def test_one_session_reads_all_three(self):
        server = Server(good_answers())
        result = self.read(server)
        self.assertEqual((len(result["overview"]), len(result["detail"]) // 2, len(result["grid"])), (7200, 600, 4))
        self.assertEqual([kind for kind, _ in server.requests], [0x2C04, 0x2C04, 0x2204])
        self.assertEqual(server.requests[1][1][2], ("n", waveforms.tag("PWV5")))

    def test_a_wrong_transaction_is_refused(self):
        with self.assertRaises(ValueError):
            self.read(Server(good_answers(), txids=[1, 9, 3]))

    def test_no_waveform_for_the_track(self):
        with self.assertRaises(waveforms.Unavailable):
            self.read(Server([(0x4F02, [("n", 0x2C04), ("n", 0), ("n", 0), ("b", b""), ("n", 0)])]))

    def test_a_grid_past_the_waveform_is_refused(self):
        with self.assertRaises(ValueError):
            self.read(Server(good_answers(times=(50, 9000))))


class Cache(unittest.TestCase):
    """The bench's side: which track, read once, by itself, dropped when its source goes or the track changes."""
    setUp = controls.PlayerControl.setUp
    feed = controls.PlayerControl.feed

    def rounds(self, n, result):
        reads = []
        stops = iter([False] * n + [True])
        def read(address, source, number, slot, rbid, **k):
            reads.append((address, number, slot, rbid))
            if isinstance(result, Exception):
                raise result
            return result
        with patch("deckbench.waveforms.read_track_waveforms", read), \
             patch.object(self.net.runtime.stopping, "wait", lambda seconds: next(stops)):
            self.net.read_waveforms()
        return reads

    def data(self):
        return {"overview": b"\0" * 12, "detail": b"\0" * 300, "grid": [[100, 1, 12000]]}

    def device(self):
        return self.net.info()["devices"][0]

    def test_read_once_from_the_source_and_served_apart(self):
        self.world.decks[3].enabled = True                  # a bench player 1 to 4 to ask as
        self.net.auto_info = True
        self.assertEqual(self.device()["waveform"]["state"], "waiting")
        reads = self.rounds(3, self.data())
        self.assertEqual(reads, [(self.ip, 3, 3, 102)])     # the source: player 2 at its address, the track it has
        self.assertEqual(self.device()["waveform"]["state"], "ready")
        self.assertNotIn("detail", self.device()["waveform"])   # the state stays small
        code, body = self.net.waveform_asset(self.ip)
        self.assertEqual((code, body["rate"], body["grid"]), (200, 150, [[100, 1, 12000]]))

    def test_a_new_track_is_read_and_a_failure_is_not_retried_at_once(self):
        self.world.decks[3].enabled = True
        self.net.auto_info = True
        self.rounds(1, self.data())
        self.player.rbid = 103
        self.feed()
        self.assertEqual(self.device()["waveform"]["state"], "waiting")
        self.assertEqual(self.net.waveform_asset(self.ip)[0], 404)     # never the last track's
        reads = self.rounds(3, waveforms.Unavailable("no overview"))
        self.assertEqual(len(reads), 1)
        self.assertEqual(self.device()["waveform"]["state"], "failed")

    def test_a_source_that_goes_drops_its_waveforms(self):
        self.world.decks[3].enabled = True
        self.net.auto_info = True
        self.rounds(1, self.data())
        self.assertEqual(len(self.net.waves), 1)
        self.net.monitor.devices.clear()
        self.rounds(1, self.data())
        self.assertEqual(len(self.net.waves), 0)

    def test_nothing_is_read_without_a_number_to_ask_as_or_with_the_setting_off(self):
        self.net.auto_info = True
        self.assertEqual(self.rounds(2, self.data()), [])          # no bench player 1 to 4 on
        self.world.decks[3].enabled = True
        self.net.auto_info = False
        self.assertEqual(self.rounds(2, self.data()), [])


if __name__ == "__main__":
    unittest.main()
