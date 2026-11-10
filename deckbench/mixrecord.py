# SPDX-License-Identifier: MIT OR Apache-2.0
"""Recording what the real players do during a mix, as a scenario that plays it again on them.

    python -m deckbench.mixrecord CAPTURE.json [--out mix.json]

While a recording runs, every status of a real player (not the bench's own decks, not the device under test) is compared
with the one before. What changed becomes an event: a track loaded, PLAY, a pause, CUE (pressed, or held for a while),
SYNC on or off, MASTER taken. `MixRecorder.stop` turns them into scenario steps: `player` to do it again, then
`expect_player` to check that the player did it.

The network lets the bench load a track and press PLAY/PAUSE, CUE, SYNC and MASTER, nothing more. What a player cannot be
made to do (a pitch moved by hand, a loop, a hot cue or a jump to another place in the track, an eject) is kept as a `log`
step at its time and in the scenario's `notes`, so that whoever replays it does it by hand or knows where it differs.

A replay begins with a setup: each player is checked (on the link, the same model, stopped) and loads the track it had
when the recording began. The recorded events follow, at their seconds after the start of the recording plus the setup's
time. A track starts from where the player puts it when it loads (its cue, or its first beat): a mix that played a track
from elsewhere is noted.
"""
import argparse
import json
import threading
import time

RUNNING = ("playing", "looping")
HELD = ("cue playing", "cue scratching")
SLOT_NAMES = {2: "sd", 3: "usb"}
JOINED = 1.5            # a player first heard this many seconds into a recording joined the link then
SETUP = 12.0            # the setup's seconds before the first recorded event, with loads to wait for
SETUP_PLAIN = 3.0       # the same when no player loads a track before the mix
PITCH_STEP = 0.1        # a pitch moved by less, in percent, is not noted
JUMP_BEATS = 4          # a playing track whose beat is this far from where it should be has jumped
MERGE = 3.0             # pitch moves of one player closer in time than this are one note


class MixRecorder:
    """Keeps the changes of the real players between `start` and `stop`. `observe` is called with each status."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.began = None
        self.players = {}           # number: {"model", "first", "first_t", "last", "last_t", "hold", "pitch"}
        self.events = []            # (t, number, kind, details)

    @property
    def recording(self):
        return self.began is not None

    def start(self, now=None):
        with self.lock:
            self.began = self.clock() if now is None else now
            self.players, self.events = {}, []

    def observe(self, number, model, st, now):
        """A status of player `number` (the monitor's status dict) heard at `now`."""
        with self.lock:
            if self.began is None or not number or st.get("state") == "loading":
                return
            t = max(0.0, now - self.began)
            p = self.players.get(number)
            if p is None:
                self.players[number] = {"model": model, "first": dict(st), "first_t": t, "last": dict(st), "last_t": t,
                                        "hold": None, "pitch": st.get("pitch")}
                if t > JOINED and st.get("rbid"):
                    self.events.append((t, number, "joined", {"rbid": st["rbid"], "state": st["state"]}))
                return
            self._compare(number, p, p["last"], st, p["last_t"], t)
            p["last"], p["last_t"] = dict(st), t

    def _compare(self, number, p, prev, st, prev_t, t):
        add = lambda kind, **details: self.events.append((t, number, kind, details))
        key, before = (st["source"], st["slot"], st["rbid"]), (prev["source"], prev["slot"], prev["rbid"])
        if key != before:
            p["hold"] = None
            if st["rbid"]:
                add("load", rbid=st["rbid"], source=st["source"], slot=st["slot"], track_type=st.get("track_type"))
            else:
                add("eject")
            return
        was, now = prev["state"], st["state"]
        if was not in HELD and now in HELD:
            p["hold"] = t
        elif was in HELD and now not in HELD:
            began, p["hold"] = p["hold"], None
            if now in RUNNING:                          # held on CUE, then PLAY: it plays on from the cue
                self.events.append((began if began is not None else t, number, "play", {"from": prev.get("track_beat")}))
            elif began is not None:
                self.events.append((began, number, "cue_hold", {"seconds": round(t - began, 2)}))
        elif was not in RUNNING and now in RUNNING:
            add("play", **{"from": prev.get("track_beat")})
        elif was in RUNNING and now not in RUNNING:
            if now == "cued":
                add("cue")
            elif now == "paused":
                add("pause")
            elif now not in HELD:
                add("stopped", state=now)
        elif was == "paused" and now == "cued":
            add("cue")
        if now == "searching" and was != "searching":
            add("search")
        if now == "looping" and was != "looping":
            add("loop")
        elif was == "looping" and now != "looping":
            add("loop_end")
        if (was in RUNNING and now in RUNNING and "looping" not in (was, now) and st.get("track_beat") is not None
                and prev.get("track_beat") is not None and st.get("bpm")):
            expected = prev["track_beat"] + (t - prev_t) * st["bpm"] / 60.0
            if abs(st["track_beat"] - expected) > JUMP_BEATS:
                add("jump", **{"from": prev["track_beat"], "to": st["track_beat"]})
        if st["sync"] != prev["sync"]:
            add("sync_on" if st["sync"] else "sync_off")
        if st["master"] and not prev["master"]:
            add("master")
        pitch = st.get("pitch")
        if pitch is not None and p["pitch"] is not None and abs(pitch - p["pitch"]) >= PITCH_STEP and not st["sync"]:
            p["pitch"] = pitch
            add("pitch", value=pitch)
        elif st["sync"]:
            p["pitch"] = pitch                          # synced, it follows the master: its fader is not what sets it

    def snapshot(self):
        with self.lock:
            return {"recording": self.began is not None,
                    "seconds": round(self.clock() - self.began, 1) if self.began is not None else 0,
                    "players": sorted(self.players), "events": len(self.events)}

    def stop(self, name=None):
        """Ends the recording: the scenario (a dict, with its `notes`). Nothing heard gives a scenario with no steps."""
        with self.lock:
            began, players, events = self.began, self.players, list(self.events)
            self.began = None
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(began if began else time.time()))
        return build(players, events, name or "Mix recorded %s" % stamp)


def slot_of(slot):
    return SLOT_NAMES.get(slot, slot)


def build(players, events, name):
    """The scenario of a recording: `players` as MixRecorder keeps them, `events` its (t, number, kind, details)."""
    notes, setup, steps = [], [], []
    loads = {n: p for n, p in sorted(players.items()) if p["first_t"] <= JOINED and p["first"].get("rbid")}
    lead = SETUP if loads else SETUP_PLAIN

    def note(at, text):
        notes.append("%s: %s" % (clock(at), text))
        steps.append({"at": round(at, 2), "do": "log", "text": text})

    # the setup: the same players, stopped, with the tracks they had
    for n, p in sorted(players.items()):
        if p["first_t"] > JOINED:
            continue
        match = {"online": True, "play": False}
        if p.get("model"):
            match["model"] = p["model"]
        setup.append({"at": 0, "do": "expect_player", "player": n, "match": match, "within": 5})
    for n, p in loads.items():
        st = p["first"]
        setup.append({"at": 0.5, "do": "player", "player": n, "load": st["rbid"], "source": st["source"],
                      "slot": slot_of(st["slot"])})
        setup.append({"at": 0.5, "do": "expect_player", "player": n, "match": {"rbid": st["rbid"]}, "within": 10})
    for n, p in sorted(players.items()):
        st = p["first"]
        if p["first_t"] > JOINED:
            continue
        if st.get("sync"):
            setup.append({"at": lead - 2, "do": "player", "player": n, "press": "sync-on"})
            setup.append({"at": lead - 2, "do": "expect_player", "player": n, "match": {"sync": True}, "within": 1})
        elif st.get("pitch"):
            note(lead - 2.5, "player %d: set its pitch to %+.2f %% by hand (it was there when the recording began)"
                 % (n, st["pitch"]))
        if st.get("master"):
            setup.append({"at": lead - 1, "do": "player", "player": n, "press": "master"})
            setup.append({"at": lead - 1, "do": "expect_player", "player": n, "match": {"master": True}, "within": 1})
        if st.get("state") in RUNNING:
            events.append((0.0, n, "play", {"from": None, "already": True}))

    # the recorded events, after the setup
    events = merge_pitch(sorted(events, key=lambda e: e[0]))
    actions = []                    # (at, step, expectation, default within)
    for t, n, kind, d in events:
        at = round(lead + t, 2)
        if kind == "load":
            actions.append((at, {"do": "player", "player": n, "load": d["rbid"], "source": d["source"], "slot": slot_of(d["slot"])},
                            {"rbid": d["rbid"]}, 10))
        elif kind == "play":
            actions.append((at, {"do": "player", "player": n, "press": "play-pause"}, {"play": True}, 2))
            if d.get("already"):
                note(at, "player %d was playing when the recording began: it starts from where it loads, not from "
                         "where it was" % n)
            elif d.get("from") not in (None, 0, 1):
                note(at, "player %d played from beat %d: start it from there by hand if its cue is elsewhere"
                     % (n, d["from"]))
        elif kind == "pause":
            actions.append((at, {"do": "player", "player": n, "press": "play-pause"}, {"play": False}, 2))
        elif kind == "cue":
            actions.append((at, {"do": "player", "player": n, "press": "cue"}, {"state": "cued"}, 2))
        elif kind == "cue_hold":
            actions.append((at, {"do": "player", "player": n, "press": "cue", "hold": d["seconds"]}, None, 0))
            note(at, "player %d: CUE held for %.1f s (the steps after it wait for it to be let go)" % (n, d["seconds"]))
        elif kind == "sync_on":
            actions.append((at, {"do": "player", "player": n, "press": "sync-on"}, {"sync": True}, 2))
        elif kind == "sync_off":
            actions.append((at, {"do": "player", "player": n, "press": "sync-off"}, {"sync": False}, 2))
        elif kind == "master":
            actions.append((at, {"do": "player", "player": n, "press": "master"}, {"master": True}, 2))
        elif kind == "pitch":
            note(at, "player %d: pitch to %+.2f %% (by hand)" % (n, d["value"]))
        elif kind == "loop":
            note(at, "player %d: a loop began (by hand)" % n)
        elif kind == "loop_end":
            note(at, "player %d: its loop ended (by hand)" % n)
        elif kind == "jump":
            note(at, "player %d: jumped from beat %d to %d (a hot cue, a beat jump or a search: by hand)"
                 % (n, d["from"], d["to"]))
        elif kind == "search":
            note(at, "player %d: searched in its track (by hand)" % n)
        elif kind == "eject":
            note(at, "player %d: its track was ejected (by hand)" % n)
        elif kind == "stopped":
            note(at, "player %d stopped (%s)" % (n, d["state"]))
        elif kind == "joined":
            note(at, "player %d came on the link with track %d loaded: not replayed" % (n, d["rbid"]))
    # an expectation waits until it holds, and the next steps wait for it: it waits no longer than the gap to the next
    for i, (at, step, match, within) in enumerate(actions):
        steps.append(dict({"at": at}, **step))
        if match is None:
            continue
        gap = actions[i + 1][0] - at if i + 1 < len(actions) else within
        steps.append({"at": at, "do": "expect_player", "player": step["player"], "match": match,
                      "within": round(max(0.5, min(within, gap - 0.1)), 2)})
    steps = setup + sorted(steps, key=lambda s: s["at"])
    scenario = {"name": name, "steps": steps}
    if notes:
        scenario["notes"] = notes
    return scenario


def merge_pitch(events):
    """One note for a pitch fader moved in one go: the last value of each player's run of moves."""
    out, last = [], {}
    for event in events:
        t, n, kind, d = event
        if kind == "pitch" and n in last and t - out[last[n]][0] <= MERGE and out[last[n]][2] == "pitch":
            out[last[n]] = (out[last[n]][0], n, "pitch", d)
            continue
        if kind == "pitch":
            last[n] = len(out)
        out.append(event)
    return out


def clock(seconds):
    return "%d:%04.1f" % (seconds // 60, seconds % 60)


def from_capture(packets, name=None):
    """The scenario of a mix from a capture of the link (the packets as the bench exports or --capture writes them)."""
    from .capture import replay_packets
    recorder = MixRecorder(clock=lambda: 0.0)
    recorder.start(0.0)
    replay_packets(packets, mix=recorder)
    return recorder.stop(name or "Mix from a capture")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("capture", help="a capture of the link: Export capture's JSON, or --capture's JSON Lines")
    parser.add_argument("--out", help="write the scenario there instead of printing it")
    parser.add_argument("--name", help="the scenario's name")
    args = parser.parse_args()
    from .capture import read_capture
    try:
        scenario = from_capture(read_capture(args.capture), args.name)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    text = json.dumps(scenario, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
