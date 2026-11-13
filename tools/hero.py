#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Takes the hero picture of deckbench: its page with three players on the link and one bench deck, for the README and the website.

    hero.py [--out PNG] [--width 1600] [--height 1060] [--browser PATH]

It starts a bench of its own (on shifted ports, so a bench or rekordbox that is running does not matter) with one deck. A CDJ-3000,
a CDJ-2000NXS2 and an XDJ-1000MK2 stand in for real players on its link: they announce themselves, report their status and beats,
and answer the database requests for their tracks' titles, waveforms and beat grids, as players do. Then it takes a screenshot of
the page with a headless Chrome or Edge. By default the picture is written where the website keeps it,
`../commitcollective.cc/public/deckbench/hero.png`. Run it again after the page's look changes, then commit the picture in the
website's repository.
"""
import argparse
import json
import math
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from deckbench import waveforms  # noqa: E402
from deckbench.protocols import startup  # noqa: E402
from deckbench.protocols.prolink import QUERY_PORT, header, num, read_message, string  # noqa: E402
from deckbench.testing import Bench  # noqa: E402

SITE_HERO = os.path.join(ROOT, "..", "commitcollective.cc", "public", "deckbench", "hero.png")
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]

# The players on the link: model, status length and nexus byte (profiles.py), their track and what they do.
PLAYERS = [
    dict(number=1, model=b"CDJ-3000", length=0x200, nexus=0x1F, rbid=211, bpm=126.0, title="Night Shift", artist="Lumen Park",
         seconds=372, start=161, state="playing", master=True, on_air=True),
    dict(number=2, model=b"CDJ-2000NXS2", length=0x124, nexus=0x0F, rbid=48, bpm=126.0, title="Hollow Signal", artist="Kessa",
         seconds=344, start=97, state="playing", synced=True, on_air=True),
    dict(number=3, model=b"XDJ-1000MK2", length=0x11B, nexus=0x0F, rbid=97, bpm=124.0, title="Paper Moons", artist="Odd Weather",
         seconds=318, start=33, state="cued"),
]


def track_shape(seconds, bpm, seed):
    """Detail heights (0 to 31, waveforms.RATE a second) of a made-up dance track: an intro, builds, drops and a
    breakdown, with a hit on each beat."""
    rng = random.Random(seed)
    beat = 60.0 / bpm
    plan = [(0.00, 0.35), (0.12, 0.6), (0.25, 0.95), (0.45, 0.4), (0.55, 0.7), (0.62, 1.0), (0.85, 0.55), (0.95, 0.25)]
    heights = bytearray()
    for i in range(int(seconds * waveforms.RATE)):
        t = i / waveforms.RATE
        where = t / seconds
        level = [lv for at, lv in plan if at <= where][-1]
        since = (t % beat) / beat
        hit = math.exp(-since * 6.0)
        bar = (t / (4 * beat)) % 8
        fill = 0.15 if bar > 7 and where < 0.95 else 0.0
        value = level * (0.45 + 0.45 * hit + fill) + rng.uniform(-0.06, 0.06)
        heights.append(max(1, min(31, int(round(value * 31)))))
    return heights


def envelope(name, width, columns):
    """An analysis tag as a player serves it (waveforms.envelope reads it)."""
    return b"\0\0\0\0" + name + struct.pack(">IIII", 24, 24 + len(columns), width, len(columns) // width) + b"\0" * 4 + columns


def detail_blob(heights):
    colour = 5 << 13 | 3 << 10 | 6 << 7
    return envelope(b"PWV5", 2, b"".join(struct.pack(">H", colour | h << 2) for h in heights))


def overview_blob(heights, columns=1200):
    out = bytearray()
    step = len(heights) / columns
    for c in range(columns):
        part = heights[int(c * step):int((c + 1) * step)] or b"\0"
        h = int(max(part) * 127 / 31)
        out += bytes((0, 0, 0, h // 2, h, h * 3 // 4))
    return envelope(b"PWV4", 6, bytes(out))


def grid_blob(seconds, bpm):
    beats = int(seconds * bpm / 60.0)
    return b"\0" * 20 + b"".join(struct.pack("<HHI", i % 4 + 1, int(bpm * 100), int(i * 60000 / bpm)) + b"\0" * 8
                                 for i in range(beats))


def blob_message(txid, kind, args):
    """A database message whose arguments may be blobs, as players answer the waveform requests."""
    tags, body = bytearray(12), b""
    for i, (k, v) in enumerate(args):
        tags[i] = 6 if k == "n" else 3
        body += num(v) if k == "n" else b"\x14" + struct.pack(">I", len(v)) + v
    return num(0x872349AE) + num(txid) + num(kind, 2) + num(len(args), 1) + b"\x14" + struct.pack(">I", 12) + bytes(tags) + body


def menu_item(txid, kind, value, text):
    tags = bytearray(12)
    args = [("n", 0), ("n", value), ("n", 2 * (len(text) + 1)), ("s", text), ("n", 2), ("s", " "), ("n", kind),
            ("n", 0), ("n", 0), ("n", 0), ("n", 0), ("n", 0)]
    body = b""
    for i, (k, v) in enumerate(args):
        tags[i] = 6 if k == "n" else 2
        body += num(v) if k == "n" else string(v)
    return num(0x872349AE) + num(txid) + num(0x4101, 2) + num(len(args), 1) + b"\x14" + struct.pack(">I", 12) + bytes(tags) + body


class Player:
    """A player on the bench's link: its keep-alives, status and beats, and a database server for its track."""

    def __init__(self, ports, spec):
        self.ports, self.spec = ports, spec
        self.number, self.name = spec["number"], spec["model"]
        self.address = "127.0.0.%d" % self.number
        self.mac = bytes((0x02, 0xFA, 0x4E, 0xDE, 0xC0, self.number))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind((self.address, 0))
        self.counter = 0
        self.started = time.time()
        heights = track_shape(spec["seconds"], spec["bpm"], self.number)
        self.blobs = {waveforms.tag("PWV4"): overview_blob(heights), waveforms.tag("PWV5"): detail_blob(heights)}
        self.grid = grid_blob(spec["seconds"], spec["bpm"])
        self.listeners = []
        self.db = socket.create_server((self.address, 0))
        self.listeners.append(self.db)
        for port in dict.fromkeys((QUERY_PORT, ports.query)):
            query = socket.create_server((self.address, port))
            self.listeners.append(query)
            threading.Thread(target=self.answer_port_queries, args=(query,), daemon=True).start()
        threading.Thread(target=self.serve, daemon=True).start()

    def beat_index(self):
        """The beat the player is at, counted from 0."""
        spec = self.spec
        if spec["state"] != "playing":
            return spec["start"]
        return spec["start"] + int((time.time() - self.started) * spec["bpm"] / 60.0)

    def announce(self):
        self.sock.sendto(startup.keepalive(self.name, self.number, self.address, self.mac), ("127.255.255.255", self.ports.announce))

    def beat(self):
        p = bytearray(0x60)
        p[:0x1F] = header(0x28, self.name)
        p[0x21] = self.number
        p[0x55:0x58] = bytes((0x10, 0x00, 0x00))
        p[0x5A:0x5C] = struct.pack(">H", int(round(self.spec["bpm"] * 100)))
        p[0x5C] = self.beat_index() % 4 + 1
        self.sock.sendto(bytes(p), ("127.255.255.255", self.ports.beat))

    def status(self):
        spec = self.spec
        playing = spec["state"] == "playing"
        p = bytearray(spec["length"])
        p[:0x1F] = header(0x0A, self.name)
        p[0x1F], p[0x20], p[0x21] = 0x01, 0x03, self.number
        p[0x22:0x24] = struct.pack(">H", len(p) - 0x24)
        p[0x24], p[0x27] = self.number, 1
        p[0x28], p[0x29], p[0x2A] = self.number, 3, 1                   # its own USB stick, a rekordbox track
        p[0x2C:0x30] = struct.pack(">I", spec["rbid"])
        p[0x7B] = 3 if playing else 6                                   # playing, or paused at the cue point
        p[0x7C:0x80] = b"1.00"
        self.counter += 1
        p[0x84:0x88] = struct.pack(">I", self.counter)
        p[0x89] = (0x84 | (0x40 if playing else 0) | (0x20 if spec.get("master") else 0)
                   | (0x10 if spec.get("synced") else 0) | (0x08 if spec.get("on_air") else 0))
        pitch = struct.pack(">I", 0x100000)
        for at in (0x8C, 0x98, 0xC0, 0xC4):
            p[at:at + 4] = pitch
        p[0x90:0x92] = struct.pack(">H", 0x8000)
        p[0x92:0x94] = struct.pack(">H", int(round(spec["bpm"] * 100)))
        p[0x9D], p[0x9F] = 0x0D, (0x00 if spec.get("master") else 0xFF)
        index = self.beat_index()
        p[0xA0:0xA4] = struct.pack(">I", index + 1)
        p[0xA4:0xA6] = bytes((0x01, 0xFF))
        p[0xA6] = index % 4 + 1
        if spec["nexus"] == 0x0F:
            p[0xC8:0xCC] = struct.pack(">I", self.counter)
        p[0xCC] = spec["nexus"]
        self.sock.sendto(bytes(p), ("127.255.255.255", self.ports.update))

    def answer_port_queries(self, query):
        while True:
            try:
                conn, _ = query.accept()
            except OSError:
                return
            with conn:
                conn.recv(64)
                conn.sendall(struct.pack(">H", self.db.getsockname()[1]))

    def serve(self):
        while True:
            try:
                conn, _ = self.db.accept()
            except OSError:
                return
            threading.Thread(target=self.session, args=(conn,), daemon=True).start()

    def session(self, conn):
        spec = self.spec
        stream = conn.makefile("rb")
        reader = type("R", (), {"recv": lambda _, n: stream.read(n)})()
        try:
            conn.recv(5)
            conn.sendall(num(1))
            while True:
                txid, kind, args = read_message(reader)
                if kind == 0x0000:                                      # the requester's number
                    conn.sendall(blob_message(txid, 0x4000, [("n", 0), ("n", self.number)]))
                elif kind == 0x2002:                                    # track metadata: three items follow
                    conn.sendall(blob_message(txid, 0x4000, [("n", 0x2002), ("n", 3)]))
                elif kind == 0x3000:
                    out = blob_message(txid, 0x4001, [("n", 1), ("n", 0)])
                    out += menu_item(txid, 0x04, spec["rbid"], spec["title"])
                    out += menu_item(txid, 0x07, 0, spec["artist"])
                    out += menu_item(txid, 0x0D, int(spec["bpm"] * 100), "")
                    conn.sendall(out + blob_message(txid, 0x4201, []))
                elif kind == waveforms.EXT:                             # the RGB overview and detail
                    data = self.blobs.get(args[2][1], b"")
                    conn.sendall(blob_message(txid, waveforms.EXT_REPLY,
                                              [("n", waveforms.EXT), ("n", 0), ("n", len(data)), ("b", data), ("n", 0)]))
                elif kind == waveforms.GRID:
                    conn.sendall(blob_message(txid, waveforms.GRID_REPLY,
                                              [("n", waveforms.GRID), ("n", 0), ("n", len(self.grid)), ("b", self.grid)]))
                elif kind == 0x0100:                                    # the end of the session
                    break
                else:
                    conn.sendall(blob_message(txid, 0x4003, []))
        except (EOFError, OSError, ValueError):
            pass
        conn.close()

    def close(self):
        for listener in self.listeners:
            listener.close()
        self.sock.close()


def find_browser(given):
    for name in ([given] if given else BROWSERS):
        path = name if os.path.isfile(name) else shutil.which(name)
        if path:
            return path
    sys.exit("no Chrome or Edge found: name one with --browser")


def devices_of(state):
    """The devices of the bench's state, wherever its link puts them."""
    if isinstance(state, dict):
        if isinstance(state.get("devices"), list):
            return state["devices"]
        for value in state.values():
            found = devices_of(value)
            if found is not None:
                return found
    return None


def wait_for_players(bench, timeout=30.0):
    """Until the bench has read every player's title and waveform."""
    deadline, players = time.time() + timeout, []
    while time.time() < deadline:
        players = [d for d in devices_of(bench.state()) or [] if d.get("kind") == "player"]
        if len(players) >= len(PLAYERS) and all((d.get("waveform") or {}).get("state") == "ready"
                                                and (d.get("metadata") or {}).get("title") for d in players):
            return
        time.sleep(0.5)
    print("not every player's track was read: %s" % json.dumps(
        [(d.get("number"), (d.get("waveform") or {}).get("state"), (d.get("metadata") or {}).get("title")) for d in players]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=SITE_HERO)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1060)
    ap.add_argument("--browser")
    args = ap.parse_args()
    browser = find_browser(args.browser)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    profile = tempfile.mkdtemp(prefix="deckbench-hero-")
    stop = threading.Event()
    players = []
    try:
        with Bench(numbers=[4], on=True, init={4: "play,sync"}) as bench:
            players = [Player(bench.ports, spec) for spec in PLAYERS]

            def run():
                last, ticks = {}, 0
                while not stop.is_set():
                    for player in players:
                        if ticks % 6 == 0:
                            player.announce()
                        player.status()
                        index = player.beat_index()
                        if player.spec["state"] == "playing" and last.get(player.number) != index:
                            player.beat()
                            last[player.number] = index
                    ticks += 1
                    stop.wait(0.05)

            threading.Thread(target=run, daemon=True).start()
            bench.post("api/deck/4/tempo/126")
            bench.post("api/deck/4/loop/4")
            wait_for_players(bench)
            time.sleep(1.0)
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--user-data-dir=" + profile,
                            "--window-size=%d,%d" % (args.width, args.height), "--timeout=6000", "--screenshot=" + out,
                            bench.url + "#events"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    finally:
        stop.set()
        for player in players:
            player.close()
        shutil.rmtree(profile, ignore_errors=True)
    if not os.path.isfile(out):
        sys.exit("the browser took no picture")
    print(out)


if __name__ == "__main__":
    main()
