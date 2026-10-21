# SPDX-License-Identifier: MIT OR Apache-2.0
"""What is heard on the link: a log of every Pro DJ Link packet, and the devices on it with what they say of themselves.

The bench's decks, its mixer and whatever else is on the network (a unit under test, real players, a real mixer, rekordbox) all
send on UDP 50000 (who is there), 50001 (beats, the mixer's on air and fader start, sync commands) and 50002 (statuses). The
monitor is told each packet that the bench's sockets receive, and each one its decks send to a single device, and:

  - names its kind and writes a line about it, for the page's log (`packets`: a ring for the many statuses and beats, another for the
    rest, so that a claim or a number in use is not pushed out in a minute by the statuses)
  - keeps a record of each device: its model (the name it announces), number, address, whether it plays, is the master, is synced, is on
    air, its tempo, its place in the bar, the track it has loaded, and for a mixer the channels it says are on air

The layouts are those of the other modules here (Deep Symmetry's analysis). It reads and never answers. A packet that is too short or
odd is logged as it is and its device is not updated: it must not stop the bench.
"""
import collections
import struct
import threading
import time

from .. import profiles
from . import startup
from .mixer import parse_on_air

PITCH_NORMAL = 0x100000
NOISY = ("status", "beat", "position")           # many a second: kept apart from the rest

STATE_NAMES = {0: "no track", 2: "loading", 3: "playing", 4: "looping", 5: "paused", 6: "cued", 7: "cue playing", 8: "cue scratching",
               9: "searching", 14: "spun down", 17: "track ended"}


def text(data, start, end):
    return data[start:end].split(b"\0")[0].decode("latin-1", "replace").strip()


def classify(port, data, announce=50000, beat=50001, update=50002):
    """The kind of packet that this is (a short word), by the port it was heard on and its type byte."""
    if len(data) < 0x0B or data[:10] != startup.MAGIC:
        return "other"
    t = data[0x0A]
    if port == announce:
        return {0x0A: "hello", 0x00: "claim 1", 0x01: "will assign", 0x02: "claim 2", 0x04: "claim 3", 0x06: "keep-alive",
                0x08: "number in use"}.get(t, "other")
    if port == beat:
        return {0x28: "beat", 0x03: "on air", 0x02: "fader start", 0x26: "takeover request", 0x2A: "sync command",
                0x0B: "position"}.get(t, "other")
    if port == update:
        return {0x0A: "status", 0x27: "takeover reply"}.get(t, "other")
    return "other"


class Monitor:
    def __init__(self, net):
        self.net = net
        self.began = time.time()
        self.lock = threading.Lock()
        self.n = 0
        self.rings = {"noisy": collections.deque(maxlen=1500), "rest": collections.deque(maxlen=2500)}
        self.devices = {}                       # by address
        self.counts = collections.Counter()
        self.recent = {}                        # (source, port, bytes): when it was last heard

    # -- who is ours --
    def own_addresses(self):
        out = {link.address for link in self.net.decks.values()}
        out.add(self.net.mixer.address)
        return out

    def is_ours(self, source, name, number):
        """Whether a packet is one of the bench's own: from the address of one of its decks (or its mixer) and as that deck says it is.
        A unit on the same machine sends from 127.0.0.1 as well, which is the address of deck 1: the name tells them apart."""
        for link in self.net.decks.values():
            if link.address == source:
                return (not name or name == link.name.decode()) and (number is None or number == link.number)
        mixer = self.net.mixer
        return source == mixer.address and (not name or name == mixer.name.decode())

    # -- what is heard --
    def feed(self, data, source, port, to="*"):
        """A datagram heard (or, for one the bench sends to a single device, sent) from `source`, on `port`. `to` is the address
        it was heard at ("*": any). Never raises."""
        try:
            self._feed(bytes(data), source, port, to)
        except Exception as e:                    # an odd packet is not worth the sniffer thread
            if not getattr(self, "complained", False):
                self.complained = True
                from ..core import log
                log("the monitor could not read a packet (%s): %s" % (type(e).__name__, e))

    def _feed(self, data, source, port, to):
        ports = self.net.ports
        kind = classify(port, data, ports.announce, ports.beat, ports.update)
        now = time.time()
        # A broadcast reaches every socket of the bench that listens on the port (on Windows even those bound to one address): once is enough
        with self.lock:
            key = (source, port, data)
            if now - self.recent.get(key, 0.0) < 0.03:
                return
            self.recent[key] = now
            if len(self.recent) > 800:
                self.recent = {k: t for k, t in self.recent.items() if now - t < 0.5}
        ours, device = False, None
        if data[:10] == startup.MAGIC:
            name, number, declared = self.identify(kind, data)
            ours = self.is_ours(source, name, number)
            device = self.device(source, now, ours, name, number, declared)
        else:
            ours = source in self.own_addresses()
        summary = self.read(kind, data, device, now) if device is not None else ""
        with self.lock:
            self.n += 1
            self.counts[kind] += 1
            item = {"n": self.n, "t": round(now - self.began, 3), "port": port, "kind": kind, "src": source, "to": to,
                    "ours": ours, "len": len(data), "text": summary,
                    "name": device["name"] if device else "", "number": device["number"] if device else None,
                    "hex": data[:96].hex() + ("..." if len(data) > 96 else "")}
            self.rings["noisy" if kind in NOISY else "rest"].append(item)

    # -- the log --
    def since(self, n=0, noisy=True, limit=400):
        """The packets after number n (oldest first), the status and beat ones too if `noisy`. At most `limit`, the newest."""
        with self.lock:
            items = [p for ring in ((self.rings["noisy"], self.rings["rest"]) if noisy else (self.rings["rest"],)) for p in ring if p["n"] > n]
            total = self.n
        items.sort(key=lambda p: p["n"])
        return {"packets": items[-limit:], "next": total, "counts": dict(self.counts)}

    def clear(self):
        with self.lock:
            for ring in self.rings.values():
                ring.clear()
            self.counts.clear()

    # -- the devices --
    @staticmethod
    def identify(kind, data):
        """(name, number, the address it declares) of the sender of a packet, as far as the packet says: None for what it does not."""
        n = len(data)
        if kind == "keep-alive" and n >= 0x30:
            return text(data, 0x0C, 0x20), data[0x24], ".".join(str(b) for b in data[0x2C:0x30])
        if kind in ("hello", "claim 1") and n >= 0x20:
            return text(data, 0x0C, 0x20), None, None
        if kind == "claim 2" and n >= 0x2F:
            return text(data, 0x0C, 0x20), data[0x2E], ".".join(str(b) for b in data[0x24:0x28])
        if kind == "claim 3" and n >= 0x26:
            return text(data, 0x0C, 0x20), data[0x24], None
        if kind in ("status", "beat", "on air", "fader start", "sync command", "takeover request", "takeover reply") and n >= 0x22:
            return text(data, 0x0B, 0x1F), data[0x21], None
        return "", None, None

    def device(self, source, now, ours, name="", number=None, declared=None):
        """The record of the device that sent a packet. A device is who it says it is (its name and number): its statuses can come from
        another address than its keep-alives (a unit's do, from its loopback), so it is not told by the address."""
        with self.lock:
            key = (name, number) if name and number is not None else ("ip", source)
            d = self.devices.get(key)
            if d is None and key[0] != "ip":
                d = self.devices.pop(("ip", source), None)        # it was heard before it said who it was
            if d is None:
                d = {"ip": declared or source, "sources": set(), "name": "", "number": None, "kind": "", "mac": "", "peers": None, "ours": ours,
                     "unit": False, "first": now, "seen": now, "firmware": "", "status": None, "phase": None, "phase_seen": 0.0, "at": None,
                     "air": None, "air_seen": 0.0, "fader": None}
            self.devices[key] = d
            d["sources"].add(source)
            if declared and declared != "0.0.0.0":
                d["ip"] = declared
            elif not d["ip"]:
                d["ip"] = source
            d["seen"] = now
            d["ours"] = d["ours"] or ours
            return d

    def read(self, kind, data, d, now):
        """Updates the device from a packet, and says in a line what it is."""
        n = len(data)
        if kind == "keep-alive" and n >= 0x30:
            d["name"], d["number"] = text(data, 0x0C, 0x20), data[0x24]
            d["mac"] = ":".join("%02x" % b for b in data[0x26:0x2C])
            d["kind"] = {1: "player", 2: "mixer"}.get(data[0x34] if n > 0x34 else 0, d["kind"] or "device")
            d["peers"] = data[0x30]
            d["unit"] = d["name"].startswith("DJS-")
            return "%s #%d at %s, %s, knows %d device%s" % (d["name"], d["number"], ".".join(str(b) for b in data[0x2C:0x30]),
                                                            d["kind"], d["peers"], "" if d["peers"] == 1 else "s")
        if kind == "hello" and n >= 0x25:
            d["name"] = text(data, 0x0C, 0x20)
            return "%s says hello (%s)" % (d["name"], {1: "a player", 2: "a mixer"}.get(data[0x24], "a device"))
        if kind == "claim 1" and n >= 0x26:
            d["name"] = text(data, 0x0C, 0x20)
            return "%s claims a number, step 1 of 3 (%d)" % (d["name"], data[0x24])
        if kind == "claim 2" and n >= 0x2F:
            d["name"], d["number"] = text(data, 0x0C, 0x20), data[0x2E]
            return "%s claims number %d, step 2 of 3 (%d)%s" % (d["name"], data[0x2E], data[0x2F], ", auto-assign" if n > 0x31 and data[0x31] == 1 else "")
        if kind == "claim 3" and n >= 0x26:
            d["name"], d["number"] = text(data, 0x0C, 0x20), data[0x24]
            return "%s claims number %d, step 3 of 3 (%d)" % (d["name"], data[0x24], data[0x25])
        if kind == "number in use" and n >= 0x25:
            return "%s says number %d is in use" % (text(data, 0x0C, 0x20), data[0x24])
        if kind == "status" and n >= 0xA7:
            return self.status(d, data, now)
        if kind == "beat" and n >= 0x5D:
            return self.beat(d, data, now)
        if kind == "on air":
            flags = parse_on_air(data)
            if flags is None:
                return ""
            d["name"] = d["name"] or text(data, 0x0B, 0x1F)
            d["number"] = d["number"] if d["number"] is not None else data[0x21]
            d["kind"] = d["kind"] or "mixer"
            d["air"], d["air_seen"] = flags, now
            return "%s: on air %s" % (d["name"] or "mixer", " ".join(str(c) for c, on in sorted(flags.items()) if on) or "none")
        if kind == "fader start" and n >= 0x28:
            commands = {i + 1: {0: "start", 1: "stop"}.get(data[0x24 + i]) for i in range(4) if data[0x24 + i] in (0, 1)}
            d["name"] = d["name"] or text(data, 0x0B, 0x1F)
            d["fader"] = {"t": now, "commands": commands}
            return "fader start by %s: %s" % (d["name"] or "?", ", ".join("%d %s" % (p, c) for p, c in sorted(commands.items())) or "nothing")
        if kind == "sync command" and n > 0x2B:
            what = {0x10: "sync on", 0x20: "sync off", 0x01: "become the master"}.get(data[0x2B], "command %#x" % data[0x2B])
            return "%s tells a player: %s" % (text(data, 0x0B, 0x1F) or "?", what)
        if kind == "takeover request":
            return "%s asks for the master role" % (text(data, 0x0B, 0x1F) or "?")
        if kind == "takeover reply" and n > 0x30:
            return "%s answers a request for the master role (%s)" % (text(data, 0x0B, 0x1F) or "?", "yes" if data[-1] == 1 else "no")
        return "type %#04x, %d bytes" % (data[0x0A], n)

    def status(self, d, data, now):
        flags = data[0x89]
        pitch = struct.unpack(">I", data[0x8C:0x90])[0]
        track_bpm = struct.unpack(">H", data[0x92:0x94])[0] / 100.0
        beat_in_track = struct.unpack(">I", data[0xA0:0xA4])[0]
        d["name"] = text(data, 0x0B, 0x1F) or d["name"]
        d["number"] = data[0x21]
        d["kind"] = d["kind"] or "player"
        d["unit"] = d["name"].startswith("DJS-")
        d["firmware"] = text(data, 0x7C, 0x80)
        state = data[0x7B]
        playing = bool(flags & 0x40)
        st = {"play": playing, "master": bool(flags & 0x20), "sync": bool(flags & 0x10), "on_air": bool(flags & 0x08),
              "state": STATE_NAMES.get(state, "state %d" % state), "loop": state == 4,
              "bpm": round(track_bpm * pitch / PITCH_NORMAL, 2), "track_bpm": track_bpm,
              "pitch": round((pitch / PITCH_NORMAL - 1) * 100, 2), "bar": data[0xA6] or None,
              "track_beat": beat_in_track if beat_in_track != 0xFFFFFFFF else None,
              "source": data[0x28], "slot": data[0x29], "track_type": data[0x2A], "rbid": struct.unpack(">I", data[0x2C:0x30])[0],
              "sync_counter": struct.unpack(">I", data[0x84:0x88])[0], "seen": now}
        d["status"] = st
        if not playing and st["track_beat"] is not None:
            d["at"] = st["track_beat"] - 1
        return "%s #%d: %s%s%s%s, %.1f BPM, beat %s%s" % (
            d["name"], d["number"], st["state"], ", master" if st["master"] else "", ", synced" if st["sync"] else "",
            ", on air" if st["on_air"] else "", st["bpm"], st["bar"] if st["bar"] else "-",
            ", track %d:%d:%d" % (st["source"], st["slot"], st["rbid"]) if st["rbid"] else "")

    def beat(self, d, data, now):
        bar = data[0x5C]
        track_bpm = struct.unpack(">H", data[0x5A:0x5C])[0] / 100.0
        pitch = int.from_bytes(data[0x55:0x58], "big")
        bpm = round(track_bpm * (pitch / PITCH_NORMAL if pitch else 1.0), 2)
        d["name"] = d["name"] or text(data, 0x0B, 0x1F)
        d["number"] = d["number"] if d["number"] is not None else data[0x21]
        st = d["status"]
        if 1 <= bar <= 4:
            pos = bar - 1.0
            if st and now - st["seen"] < 1.0 and st["track_beat"] is not None and st["bar"]:
                pos = st["track_beat"] - 1.0 + ((bar - st["bar"]) % 4)      # the track's own count, which a loop sends back
            d["phase"], d["phase_seen"] = [now, pos, bpm], now
            self.net.align_synced(d, now)
        return "%s #%d: beat %d of 4, %.1f BPM" % (d["name"] or "?", d["number"] if d["number"] is not None else 0, bar, bpm)

    # -- what the page is given --
    def snapshot(self, now=None):
        """The devices that are not the bench's own, as the page shows them. Volatile things (a time since a packet) are left out:
        `online` says whether it was heard in the last eight seconds."""
        now = now or time.time()
        out = []
        with self.lock:
            devices = list(self.devices.values())
        for d in devices:
            if d["ours"] or now - d["seen"] > 60 or not (d["name"] or d["number"] is not None):
                continue
            model = d["name"]
            for key, profile in profiles.PROFILES.items():
                if profile["model"].upper() == d["name"].upper():
                    model = profile["title"]
            st = d["status"] if d["status"] and now - d["status"]["seen"] < 8 else None
            item = {"ip": d["ip"], "name": d["name"], "model": model, "number": d["number"], "kind": d["kind"] or "device", "unit": d["unit"],
                    "online": now - d["seen"] < 8, "mac": d["mac"], "peers": d["peers"], "firmware": d["firmware"],
                    "status": {k: v for k, v in st.items() if k != "seen"} if st else None,
                    "phase": d["phase"] if d["phase"] and now - d["phase_seen"] < 2.0 and st and st["play"] else None,
                    "at": d["at"] if not (st and st["play"]) else None,
                    "air": d["air"] if d["air"] and now - d["air_seen"] < 8 else None,
                    "fader": d["fader"]["commands"] if d["fader"] and now - d["fader"]["t"] < 8 else None}
            out.append(item)
        out.sort(key=lambda x: (x["number"] if x["number"] is not None else 99, x["ip"]))
        return out
