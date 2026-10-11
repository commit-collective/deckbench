# SPDX-License-Identifier: MIT OR Apache-2.0
"""The command line: python -m deckbench [options]."""
import argparse
import socket
import time

from . import __version__
from .core import Deck, World, log
from .protocols.prolink import Prolink
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
    ap.add_argument("--http-port", type=int, default=8750, metavar="PORT",
                    help="the page and API's port (default 8750, 0 for any, -1 for none)")
    ap.add_argument("--http-host", default="127.0.0.1", metavar="ADDRESS",
                    help="the address the page listens on (default 127.0.0.1)")
    a = ap.parse_args(argv)

    numbers = [int(x) for x in a.numbers.split(",")] if a.numbers else list(range(1, a.decks + 1))
    world = World()
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
    Prolink(world, loaded=parse_loaded(a.loaded),
            titles=parse_titles(a.titles) if a.titles else None,
            model=a.model, status_length=a.status_length,
            addresses=addresses, broadcast=broadcast, refuse_db=a.refuse_db).start()
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
    if a.http_port >= 0:
        serve(world, a.http_host, a.http_port)
    log("running; Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
