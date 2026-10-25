# SPDX-License-Identifier: MIT OR Apache-2.0
"""Sound from the decks, for what listens to them: a sampler's input, a recorder, an ear.

Each playing deck is a simple drum loop in time with the deck: a kick on every beat, a hat between the beats and a higher
tick on the bar line, each deck with a pitch of its own so that they can be told apart. The loop follows the deck as it
plays: its tempo, its loop, a stop. It is made up of a few clicks, not a track, and there is nothing in it of anyone's
music. A deck can be given a track of its own instead, a sound file and the tempo it was made at (`Track`, `load_file`).

`Mixer.block(frames, now)` gives that many stereo frames (16 bit, 44.1 kHz) for the moment `now`; `AudioServer` hands them
out in real time to whoever connects to a TCP port, as raw stereo 16-bit little-endian samples (what the DJS-1000 emulator's
`--input-tcp` takes). A deck that is off, stopped or unplugged is silent.
"""
import array
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import wave

RATE = 44100
BLOCK = 441                              # frames a block of the stream: 10 ms
LONGEST = 30 * 60                        # seconds: a longer file is refused (it is all kept in memory)


class AudioError(ValueError):
    """A file that cannot be a deck's track: the message says why, to whoever asked."""


class Track:
    """A deck's track of its own: a sound file and the tempo it was made at (its source BPM, given by hand: nothing here finds the
    beats). The deck plays it at its own tempo as a CDJ does with the master tempo off, faster and higher or slower and lower,
    and its place in the file follows the deck's place in beats: a loop, a stop and a change of tempo carry it along.

    The deck's beat 0 is `offset` seconds into the file (a file that starts with a bar of silence has an offset)."""

    def __init__(self, path, left, right, bpm, offset=0.0):
        self.path = path
        self.left, self.right = left, right      # array('h'), 44.1 kHz
        self.bpm = float(bpm)
        self.offset = float(offset)
        self.frames = len(left)
        self._wav = None
        self._peaks = None

    @property
    def seconds(self):
        return self.frames / float(RATE)

    def peaks(self, per_second=100):
        """The loudness of the track, one value of 0 to 100 for each 1 / per_second of it (the largest sample of either side in that time,
        as a share of full scale): what the page draws as the waveform."""
        if self._peaks is None or self._peaks[0] != per_second:
            step = max(1, RATE // per_second)
            out = []
            for i in range(0, self.frames, step):
                loud = max(max(self.left[i:i + step]), -min(self.left[i:i + step]), max(self.right[i:i + step]), -min(self.right[i:i + step]))
                out.append(min(100, int(round(loud * 100 / 32767.0))))
            self._peaks = (per_second, out)
        return {"rate": per_second, "peaks": self._peaks[1]}

    def wav(self):
        """The track as a PCM WAV (16 bits, stereo, 44.1 kHz) in bytes: what the page fetches to play it (api/deck/N/audio.wav)."""
        if self._wav is None:
            both = array.array("h", bytes(4 * self.frames))
            both[0::2] = self.left
            both[1::2] = self.right
            if sys.byteorder == "big":
                both.byteswap()
            data = both.tobytes()
            head = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16, 1, 2, RATE, RATE * 4, 4, 16,
                               b"data", len(data))
            self._wav = head + data
        return self._wav

    def block(self, position, tempo, frames):
        """`frames` frames, as floats of -1 to 1 in two lists (left, right), for a deck that is at beat `position` and plays at `tempo`
        BPM. Silence before the file and after it."""
        ratio = tempo / self.bpm
        start = (self.offset + position * 60.0 / self.bpm) * RATE        # the frame of the file under the first frame of the block
        out_l, out_r = [0.0] * frames, [0.0] * frames
        scale, n = 1.0 / 32768.0, self.frames
        left, right = self.left, self.right
        if abs(ratio - 1.0) < 1e-3:                                      # at its own tempo: the frames as they are
            first = int(round(start))
            lo, hi = max(first, 0), min(first + frames, n)
            for i in range(lo, hi):
                out_l[i - first] = left[i] * scale
                out_r[i - first] = right[i] * scale
            return out_l, out_r
        for k in range(frames):
            x = start + k * ratio
            if x < 0.0:
                continue
            i = int(x)
            if i + 1 >= n:
                break
            f = x - i
            a, b = left[i], right[i]
            out_l[k] = (a + (left[i + 1] - a) * f) * scale
            out_r[k] = (b + (right[i + 1] - b) * f) * scale
        return out_l, out_r


def _pcm16(raw, width):
    """The samples of a PCM file's bytes as 16-bit integers (the high ones of a wider sample)."""
    if width == 2:
        out = array.array("h")
        out.frombytes(raw)
        if sys.byteorder == "big":
            out.byteswap()
        return out
    if width == 1:
        return array.array("h", [(v - 128) << 8 for v in raw])
    if width in (3, 4):
        count = len(raw) // width
        two = bytearray(count * 2)
        two[0::2] = raw[width - 2::width]
        two[1::2] = raw[width - 1::width]
        out = array.array("h")
        out.frombytes(bytes(two))
        if sys.byteorder == "big":
            out.byteswap()
        return out
    raise AudioError("samples of %d bytes are not supported" % width)


def _resample(samples, rate):
    """Linear interpolation of 16-bit samples from `rate` to 44.1 kHz (slow, in Python: ffmpeg does it when it is there)."""
    step = rate / float(RATE)
    n = int((len(samples) - 1) / step)
    out = array.array("h")
    for k in range(n):
        x = k * step
        i = int(x)
        out.append(int(samples[i] + (samples[i + 1] - samples[i]) * (x - i)))
    return out


def _split(samples, channels):
    """(left, right) from interleaved samples: a mono file is both, more than two channels are cut to two."""
    if channels == 1:
        return samples, samples
    return samples[0::channels], samples[1::channels]


def _read_wav(path):
    """(left, right, rate) of a PCM WAV file, or None if it is another kind of file."""
    try:
        with wave.open(path, "rb") as f:
            channels, width, rate, frames = f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getnframes()
            if frames > LONGEST * rate:
                raise AudioError("that file is longer than %d minutes" % (LONGEST // 60))
            raw = f.readframes(frames)
    except (wave.Error, EOFError):
        return None
    left, right = _split(_pcm16(raw, width), channels)
    return left, right, rate


def _read_ffmpeg(path):
    """(left, right, 44100) of any file that ffmpeg reads."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AudioError("that is not a PCM WAV file, and ffmpeg is not on the path to read it")
    run = subprocess.run([exe, "-v", "error", "-i", path, "-t", str(LONGEST), "-f", "s16le", "-ac", "2", "-ar", str(RATE), "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run.returncode or not run.stdout:
        raise AudioError("ffmpeg could not read it: %s" % (run.stderr.decode("utf-8", "replace").strip() or "no sound in it"))
    left, right = _split(_pcm16(run.stdout, 2), 2)
    return left, right, RATE


def load_file(path, bpm, offset=0.0):
    """The Track of a sound file made at `bpm`. A PCM WAV is read here, with no packages, and anything else (mp3, flac, a WAV of
    another rate when ffmpeg can be had) by ffmpeg."""
    if not bpm or float(bpm) <= 0:
        raise AudioError("a track needs its BPM (the tempo it was made at)")
    if not os.path.isfile(path):
        raise AudioError("no such file: %s" % path)
    got = _read_wav(path)
    if got and got[2] != RATE and shutil.which("ffmpeg"):
        got = None                                       # ffmpeg resamples far faster than this module does
    if got is None:
        got = _read_ffmpeg(path)
    left, right, rate = got
    if rate != RATE:
        left, right = _resample(left, rate), _resample(right, rate)
    if len(left) < 2:
        raise AudioError("there is no sound in that file")
    return Track(path, left, right, bpm, offset)


def _tone(freq, length, decay, rate=RATE):
    n = int(length * rate)
    return [math.sin(2 * math.pi * freq * i / rate) * math.exp(-i / (decay * rate)) for i in range(n)]


def _noise(length, decay, rate=RATE):
    n = int(length * rate)
    seed, out = 12345, []
    for i in range(n):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        out.append(((seed / 0x7FFFFFFF) * 2 - 1) * math.exp(-i / (decay * rate)))
    return out


_cache = {}


def sounds(number):
    """The samples of deck `number`: (kick, hat, tick), as lists of floats."""
    if number not in _cache:
        _cache[number] = (
            [x * 0.8 for x in _tone(48 + 9 * number, 0.16, 0.05)],
            [x * 0.18 for x in _noise(0.04, 0.010)],
            [x * 0.30 for x in _tone(1100 + 140 * number, 0.06, 0.012)],
        )
    return _cache[number]


def voice(number, start, tempo, frames, rate=RATE):
    """Mono samples (floats) of deck `number` for `frames` frames, beginning at the place `start` (in beats) of a deck that
    plays at `tempo` BPM. A kick on each beat, a hat on each half beat and a tick on each bar line (the beats of 0 to 3
    make a bar, as the bench counts them)."""
    out = [0.0] * frames
    per_beat = 60.0 / tempo * rate                       # frames a beat
    kick, hat, tick = sounds(number)
    longest = max(len(kick), len(hat), len(tick))
    first = int(math.floor(start - longest / per_beat))  # the first half beat that can still sound
    last = int(math.ceil(start + frames / per_beat))
    for half in range(first * 2, last * 2 + 1):
        beat = half / 2.0
        at = int(round((beat - start) * per_beat))       # where it begins in the block (negative: before it)
        layers = []
        if half % 2 == 0:
            layers.append(kick)
            if (half // 2) % 4 == 0:
                layers.append(tick)
        else:
            layers.append(hat)
        for sample in layers:
            lo, hi = max(at, 0), min(at + len(sample), frames)
            for i in range(lo, hi):
                out[i] += sample[i - at]
    return out


class Mixer:
    def __init__(self, world, numbers=None):
        self.world = world
        self.numbers = numbers               # the decks that are heard (None: all of them)

    def block(self, frames, now=None):
        """`frames` stereo frames for the moment `now`, as 16-bit little-endian bytes."""
        now = time.time() if now is None else now
        mix_l, mix_r = [0.0] * frames, [0.0] * frames
        with self.world.lock:
            heard = [(d.number, d.position(now), d.tempo(), getattr(d, "audio", None)) for d in self.world.decks.values()
                     if d.enabled and d.playing and not getattr(d, "unplugged", False)
                     and (self.numbers is None or d.number in self.numbers)]
        for number, position, tempo, track in heard:
            if track:                                  # a track of its own: the file, at the deck's tempo
                left, right = track.block(position, tempo, frames)
                for i in range(frames):
                    mix_l[i] += left[i]
                    mix_r[i] += right[i]
                continue
            for i, x in enumerate(voice(number, position, tempo, frames)):
                mix_l[i] += x
                mix_r[i] += x
        samples = array.array("h")
        for i in range(frames):
            samples.append(int(max(-1.0, min(1.0, mix_l[i])) * 32767))
            samples.append(int(max(-1.0, min(1.0, mix_r[i])) * 32767))
        return samples.tobytes()


class AudioServer:
    """The decks' sound, in real time, to each client of a TCP port."""

    def __init__(self, world, host="127.0.0.1", port=7320, numbers=None):
        self.mixer = Mixer(world, numbers)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        self.closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self.closed = True
        self.srv.close()

    def _accept(self):
        while not self.closed:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        step = BLOCK / RATE
        due = time.perf_counter()
        began = time.time()
        sent = 0
        try:
            while not self.closed:
                # the moment of this block, from the frames already sent: it follows the clock, not the sleeps
                now = began + sent / RATE
                conn.sendall(self.mixer.block(BLOCK, now))
                sent += BLOCK
                due += step
                wait = due - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                elif wait < -0.5:            # far behind (a stall): start over from now
                    due = time.perf_counter()
                    began, sent = time.time(), 0
        except OSError:
            pass
        finally:
            conn.close()
