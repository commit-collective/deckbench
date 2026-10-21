# SPDX-License-Identifier: MIT OR Apache-2.0
"""A DJM mixer on the link: a device that announces itself as a mixer, tells the players which channels are on the air,
and starts and stops them with its faders (the "fader start" feature).

It is what a DJS-1000 or a player sees of a mixer, and what the unit's choice of the deck to sync to depends on (the
status flags of a deck say whether it is on air).

    on air         type 0x03 to the broadcast address, UDP 50001, several times a second. A byte for each channel
                   (0 off the air, 1 on): the channels 1 to 4 at 0x24, and for a six channel mixer 5 and 6 at 0x2d.
    fader start    type 0x02 to the same port: a byte for each of the players 1 to 4, 0 start, 1 stop, 2 leave it.

A channel is on the air while the mixer's master is on and its fader is open (above 0). With fader start on for a
channel, opening its fader tells its player to start and closing it, to stop. The packets are those of Deep Symmetry's
analysis (mixer_integration.html) and of Beat Link's `VirtualCdj`.
"""
import random
import socket
import threading
import time

from . import startup
from ..core import log

ON_AIR, FADER_START = 0x03, 0x02


def control_packet(ptype, name, number, payload):
    """A control packet (type 0x02, 0x03...): the magic, the type, the name from 0x0b, then 01 00, the sender's
    number, 00, and the payload, whose length is at 0x23."""
    p = bytearray(0x24 + len(payload))
    p[0:10] = startup.MAGIC
    p[0x0A] = ptype
    p[0x0B:0x0B + len(name)] = name
    p[0x1F], p[0x20], p[0x21], p[0x22] = 0x01, 0x00, number, 0x00
    p[0x23] = len(payload)
    p[0x24:0x24 + len(payload)] = payload
    return bytes(p)


def on_air_packet(name, number, flags, six=False):
    """`flags`: {channel: bool}. The six channel packet has its own subtype (03) and length (0x11)."""
    if six:
        payload = bytearray(0x11)
        for channel, on in flags.items():
            if 1 <= channel <= 4:
                payload[channel - 1] = 1 if on else 0
            elif channel in (5, 6):
                payload[channel + 4] = 1 if on else 0           # 0x2d and 0x2e
        payload[12] = 0x30
        p = bytearray(control_packet(ON_AIR, name, number, bytes(payload)))
        p[0x20] = 0x03
        return bytes(p)
    payload = bytearray(9)
    for channel, on in flags.items():
        if 1 <= channel <= 4:
            payload[channel - 1] = 1 if on else 0
    return control_packet(ON_AIR, name, number, bytes(payload))


def fader_start_packet(name, number, commands):
    """`commands`: {player: "start" | "stop"} (the others are told to stay as they are)."""
    payload = bytearray([2, 2, 2, 2])
    for player, what in commands.items():
        if 1 <= player <= 4:
            payload[player - 1] = 0 if what == "start" else 1
    return control_packet(FADER_START, name, number, bytes(payload))


def parse_on_air(data):
    """{channel: bool} from an on-air packet, or None if it is not one."""
    if len(data) < 0x2D or data[:10] != startup.MAGIC or data[0x0A] != ON_AIR:
        return None
    flags = {i + 1: bool(data[0x24 + i]) for i in range(4)}
    if len(data) >= 0x2F and data[0x20] == 0x03:
        flags.update({5: bool(data[0x2D]), 6: bool(data[0x2E])})
    return flags


class LinkMixer:
    """The mixer's state, and the thread that keeps it on the network (while it is on)."""

    def __init__(self, net, name=b"DJM-900NXS2", number=33, address=None, broadcast="127.255.255.255", channels=4):
        self.net = net
        self.name = name
        self.number = number
        self.address = address or "127.0.0.%d" % number
        self.broadcast = broadcast
        self.six = channels == 6
        self.on = False
        self.master = True                              # the master level is up: channels can be on the air
        self.channels = {n: {"fader": 0, "fader_start": False} for n in range(1, channels + 1)}
        self.mac = bytes([0x02, 0xFA, 0x4E, 0xDE, 0xC1, number])
        self.alone = False
        self.changed = threading.Event()
        self.sock = None

    # -- what it says --
    def on_air(self, channel):
        entry = self.channels.get(channel)
        return bool(self.on and self.master and entry and entry["fader"] > 0)

    def flags(self):
        return {n: self.on_air(n) for n in self.channels}

    def snapshot(self):
        return {"on": self.on, "name": self.name.decode(), "number": self.number, "address": self.address,
                "master": self.master, "six": self.six,
                "channels": {str(n): {"fader": c["fader"], "fader_start": c["fader_start"], "on_air": self.on_air(n)}
                             for n, c in self.channels.items()}}

    # -- what is done to it --
    def set_on(self, on):
        """Switches it on or off. False if it cannot be on: its address is not one of this machine's."""
        on = bool(on)
        if on == self.on:
            return True
        if on:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.bind((self.address, 0))
            except OSError as e:
                log("the mixer cannot use %s (%s). Give --mixer-address an address of this machine" % (self.address, e))
                return False
            finally:
                probe.close()
            self.alone = self.net.peer_count(exclude_mixer=True) == 0
        self.on = on
        log("the mixer %s is %s" % (self.name.decode(), "on" if on else "off"))
        if not on:
            self.net.mixer_gone()
        self.changed.set()
        return True

    def set_master(self, on):
        self.master = bool(on)
        self.changed.set()

    def set_fader(self, channel, level):
        """Moves a channel's fader (0 to 100). With fader start on for it, opening it starts the player and closing it
        stops it."""
        entry = self.channels[channel]
        level = max(0, min(100, int(level)))
        was_open, now_open = entry["fader"] > 0, level > 0
        entry["fader"] = level
        if self.on and entry["fader_start"] and was_open != now_open:
            self.send_fader_start({channel: "start" if now_open else "stop"})
        self.changed.set()

    def set_fader_start(self, channel, on):
        self.channels[channel]["fader_start"] = bool(on)

    def send_fader_start(self, commands):
        """Tells players to start or stop: {player: "start" | "stop"}."""
        if not self.on:
            return False
        log("the mixer tells %s" % ", ".join("player %d to %s" % (p, c) for p, c in sorted(commands.items())))
        self.send(fader_start_packet(self.name, self.number, commands), self.net.ports.beat)
        return True

    # -- the network --
    def send(self, packet, port):
        loss = self.net.world.loss
        if self.sock is None or (loss and random.random() < loss):
            return
        self.sock.sendto(packet, (self.broadcast, port))

    def keepalive(self):
        return startup.keepalive(self.name, self.number, self.address, self.mac, self.net.peer_count(), self.alone,
                                 kind=startup.MIXER)

    def claim(self):
        """The startup sequence, at 300 ms: hello, then the three stages of claiming its number."""
        steps = [startup.hello(self.name, startup.MIXER)] * 3
        steps += [startup.stage1(self.name, self.mac, n, startup.MIXER) for n in (1, 2, 3)]
        steps += [startup.stage2(self.name, self.address, self.mac, self.number, n, startup.MIXER) for n in (1, 2, 3)]
        steps += [startup.stage3(self.name, self.number, n) for n in (1, 2, 3)]
        for packet in steps:
            if not self.on:
                return False
            self.send(packet, self.net.ports.announce)
            time.sleep(0.3)
        return True

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.sock.bind((self.address, 0))
        except OSError as e:
            log("the mixer cannot use %s (%s): it stays off. Give --mixer-address an address of this machine" % (self.address, e))
            self.sock = None
            return
        last_keep = last_air = 0.0
        was_on = False
        while True:
            if not self.on:
                was_on = False
                self.changed.wait(0.2)
                self.changed.clear()
                continue
            if not was_on:
                was_on = True
                if self.net.claim and not self.claim():
                    continue
                last_keep = last_air = 0.0
            now = time.time()
            if now - last_keep >= 1.5:
                self.send(self.keepalive(), self.net.ports.announce)
                last_keep = now
            if now - last_air >= 0.25 or self.changed.is_set():
                self.changed.clear()
                self.send(on_air_packet(self.name, self.number, self.flags(), self.six), self.net.ports.beat)
                last_air = now
            time.sleep(0.02)
