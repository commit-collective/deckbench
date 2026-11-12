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
import json
import struct
import threading
import time

from .. import profiles
from . import startup
from .mixer import parse_on_air

PITCH_NORMAL = 0x100000


def tempo_of(field):
    """A track tempo field (BPM x 100) in BPM, or None for 0xFFFF and 0: a player with no track says it has none."""
    raw = struct.unpack(">H", field)[0]
    return None if raw in (0, 0xFFFF) else raw / 100.0


AT_CUE = (5, 6, 7, 8)                           # paused, cued, cue playing, cue scratching: where beat 0 is a place
NOISY = ("status", "beat", "position")           # many a second: kept apart from the rest

STATE_NAMES = {0: "no track", 2: "loading", 3: "playing", 4: "looping", 5: "paused", 6: "cued", 7: "cue playing", 8: "cue scratching",
               9: "searching", 14: "spun down", 17: "track ended"}


def text(data, start, end):
    return data[start:end].split(b"\0")[0].decode("latin-1", "replace").strip()


MOVING = ("playing", "looping", "cue playing", "cue scratching")


def follow_stop(d, previous, st, now):
    """Where a stopped player waits and where its cue is, as beats of the track counted from 0 (d["held"], d["cue"]),
    from what the bench saw it do. An older player reports only the beat it has passed, and its cue, set with CUE, is
    nowhere to read. A pause while playing is placed from the beats it played, CUE on a paused player sets the cue
    there (on the nearest beat, as quantize does, when the reported beat allows it), and a return to the cue lands on it.
    Anything the bench did not see, a gap in its status, another track, a reported beat that disagrees, leaves either
    unknown: the page then falls back to the beat."""
    key = (st["source"], st["slot"], st["rbid"])
    if (not previous or now - previous.get("seen", 0) > 1.5 or d.get("cue_track") != key
            or st["track_beat"] is None):
        d["held"] = d["cue"] = None
    d["cue_track"] = key
    if st["track_beat"] is None:
        return
    r = st["track_beat"] - 1
    agrees = lambda at: at is not None and r - 0.001 <= at <= r + 1.001     # a cue a hair before beat k reports k - 1
    state, before = st["state"], previous.get("state") if previous else None
    if state in MOVING:
        d["held"] = None
        return
    held = None
    phase = d.get("phase")
    if before in ("playing", "looping") and state == "paused" and phase and phase[2] > 0 \
            and now - phase[0] < 4 * 60 / phase[2]:
        # it stopped as this status came: a player sends one at once when its state changes
        held = phase[1] + (now - phase[0]) * phase[2] / 60
        held = min(max(held, r), r + 1) if abs(held - (r + 0.5)) < 1 else None
    elif state == "cued" and before == "paused":
        p = d.get("held")
        if p is not None:
            held = next((at for at in (float(round(p)), p) if agrees(at)), None)
    elif state == "cued" and before != "cued":
        held = d.get("cue")
    elif state == before:
        held = d.get("held")
        # stopped right before a beat, it can still report that beat a moment later: it stands on it
        if held is not None and r - 0.15 <= held < r - 0.001:
            held = float(r)
    d["held"] = held if agrees(held) else None
    if state == "cued":
        d["cue"] = d["held"]


def classify(port, data, announce=50000, beat=50001, update=50002):
    """The kind of packet that this is (a short word), by the port it was heard on and its type byte."""
    if len(data) < 0x0B or data[:10] != startup.MAGIC:
        return "other"
    t = data[0x0A]
    if port == announce:
        return {0x0A: "hello", 0x00: "claim 1", 0x01: "will assign", 0x02: "claim 2", 0x04: "claim 3", 0x06: "keep-alive",
                0x08: "number in use"}.get(t, "other")
    if port == beat:
        return {0x28: "beat", 0x03: "on air", 0x02: "fader start", 0x26: "takeover request", 0x27: "takeover reply", 0x2A: "sync command",
                0x0B: "position"}.get(t, "other")
    if port == update:
        return {0x0A: "status", 0x29: "mixer status", 0x27: "takeover reply",
                0x19: "load track", 0x1A: "load acknowledgement"}.get(t, "other")
    return "other"


class Monitor:
    def __init__(self, net, clock=None):
        self.net = net
        self.clock = clock or (lambda: time.time())
        self.began = net.world.events.began if clock is None else self.clock()
        self.lock = threading.Lock()
        self.n = 0
        self.rings = {"noisy": collections.deque(maxlen=12000), "rest": collections.deque(maxlen=8000)}
        self.recording = None
        self.devices = {}                       # by address
        self.counts = collections.Counter()
        self.recent = {}                        # (source, port, bytes): when it was last heard
        self.busy = 0                           # packets being read now, by whichever thread: 0 when everything heard is taken in

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
                if name == "deckbench":             # the bench's presence with its decks off, or its observer
                    return True
                return (not name or name == link.name.decode()) and (number is None or number == link.number)
        mixer = self.net.mixer
        return source == mixer.address and (not name or name == mixer.name.decode())

    # -- what is heard --
    def feed(self, data, source, port, to="*"):
        """A datagram heard (or, for one the bench sends to a single device, sent) from `source`, on `port`. `to` is the address
        it was heard at ("*": any). Never raises."""
        with self.lock:
            self.busy += 1
        try:
            self._feed(bytes(data), source, port, to)
        except Exception as e:                    # an odd packet is not worth the sniffer thread
            if not getattr(self, "complained", False):
                self.complained = True
                from ..core import log
                log("the monitor could not read a packet (%s): %s" % (type(e).__name__, e))
        finally:
            with self.lock:
                self.busy -= 1

    def _feed(self, data, source, port, to):
        ports = self.net.ports
        kind = classify(port, data, ports.announce, ports.beat, ports.update)
        now = self.clock()
        # A broadcast reaches every socket of the bench that listens on the port (on Windows even those bound to one address): once is enough
        with self.lock:
            key = (source, port, data)
            if key in self.recent and now - self.recent[key] < 0.03:
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
        if device is not None:
            device["packet_source"] = source
        summary = self.read(kind, data, device, now) if device is not None else ""
        with self.lock:
            self.n += 1
            self.counts[kind] += 1
            item = {"n": self.n, "t": round(now - self.began, 3), "port": port, "kind": kind, "src": source, "to": to,
                    "ours": ours, "len": len(data), "text": summary,
                    "name": device["name"] if device else "", "number": device["number"] if device else None,
                    "hex": data.hex()}
            item["session"] = self.net.world.events.session
            self.rings["noisy" if kind in NOISY else "rest"].append(item)
            if self.recording:
                self.recording.write(json.dumps(item) + "\n")
                self.recording.flush()

    def record(self, path):
        """Keep all observed UDP packets as JSON Lines, independent of UI filters."""
        with self.lock:
            if self.recording:
                raise ValueError("a capture is already open")
            self.recording = open(path, "x", encoding="utf-8")

    def close(self):
        with self.lock:
            if self.recording:
                self.recording.close()
                self.recording = None

    # -- the log --
    def since(self, n=0, noisy=True, limit=400):
        """The packets after number n (oldest first), the status and beat ones too if `noisy`. At most `limit`, the newest."""
        with self.lock:
            items = [p for ring in ((self.rings["noisy"], self.rings["rest"]) if noisy else (self.rings["rest"],)) for p in ring if p["n"] > n]
            total = self.n
        items.sort(key=lambda p: p["n"])
        return {"packets": items[-limit:], "next": total, "counts": dict(self.counts),
                "session": self.net.world.events.session, "started": self.began}

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
        if kind in ("status", "mixer status", "position", "beat", "on air", "fader start", "sync command", "takeover request", "takeover reply") and n >= 0x22:
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
        if kind == "position" and n >= 0x3C:
            length, position, pitch = struct.unpack_from(">IIi", data, 0x24)
            raw_bpm = struct.unpack_from(">I", data, 0x38)[0]
            d["name"] = text(data, 0x0B, 0x1F) or d["name"]
            d["number"], d["kind"] = data[0x21], "player"
            d["precise"] = {"seen": now, "position_ms": position, "length_s": length,
                            "pitch": pitch / 100.0, "bpm": None if raw_bpm == 0xFFFFFFFF else raw_bpm / 10.0}
            return "%s #%d: position %.3f s" % (d["name"], d["number"], position / 1000.0)
        if kind == "mixer status" and n >= 0x38:
            flags = data[0x27]
            pitch = struct.unpack_from(">I", data, 0x28)[0]
            bpm = struct.unpack_from(">H", data, 0x2E)[0] / 100.0
            d["name"], d["number"], d["kind"] = text(data, 0x0B, 0x1F), data[0x21], "mixer"
            d["status"] = {"seen": now, "play": True, "master": bool(flags & 0x20), "sync": bool(flags & 0x10),
                           "on_air": False, "state": "mixer", "loop": False, "bar": None,
                           "bpm": bpm * pitch / PITCH_NORMAL, "pitch": (pitch / PITCH_NORMAL - 1) * 100,
                           "track_bpm": bpm, "source": 0, "slot": 0, "rbid": 0, "track_beat": None,
                           "sync_counter": 0, "handoff": data[0x36]}
            self.net.peer_status(d, data)
            return "%s: mixer %.1f BPM%s" % (d["name"], d["status"]["bpm"], " master" if flags & 0x20 else "")
        if kind == "keep-alive" and n >= 0x30:
            d["name"], d["number"] = text(data, 0x0C, 0x20), data[0x24]
            d["mac"] = ":".join("%02x" % b for b in data[0x26:0x2C])
            d["kind"] = {1: "player", 2: "mixer"}.get(data[0x34] if n > 0x34 else 0, d["kind"] or "device")
            d["peers"] = data[0x30]
            d["unit"] = self.net.matches_target(d["name"], d["number"], d["ip"])
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
        if kind == "takeover reply" and n >= 0x2C:
            return "%s answers a request for the master role (%s)" % (text(data, 0x0B, 0x1F) or "?", "yes" if data[-1] == 1 else "no")
        return "type %#04x, %d bytes" % (data[0x0A], n)

    def status(self, d, data, now):
        d["beat_since_status"] = False
        flags = data[0x89]
        pitch = struct.unpack(">I", data[0x8C:0x90])[0]
        track_bpm = tempo_of(data[0x92:0x94])
        beat_in_track = struct.unpack(">I", data[0xA0:0xA4])[0]
        d["name"] = text(data, 0x0B, 0x1F) or d["name"]
        d["number"] = data[0x21]
        d["kind"] = d["kind"] or "player"
        d["unit"] = self.net.matches_target(d["name"], d["number"], d["ip"])
        d["firmware"] = text(data, 0x7C, 0x80)
        state = data[0x7B]
        playing = bool(flags & 0x40)
        rbid = struct.unpack(">I", data[0x2C:0x30])[0]
        st = {"play": playing, "master": bool(flags & 0x20), "sync": bool(flags & 0x10), "on_air": bool(flags & 0x08),
              "state": STATE_NAMES.get(state, "state %d" % state), "loop": state == 4,
              "bpm": round(track_bpm * pitch / PITCH_NORMAL, 2) if track_bpm else None, "track_bpm": track_bpm,
              "pitch": round((pitch / PITCH_NORMAL - 1) * 100, 2), "bar": data[0xA6] or None,
              # counted from 1. 0 is a player stopped before the first beat of its track (paused, cued or held on CUE
              # there: a cue on the first beat), and otherwise a player with no count, as a sampler playing patterns
              "track_beat": (None if beat_in_track == 0xFFFFFFFF or (beat_in_track == 0 and not (rbid and state in AT_CUE))
                             else beat_in_track),
              "source": data[0x28], "slot": data[0x29], "track_type": data[0x2A], "rbid": rbid,
              "sync_counter": struct.unpack(">I", data[0x84:0x88])[0], "handoff": data[0x9F], "seen": now}
        if len(data) >= 0x1CA:
            # A CDJ-3000 says where its loop is while it plays one: its start and end in the track, each a count of
            # 65.536 ms, and its whole beats (0 for a loop under a beat). Older players say nothing of it.
            start, end = struct.unpack(">I", data[0x1B6:0x1BA])[0], struct.unpack(">I", data[0x1BE:0x1C2])[0]
            if start or end:
                st["loop_ms"] = [round(start * 65.536, 1), round(end * 65.536, 1)]
                st["loop_beats"] = struct.unpack(">H", data[0x1C8:0x1CA])[0]
        previous = d.get("status") or {}
        # When its beat changed: after the last status with the old beat, before this one. A page that runs a player
        # with no beat packets (cue playing) keeps its strip within that, where it would step on each status
        if previous.get("track_beat") is not None and st["track_beat"] != previous.get("track_beat"):
            st["beat_window"] = [previous["seen"], now]
        else:
            st["beat_window"] = previous.get("beat_window")
        # how its beats line up with its bars: two statuses in a row that agree. A status in the middle of a change
        # (its bar moved on, its beat not yet, as at a loop's jump back) does not, and beats are not counted from it
        if st["track_beat"] is not None and st["bar"]:
            offset = (st["bar"] - st["track_beat"]) % 4
            if offset == d.get("bar_offset_seen"):
                d["bar_offset"] = offset
            d["bar_offset_seen"] = offset
            if offset == d.get("bar_offset"):
                d["good_status"] = st
        # when its state last changed (as when it started), bench time
        st["since"] = previous.get("since", now) if previous.get("state") == st["state"] else now
        # started from a stop: a beat from before it (the previous play or CUE hold) is not where it is now
        if previous.get("state") not in MOVING and st["state"] in MOVING:
            if d.get("phase") and d["phase"][0] < previous.get("seen", 0):
                d["phase"] = d["bar_phase"] = None
            # where it starts from: where the bench followed it, else where it stood at its cue
            stands = previous.get("stands")
            d["start_from"] = d.get("held") if d.get("held") is not None else (
                float(stands) if stands is not None and previous.get("state") == "cued" else None)
        elif st["state"] not in MOVING:
            d["start_from"] = None
        if d["ours"]:
            d["status"] = st
        else:
            follow_stop(d, previous, st, now)
            with self.net.world.lock:
                # Preserve position through a tempo update without aligning
                # local followers to their master on an unrelated status.
                at = time.time()
                for deck in self.net.world.decks.values():
                    deck.reanchor(at)
                d["status"] = st
        if st["track_beat"] is not None and st["state"] == "cued":
            st["stands"] = self.stands(st)
        if not d["ours"]:
            changed = {k: st[k] for k in ("play", "master", "sync", "on_air", "state", "source", "slot", "rbid", "handoff")
                       if previous.get(k) != st[k]}
            if changed:
                self.net.world.events.add("player_state", number=d["number"], ip=d["ip"], name=d["name"], changes=changed)
        self.net.peer_status(d, data)
        phase, bar_phase = d["phase"], d.get("bar_phase")
        if (playing and st["loop"] and phase and bar_phase and phase[2] > 0
                and now - phase[0] < min(1.0, 60.0 / phase[2])
                and st["track_beat"] is not None and st["bar"]):
            # A wrap status can arrive after its beat. Correct that beat's
            # track position now, keeping its original time and bar phase.
            delta = (int(bar_phase[1]) + 1 - st["bar"] + 2) % 4 - 2
            corrected = st["track_beat"] - 1.0 + delta
            if 0 <= corrected < phase[1] - 1.5:
                d["phase"] = [phase[0], corrected, phase[2]]
        if not playing and st["track_beat"] is not None:
            d["at"] = st["track_beat"] - 1
        return "%s #%d: %s%s%s%s, %s, beat %s%s" % (
            d["name"], d["number"], st["state"], ", master" if st["master"] else "", ", synced" if st["sync"] else "",
            ", on air" if st["on_air"] else "", "%.1f BPM" % st["bpm"] if st["bpm"] else "no tempo", st["bar"] if st["bar"] else "-",
            ", track %d:%d:%d" % (st["source"], st["slot"], st["rbid"]) if st["rbid"] else "")

    def stands(self, st):
        """Where a player waiting at its cue stands, as a beat of the track counted from 0. A cue sits a hair before its
        beat, so the player reports the beat before, with the cue's bar: it stands on the next one. On the track's first
        beat there is no beat before, and an NXS2 reports that beat itself, beat 1 with its own bar. The reported beat's
        bar, from the track's grid, tells which. Without the grid, beat 1 in bar 1 is taken for the first beat, as a
        track's first beat mostly starts a bar."""
        r = st["track_beat"]
        if r >= 1 and st["bar"]:
            own = self.net.beat_bar(st, r - 1) if hasattr(self.net, "beat_bar") else None
            if own is None and r == 1:
                own = 1
            if own == st["bar"]:
                return r - 1
        return r

    def beat(self, d, data, now):
        bar = data[0x5C]
        track_bpm = tempo_of(data[0x5A:0x5C])
        if not track_bpm:                       # no tempo: no beat to place
            return "%s #%d: beat with no tempo" % (d["name"] or "?", d["number"] if d["number"] is not None else 0)
        pitch = int.from_bytes(data[0x55:0x58], "big")
        bpm = round(track_bpm * (pitch / PITCH_NORMAL if pitch else 1.0), 2)
        d["name"] = d["name"] or text(data, 0x0B, 0x1F)
        d["number"] = d["number"] if d["number"] is not None else data[0x21]
        st = d["status"]
        if 1 <= bar <= 4:
            pos = bar - 1.0
            good = d.get("good_status")
            if (st and good is not None and good is not st and st["track_beat"] is not None and st["bar"]
                    and (st["bar"] - st["track_beat"]) % 4 != d.get("bar_offset") and now - good["seen"] < 1.0
                    and good.get("since") == st.get("since")):     # from this run, not before a stop
                st = good                           # counted from the last status that fits, not a half-changed one
            if st and now - st["seen"] < 1.0 and st["track_beat"] is not None and st["bar"]:
                delta = (bar - st["bar"] + 2) % 4 - 2
                pos = st["track_beat"] - 1.0 + delta
                # the first beat after a start from a stop: where it stood and the time since, at its tempo. Waiting at
                # a cue a player reports the beat before it with the cue's bar, so the count above can be one short.
                # The beat it starts on is often not sent: this one can be the next
                start = d.get("start_from")
                if start is not None and st.get("since") is not None and bpm > 0:
                    first = float(round(start + (now - st["since"]) * bpm / 60))
                    if abs(first - pos) <= 1:
                        pos = first
                d["start_from"] = None
            # The reported bar need not match the absolute track count.
            d["bar_phase"] = [now, bar - 1.0, bpm]
            d["beat_since_status"] = True
            d["phase"], d["phase_seen"] = [now, pos, bpm], now
            self.net.align_synced(d, now)
        return "%s #%d: beat %d of 4, %.1f BPM" % (d["name"] or "?", d["number"] if d["number"] is not None else 0, bar, bpm)

    # -- what the page is given --
    def snapshot(self, now=None):
        """The devices that are not the bench's own, as the page shows them. Volatile things (a time since a packet) are left out:
        `online` says whether it was heard in the last eight seconds."""
        now = self.clock() if now is None else now
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
            # held on CUE (cue playing) it sends its beats with its play flag off: it moves all the same
            moving = bool(st and (st["play"] or st["state"] in MOVING))
            live_phase = (d["phase"] and now - d["phase_seen"] < 2.0
                          and (st is None or moving or d.get("beat_since_status", False)))
            item = {"ip": d["ip"], "name": d["name"], "model": model, "number": d["number"], "kind": d["kind"] or "device", "unit": d["unit"],
                    "online": now - d["seen"] < 8, "mac": d["mac"], "peers": d["peers"], "firmware": d["firmware"],
                    "status": {k: v for k, v in st.items() if k != "seen"} if st else None,
                    "phase": d["phase"] if live_phase else None,
                    "bar_phase": d.get("bar_phase") if live_phase else None,
                    "at": d["at"] if not moving else None,
                    "held": d.get("held") if st else None, "cue": d.get("cue") if st else None,
                    "precise": dict({k: v for k, v in d["precise"].items() if k != "seen"}, at=d["precise"]["seen"])
                               if d.get("precise") and now - d["precise"]["seen"] < 2 else None,
                    "air": d["air"] if d["air"] and now - d["air_seen"] < 8 else None,
                    "fader": d["fader"]["commands"] if d["fader"] and now - d["fader"]["t"] < 8 else None}
            out.append(item)
        out.sort(key=lambda x: (x["number"] if x["number"] is not None else 99, x["ip"]))
        return out
