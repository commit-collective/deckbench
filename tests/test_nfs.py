# SPDX-License-Identifier: MIT OR Apache-2.0
"""Reading a player's files over NFS (deckbench/nfs.py), against a small server that answers as the players do, and a
bench deck that plays a real player's track getting its audio that way."""
import io
import os
import shutil
import socket
import struct
import tempfile
import threading
import unittest
import wave
from unittest.mock import patch

import test_linked_track as linked
from deckbench import nfs
from deckbench.protocols import pdb


class FakePlayer(threading.Thread):
    """The portmapper, MOUNT 1 and NFS 2 of a player, on one UDP socket: `files` are {"/C/path/in/it": bytes}. It takes
    names in UTF-16LE only, and drops every `drop`-th request, to have the client send again."""

    def __init__(self, files, address="127.0.0.1", drop=0):
        super().__init__(daemon=True)
        self.files, self.drop, self.count, self.names = files, drop, 0, []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((address, 0))
        self.port = self.sock.getsockname()[1]
        self.handles = {}
        self.stopped = False
        self.start()

    def stop(self):
        self.stopped = True
        self.sock.close()

    def handle(self, path):
        raw = path.encode("utf-8")[:32].ljust(32, b"\0")
        key = bytes([len(self.handles) + 1]) + raw[1:]
        self.handles[key] = path
        return key

    def kind(self, path):
        if path in self.files:
            return 1
        return 2 if any(name.startswith(path.rstrip("/") + "/") for name in self.files) else None

    def attributes(self, path):
        size = len(self.files.get(path, b""))
        return struct.pack(">17I", self.kind(path), 0o644, 1, 0, 0, size, 2048, 0, 1, 1, 1, 0, 0, 7, 0, 0, 0)

    @staticmethod
    def string(data, at):
        length = struct.unpack_from(">I", data, at)[0]
        return data[at + 4:at + 4 + length], at + 4 + length + (-length % 4)

    def answer(self, data):
        xid, _, _, prog, vers, proc = struct.unpack_from(">6I", data)
        at = 24
        for _ in range(2):                                  # credentials and verifier
            length = struct.unpack_from(">I", data, at + 4)[0]
            at += 8 + length + (-length % 4)
        args = data[at:]
        result = b""
        if prog == nfs.PORTMAP and proc == 3:
            result = struct.pack(">I", self.port)
        elif prog == nfs.MOUNT and proc == 1:
            raw, _ = self.string(args, 0)
            path = raw.decode("utf-16-le")
            result = struct.pack(">I", 0) + self.handle(path) if self.kind(path) == 2 else struct.pack(">I", 2)
        elif prog == nfs.NFS and proc == 4:
            folder = self.handles[args[:32]]
            raw, _ = self.string(args, 32)
            try:
                name = raw.decode("utf-16-le")
            except UnicodeDecodeError:
                name = "\0"
            self.names.append(name)
            path = folder.rstrip("/") + "/" + name
            result = (struct.pack(">I", 0) + self.handle(path) + self.attributes(path)) if self.kind(path) else struct.pack(">I", 2)
        elif prog == nfs.NFS and proc == 6:
            path = self.handles[args[:32]]
            offset, count, _ = struct.unpack_from(">III", args, 32)
            chunk = self.files[path][offset:offset + count]
            result = struct.pack(">I", 0) + self.attributes(path) + struct.pack(">I", len(chunk)) + chunk + b"\0" * (-len(chunk) % 4)
        return struct.pack(">IIIIII", xid, 1, 0, 0, 0, 0) + result

    def run(self):
        while not self.stopped:
            try:
                data, peer = self.sock.recvfrom(65536)
            except OSError:
                return
            self.count += 1
            if self.drop and self.count % self.drop == 0:
                continue
            self.sock.sendto(self.answer(data), peer)


def wav_bytes(seconds=1.0):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x10\x00\x20\x00" * int(44100 * seconds))
    return out.getvalue()


class Client(unittest.TestCase):
    def test_a_file_is_read_whole_even_when_answers_are_lost(self):
        data = bytes(range(256)) * 41 + b"end"               # five reads and a bit
        player = FakePlayer({"/C/Contents/Artist/track.mp3": data}, drop=4)
        self.addCleanup(player.stop)
        got = nfs.read_file("127.0.0.1", 3, "/Contents/Artist/track.mp3", portmap_port=player.port)
        self.assertEqual(got, data)
        self.assertEqual(player.names[:3], ["Contents", "Artist", "track.mp3"])    # one part at a time, in UTF-16LE

    def test_a_missing_file_and_a_hidden_pioneer_folder(self):
        player = FakePlayer({"/B/.PIONEER/rekordbox/export.pdb": b"x" * 10})
        self.addCleanup(player.stop)
        self.assertEqual(nfs.read_file("127.0.0.1", 2, "PIONEER/rekordbox/export.pdb", portmap_port=player.port), b"x" * 10)
        with self.assertRaises(nfs.NotFound):
            nfs.read_file("127.0.0.1", 2, "Contents/none.mp3", portmap_port=player.port)
        with self.assertRaises(nfs.NfsError):
            nfs.read_file("127.0.0.1", 1, "a", portmap_port=player.port)       # a CD is not read

    def test_a_file_over_the_limit_is_refused(self):
        player = FakePlayer({"/C/big.wav": b"\0" * 5000})
        self.addCleanup(player.stop)
        with self.assertRaises(nfs.NfsError):
            nfs.read_file("127.0.0.1", 3, "big.wav", portmap_port=player.port, limit=4096)


class TrackAudio(unittest.TestCase):
    """A bench deck on a real player's track gets that track's audio from the player's USB."""

    feed = linked.LinkedTrack.feed
    rounds = linked.LinkedTrack.rounds

    def setUp(self):
        linked.LinkedTrack.setUp(self)
        self.folder = tempfile.mkdtemp()
        self.addCleanup(lambda: [os.remove(os.path.join(self.folder, f)) for f in os.listdir(self.folder)])
        self.net.tracks_dir = self.folder
        self.addCleanup(lambda: self.net.session_audio and shutil.rmtree(self.net.session_audio, ignore_errors=True))
        export = pdb.build_pdb({57: ("Real träck", "/Contents/Someone/Real track.wav"), 58: ("Other", "")})
        self.player_media = FakePlayer({"/C/PIONEER/rekordbox/export.pdb": export,
                                        "/C/Contents/Someone/Real track.wav": wav_bytes()}, address=self.ip)
        self.addCleanup(self.player_media.stop)
        self.net.nfs_portmap = self.player_media.port

    def audio_rounds(self, n):
        stops = iter([False] * n + [True])
        with patch.object(self.net.runtime.stopping, "wait", lambda seconds: next(stops)):
            self.net.read_linked_audio()

    def test_the_deck_plays_the_tracks_own_audio_on_its_grid(self):
        self.assertEqual(pdb.parse_tracks(self.player_media.files["/C/PIONEER/rekordbox/export.pdb"])[57]["title"], "Real träck")
        self.world.load_track(self.deck, 57, source=2, slot=3)
        self.rounds(2)                                        # the grid first
        self.audio_rounds(1)
        audio = self.deck.audio
        self.assertIsNotNone(audio)
        self.assertEqual((audio.bpm, audio.offset), (125.5, 0.25))      # made at the grid's tempo, from its first beat
        self.assertTrue(audio.path.startswith(self.net.session_audio) and audio.path.endswith("Real track.wav"))
        self.assertEqual(os.listdir(self.folder), [])                   # not kept with the page's files
        self.assertEqual(self.net.describe(self.deck)["linked_audio"]["state"], "ready")
        self.assertEqual(self.deck.grid["first"], 3)                    # the track and its grid stay
        self.assertEqual(self.world.events.since(0)[-1]["kind"], "linked_audio_read")
        asked = len(self.player_media.names)
        self.audio_rounds(2)
        self.assertEqual(len(self.player_media.names), asked)           # read once

    def test_a_track_without_a_file_is_said_and_a_new_load_drops_the_audio(self):
        self.world.load_track(self.deck, 58, source=2, slot=3)
        self.rounds(2)
        self.audio_rounds(1)
        state = self.net.describe(self.deck)["linked_audio"]
        self.assertEqual((state["state"], state["reason"]), ("failed", "track 58 is not in the media's export.pdb"))
        self.world.load_track(self.deck, 57, source=2, slot=3)
        self.rounds(2)
        self.audio_rounds(1)
        self.assertIsNotNone(self.deck.audio)
        self.world.load_track(self.deck, 58, source=2, slot=3)
        self.assertIsNone(self.deck.audio)
        self.assertIsNone(self.net.describe(self.deck)["linked_audio"])

    def test_the_audio_goes_when_the_bench_stops_unless_it_is_kept(self):
        self.world.load_track(self.deck, 57, source=2, slot=3)
        self.rounds(2)
        self.audio_rounds(1)
        session = self.net.session_audio
        self.assertTrue(os.path.isfile(self.deck.audio.path))
        self.net.stop()
        self.assertFalse(os.path.exists(session))
        self.net.set_option("keep_track_audio", "1")
        self.assertEqual(self.net.audio_folder(), self.folder)

    def test_nothing_is_read_with_the_setting_off(self):
        self.net.set_option("track_audio", "0")
        self.world.load_track(self.deck, 57, source=2, slot=3)
        self.rounds(2)
        self.audio_rounds(2)
        self.assertIsNone(self.deck.audio)
        self.assertEqual(self.player_media.names, [])


if __name__ == "__main__":
    unittest.main()
