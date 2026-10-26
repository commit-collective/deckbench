# SPDX-License-Identifier: MIT OR Apache-2.0
"""A deck's track of its own: a sound file played at the deck's tempo (audio.Track, World.load_audio)."""
import array
import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import wave

from deckbench.audio import AudioError, Mixer, Track, load_file
from deckbench import web
from deckbench.core import Deck, World
from deckbench.web import serve


def ramp(frames, step=1):
    """A signal that says where it is: sample i is i * step, going up on the left and down on the right."""
    left = array.array("h", [(i * step) % 30000 for i in range(frames)])
    right = array.array("h", [-((i * step) % 30000) for i in range(frames)])
    return left, right


def write_wav(path, left, right=None, rate=44100, width=2):
    """A PCM WAV of 16-bit samples (or the same widened to 8, 24 or 32 bits), mono if there is no right."""
    with wave.open(path, "wb") as f:
        f.setnchannels(1 if right is None else 2)
        f.setsampwidth(width)
        f.setframerate(rate)
        chans = [left] if right is None else [left, right]
        raw = bytearray()
        for i in range(len(left)):
            for c in chans:
                v = c[i]
                if width == 2:
                    raw += int(v).to_bytes(2, "little", signed=True)
                elif width == 1:
                    raw.append((v >> 8) + 128)
                elif width == 3:
                    raw += (int(v) << 8).to_bytes(3, "little", signed=True)
                else:
                    raw += (int(v) << 16).to_bytes(4, "little", signed=True)
        f.writeframes(bytes(raw))


class TrackBlocks(unittest.TestCase):
    def setUp(self):
        left, right = ramp(200000)
        self.track = Track("ramp.wav", left, right, 120.0)

    def test_at_its_own_tempo_the_frames_are_the_file(self):
        left, right = self.track.block(0.0, 120.0, 441)
        self.assertEqual(len(left), 441)
        self.assertAlmostEqual(left[0], 0.0)
        self.assertAlmostEqual(left[440], 440 / 32768.0)
        self.assertAlmostEqual(right[440], -440 / 32768.0)

    def test_the_place_in_beats_is_the_place_in_the_file(self):
        # a beat is half a second at 120 BPM
        left, _ = self.track.block(1.0, 120.0, 10)
        self.assertAlmostEqual(left[0], 22050 / 32768.0)

    def test_the_file_starts_at_its_offset(self):
        track = Track("ramp.wav", *ramp(200000), bpm=120.0, offset=0.1)
        left, _ = track.block(0.0, 120.0, 10)
        self.assertAlmostEqual(left[0], 4410 / 32768.0)

    def test_faster_is_read_faster(self):
        left, right = self.track.block(0.0, 180.0, 100)         # one and a half times: it was made at 120
        self.assertAlmostEqual(left[10], 15 / 32768.0, places=6)
        self.assertAlmostEqual(right[10], -15 / 32768.0, places=6)
        slow, _ = self.track.block(0.0, 60.0, 100)
        self.assertAlmostEqual(slow[10], 5 / 32768.0, places=6)

    def test_the_tempo_of_the_source_is_what_counts(self):
        track = Track("ramp.wav", *ramp(200000), bpm=100.0)
        a, _ = track.block(0.0, 100.0, 20)
        b, _ = track.block(0.0, 200.0, 20)
        self.assertAlmostEqual(a[10], 10 / 32768.0)
        self.assertAlmostEqual(b[10], 20 / 32768.0, places=6)

    def test_nothing_before_the_file_or_after_it(self):
        short = Track("short.wav", *ramp(100), bpm=120.0)
        left, _ = short.block(0.0, 120.0, 300)
        self.assertAlmostEqual(left[99], 99 / 32768.0)
        self.assertEqual(left[100:], [0.0] * 200)
        beyond, _ = short.block(100.0, 120.0, 50)
        self.assertEqual(beyond, [0.0] * 50)
        early = Track("early.wav", *ramp(1000), bpm=120.0, offset=0.01)
        before, _ = early.block(-1.0, 120.0, 20)
        self.assertEqual(before, [0.0] * 20)


class AsWav(unittest.TestCase):
    def test_the_page_gets_the_samples_it_would_hear(self):
        left, right = ramp(3000, step=5)
        track = Track("t.wav", left, right, 120.0)
        path = os.path.join(tempfile.mkdtemp(), "out.wav")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        with open(path, "wb") as f:
            f.write(track.wav())
        with wave.open(path, "rb") as f:
            self.assertEqual((f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getnframes()), (2, 2, 44100, 3000))
            both = array.array("h")
            both.frombytes(f.readframes(3000))
        self.assertEqual(list(both[0::2]), list(left))
        self.assertEqual(list(both[1::2]), list(right))
        self.assertIs(track.wav(), track.wav())                  # made once


class Peaks(unittest.TestCase):
    def test_the_loudness_of_each_hundredth_of_a_second(self):
        loud = array.array("h", [16384] * 441 + [0] * 441 + [-32767] * 441)          # 10 ms of half scale, 10 ms of silence, 10 ms at full
        track = Track("p.wav", loud, array.array("h", [0] * len(loud)), 120.0)
        got = track.peaks()
        self.assertEqual(got["rate"], 100)
        self.assertEqual(got["peaks"], [50, 0, 100])

    def test_the_other_side_counts_too(self):
        silent = array.array("h", [0] * 441)
        track = Track("p.wav", silent, array.array("h", [8192] * 441), 120.0)
        self.assertEqual(track.peaks()["peaks"], [25])


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def test_a_stereo_wav(self):
        left, right = ramp(5000)
        write_wav(self.path("s.wav"), left, right)
        track = load_file(self.path("s.wav"), 128.0)
        self.assertEqual(list(track.left), list(left))
        self.assertEqual(list(track.right), list(right))
        self.assertEqual(track.bpm, 128.0)

    def test_a_mono_wav_is_both_sides(self):
        left, _ = ramp(3000)
        write_wav(self.path("m.wav"), left)
        track = load_file(self.path("m.wav"), 100.0)
        self.assertEqual(list(track.left), list(track.right))
        self.assertEqual(list(track.left), list(left))

    def test_wider_and_narrower_samples(self):
        left, right = ramp(2000, step=7)
        for width in (3, 4):
            write_wav(self.path("w%d.wav" % width), left, right, width=width)
            track = load_file(self.path("w%d.wav" % width), 120.0)
            self.assertEqual(list(track.left), list(left), "width %d" % width)
        write_wav(self.path("w1.wav"), left, right, width=1)
        track = load_file(self.path("w1.wav"), 120.0)
        for a, b in zip(track.left, left):
            self.assertLess(abs(a - b), 256)                    # 8 bits keep the high byte

    def test_what_will_not_do(self):
        with self.assertRaises(AudioError):
            load_file(self.path("none.wav"), 120.0)
        write_wav(self.path("s.wav"), *ramp(1000))
        with self.assertRaises(AudioError):
            load_file(self.path("s.wav"), 0)
        with self.assertRaises(AudioError):
            load_file(self.path("s.wav"), None)
        with open(self.path("not.wav"), "wb") as f:
            f.write(b"this is not sound")
        if not shutil.which("ffmpeg"):
            with self.assertRaises(AudioError):
                load_file(self.path("not.wav"), 120.0)


class OnADeck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.file = os.path.join(self.dir, "My Loop.wav")
        write_wav(self.file, *ramp(100000))
        self.world = World()
        self.deck = Deck(self.world, 1, 120.0)
        self.world.decks[1] = self.deck

    def test_it_is_loaded_as_a_track(self):
        track = self.world.load_audio(self.deck, self.file, 126.0)
        self.assertIs(self.deck.audio, track)
        self.assertEqual(self.deck.track, (1001, "My Loop"))
        self.assertEqual(self.deck.base_bpm, 126.0)             # the deck plays at the tempo it was made at

    def test_it_is_the_decks_sound_while_it_plays(self):
        self.world.load_audio(self.deck, self.file, 120.0)
        self.deck.enabled = self.deck.playing = True
        now = time.time()
        self.deck.anchor_t, self.deck.anchor_pos = now, 0.0
        data = array.array("h")
        data.frombytes(Mixer(self.world).block(441, now))
        left, right = data[0::2], data[1::2]
        self.assertGreater(left[400], left[10])                  # the left side of the ramp goes up
        self.assertLess(right[400], right[10])                   # and the right goes down: it is the file, not the drum loop
        self.assertGreater(left[400], 300)

    def test_a_stopped_deck_is_silent(self):
        self.world.load_audio(self.deck, self.file, 120.0)
        self.deck.enabled = True
        self.assertEqual(set(Mixer(self.world).block(441, time.time())), {0})

    def test_a_deck_without_a_file_still_has_its_drum_loop(self):
        self.deck.enabled = self.deck.playing = True
        now = time.time()
        self.deck.anchor_t, self.deck.anchor_pos = now, 0.0
        data = array.array("h")
        data.frombytes(Mixer(self.world).block(441, now))
        self.assertEqual(list(data[0::2]), list(data[1::2]))     # the same on both sides, as it was
        self.assertTrue(any(data))

    def test_another_track_or_clearing_gives_the_loop_back(self):
        self.world.load_audio(self.deck, self.file, 120.0)
        self.world.load_track(self.deck, 5, "Other")
        self.assertIsNone(self.deck.audio)
        self.world.load_audio(self.deck, self.file, 120.0)
        self.world.clear_audio(self.deck)
        self.assertIsNone(self.deck.audio)

    def test_a_file_that_will_not_do_changes_nothing(self):
        self.deck.track = (7, "Before")
        with self.assertRaises(AudioError):
            self.world.load_audio(self.deck, os.path.join(self.dir, "none.wav"), 120.0)
        self.assertEqual(self.deck.track, (7, "Before"))
        self.assertIsNone(self.deck.audio)

    def test_the_state_says_it(self):
        self.assertIsNone(self.world.snapshot()["decks"]["1"]["audio"])
        self.world.load_audio(self.deck, self.file, 120.0, offset=0.25)
        said = self.world.snapshot()["decks"]["1"]["audio"]
        self.assertEqual(said["file"], "My Loop.wav")
        self.assertEqual(said["bpm"], 120.0)
        self.assertEqual(said["offset"], 0.25)


class Upload(unittest.TestCase):
    """The page's Browse: a file from the browser's computer goes to the bench, which keeps it and says where."""

    @classmethod
    def setUpClass(cls):
        cls.world = World()
        cls.world.decks[2] = Deck(cls.world, 2, 120.0)
        cls.folder = tempfile.mkdtemp(prefix="deckbench-test-tracks-")      # not the user's own folder of sent files
        cls.server = serve(cls.world, "127.0.0.1", 0, tracks=cls.folder)
        cls.base = "http://127.0.0.1:%d/" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.folder, True)

    def test_the_same_file_is_one_file_and_stays(self):
        data = self.wav_bytes()
        first = self.post("api/upload?name=same.wav", data)[1]["path"]
        second = self.post("api/upload?name=same.wav", data)[1]["path"]
        self.assertEqual(first, second)
        self.assertEqual(os.path.dirname(first), self.folder)
        self.assertTrue(os.path.basename(first).endswith("-same.wav"))
        other = self.post("api/upload?name=same.wav", data + b"x")[1]["path"]      # other contents, other file
        self.assertNotEqual(first, other)

    def test_what_is_kept_is_told_and_cleared_but_not_what_a_deck_plays(self):
        playing = self.post("api/upload?name=playing.wav", self.wav_bytes())[1]["path"]
        self.post("api/upload?name=spare.wav", b"spare" * 100)
        self.post("api/deck/2/load/60?bpm=120&audio=" + urllib.request.quote(playing))
        with urllib.request.urlopen(self.base + "api/uploads", timeout=5) as r:
            said = json.loads(r.read().decode("utf-8"))
        self.assertEqual(said["dir"], self.folder)
        self.assertGreaterEqual(said["files"], 2)
        code, got = self.post("api/uploads/clear")
        self.assertEqual(code, 200)
        self.assertGreaterEqual(got["removed"], 1)
        self.assertTrue(os.path.exists(playing))                 # a deck plays it
        with urllib.request.urlopen(self.base + "api/uploads", timeout=5) as r:
            self.assertEqual(json.loads(r.read().decode("utf-8"))["files"], 1)

    def test_old_files_and_the_oldest_over_the_size_go(self):
        from deckbench import uploads
        folder = tempfile.mkdtemp(prefix="deckbench-trim-")
        self.addCleanup(shutil.rmtree, folder, True)
        now = time.time()
        for name, size, age in (("a-old.wav", 10, 40 * 86400), ("b-mid.wav", 600, 5 * 86400), ("c-new.wav", 600, 60)):
            path = os.path.join(folder, name)
            with open(path, "wb") as f:
                f.write(b"x" * size)
            os.utime(path, (now - age, now - age))
        count, size = uploads.trim(folder, max_age=30 * 86400, max_total=1000)
        left = sorted(os.listdir(folder))
        self.assertEqual(left, ["c-new.wav"])                      # the old one by its age, the middle one because 1200 > 1000
        self.assertEqual(count, 2)
        keep = os.path.join(folder, "c-new.wav")
        os.utime(keep, (now - 60 * 86400, now - 60 * 86400))
        self.assertEqual(uploads.trim(folder, busy=[keep], max_age=30 * 86400)[0], 0)       # but not one that is in use

    def post(self, path, body=None):
        request = urllib.request.Request(self.base + path, data=body, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def wav_bytes(self):
        path = os.path.join(tempfile.mkdtemp(), "x.wav")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        write_wav(path, *ramp(20000))
        with open(path, "rb") as f:
            return f.read()

    def test_the_file_is_kept_and_its_path_given(self):
        data = self.wav_bytes()
        code, got = self.post("api/upload?name=My%20Break%20128bpm.wav", data)
        self.assertEqual(code, 200)
        self.assertEqual(got["bytes"], len(data))
        self.assertTrue(got["name"].endswith("My Break 128bpm.wav"))
        with open(got["path"], "rb") as f:
            self.assertEqual(f.read(), data)

    def test_it_can_then_be_a_decks_track(self):
        code, got = self.post("api/upload?name=loop.wav", self.wav_bytes())
        code, state = self.post("api/deck/2/load/55?bpm=128&audio=" + urllib.request.quote(got["path"]))
        self.assertEqual(code, 200)
        self.assertEqual(state["decks"]["2"]["audio"]["file"], os.path.basename(got["path"]))
        self.assertEqual(state["decks"]["2"]["audio"]["bpm"], 128.0)

    def test_a_name_cannot_walk_out_of_the_folder(self):
        code, got = self.post("api/upload?name=..%2F..%2Fevil.wav", b"abcd")
        self.assertEqual(code, 200)
        other = self.post("api/upload?name=a.wav", b"x")[1]
        self.assertEqual(os.path.dirname(got["path"]), os.path.dirname(other["path"]))      # the same folder, whatever the name said
        self.assertTrue(got["name"].endswith("evil.wav"))
        self.assertNotIn("/", got["name"])
        code, got = self.post("api/upload?name=..%5C..%5Cevil2.wav", b"abcd")                # and a Windows path
        self.assertEqual(os.path.dirname(got["path"]), os.path.dirname(other["path"]))
        self.assertTrue(got["name"].endswith("evil2.wav"))

    def test_no_body_and_too_big(self):
        code, got = self.post("api/upload?name=a.wav")
        self.assertEqual(code, 400)
        old = web.UPLOAD_LIMIT
        web.UPLOAD_LIMIT = 10
        try:
            code, got = self.post("api/upload?name=a.wav", b"x" * 100)
        finally:
            web.UPLOAD_LIMIT = old
        self.assertEqual(code, 413)

    def test_the_decks_file_is_served_as_a_wav_for_the_page(self):
        code, got = self.post("api/upload?name=page.wav", self.wav_bytes())
        self.post("api/deck/2/load/57?bpm=120&audio=" + urllib.request.quote(got["path"]))
        with urllib.request.urlopen(self.base + "api/deck/2/audio.wav", timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("audio/wav", r.headers["Content-Type"])
            body = r.read()
        self.assertEqual(body[:4], b"RIFF")
        self.assertEqual(body, self.world.decks[2].audio.wav())
        self.world.clear_audio(self.world.decks[2])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "api/deck/2/audio.wav", timeout=10)
        self.assertEqual(caught.exception.code, 404)

    def test_the_page_gets_the_waveform(self):
        code, got = self.post("api/upload?name=wave.wav", self.wav_bytes())
        self.post("api/deck/2/load/58?bpm=120&audio=" + urllib.request.quote(got["path"]))
        with urllib.request.urlopen(self.base + "api/deck/2/waveform", timeout=10) as r:
            wave_info = json.loads(r.read().decode("utf-8"))
        self.assertEqual(wave_info["rate"], 100)
        self.assertEqual(len(wave_info["peaks"]), 46)                               # the 20000 frames of the file, 441 to a value
        self.assertTrue(all(0 <= v <= 100 for v in wave_info["peaks"]))
        self.assertTrue(wave_info["file"].endswith("x.wav") or wave_info["file"].endswith("wave.wav"))
        self.world.clear_audio(self.world.decks[2])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "api/deck/2/waveform", timeout=10)
        self.assertEqual(caught.exception.code, 404)

    def test_what_is_not_sound_is_refused_when_loaded(self):
        code, got = self.post("api/upload?name=notes.txt", b"this is not sound at all")
        code, said = self.post("api/deck/2/load/56?bpm=120&audio=" + urllib.request.quote(got["path"]))
        self.assertEqual(code, 400)
        self.assertIn("error", said)


if __name__ == "__main__":
    unittest.main()
