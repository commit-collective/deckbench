# SPDX-License-Identifier: MIT OR Apache-2.0
"""Recording what the real players do during a mix, as a scenario that plays it again on them.

    python -m deckbench.mixrecord CAPTURE.json [--out mix.json]

While a recording runs, every status of a real player (not the bench's own decks, not the device under test) is compared
with the one before. What changed becomes an event: a track loaded, PLAY, a pause, CUE (pressed, or held for a while),
SYNC on or off, MASTER taken. `MixRecorder.stop` turns them into scenario steps: `player` to do it again, then
`expect_player` to check that the player did it.

A track's title and artist, when the bench has read them, go with its load. When a mixer reports what is on air, the
changes are noted for bringing each channel in by hand. Hot cues, beat jumps and loop buttons sent by the bench
to a CDJ-2000NXS2 are captured as explicit presses. Unexplained loops and position changes, pitch moves and ejects
are kept as `log` steps and notes.

A PLAY pressed while another player was the tempo master and playing is replayed on the same beat of the master's
bar (`on_beat`): it is sent from half a bar before its time and waits for that beat, so it lands on the beat nearest
to where it was, at the master's tempo of the replay.

A replay begins with a setup: each player is checked (on the link, the same model, stopped) and loads the track it had
when the recording began. The recorded events follow, at their seconds after the start of the recording plus the setup's
time. A track starts from where the player puts it when it loads (its cue, or its first beat): a mix that played a track
from elsewhere is noted.
"""
import argparse
import json
import threading
import time

from .protocols.monitor import model_title
from .protocols.transport import NXS2_BEAT_LOOPS, NXS2_EXTRA_SETTLE, NXS2_HOT_CUES, NXS2_JUMPS
from .protocols.prolink import Prolink

RUNNING = ("playing", "looping")
HELD = ("cue playing", "cue scratching")
SLOT_NAMES = {2: "sd", 3: "usb"}     # what a player can be told to load from: another player's (1 to 6) SD or USB
JOINED = 1.5            # a player first heard this many seconds into a recording joined the link then
SETUP = 12.0            # the setup's seconds before the first recorded event, with loads to wait for
SETUP_PLAIN = 3.0       # the same when no player loads a track before the mix
PITCH_STEP = 0.1        # a pitch moved by less, in percent, is not noted
JUMP_BEATS = 4          # a playing track whose beat is this far from where it should be has jumped
MERGE = 3.0             # pitch moves of one player closer in time than this are one note
BUTTON_STATUS_WINDOW = 0.6   # allow three status intervals for the effect of a press
STATUS_LAG = 0.1        # a status says a player started about this long after PLAY was pressed (they come each 0.2 s)


class MixRecorder:
    """Keeps the changes of the real players between `start` and `stop`. `observe` is called with each status."""

    def __init__(self, clock=time.time, titles=None):
        self.clock = clock
        self.titles = titles        # (source, slot, rbid): what the bench read of that track ({"title", "artist"}), or None
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

    def observe(self, number, name, st, now):
        """A status of player `number`, whose device name is `name` (the monitor's status dict), heard at `now`."""
        with self.lock:
            if self.began is None or not number or st.get("state") == "loading":
                return
            t = max(0.0, now - self.began)
            p = self.players.get(number)
            if p is None:
                self._add_player(number, name, st, t)
                if t > JOINED and st.get("rbid"):
                    self.events.append((t, number, "joined", {"rbid": st["rbid"], "state": st["state"]}))
                return
            self._compare(number, p, p["last"], st, p["last_t"], t)
            p["last"], p["last_t"] = dict(st), t
            window = st.get("beat_window")
            if window and st.get("bar") and st.get("state") in RUNNING:     # its beat changed: when, and where in the bar
                p["beat_t"], p["beat_bar"] = (window[0] + window[1]) / 2.0 - self.began, st["bar"]

    def _add_player(self, number, name, st, t):
        self.players[number] = {"name": name, "model": model_title(name), "first": dict(st), "first_t": t,
                                "last": dict(st), "last_t": t, "hold": None, "pitch": st.get("pitch")}

    def command(self, device, button, now):
        """Keep the actual press time and the reported track and loop context."""
        with self.lock:
            if self.began is None or now < self.began:
                return
            number, st = device["number"], device["status"]
            at = now - self.began
            if number not in self.players:
                self._add_player(number, device["name"], st, at)
            context = {key: st[key] for key in ("source", "slot", "rbid")}
            self.events.append((at, number, "button", {"press": button, "track": context, "loop": st["loop"]}))

    def master_beat(self, number, t):
        """The beat of the master's bar that player `number`'s start at `t` fell on: {"player", "beat", "period"}, or
        None when no other player was the master and playing, with its beats known."""
        for n, q in self.players.items():
            st = q["last"]
            if (n != number and st.get("master") and st.get("state") in RUNNING and st.get("bpm")
                    and q.get("beat_t") is not None):
                period = 60.0 / st["bpm"]
                k = round((t - STATUS_LAG - q["beat_t"]) / period)
                return {"player": n, "beat": int((q["beat_bar"] - 1 + k) % 4) + 1, "period": period}
        return None

    def _compare(self, number, p, prev, st, prev_t, t):
        track = {key: st[key] for key in ("source", "slot", "rbid")}
        add = lambda kind, **details: self.events.append((t, number, kind, {"track": track, **details}))
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
                at = began if began is not None else t
                self.events.append((at, number, "play", {"from": prev.get("track_beat"), "on": self.master_beat(number, at)}))
            elif began is not None:
                self.events.append((began, number, "cue_hold", {"seconds": round(t - began, 2)}))
        elif was not in RUNNING and now in RUNNING:
            add("play", **{"from": prev.get("track_beat"), "on": self.master_beat(number, t)})
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
        if bool(st.get("on_air")) != bool(prev.get("on_air")):      # set by a mixer on the link: none, no change
            add("on_air" if st.get("on_air") else "off_air")
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
        return build(players, events, name or "Mix recorded %s" % stamp, self.titles)


def slot_of(slot):
    return SLOT_NAMES.get(slot, slot)


def loadable(source, slot):
    """Whether the bench can tell a player to load a track from there: a player's SD or USB, not a computer's
    rekordbox (a source above 6) or a CD."""
    return 1 <= (source or 0) <= 6 and slot in SLOT_NAMES


def transport(p):
    """How a player is played: 'buttons' (PLAY/PAUSE and CUE), 'fader' (fader start's start and stop only) or ''."""
    return Prolink.transport_method({"name": p.get("name") or p.get("model") or ""})


def build(players, events, name, titles=None):
    """The scenario of a recording: `players` as MixRecorder keeps them, `events` its (t, number, kind, details).
    `titles(source, slot, rbid)` names the tracks the bench read."""
    notes, setup, steps = [], [], []

    def named(source, slot, rbid):
        """"Title (Artist)" of a track, or None."""
        try:
            found = titles(source, slot, rbid) if titles else None
        except Exception:
            found = None
        if not found or not found.get("title"):
            return None
        return found["title"] + (" (%s)" % found["artist"] if found.get("artist") else "")

    def track(rbid, title):
        return "track %d%s" % (rbid, " (%s)" % title if title else "")
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
        setup.append({"at": 0, "do": "expect_player", "player": n, "match": match, "within": 5, "required": True})
    for n, p in loads.items():
        st = p["first"]
        title = named(st["source"], st["slot"], st["rbid"])
        if not loadable(st["source"], st["slot"]):
            note(0.5, "player %d: load %s by hand (from player %d, slot %d: the bench cannot load from there)"
                 % (n, track(st["rbid"], title), st["source"], st["slot"]))
            setup.append({"at": 0.5, "do": "expect_player", "player": n, "match": {"rbid": st["rbid"]}, "within": 10,
                          "required": True})
            continue
        setup.append(dict({"at": 0.5, "do": "player", "player": n, "load": st["rbid"], "source": st["source"],
                           "slot": slot_of(st["slot"])}, **({"title": title} if title else {})))
        setup.append({"at": 0.5, "do": "expect_player", "player": n, "match": {"rbid": st["rbid"]}, "within": 10,
                      "required": True})
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
    # A prompt status can arrive on the same clock tick as the command.
    ordered = sorted(events, key=lambda event: (event[0], event[2] != "button"))
    events = merge_pitch(match_button_status(ordered))
    actions = []                    # (at, step, expectation, default within)
    for t, n, kind, d in events:
        at = round(lead + t, 2)
        how = transport(players.get(n, {}))
        if kind in ("play", "pause", "cue", "cue_hold") and how != "buttons":
            fader = how == "fader"
            if kind == "play" and fader:
                actions.append(on_beat(at, {"do": "player", "player": n, "press": "start"}, d.get("on")) + ({"play": True}, 2))
            elif kind == "cue" and fader:          # fader start's stop takes the player back to its cue
                actions.append((at, {"do": "player", "player": n, "press": "stop"}, {"play": False}, 2))
            elif kind == "pause" and fader:
                actions.append((at, {"do": "player", "player": n, "press": "stop"}, {"play": False}, 2))
                note(at, "player %d: paused here, which fader start cannot do: it goes back to its cue instead" % n)
            else:
                note(at, "player %d (%s): %s by hand (the bench cannot press it on this model)"
                     % (n, players.get(n, {}).get("model") or "?", {"play": "PLAY", "pause": "PAUSE", "cue": "CUE",
                                                                    "cue_hold": "CUE held"}[kind]))
            if kind == "play" and d.get("already"):
                note(at, "player %d was playing when the recording began: it starts from where it loads, not from "
                         "where it was" % n)
            continue
        if kind == "button":
            match = {"model": players[n]["model"], "online": True, **d["track"]}
            if d["press"] in LOOP_BUTTONS or d["press"] in NXS2_BEAT_LOOPS:
                match["loop"] = d["loop"]
            send_at = round(at - NXS2_EXTRA_SETTLE, 2)
            steps.append({"at": send_at, "do": "expect_player", "player": n, "match": match,
                          "within": 0.2, "required": True})
            actions.append((at, {"do": "player", "player": n, "press": d["press"], "send_at": send_at},
                            d.get("result"), 1))
        elif kind == "load":
            title = named(d["source"], d["slot"], d["rbid"])
            if not loadable(d["source"], d["slot"]):
                note(at, "player %d: load %s by hand (from player %d, slot %d: the bench cannot load from there)"
                     % (n, track(d["rbid"], title), d["source"], d["slot"]))
                continue
            actions.append((at, dict({"do": "player", "player": n, "load": d["rbid"], "source": d["source"],
                                      "slot": slot_of(d["slot"])}, **({"title": title} if title else {})),
                            {"rbid": d["rbid"]}, 10))
        elif kind == "play":
            actions.append(on_beat(at, {"do": "player", "player": n, "press": "play-pause"}, d.get("on")) + ({"play": True}, 2))
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
        elif kind == "on_air":
            note(at, "player %d on air (its channel fader up)" % n)
        elif kind == "off_air":
            note(at, "player %d off air (its channel fader down)" % n)
        elif kind == "eject":
            note(at, "player %d: its track was ejected (by hand)" % n)
        elif kind == "stopped":
            note(at, "player %d stopped (%s)" % (n, d["state"]))
        elif kind == "joined":
            note(at, "player %d came on the link with track %d loaded: not replayed" % (n, d["rbid"]))
    # an expectation waits until it holds, and the next steps wait for it: it waits no longer than the gap to the next
    for i, (at, step, match, within) in enumerate(actions):
        sent = step.pop("send_at", at)                  # a step on a beat is sent before its time and waits for the beat
        steps.append(dict({"at": sent}, **step))
        if match is None:
            continue
        gap = actions[i + 1][0] - at if i + 1 < len(actions) else within
        check = {"at": at, "do": "expect_player", "player": step["player"], "match": match,
                 "within": round(max(0.5, min(within, gap - 0.1)), 2)}
        if "on_beat" in step:                           # and how close to that beat it came
            check["phase_to"] = {"player": step["on_beat"]["player"]}
        steps.append(check)
    steps = setup + sorted(steps, key=lambda s: s["at"])
    scenario = {"name": name, "steps": steps}
    if notes:
        scenario["notes"] = notes
    return scenario


LOOP_BUTTONS = {"loop-in", "loop-out", "four-beat-loop", "reloop-exit"}
BUTTON_EFFECTS = {
    **dict.fromkeys(NXS2_HOT_CUES, {"jump", "loop", "loop_end", "play"}),
    **dict.fromkeys(NXS2_JUMPS, {"jump"}),
    **dict.fromkeys(NXS2_BEAT_LOOPS, {"loop", "loop_end"}),
    "loop-out": {"loop"}, "four-beat-loop": {"loop", "loop_end"},
    "reloop-exit": {"loop", "loop_end"},
}


def match_button_status(events):
    """Associate one status transition of each expected kind with a recent explicit press."""
    pending = {}
    for at, number, kind, detail in events:
        if kind == "button":
            detail = dict(detail)
            pending[number] = (at, detail, set(BUTTON_EFFECTS.get(detail["press"], ())))
        elif kind in ("load", "eject"):
            pending.pop(number, None)
        elif number in pending:
            sent_at, command, effects = pending[number]
            if at - sent_at > BUTTON_STATUS_WINDOW:
                pending.pop(number)
            elif detail.get("track") == command["track"] and kind in effects:
                effects.remove(kind)
                if kind in ("loop", "loop_end"):
                    command.setdefault("result", {})["loop"] = kind == "loop"
                elif kind == "play":
                    command.setdefault("result", {})["play"] = True
                continue
        yield at, number, kind, detail


def on_beat(at, step, on):
    """(at, step) for an action, on the master's beat it was done on if `on` says one: sent half a bar early."""
    if not on:
        return (at, step)
    step = dict(step, on_beat={"player": on["player"], "beat": on["beat"]}, send_at=round(max(0.0, at - 2 * on["period"]), 2))
    return (at, step)


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
