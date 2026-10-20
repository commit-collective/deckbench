# SPDX-License-Identifier: MIT OR Apache-2.0
"""The command line: python -m deckbench [options]."""
import argparse
import json
import os
import socket
import sys
import threading
import time

from . import __version__
from .core import Deck, World, log
from .audio import AudioServer
from .events import Events
from .protocols.prolink import Ports, PortError, Prolink
from .scenario import Scenario, ScenarioError
from .web import serve


def broadcast_of(address, netmask):
    """The broadcast address of the network that `address` is on."""
    ip = int.from_bytes(socket.inet_aton(address), "big")
    mask = int.from_bytes(socket.inet_aton(netmask), "big")
    return socket.inet_ntoa(((ip & mask) | (~mask & 0xFFFFFFFF)).to_bytes(4, "big"))


def parse_loaded(items):
    loaded = {}
    for item in items:
        deck, rest = item.split("=")
        loaded[int(deck)] = tuple(int(x) for x in rest.split(":"))
    return loaded


def parse_titles(path):
    """Lines "SOURCE:SLOT:ID=Title" (UTF-8): {source: {(slot, id): title}}."""
    titles = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "=" in line and ":" in line.split("=")[0]:
                key, title = line.split("=", 1)
                source, slot, rbid = (int(x) for x in key.split(":"))
                titles.setdefault(source, {})[(slot, rbid)] = title
    return titles


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="deckbench",
        description="Simulated DJ decks on a network, for testing what talks to them. "
                    "Pro DJ Link: CDJs on 127.0.0.<number>, with a page and an API to drive them.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--decks", type=int, default=4, help="how many decks, numbered 1.. (default 4)")
    ap.add_argument("--numbers", metavar="N,N,...",
                    help="the decks' player numbers, instead of 1..DECKS")
    ap.add_argument("--on", action="store_true",
                    help="start the decks on (by default they are off, to switch on from the page)")
    ap.add_argument("--init", action="append", default=[], metavar="DECK=play,sync,master",
                    help="start this deck on, and playing, synced and/or the master "
                         "(loopN: and looping N beats from its start)")
    ap.add_argument("--loaded", action="append", default=[], metavar="DECK=SOURCE:SLOT:ID",
                    help="the track a deck has loaded: a track of the source player's database "
                         "(default: 100 + its number, from itself, slot 3)")
    ap.add_argument("--titles", metavar="FILE",
                    help='lines "SOURCE:SLOT:ID=Title" (UTF-8): the titles the decks know')
    ap.add_argument("--refuse-db", action="store_true",
                    help="the decks' database servers turn metadata requests down, as real decks "
                         "do those of a device that is not a player they know")
    ap.add_argument("--strict", action="store_true",
                    help="the decks behave as a CDJ-2000NXS2 or an XDJ-1000MK2 does: they serve the players 1 to 4 that "
                         "announced themselves and nobody else (a fifth device gets no answer, a unit that is not a "
                         "player has its requests turned down)")
    ap.add_argument("--audio-port", type=int, default=0, metavar="PORT",
                    help="serve the decks' sound (a drum loop in time with each playing deck) on this TCP port, as raw "
                         "stereo 16-bit 44.1 kHz samples in real time (default 0: none; 7320 is the emulator's)")
    ap.add_argument("--audio-decks", metavar="N,N,...", help="the decks that are heard (default all)")
    ap.add_argument("--scenario", metavar="FILE", help="play a scenario (see deckbench/scenario.py) once it runs")
    ap.add_argument("--then-exit", action="store_true",
                    help="with --scenario: leave when it is over, with status 1 if an expectation failed")
    ap.add_argument("--events", metavar="FILE", help="write what the device under test does to FILE, a JSON object a line")
    ap.add_argument("--model", help="the device name every deck announces (default CDJ-FAKEn)")
    ap.add_argument("--status-length", type=lambda x: int(x, 0), default=0x124, metavar="N",
                    help="the length of the Pro DJ Link status packets (default 0x124)")
    ap.add_argument("--bind", metavar="ADDRESS,ADDRESS,...",
                    help="a real network: the address of each deck, in the order of the "
                         "decks (aliases of a network card; see docs/real-network.md); "
                         "default the loopback, 127.0.0.<number>")
    ap.add_argument("--netmask", default="255.255.255.0", metavar="MASK",
                    help="the network's mask, to find its broadcast address from --bind "
                         "(default 255.255.255.0)")
    ap.add_argument("--broadcast", metavar="ADDRESS",
                    help="the network's broadcast address (default: from the first --bind "
                         "address and --netmask)")
    ap.add_argument("--port-shift", type=int, default=0, metavar="N",
                    help="move every port of the decks by N (UDP 50000-50002, TCP 12523 and 1051), to run beside "
                         "something that holds the real ones or where the system keeps them back. A unit on the real "
                         "ports does not hear them (default 0)")
    ap.add_argument("--ready-file", metavar="FILE",
                    help="once the decks and the page are up, write FILE: a JSON object with the page's address, the "
                         "ports and the process (a script starting the bench waits for it; GET /api/ready says the same)")
    ap.add_argument("--http-port", type=int, default=8750, metavar="PORT",
                    help="the page and API's port (default 8750, 0 for any, -1 for none)")
    ap.add_argument("--http-host", default="127.0.0.1", metavar="ADDRESS",
                    help="the address the page listens on (default 127.0.0.1)")
    a = ap.parse_args(argv)

    numbers = [int(x) for x in a.numbers.split(",")] if a.numbers else list(range(1, a.decks + 1))
    world = World()
    if a.events:
        world.events = Events(a.events)
    scenario = None
    if a.scenario:
        try:
            scenario = Scenario.load(a.scenario)
        except (OSError, ValueError, ScenarioError) as e:
            ap.error("--scenario: %s" % e)
    for i, n in enumerate(numbers):
        world.decks[n] = Deck(world, n, 128.0 - 2 * i, "deck %d" % n)
    addresses, broadcast = None, "127.255.255.255"
    if a.bind:
        given = a.bind.split(",")
        if len(given) != len(numbers):
            ap.error("--bind needs an address for each of the %d decks (%s), it has %d"
                     % (len(numbers), ",".join(map(str, numbers)), len(given)))
        addresses = dict(zip(numbers, given))
        broadcast = a.broadcast or broadcast_of(given[0], a.netmask)
    elif a.broadcast:
        broadcast = a.broadcast
    link = Prolink(world, loaded=parse_loaded(a.loaded),
                   titles=parse_titles(a.titles) if a.titles else None,
                   model=a.model, status_length=a.status_length,
                   addresses=addresses, broadcast=broadcast, refuse_db=a.refuse_db, strict=a.strict,
                   ports=Ports.shifted(a.port_shift))
    try:
        link.start()
    except PortError as e:
        ap.exit(2, "deckbench: %s\n" % e)
    world.info["strict"] = a.strict
    if a.audio_port:
        heard = {int(x) for x in a.audio_decks.split(",")} if a.audio_decks else None
        server = AudioServer(world, "127.0.0.1", a.audio_port, heard)
        log("sound on tcp://127.0.0.1:%d (raw stereo 16-bit 44.1 kHz)" % server.port)
        world.info["audio"] = "tcp://127.0.0.1:%d" % server.port
    log("broadcasting to %s" % broadcast)
    for n, deck in world.decks.items():
        wanted = [item.partition("=")[2] for item in a.init if int(item.partition("=")[0]) == n]
        if a.on or wanted:
            deck.enabled = True
        for what in wanted:
            deck.playing = "play" in what
            deck.sync = "sync" in what
            deck.master = "master" in what
            for word in what.split(","):
                if word.startswith("loop") and word[4:].isdigit():
                    deck.loop = (0.0, float(word[4:]))
    world.info.update(version=__version__, broadcast=broadcast, pid=os.getpid(), numbers=numbers,
                      ports={"announce": link.ports.announce, "beat": link.ports.beat, "update": link.ports.update,
                             "query": link.ports.query, "db": link.ports.db})
    server = serve(world, a.http_host, a.http_port) if a.http_port >= 0 else None
    if server:
        world.info["http"] = "http://%s:%d/" % (a.http_host, server.server_address[1])
    if a.ready_file:
        tmp = a.ready_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(world.info, f)
        os.replace(tmp, a.ready_file)               # it appears whole
    failed = []
    if scenario:
        def play():
            log("scenario %s: %d steps" % (scenario.name, len(scenario.steps)))
            for step, ok, message in scenario.run(world, log=log):
                if not ok:
                    failed.append((step, message))
            log("scenario %s: %s" % (scenario.name, "%d expectations failed" % len(failed) if failed else "done"))
            if a.then_exit:
                done.set()
        done = threading.Event()
        threading.Thread(target=play, daemon=True).start()
        if a.then_exit:
            done.wait()
            return 1 if failed else 0
    log("running; Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0
