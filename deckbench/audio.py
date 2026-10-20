# SPDX-License-Identifier: MIT OR Apache-2.0
"""Sound from the decks, for what listens to them: a sampler's input, a recorder, an ear.

Each playing deck is a simple drum loop in time with the deck: a kick on every beat, a hat between the beats and a higher
tick on the bar line, each deck with a pitch of its own so that they can be told apart. The loop follows the deck as it
plays: its tempo, its loop, a stop. It is made up of a few clicks, not a track, and there is nothing in it of anyone's
music.

`Mixer.block(frames, now)` gives that many stereo frames (16 bit, 44.1 kHz) for the moment `now`; `AudioServer` hands them
out in real time to whoever connects to a TCP port, as raw stereo 16-bit little-endian samples (what the DJS-1000 emulator's
`--input-tcp` takes). A deck that is off, stopped or unplugged is silent.
"""
import array
import math
import socket
import threading
import time

RATE = 44100
BLOCK = 441                              # frames a block of the stream: 10 ms


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
        mix = [0.0] * frames
        with self.world.lock:
            heard = [(d.number, d.position(now), d.tempo()) for d in self.world.decks.values()
                     if d.enabled and d.playing and not getattr(d, "unplugged", False)
                     and (self.numbers is None or d.number in self.numbers)]
        for number, position, tempo in heard:
            for i, x in enumerate(voice(number, position, tempo, frames)):
                mix[i] += x
        samples = array.array("h")
        for x in mix:
            v = int(max(-1.0, min(1.0, x)) * 32767)
            samples.append(v)
            samples.append(v)
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
