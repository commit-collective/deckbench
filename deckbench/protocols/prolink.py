# SPDX-License-Identifier: MIT OR Apache-2.0
"""Pro DJ Link: the decks as CDJs on the network.

Each deck is on an address of its own. By default that is the loopback address
127.0.0.<player number> and its broadcasts go to 127.255.255.255, so that
everything stays on one machine (run it in the network namespace of the client:
in WSL for an emulator there). On a real network a deck is given an address of
the machine's (an alias of a network card; see docs/real-network.md) and the
network's broadcast address. A deck that is on

- broadcasts a keep-alive on UDP 50000 every 2 s, to 127.255.255.255;
- broadcasts a CDJ status on UDP 50002 every 200 ms: the track it has loaded
  (the player it came from, the slot, the type and the rekordbox ID), whether
  it plays, is synced, is the tempo master, its tempo, and while it hands the
  master role over to another player, which one;
- while it plays, broadcasts a beat packet on UDP 50001 at each beat of its
  tempo (its own, or the master's when it is synced);
- answers the database server: TCP 12523 gives the port (1051), where the
  greeting, the query context setup, a track metadata request and a render
  menu request are answered with the menu items of the track, whose title is
  the first string of the item of type 4;
- takes the tempo master role from a player that asks (a master hand-off
  request, UDP 50001), answering that it yields, and obeys the sync commands
  (sync on/off, become master) sent to it.

And it listens for the unit under test: a device whose name begins "DJS-"
(a Pioneer DJS-1000) is followed, to know when it is the tempo master and at
what tempo, so that a deck can take the role from it by asking, as a CDJ does.

A deck that is off sends nothing and closes the connections made to it.

The layouts are those of the public Pro DJ Link analysis (Deep Symmetry's
djl-analysis, Beat Link); docs/prolink.md has what is set, and what a unit was
found to need.
"""
import select
import random
import os
import socket
import struct
import threading
import time
import ipaddress

from ..core import Protocol, log

from .. import profiles
from ..net import share, interface_macs
from . import startup
from .mixer import LinkMixer, parse_on_air
from .monitor import Monitor
from .startup import MAGIC
BROADCAST = "127.255.255.255"
DB_PORT = 1051
QUERY_PORT = 12523
BEAT_PORT, UPDATE_PORT, ANNOUNCE_PORT = 50001, 50002, 50000


class PortError(OSError):
    """A port the decks need is taken, or not allowed to this program."""


class Ports:
    """The ports of the protocol. The real ones by default. `Ports.shifted(n)` moves them all by n, to run the bench
    beside something that holds the real ones, or where the system keeps them back (Windows can reserve
    UDP 50000-50059). A unit on the real ports does not hear decks on shifted ones."""

    def __init__(self, shift=0):
        self.shift = shift
        self.announce, self.beat, self.update = ANNOUNCE_PORT + shift, BEAT_PORT + shift, UPDATE_PORT + shift
        self.query, self.db = QUERY_PORT + shift, DB_PORT + shift

    @classmethod
    def shifted(cls, n):
        return cls(n)


DEFAULT_PORTS = Ports()
PITCH_NORMAL = 0x100000


def header(ptype, name):
    p = bytearray(0x1F)
    p[0:10] = MAGIC
    p[0x0A] = ptype
    p[0x0B:0x0B + len(name)] = name
    return p


# ---- the database server's fields -----------------------------------------

def num(v, size=4):
    return {1: b"\x0f", 2: b"\x10", 4: b"\x11"}[size] + v.to_bytes(size, "big")


def string(text):
    data = (text + "\0").encode("utf-16-be")
    return b"\x26" + struct.pack(">I", len(data) // 2) + data


def message(txid, mtype, args):
    """args: list of ('n', value) or ('s', text)."""
    tags = bytearray(12)
    body = b""
    for i, (kind, v) in enumerate(args):
        if kind == "n":
            tags[i] = 0x06
            body += num(v)
        else:
            tags[i] = 0x02
            body += string(v)
    return (num(0x872349AE) + num(txid) + num(mtype, 2) + num(len(args), 1)
            + b"\x14" + struct.pack(">I", 12) + bytes(tags) + body)


def read_exact(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def read_field(conn):
    tag = read_exact(conn, 1)[0]
    if tag in (0x0F, 0x10, 0x11):
        size = {0x0F: 1, 0x10: 2, 0x11: 4}[tag]
        return ("n", int.from_bytes(read_exact(conn, size), "big"))
    if tag == 0x14:
        length = struct.unpack(">I", read_exact(conn, 4))[0]
        return ("b", read_exact(conn, length))
    if tag == 0x26:
        length = struct.unpack(">I", read_exact(conn, 4))[0]
        return ("s", read_exact(conn, 2 * length).decode("utf-16-be").rstrip("\0"))
    raise ValueError("field tag %#x" % tag)


def read_message(conn):
    assert read_field(conn) == ("n", 0x872349AE), "no magic"
    txid = read_field(conn)[1]
    mtype = read_field(conn)[1]
    count = read_field(conn)[1]
    read_field(conn)                        # the tags
    args = [read_field(conn) for _ in range(count)]
    return txid, mtype, args


# ---- one deck on the network ------------------------------------------------

class LinkDeck:
    """What a deck is to Pro DJ Link, beside what it is (core.Deck)."""

    def __init__(self, net, deck, loaded, titles, model, address, broadcast, refuse_db=False, strict=False,
                 ports=DEFAULT_PORTS):
        self.net = net
        self.ports = ports
        self.refuse_db = refuse_db          # the database server turns requests down (as it does a stranger's)
        self.strict = strict                # answers only the players it knows, as a CDJ-2000NXS2 does (see session())
        self.deck = deck
        self.address = address              # the address it is on
        self.broadcast = broadcast          # where its broadcasts go
        self.source, self.slot, self.rbid = loaded
        self.titles = titles                # {(slot, id): title} this deck knows
        self.queries = []
        self.name = (model or "CDJ-FAKE%d" % deck.number).encode()
        self.handing_to = 0xFF              # while it hands the role over: to whom
        self.pending = False                # has asked the unit for the master role
        self.pending_peer = None
        self.pending_since = 0.0
        self.sync_number = 0
        self.counter = 0
        self.online = False                 # it has come onto the network (and claimed its number, if that is asked)
        self.alone = False                  # nothing else was on the network when it came online (a byte of its keep-alive)
        self.mac = bytes([0x02, 0xFA, 0x4E, 0xDE, 0xC0, deck.number])

    @property
    def number(self):
        return self.deck.number

    def keepalive(self):
        return startup.keepalive(self.name, self.number, self.address, self.mac, self.net.peer_count(), self.alone)

    def claim(self, sock):
        """What a player sends when it comes online, at 300 ms: three hellos, then the three stages of claiming its
        number. False if it was switched off or unplugged on the way."""
        steps = [startup.hello(self.name)] * 3
        steps += [startup.stage1(self.name, self.mac, n) for n in (1, 2, 3)]
        steps += [startup.stage2(self.name, self.address, self.mac, self.number, n) for n in (1, 2, 3)]
        steps += [startup.stage3(self.name, self.number, n) for n in (1, 2, 3)]
        log("%s comes online: claiming number %d" % (self.deck.name, self.number))
        for packet in steps:
            if not self.deck.enabled or self.deck.unplugged:
                return False
            self.send(sock, packet, (self.broadcast, self.ports.announce))
            time.sleep(0.3)
        return True

    def flags(self):
        # Bits 7 and 2 are set on a real player (the analysis does not explain
        # them); the unit's choice of the deck to sync to looks for playing +
        # synced + on air + bit 2 (flags & 0x5c == 0x5c), and it does not let go
        # of the master role to a deck without bit 7.
        deck = self.deck
        f = 0x84
        if deck.playing:
            f |= 0x40
        if deck.on_air if deck.on_air is not None else deck.playing:
            f |= 0x08                                    # on air: a mixer says so, and with none it is while it plays
        if deck.master:
            f |= 0x20
        # While it waits for the unit to hand the master role over, its status
        # says it is synced: the unit only hands over to a deck that is (its
        # SYNC switch is not touched).
        if deck.sync or self.pending:
            f |= 0x10
        return f

    def status(self):
        deck = self.deck
        p = bytearray(max(self.net.status_length, 0xD4))
        p[0:10] = MAGIC
        p[0x0A] = 0x0A
        p[0x0B:0x0B + len(self.name)] = self.name
        # The header a CDJ's status has after its name: 01, the subtype (03),
        # the player, and the number of bytes that follow (lenr).
        p[0x1F], p[0x20], p[0x21] = 0x01, 0x03, self.number
        p[0x22:0x24] = struct.pack(">H", len(p) - 0x24)
        p[0x24] = self.number
        p[0x27] = 1 if deck.playing else 0               # activity
        p[0x28], p[0x29], p[0x2A] = self.source, self.slot, 1
        p[0x2C:0x30] = struct.pack(">I", self.rbid)
        p[0x6F] = p[0x73] = 4                           # no USB or SD media to mount over NFS
        # playing (looping) / playing while CUE is held / paused on the cue point / paused elsewhere
        p[0x7B] = (7 if deck.cueing else 4 if deck.loop else 3) if deck.playing else 6 if deck.at_cue() else 5
        p[0x7C:0x80] = b"1.00"
        p[0x84:0x88] = struct.pack(">I", self.sync_number if self.net.sync_counter else 0)
        p[0x89] = self.flags()
        p[0x8B] = 0x7A if deck.playing else 0x7E
        pitch = struct.pack(">I", PITCH_NORMAL)
        for at in (0x8C, 0x98, 0xC0, 0xC4):              # the four copies of the pitch
            p[at:at + 4] = pitch
        p[0x90:0x92] = struct.pack(">H", 0x8000)         # a rekordbox track: its tempo counts
        p[0x92:0x94] = struct.pack(">H", int(round(deck.tempo() * 100)))
        p[0x94:0x98] = bytes((0x7F, 0xFF, 0xFF, 0xFF))   # no slip play
        p[0x9D] = 0x0D if deck.playing else 0x01         # forward, CDJ jog / paused
        p[0x9E] = 1 if deck.master else 0                # "master meaningful"
        p[0x9F] = self.handing_to
        p[0xA0:0xA4] = struct.pack(">I", int(deck.position(time.time())) + 1)   # the beat in the track
        p[0xA4:0xA6] = bytes((0x01, 0xFF))               # no cue point ahead
        p[0xA6] = deck.beat_in_bar
        p[0xB6] = 1                                     # compatibility flag, see prolink-go issue 11
        self.counter += 1
        p[0xC8:0xCC] = struct.pack(">I", self.counter)
        p[0xCC] = self.net.nexus                         # 0x0f for a nexus, 0x1f for a CDJ-3000 or an XDJ-XZ
        return bytes(p)

    def beat(self, position):
        """The beat packet at the beginning of the beat that `position` (in beats) is in."""
        deck = self.deck
        period = 60000.0 / deck.tempo()
        beat = int(position) % 4 + 1
        left = 5 - beat                                  # beats to the next bar line
        p = bytearray(0x60)
        p[0:0x1F] = header(0x28, self.name)
        p[0x1F], p[0x21], p[0x23] = 0x01, self.number, 0x3C
        for i, beats in enumerate((1, 2, left, 4, left + 4, 8)):
            p[0x24 + 4 * i:0x28 + 4 * i] = struct.pack(">I", int(period * beats))
        p[0x55:0x58] = struct.pack(">I", PITCH_NORMAL)[1:]
        p[0x5A:0x5C] = struct.pack(">H", int(round(deck.tempo() * 100)))
        p[0x5C] = beat
        p[0x5F] = self.number
        return bytes(p)

    # -- UDP --
    @property
    def silent(self):
        """The cable is pulled."""
        return self.deck.unplugged

    def send(self, sock, packet, addr):
        """A datagram, unless the cable is pulled, and unless the network loses it (World.loss)."""
        if self.deck.unplugged:
            return
        loss = self.net.world.loss
        if loss and random.random() < loss:
            return
        sock.sendto(packet, addr)
        if addr[0] != self.broadcast:                   # a broadcast comes back to the sockets that listen, a packet to one device does not
            self.net.monitor.feed(packet, self.address, addr[1], to=addr[0])

    def announce(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind((self.address, 0))
        last_status = 0.0
        last_keep = 0.0
        while True:
            now = time.time()
            if not self.deck.enabled or self.deck.unplugged:
                last_keep = last_status = 0.0
                self.online = False
                time.sleep(0.1)
                continue
            if not self.online:
                self.online = True
                self.alone = self.net.peer_count(exclude=self) == 0
                if self.net.claim and not self.claim(s):
                    continue
                last_keep = last_status = 0.0
                now = time.time()
            if now - last_keep >= 2.0:
                self.send(s, self.keepalive(), (self.broadcast, self.ports.announce))
                last_keep = now
            if now - last_status >= 0.2:
                with self.net.world.lock:
                    packet = self.status()
                for destination in self.net.status_destinations(self):
                    self.send(s, packet, (destination, self.ports.update))
                last_status = now
            time.sleep(0.05)

    def beats(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind((self.address, 0))
        deck = self.deck
        sent = None                         # the beat (counted from the anchor) last sent
        while True:
            if not (deck.enabled and deck.playing) or deck.unplugged:
                sent = None
                time.sleep(0.05)
                continue
            with self.net.world.lock:
                now = time.time()
                pos = deck.position(now)
                tempo = deck.tempo()
                beat = int(pos)
                due = (beat + 1 - pos) * 60.0 / tempo
                packet = self.beat(pos) if sent != beat else None
            if packet:
                self.send(s, packet, (self.broadcast, self.ports.beat))
                sent = beat
            time.sleep(min(max(due, 0.002), 0.02))

    def control(self):
        """Master hand-off requests and sync commands, sent to this deck."""
        s = share(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        s.bind((self.address, self.ports.beat))
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        out.bind((self.address, 0))
        self.net.listening()
        deck, world = self.deck, self.net.world
        while True:
            data, addr = s.recvfrom(2048)
            self.net.monitor.feed(data, addr[0], self.ports.beat, to=self.address)
            if not deck.enabled or deck.unplugged or len(data) < 0x25 or data[:10] != MAGIC:
                continue
            kind, sender = data[0x0A], data[0x21]
            if kind not in (0x26, 0x2A):
                log("%s: packet type %#04x from %d, %d bytes: %s"
                    % (deck.name, kind, sender, len(data), data[0x1F:].hex()))
            if kind == 0x26:                                     # master hand-off request
                with world.lock:
                    world.events.add("handoff_request", deck=deck.number, sender=sender, granted=bool(deck.master))
                    if not deck.master:
                        log("%s: hand-off request from %d, but it is not the master"
                            % (deck.name, sender))
                        continue
                    log("%s: yields the master role to %d" % (deck.name, sender))
                    self.handing_to = sender
                reply = header(0x27, self.name) + bytes([
                    0x01, 0x00, self.number, 0x00, 0x08, 0x00, 0x00, 0x00, self.number,
                    0x00, 0x00, 0x00, 0x01])
                self.send(out, bytes(reply), (addr[0], self.ports.beat))
                threading.Timer(4.0, self.cancel_handoff, args=(sender,)).start()
                world.changed()
            elif kind == 0x2A:                                   # a sync command
                command = data[0x2B] if len(data) > 0x2B else 0
                log("%s: sync command %#x from %d" % (deck.name, command, sender))
                world.events.add("sync_command", deck=deck.number, sender=sender, command=command)
                if command == 0x10:
                    world.set_sync(deck, True)
                elif command == 0x20:
                    world.set_sync(deck, False)
                elif command == 0x01:
                    world.set_master(deck, True)

    # -- the master role --
    def cancel_handoff(self, target):
        """Keep the role if the requester never confirms becoming master."""
        with self.net.world.lock:
            if self.handing_to != target:
                return
            self.handing_to = 0xFF
        self.net.world.changed()

    def finish_handoff(self, to=None):
        """The new master has confirmed taking the role."""
        deck = self.deck

        def change():
            if deck.master and self.handing_to != 0xFF and (to is None or to == self.handing_to):
                deck.master = False
                self.handing_to = 0xFF
                self.sync_number = self.net.next_sync_number()
                log("%s is no longer the master" % deck.name)
        self.net.world.settle(change)
        self.net.world.changed()

    def take_after_handoff(self, sync_number=None):
        """The unit's status names this deck as the next master: it is."""
        if not self.pending:
            return
        deck = self.deck

        def change():
            tempo = deck.tempo()
            self.pending = False
            self.pending_peer = None
            deck.base_bpm = tempo
            deck.master = True
            self.sync_number = max(self.sync_number, sync_number if sync_number is not None
                                   else self.net.unit.get("syncn", 0)) + 1
        self.net.world.settle(change)
        log("%s is now the master (handoff confirmed)" % deck.name)
        self.net.world.changed()

    def give_up(self):
        """Cancel an unanswered request without creating a second master."""
        with self.net.world.lock:
            if not self.pending or time.time() - self.pending_since < 3.0:
                return
            self.pending = False
            self.pending_peer = None
            self.net.world.events.add("handoff_timeout", deck=self.number)
        log("%s: master handoff timed out" % self.deck.name)
        self.net.world.changed()

    # -- TCP --
    def serve_port(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.address, self.ports.query))
        srv.listen(5)
        self.net.listening()
        while True:
            conn, _ = srv.accept()
            if not self.deck.enabled or self.deck.unplugged:
                conn.close()
                continue
            try:
                length = struct.unpack(">I", read_exact(conn, 4))[0]
                if read_exact(conn, length) == b"RemoteDBServer\0":
                    conn.sendall(struct.pack(">H", self.ports.db))
                    log("%s: told the database port" % self.deck.name)
            except (EOFError, OSError):
                pass
            conn.close()

    def serve_db(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.address, self.ports.db))
        srv.listen(5)
        self.net.listening()
        while True:
            conn, _ = srv.accept()
            if not self.deck.enabled or self.deck.unplugged:
                conn.close()
                continue
            threading.Thread(target=self.session, args=(conn,), daemon=True).start()

    def unknown_player(self, requester):
        """Strict: a device is only a player this deck knows if it announced itself with that number (the unit under test
        does, in player mode: in drum machine mode it has no number on the link, and the decks turn its requests down)."""
        if not self.strict:
            return False
        unit = self.net.unit
        return not (unit["number"] and requester == unit["number"])

    def session(self, conn):
        name = self.deck.name
        try:
            conn.sendall(read_exact(conn, 5))               # the greeting, echoed
            track = None
            while True:
                txid, mtype, args = read_message(conn)
                if mtype == 0x0000:                         # query context setup
                    requester = args[0][1]
                    self.net.world.events.add("db_connect", deck=self.number, requester=requester)
                    if self.strict and not 1 <= requester <= 4:
                        # A CDJ-2000NXS2 or an XDJ-1000MK2 serves the players 1 to 4 only: a device with any other
                        # number (a fifth one) gets no answer at all.
                        log("%s: no answer to device %d (strict: players 1 to 4 only)" % (name, requester))
                        self.net.world.events.add("db_ignored", deck=self.number, requester=requester)
                        break
                    conn.sendall(message(txid, 0x4000, [("n", 0), ("n", self.number)]))
                    log("%s: query context for device %d" % (name, requester))
                elif mtype == 0x2002 and (self.refuse_db or self.unknown_player(dmst_requester(args))):
                    # as it answers a device it does not know (a unit in drum machine mode is not a player)
                    log("%s: metadata request turned down" % name)
                    self.net.world.events.add("metadata_request", deck=self.number, requester=dmst_requester(args),
                                              rbid=args[1][1], answered=False)
                    conn.sendall(message(txid, 0x0100, []))
                elif mtype == 0x2002:                       # track metadata request
                    dmst, rbid = args[0][1], args[1][1]
                    slot = (dmst >> 8) & 0xFF
                    title = self.titles.get((slot, rbid))
                    log("%s: metadata for id %d slot %d from device %d: %s"
                        % (name, rbid, slot, dmst >> 24, title))
                    self.net.world.events.add("metadata_request", deck=self.number, requester=dmst >> 24, rbid=rbid,
                                              answered=title is not None, title=title)
                    self.queries.append(rbid)
                    track = (rbid, title)
                    count = 11 if title is not None else 0xFFFFFFFF
                    conn.sendall(message(txid, 0x4000, [("n", 0x2002), ("n", count)]))
                elif mtype == 0x3000 and track and track[1] is not None:   # render menu
                    rbid, title = track
                    out = message(txid, 0x4001, [("n", 1), ("n", 0)])
                    kinds = [0x04, 0x07, 0x02, 0x03, 0x0B, 0x0D, 0x0A, 0x23, 0x0F, 0x06, 0x01]
                    for kind in kinds:
                        text = title if kind == 0x04 else "item %02x" % kind
                        out += message(txid, 0x4101, [
                            ("n", 7), ("n", rbid), ("n", 2 * (len(text) + 1)), ("s", text),
                            ("n", 2), ("s", " "), ("n", kind), ("n", 0), ("n", 0),
                            ("n", 0), ("n", 0), ("n", 0)])
                    out += message(txid, 0x4201, [])
                    conn.sendall(out)
                else:
                    log("%s: unexpected message type %#x" % (name, mtype))
                    conn.sendall(message(txid, 0x4003, []))
        except (EOFError, OSError, ValueError, AssertionError):
            pass
        conn.close()


def dmst_requester(args):
    """The device that asks, in the first argument of a metadata request (its number is the first byte)."""
    return (args[0][1] >> 24) & 0xFF


# ---- the protocol -----------------------------------------------------------

class Prolink(Protocol):
    name = "prolink"

    def __init__(self, world, loaded=None, titles=None, model=None, status_length=None,
                 addresses=None, broadcast=BROADCAST, refuse_db=False, strict=False, ports=DEFAULT_PORTS,
                 claim=False, mixer_name=b"DJM-900NXS2", mixer_address=None, mixer_channels=4, profile=None):
        """world.decks must have the decks (core.Deck, by player number) already.
        loaded: {deck: (source player, slot, rekordbox id)}; titles: {source
        player: {(slot, id): title}}. A deck has by default the track 100 + its
        number, from itself, in slot 3 (USB), titled "Track of deck N". addresses:
        {deck: address} (default 127.0.0.<number>); broadcast: where the broadcasts
        go (default 127.255.255.255, that of the loopback). refuse_db: the database servers
        turn metadata requests down (as real decks do those of a device that is not a
        player they know). strict: the decks behave as a CDJ-2000NXS2 does: they answer the players 1 to 4 that announced
        themselves and nobody else (a fifth device gets no answer, a unit that is not a player has its requests turned down).
        profile: the model of player to stand in for (profiles.py: "cdj-2000nxs2", "xdj-1000mk2", "cdj-3000"...): the
        name the decks announce, the length of their status packets and a byte of them. `model` and `status_length`
        say it otherwise. ports: a Ports, the real ones by default. claim: a deck that comes online sends what a player does (three
        hellos and the three stages of claiming its number, 3.6 s) before its keep-alives, as real ones do, instead of
        being there at once. The mixer (off until it is switched on) is a DJM: its name, its address (default
        127.0.0.33) and its number of channels (4 or 6)."""
        self.world = world
        self.ports = ports
        self.claim = claim
        # Set when every socket that listens is bound (see listening()): a packet sent before is not lost for want of a listener.
        self.ready = threading.Event()
        self._bound = 0
        self._expected = 0
        self._bound_lock = threading.Lock()
        self.monitor = Monitor(self)         # a log of the packets heard, and the devices on the link
        self.defended = {}                  # (claimer's address, number): when it was last told that the number is in use
        self.mixer = LinkMixer(self, mixer_name if isinstance(mixer_name, bytes) else mixer_name.encode(), 33,
                               mixer_address, broadcast, mixer_channels)
        self.profile = ""
        self.status_length, self.nexus, self.sync_counter = 0x124, 0x0F, True
        if profile:
            self.apply_profile(profile, resize=status_length is None, rename=False)
        if status_length is not None:
            self.status_length = status_length
        self.unit = {"number": 0, "ip": None, "master": False, "bpm": None, "synced": False, "playing": False,
                     "on_air": False, "beat": 0, "seen": 0.0, "announced": 0.0}   # the unit under test
        loaded = dict(loaded or {})
        known = {n: {(3, 100 + n): "Track of deck %d" % n} for n in world.decks}
        for src, entries in (titles or {}).items():
            known.setdefault(src, {}).update(entries)
        self.decks = {}
        for n, deck in world.decks.items():
            self.decks[n] = LinkDeck(self, deck, loaded.get(n, (n, 3, 100 + n)),
                                     known.get(n, {}), model or (profiles.get(profile)["model"] if profile else None),
                                     (addresses or {}).get(n, "127.0.0.%d" % n), broadcast, refuse_db, strict, ports)
        physical = [link for link in self.decks.values()
                    if not ipaddress.ip_address(link.address).is_loopback]
        if physical:
            try:
                macs = interface_macs()
            except (OSError, ValueError, TimeoutError) as error:
                raise ValueError("could not read DJ adapter MAC addresses: %s" % error) from error
            for link in physical:
                if link.address not in macs:
                    raise ValueError("cannot find the adapter MAC for %s, use a configured Windows or Linux IPv4 address"
                                     % link.address)
                link.mac = macs[link.address]
        world.protocols.append(self)

    def status_destinations(self, link):
        """Keep loopback broadcast tests, unicast statuses to real peers."""
        if ipaddress.ip_address(link.address).is_loopback:
            return [link.broadcast]
        return sorted({device["ip"] for device in self.monitor.snapshot() if device["online"]})

    def check_ports(self):
        """Binds every port the decks need once, to say so at once if one cannot be had (the threads that serve
        them would die unseen). Raises PortError.

        It binds as the decks do: where sockets can share a port with SO_REUSEADDR (Linux, macOS) an emulator that
        listens on the same ports does not stop the bench, as it must not. Windows lets any socket that sets it take
        over a port, so there it binds without, and a program that holds the port (rekordbox does) is found."""
        share = os.name != "nt"
        wanted = [(socket.SOCK_DGRAM, link.address, self.ports.beat) for link in self.decks.values()]
        wanted += [(socket.SOCK_STREAM, link.address, port) for link in self.decks.values()
                   for port in (self.ports.query, self.ports.db)]
        wanted += [(socket.SOCK_DGRAM, "0.0.0.0", self.ports.announce), (socket.SOCK_DGRAM, "0.0.0.0", self.ports.update)]
        for kind, address, port in wanted:
            s = socket.socket(socket.AF_INET, kind)
            try:
                if share:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    if kind == socket.SOCK_DGRAM and hasattr(socket, "SO_REUSEPORT"):
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                s.bind((address, port))
            except OSError as e:
                raise PortError("%s %d on %s: %s. Something else holds it, or the system keeps it back "
                                "(on Windows: netsh interface ipv4 show excludedportrange protocol=udp). "
                                "--port-shift moves every port of the decks, for a bench beside it or for the tests."
                                % ("UDP" if kind == socket.SOCK_DGRAM else "TCP", port, address, e.strerror or e)) from e
            finally:
                s.close()

    def listening(self):
        """A thread of the bench has bound its socket and is about to listen on it. `ready` is set when all have."""
        with self._bound_lock:
            self._bound += 1
            if self._bound >= self._expected:
                self.ready.set()

    def start(self, wait=5.0):
        """Starts the threads, and waits (up to `wait` seconds) until every socket that listens is bound: what is sent from the moment
        this returns is heard."""
        self.check_ports()
        # the listeners: each deck's UDP socket for what is sent to it and its two TCP servers, the sniffer and the fader listener
        self._expected = 3 * len(self.decks) + 2
        for n, link in self.decks.items():
            deck = link.deck
            for target in (link.announce, link.beats, link.control, link.serve_port, link.serve_db):
                threading.Thread(target=target, daemon=True).start()
            log("%s on %s: track %d:%d:%d at %.0f BPM"
                % ((deck.name, link.address, link.source, link.slot, link.rbid, deck.base_bpm)))
        threading.Thread(target=self.sniff, daemon=True).start()
        threading.Thread(target=self.faders, daemon=True).start()
        threading.Thread(target=self.mixer.run, daemon=True).start()
        if wait:
            self.ready.wait(wait)

    def apply_profile(self, name, rename=True, resize=True, **_):
        """Stands in for another model of player (profiles.py): its name, the length of its statuses, its nexus byte and
        whether its sync counter counts."""
        profile = profiles.get(name)
        self.profile = name
        self.nexus, self.sync_counter = profile["nexus"], profile["sync_counter"]
        if resize:
            self.status_length = profile["status_length"]
        if rename:
            for link in self.decks.values():
                link.name = profile["model"].encode()
        log("the decks are now %s" % profile["title"])

    def peer_count(self, exclude=None, exclude_mixer=False):
        """The devices that are on the network, as the decks see it: the decks that are on and plugged in, the mixer if
        it is on, and the unit under test if it was heard in the last ten seconds."""
        count = sum(1 for link in self.decks.values() if link is not exclude and link.deck.enabled and not link.deck.unplugged)
        count += 1 if self.mixer.on and not exclude_mixer else 0
        count += sum(1 for device in self.monitor.snapshot() if device["online"])
        return count

    def align_synced(self, device, now):
        """A device that is the tempo master has told of a beat (see Monitor.beat): the bench's decks that are synced and play go to its
        grid, as a player does that syncs to it, and not only to its tempo. A deck is moved to the nearest place on the master's bar, by
        a jump of no more than two beats, and only when it is more than 20 ms out. Not while a deck of the bench is the master, and not
        a deck that loops (its place is its own)."""
        st, phase = device["status"], device.get("bar_phase") or device["phase"]
        if not (st and now - st["seen"] < 2.0 and st["master"] and st["play"]
                and phase and not device["ours"]):
            return
        world = self.world
        with world.lock:
            if world.master_deck() is not None:
                return
            t, pos, bpm = phase
            master = pos + (now - t) * bpm / 60.0
            moved = False
            for deck in world.decks.values():
                if not (deck.enabled and deck.playing and deck.sync and not deck.master and not deck.loop):
                    continue
                place = deck.position(now)
                target = master + 4 * round((place - master) / 4.0)
                if abs(place - target) * 60.0 / max(bpm, 1.0) > 0.02:
                    deck.anchor_t, deck.anchor_pos = now, target
                    moved = True
            if moved:
                world.changed()

    def mixer_gone(self):
        """The mixer was switched off: the decks are no longer told whether they are on air."""
        with self.world.lock:
            for deck in self.world.decks.values():
                deck.on_air = None

    def defend(self, number, claimer):
        """Another device claims or announces a number a deck of the bench is using: tell it so (type 0x08), as a player
        does, at most once a second."""
        for link in self.decks.values():
            if link.number != number or not link.deck.enabled or link.deck.unplugged or claimer == link.address:
                continue
            now = time.time()
            if now - self.defended.get((claimer, number), 0.0) < 1.0:
                return
            self.defended[(claimer, number)] = now
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.bind((link.address, 0))
                link.send(s, startup.in_use(link.name, number, link.address), (claimer, self.ports.announce))
            except OSError as e:
                log("%s could not defend its number against %s: %s" % (link.deck.name, claimer, e))
            finally:
                s.close()
            log("%s tells %s that number %d is in use" % (link.deck.name, claimer, number))
            self.world.events.add("number_defended", deck=number, claimer=claimer)

    def faders(self):
        """Fader start packets (type 0x02, broadcast on 50001, as a mixer sends them): a byte for each
        of the players 1 to 4, 0 start, 1 stop, 2 leave it."""
        s = share(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        s.bind(("", self.ports.beat))
        self.listening()
        while True:
            data, addr = s.recvfrom(2048)
            self.monitor.feed(data, addr[0], self.ports.beat)
            flags = parse_on_air(data)
            if flags is not None:
                with self.world.lock:
                    for channel, on in flags.items():
                        deck = self.world.decks.get(channel)
                        if deck and deck.on_air != on:
                            deck.on_air = on
                            self.world.events.add("on_air", deck=channel, on=on, sender=data[0x21])
                self.world.changed()
                continue
            if len(data) < 0x28 or data[:10] != MAGIC or data[0x0A] != 0x02:
                continue
            log("fader start from %d (%s): %s" % (data[0x21], data[0x0B:0x1F].rstrip(b"\0").decode("latin-1"),
                                                  data[0x24:0x28].hex()))
            for i in range(4):
                deck = self.world.decks.get(i + 1)
                if deck and deck.enabled and not deck.unplugged and data[0x24 + i] in (0, 1):
                    action = "start" if data[0x24 + i] == 0 else "stop"
                    self.world.set_play(deck, action == "start")
                    self.world.events.add("fader_start", deck=i + 1, action=action, sender=data[0x21])

    # -- what the World asks --
    def external_master_bpm(self):
        peer = self.external_master()
        if peer and 0 < peer["status"]["bpm"] < 655.35:
            return peer["status"]["bpm"]
        return None

    def external_master(self):
        """The freshest external player with a live master status."""
        now = time.time()
        with self.monitor.lock:
            peers = [dict(d) for d in self.monitor.devices.values()
                     if not d["ours"] and d["status"] and d["status"]["master"]
                     and now - d["status"]["seen"] < 2.0]
        return max(peers, key=lambda d: d["status"]["seen"]) if peers else None

    def next_sync_number(self):
        with self.monitor.lock:
            counters = [d["status"]["sync_counter"] for d in self.monitor.devices.values() if d["status"]]
        return (max(counters + [link.sync_number for link in self.decks.values()] + [0]) + 1) & 0xFFFFFFFF

    def peer_status(self, device, data):
        """Complete handoffs with any external player."""
        if device["ours"]:
            return
        with self.world.lock:
            for link in self.decks.values():
                if not link.deck.enabled or link.deck.unplugged:
                    continue
                if device["status"]["master"] and link.handing_to == device["number"]:
                    link.finish_handoff()
                if (link.pending and link.pending_peer == (device.get("packet_source", device["ip"]), device["number"])
                        and data[0x9F] == link.number):
                    link.take_after_handoff(device["status"]["sync_counter"])

    def describe(self, deck):
        link = self.decks.get(deck.number)
        if not link:
            return {}
        # The title of the track is in the database of the player it was loaded from.
        source = self.decks.get(link.source, link)
        return {"track": source.titles.get((link.slot, link.rbid), ""),
                "track_id": "%d:%d:%d" % (link.source, link.slot, link.rbid),
                "track_source": link.source, "track_slot": link.slot, "track_rbid": link.rbid,
                "model": link.name.decode(), "address": link.address}

    def info(self):
        return {"unit": dict(self.unit) if self.unit["number"] else None, "settings": self.settings(),
                "mixer": self.mixer.snapshot(), "devices": self.monitor.snapshot()}

    @staticmethod
    def truthy(value):
        return value in (True, 1, "1", "true", "on")

    def mixer_do(self, params):
        """What a scenario step or a POST to /api/mixer does: (ok, message)."""
        m = self.mixer
        if "on" in params and not m.set_on(self.truthy(params["on"])):
            return False, "the mixer cannot be on: its address (%s) is not this machine's" % m.address
        if "master" in params:
            m.set_master(self.truthy(params["master"]))
        if params.get("channel") is not None:
            try:
                channel = int(params["channel"])
            except (TypeError, ValueError):
                channel = 0
            if channel not in m.channels:
                return False, "no channel %s (the mixer has 1 to %d)" % (params["channel"], len(m.channels))
            if "fader" in params:
                try:
                    m.set_fader(channel, float(params["fader"]))
                except (TypeError, ValueError):
                    return False, "a fader is a number from 0 to 100"
            if "fader_start" in params:
                m.set_fader_start(channel, self.truthy(params["fader_start"]))
            if "command" in params:
                if params["command"] not in ("start", "stop"):
                    return False, "a command is start or stop"
                if not m.send_fader_start({channel: params["command"]}):
                    return False, "the mixer is off"
        return True, ""

    def action(self, name, params):
        if name == "mixer":
            return self.mixer_do(params)
        return None

    def handle_api(self, parts, query):
        """POST /api/mixer/on/1, /master/0, /channel/2/fader/70, /channel/2/fader_start/1, /channel/2/command/start."""
        if parts[0] != "mixer":
            return None
        rest = parts[1:]
        if len(rest) == 2 and rest[0] in ("on", "master"):
            params = {rest[0]: rest[1]}
        elif len(rest) == 4 and rest[0] == "channel" and rest[2] in ("fader", "fader_start", "command"):
            params = {"channel": rest[1], rest[2]: rest[3]}
        else:
            return 404, {"error": "no such mixer control"}
        ok, why = self.mixer_do(params)
        return (200, {}) if ok else (400, {"error": why})

    def unit_state(self):
        u = self.unit
        if not u["number"]:
            return {"heard": False}
        state = {"heard": True}
        for key in ("number", "ip", "master", "synced", "playing", "on_air", "beat", "bpm", "track_bpm", "pitch"):
            if u.get(key) is not None:
                state[key] = u[key]
        if "pitch" in state:
            state["pitch_percent"] = round((state["pitch"] / PITCH_NORMAL - 1) * 100, 2)
        state["age"] = round(time.time() - u["seen"], 2) if u["seen"] else None
        return state

    def allow_enable(self, deck):
        for device in self.monitor.snapshot():
            if device["online"] and device["number"] == deck.number:
                log("%s: player number already used by %s at %s" %
                    (deck.name, device["name"], device["ip"]))
                return False
        # A deck with the unit's own number is a clash: the unit then links to no deck at all.
        if self.unit["number"] == deck.number:
            log("%s has the number of the unit under test: left off (a clash makes the unit "
                "link to no deck)" % deck.name)
            return False
        return True

    def deck_enabled(self, deck, on):
        link = self.decks.get(deck.number)
        if link and not on:
            link.handing_to = 0xFF
            link.pending = False
            link.pending_peer = None

    def master_released(self, deck):
        link = self.decks.get(deck.number)
        if link:
            link.handing_to = 0xFF
            link.pending = False
            link.pending_peer = None

    def track_loaded(self, deck, rbid, title, source=None, slot=None):
        link = self.decks.get(deck.number)
        if not link:
            return
        if slot is not None:
            link.slot = int(slot)
        link.source, link.rbid = (deck.number if source is None else int(source)), rbid
        origin = self.decks.get(link.source, link)          # the title is in the database of the player it comes from
        key = (link.slot, rbid)
        if title is not None:
            origin.titles[key] = title
        elif key not in origin.titles:
            origin.titles[key] = "Track %d" % rbid

    def settings(self):
        links = list(self.decks.values())
        return {"strict": any(l.strict for l in links), "refuse_db": any(l.refuse_db for l in links),
                "claim": self.claim, "mixer": self.mixer.on, "profile": self.profile,
                "model": links[0].name.decode() if len({l.name for l in links}) == 1 else ""}

    def set_option(self, name, value):
        if name == "profile":
            if value in ("", "default"):
                self.profile = ""
                self.nexus, self.sync_counter, self.status_length = 0x0F, True, 0x124
                for link in self.decks.values():
                    link.name = ("CDJ-FAKE%d" % link.number).encode()
                log("the decks are CDJ-FAKEn again")
                return True
            if value in profiles.PROFILES:
                self.apply_profile(value)
                return True
            return False
        if name == "claim" and value in ("0", "1", 0, 1, True, False):
            self.claim = str(value) in ("1", "True")
            log("a deck that comes online %s" % ("claims its number first" if self.claim else "is there at once"))
            return True
        if name == "mixer" and value in ("0", "1", 0, 1, True, False):
            return self.mixer.set_on(str(value) in ("1", "True"))
        if name in ("strict", "refuse_db") and value in ("0", "1", 0, 1, True, False):
            for link in self.decks.values():
                setattr(link, name, str(value) in ("1", "True"))
            log("%s %s" % (name.replace("_", "-"), "on" if self.settings()[name] else "off"))
            return True
        if name == "model" and isinstance(value, str) and value.strip() and len(value.strip().encode()) <= 20:
            for link in self.decks.values():
                link.name = value.strip().encode()
            log("the decks now announce themselves as %s" % value.strip())
            return True
        return False

    def take_master(self, deck):
        link = self.decks.get(deck.number)
        if not link:
            return False
        world = self.world

        def change():
            # The role is a deck's, if one has it (the unit's own flag can be a
            # stale one: it does not always let go): pass it on between decks.
            # Only when none has it, the unit might.
            deck_master = any(o is not deck and o.enabled and o.master
                              for o in world.decks.values())
            peer = self.external_master()
            if peer and not deck_master:
                # The unit has the role: ask it (to port 50001), and take the
                # role when its status names this deck as the one to get it
                # (Mh): see LinkDeck.take_after_handoff().
                request = header(0x26, link.name) + bytes([
                    0x01, 0x00, link.number, 0x00, 0x04, 0x00, 0x00, 0x00, link.number])
                if link.pending:
                    return
                link.pending = True
                link.pending_peer = (peer["ip"], peer["number"])
                link.pending_since = time.time()
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.bind((link.address, 0))
                        link.send(s, bytes(request), (peer["ip"], self.ports.beat))
                except OSError:
                    link.pending = False
                    link.pending_peer = None
                    raise
                log("%s asks player %s to yield the master role" % (deck.name, peer["number"]))
                threading.Timer(3.0, link.give_up).start()
                return
            for other in world.decks.values():
                if other is not deck and other.enabled and other.master:
                    olink = self.decks.get(other.number)
                    if olink:
                        olink.handing_to = deck.number
                        threading.Timer(1.0, olink.finish_handoff, args=(deck.number,)).start()
                    else:
                        other.master = False
            deck.master = True
            link.sync_number += 1
        world.settle(change)
        if not link.pending:
            log("%s is now the master" % deck.name)
            world.changed()
        return True

    # -- the unit under test --
    def sniff(self):
        """Listens to the keep-alives and statuses on the network for the unit
        (it names itself DJS-1000): its number and address, and whether it is
        the tempo master and at what tempo; and passes the master role when the
        unit takes it from a deck that has agreed to yield it."""
        socks = []
        for port in (self.ports.announce, self.ports.update):
            s = share(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            s.bind(("0.0.0.0", port))
            s.settimeout(0.5)
            socks.append((s, port))
        # What the unit sends to a deck itself (its status, to port 50002 of the
        # deck's address) goes to the socket bound to that address, not to the
        # ones bound to any address: a socket for each deck.
        for link in self.decks.values():
            s = share(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            s.bind((link.address, self.ports.update))
            s.settimeout(0.5)
            socks.append((s, self.ports.update))
        self.listening()
        world, unit = self.world, self.unit
        while True:
            ready, _, _ = select.select([s for s, _ in socks], [], [], 0.5)
            for s in ready:
                data, addr = s.recvfrom(2048)
                bound = s.getsockname()
                port = bound[1]
                self.monitor.feed(data, addr[0], port, to="*" if bound[0] == "0.0.0.0" else bound[0])
                if len(data) < 0x30 or data[:10] != MAGIC:
                    continue
                if port == self.ports.announce and startup.claimed_number(data) is not None:
                    self.defend(startup.claimed_number(data), addr[0])
                if not (data[0x0B:0x0F] == b"DJS-" or data[0x0C:0x10] == b"DJS-"):
                    continue
                with world.lock:
                    if port == self.ports.announce and data[0x0A] == 0x06:
                        if unit["number"] != data[0x24]:
                            unit["number"] = data[0x24]
                            log("the unit under test is player %d" % data[0x24])
                            world.events.add("unit_seen", number=data[0x24])
                        unit["ip"] = ".".join(str(b) for b in data[0x2C:0x30])
                        unit["announced"] = time.time()
                    elif port == self.ports.update and data[0x0A] == 0x0A and len(data) >= 0xA7:
                        master = bool(data[0x89] & 0x20)
                        unit["syncn"] = struct.unpack(">I", data[0x84:0x88])[0]
                        seen = (data[0x89], data[0x9E], data[0x9F], unit["syncn"])
                        if seen != unit.get("flags"):
                            unit["flags"] = seen
                            log("the unit's status: flags %#04x, master meaningful %d, hand-off to "
                                "%#04x, sync counter %d" % seen)
                        if master != unit["master"]:
                            log("the unit under test %s the tempo master"
                                % ("is now" if master else "is no longer"))
                            world.events.add("unit_master", on=master)
                        unit["master"] = master
                        unit["seen"], unit["beat"] = time.time(), data[0xA6]
                        for key, bit, kind in (("playing", 0x40, "unit_play"), ("synced", 0x10, "unit_sync"),
                                               ("on_air", 0x08, None)):
                            value = bool(data[0x89] & bit)
                            if value != unit[key] and kind:
                                world.events.add(kind, on=value)
                            unit[key] = value
                        # The BPM field is the track's; the tempo it plays at is that
                        # times the pitch (0x100000 is no change), as on a CDJ.
                        unit["track_bpm"] = struct.unpack(">H", data[0x92:0x94])[0] / 100.0
                        unit["pitch"] = struct.unpack(">I", data[0x8C:0x90])[0]
                        unit["bpm"] = round(unit["track_bpm"] * unit["pitch"] / PITCH_NORMAL, 2)
                        tempo = (unit["track_bpm"], unit["pitch"])
                        if tempo != unit.get("tempo"):
                            unit["tempo"] = tempo
                            log("the unit's tempo: track %.2f BPM, pitch %#x: %.2f BPM"
                                % (tempo + (unit["bpm"],)))
                        if master:
                            for link in self.decks.values():
                                if link.deck.master and link.handing_to == data[0x21]:
                                    link.finish_handoff()
                world.changed()
