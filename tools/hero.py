#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Takes the hero picture of deckbench: its page with four decks playing, a mixer, another player heard on the link and some events, for the README and the website.

    hero.py [--out PNG] [--width 1400] [--height 1380] [--browser PATH]

It starts a bench of its own (on shifted ports, so a bench or rekordbox that is running does not matter), has a CDJ-2000NXS2 announce
itself on its link, puts them in a state worth showing, and takes a screenshot of the page with a headless Chrome or Edge. By default the picture is written where the website
keeps it, `../commitcollective.cc/public/deckbench/hero.png`. Run it again after the page's look changes, then commit the picture
in the website's repository.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from deckbench.protocols.prolink import header  # noqa: E402
from deckbench.testing import Bench, FakeUnit  # noqa: E402
import struct  # noqa: E402


class Player(FakeUnit):
    """A CDJ playing a rekordbox track from a USB stick, as the bench hears one: a status that has a track, a tempo and a beat."""

    def announce(self):
        from deckbench.protocols import startup
        mac = bytes((0x02, 0xFA, 0x4E, 0xDE, 0xC0, self.number))
        self.sock.sendto(startup.keepalive(self.name, self.number, self.address, mac), (self.broadcast, self.ports.announce))

    def beat(self, bpm=124.0, bar=1):
        """The packet a player sends on each beat, which moves the strip."""
        p = bytearray(0x60)
        p[:0x1F] = header(0x28, self.name)
        p[0x21] = self.number
        p[0x55:0x58] = bytes((0x10, 0x00, 0x00))
        p[0x5A:0x5C] = struct.pack(">H", int(round(bpm * 100)))
        p[0x5C] = bar
        self.sock.sendto(bytes(p), (self.broadcast, self.ports.beat))

    def status(self, bpm=124.0, started=None):
        beats = (time.time() - started) * bpm / 60.0
        p = bytearray(0x124)
        p[:0x1F] = header(0x0A, self.name)
        p[0x1F], p[0x20], p[0x21] = 0x01, 0x03, self.number
        p[0x22:0x24] = struct.pack(">H", len(p) - 0x24)
        p[0x24], p[0x27] = self.number, 1
        p[0x28], p[0x29], p[0x2A] = self.number, 3, 1                   # its own USB stick, a rekordbox track
        p[0x2C:0x30] = struct.pack(">I", 100 + self.number)
        p[0x7B] = 3                                                     # playing
        p[0x7C:0x80] = b"1.00"
        self.counter += 1
        p[0x84:0x88] = struct.pack(">I", self.counter)
        p[0x89] = 0x84 | 0x40 | 0x08                                    # playing, on air
        pitch = struct.pack(">I", 0x100000)
        for at in (0x8C, 0x98, 0xC0, 0xC4):
            p[at:at + 4] = pitch
        p[0x90:0x92] = struct.pack(">H", 0x8000)
        p[0x92:0x94] = struct.pack(">H", int(round(bpm * 100)))
        p[0x9D], p[0x9F] = 0x0D, 0xFF
        p[0xA0:0xA4] = struct.pack(">I", int(beats) + 1 + 180)
        p[0xA4:0xA6] = bytes((0x01, 0xFF))
        p[0xA6] = int(beats) % 4 + 1
        p[0xC8:0xCC] = struct.pack(">I", self.counter)
        p[0xCC] = 0x0F
        self.sock.sendto(bytes(p), (self.broadcast, self.ports.update))

SITE_HERO = os.path.join(ROOT, "..", "commitcollective.cc", "public", "deckbench", "hero.png")
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


def find_browser(given):
    for name in ([given] if given else BROWSERS):
        path = name if os.path.isfile(name) else shutil.which(name)
        if path:
            return path
    sys.exit("no Chrome or Edge found: name one with --browser")


def stage(bench):
    """The decks and the mixer in a state that shows what the bench does."""
    post = bench.post
    for n in (1, 2, 3, 4):
        post("api/deck/%d/tempo/126" % n)
    post("api/mixer/channel/4/fader_start/1")
    for channel, level in ((1, 100), (2, 100), (3, 70)):
        post("api/mixer/channel/%d/fader/%d" % (channel, level))
    post("api/deck/2/loop/4")
    # a few events for the list: a channel is opened, closed and opened again
    time.sleep(0.5)
    post("api/mixer/channel/4/fader/80")
    time.sleep(1.2)
    post("api/mixer/channel/4/fader/0")
    time.sleep(1.0)
    post("api/mixer/channel/4/fader/80")
    time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=SITE_HERO)
    ap.add_argument("--width", type=int, default=1400)
    ap.add_argument("--height", type=int, default=1380)
    ap.add_argument("--browser")
    args = ap.parse_args()
    browser = find_browser(args.browser)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    profile = tempfile.mkdtemp(prefix="deckbench-hero-")
    stop = threading.Event()
    try:
        with Bench(numbers=[1, 2, 3, 4], on=True, init={1: "play", 2: "play,master", 3: "play,sync", 4: "play,sync"},
                   args=["--mixer"]) as bench:
            player = Player(bench.ports, number=5, address="127.0.0.5", name=b"CDJ-2000NXS2")
            started = time.time()    # another player, heard on the link
            def play():
                last, ticks = -1, 0
                while not stop.is_set():
                    if ticks % 6 == 0:
                        player.announce()
                    player.status(bpm=124.0, started=started)
                    beat = int((time.time() - started) * 124.0 / 60.0)
                    if beat != last:
                        player.beat(bar=beat % 4 + 1)
                        last = beat
                    ticks += 1
                    stop.wait(0.05)

            threading.Thread(target=play, daemon=True).start()
            time.sleep(1.0)
            stage(bench)
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--user-data-dir=" + profile,
                            "--window-size=%d,%d" % (args.width, args.height), "--timeout=5000", "--screenshot=" + out,
                            bench.url + "#events"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    finally:
        stop.set()
        shutil.rmtree(profile, ignore_errors=True)
    if not os.path.isfile(out):
        sys.exit("the browser took no picture")
    print(out)


if __name__ == "__main__":
    main()
