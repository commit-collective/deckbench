# SPDX-License-Identifier: MIT OR Apache-2.0
"""The command line: python -m deckbench [options]."""
import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time

from . import __version__
from .core import Deck, World, log
from .adapters import make as make_adapter
from .audio import AudioServer
from .events import Events
from .profiles import PROFILES
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
    ap.add_argument("--scenario", action="append", default=[], metavar="FILE|FOLDER",
                    help="play a scenario (see docs/scenarios.md) once it runs. Again for more, or a folder for each .json "
                         "in it, in order (deckbench/examples/unit is a suite)")
    ap.add_argument("--then-exit", action="store_true",
                    help="with --scenario: leave when they are over, with status 1 if an expectation failed, else 3 if "
                         "one was skipped (its unit or adapter was not there), else 0")
    ap.add_argument("--adapter", action="append", default=[], metavar="NAME[:ARGS]",
                    help="what the device under test shows beyond the network, so a scenario can expect a lamp and press a "
                         "control (see deckbench/adapters). There is djs1000-emu[:HOST:PORT], the emulator's link "
                         "(default 127.0.0.1:7310)")
    ap.add_argument("--events", metavar="FILE", help="write what the device under test does to FILE, a JSON object a line")
    ap.add_argument("--model", help="the device name every deck announces (default CDJ-FAKEn)")
    ap.add_argument("--profile", choices=sorted(PROFILES), metavar="MODEL",
                    help="the model of player to stand in for: " + ", ".join(sorted(PROFILES)) + ". It sets the name the decks "
                         "announce, the length of their statuses and a byte of them (see deckbench/profiles.py)")
    ap.add_argument("--status-length", type=lambda x: int(x, 0), default=None, metavar="N",
                    help="the length of the Pro DJ Link status packets (default 0x124, or the profile's)")
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
    ap.add_argument("--claim", action="store_true",
                    help="a deck that comes on does what a player does first: three hellos and the three stages of claiming "
                         "its number (3.6 s), and only then its keep-alives. Without it the deck is there at once")
    ap.add_argument("--mixer", nargs="?", const="DJM-900NXS2", metavar="NAME",
                    help="a simulated DJM mixer, on from the start (NAME is what it announces, default DJM-900NXS2). It "
                         "reports which channels are on the air and can start the players with its faders")
    ap.add_argument("--mixer-address", metavar="ADDRESS",
                    help="the mixer's address (default 127.0.0.33 on the loopback, needed with --bind)")
    ap.add_argument("--mixer-channels", type=int, choices=(4, 6), default=4, help="the mixer's channels (default 4)")
    ap.add_argument("--exit-on-eof", action="store_true",
                    help="leave when standard input is closed: for a program that starts the bench and must not leave it "
                         "running if it dies (deckbench.testing.Bench does)")
    ap.add_argument("--ready-file", metavar="FILE",
                    help="once the decks and the page are up, write FILE: a JSON object with the page's address, the "
                         "ports and the process (a script starting the bench waits for it; GET /api/ready says the same)")
    ap.add_argument("--http-port", type=int, default=8750, metavar="PORT",
                    help="the page and API's port (default 8750, 0 for any, -1 for none)")
    ap.add_argument("--allow-origin", action="append", default=[], metavar="ORIGIN",
                    help="a page from this origin (https://commitcollective.cc) may use the API, with CORS. Pages of "
                         "other origins are refused: any web page can reach a bench on localhost otherwise. Repeat for more")
    ap.add_argument("--token", metavar="TOKEN",
                    help="the API wants this token (?token=... or Authorization: Bearer ...). `auto` makes one and says it")
    ap.add_argument("--http-host", default="127.0.0.1", metavar="ADDRESS",
                    help="the address the page listens on (default 127.0.0.1)")
    a = ap.parse_args(argv)

    numbers = [int(x) for x in a.numbers.split(",")] if a.numbers else list(range(1, a.decks + 1))
    adapters = []
    for spec in a.adapter:
        try:
            adapters.append((make_adapter(spec), spec))
        except ValueError as e:
            ap.error("--adapter: %s" % e)
    world = World()
    if a.events:
        world.events = Events(a.events)
    scenarios = []
    for path in a.scenario:
        files = sorted(os.path.join(path, f) for f in os.listdir(path) if f.endswith(".json")) \
            if os.path.isdir(path) else [path]
        for file in files:
            try:
                scenarios.append(Scenario.load(file))
            except (OSError, ValueError, ScenarioError) as e:
                ap.error("--scenario %s: %s" % (file, e))
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
    if a.bind and a.mixer and not a.mixer_address:
        ap.error("--mixer with --bind needs --mixer-address: an address of this machine, on that network")
    link = Prolink(world, loaded=parse_loaded(a.loaded),
                   titles=parse_titles(a.titles) if a.titles else None,
                   model=a.model, status_length=a.status_length,
                   addresses=addresses, broadcast=broadcast, refuse_db=a.refuse_db, strict=a.strict,
                   ports=Ports.shifted(a.port_shift), claim=a.claim, mixer_name=a.mixer or "DJM-900NXS2",
                   mixer_address=a.mixer_address, mixer_channels=a.mixer_channels, profile=a.profile)
    try:
        link.start()
    except PortError as e:
        ap.exit(2, "deckbench: %s\n" % e)
    if a.mixer and not link.mixer.set_on(True):
        ap.error("--mixer: the mixer cannot use %s" % link.mixer.address)
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
    for adapter, spec in adapters:
        world.adapters.append(adapter)
        adapter.start(world)
        log("adapter %s" % spec)
    world.info["profiles"] = {key: value["title"] for key, value in PROFILES.items()}
    world.info.update(version=__version__, adapters=[x.name for x in world.adapters], broadcast=broadcast, pid=os.getpid(), numbers=numbers,
                      ports={"announce": link.ports.announce, "beat": link.ports.beat, "update": link.ports.update,
                             "query": link.ports.query, "db": link.ports.db})
    token = a.token
    if token == "auto":
        token = secrets.token_urlsafe(12)
    if token and a.http_host in ("127.0.0.1", "localhost") and not a.allow_origin:
        log("the API wants a token: open the page as http://127.0.0.1:PORT/#token=%s" % token)
    elif token:
        log("the API wants a token: %s (open the page with #token=%s)" % (token, token))
    server = serve(world, a.http_host, a.http_port, a.allow_origin, token) if a.http_port >= 0 else None
    if server:
        world.info["http"] = "http://%s:%d/" % (a.http_host, server.server_address[1])
    if a.ready_file:
        tmp = a.ready_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(world.info, f)
        os.replace(tmp, a.ready_file)               # it appears whole
    outcomes = []                               # (scenario, "passed" | "failed" | "skipped", what)
    if scenarios:
        def play():
            for scenario in scenarios:
                failed = []
                log("scenario %s: %d steps" % (scenario.name, len(scenario.steps)))
                for step, ok, message in scenario.run(world, log=log):
                    if not ok:
                        failed.append((step, message))
                if scenario.skipped:
                    outcomes.append((scenario, "skipped", scenario.skipped))
                elif failed:
                    outcomes.append((scenario, "failed", "%d failed: %s" % (len(failed), "; ".join(m for _, m in failed))))
                else:
                    outcomes.append((scenario, "passed", ""))
                log("scenario %s: %s%s" % (scenario.name, outcomes[-1][1], ", " + outcomes[-1][2] if outcomes[-1][2] else ""))
            if len(scenarios) > 1:
                log("%d scenarios: %s" % (len(scenarios), ", ".join("%d %s" % (sum(1 for o in outcomes if o[1] == kind), kind)
                                                                    for kind in ("passed", "failed", "skipped"))))
            if a.then_exit:
                done.set()
        done = threading.Event()
        threading.Thread(target=play, daemon=True).start()
        if a.then_exit:
            done.wait()
            kinds = {o[1] for o in outcomes}
            return 1 if "failed" in kinds else 3 if "skipped" in kinds else 0
    if a.exit_on_eof:
        def watch():
            try:
                while sys.stdin.buffer.read(4096):
                    pass
            except (OSError, ValueError):
                pass
            log("standard input closed: leaving")
            os._exit(0)
        threading.Thread(target=watch, daemon=True).start()
    log("running; Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0
