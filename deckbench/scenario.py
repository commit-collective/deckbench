# SPDX-License-Identifier: MIT OR Apache-2.0
"""A scenario: what the decks do, and what to expect of the device under test, on a timeline.

A JSON file, a list of steps in seconds from the start (stdlib only, no YAML):

    {"name": "a loop and a stop",
     "steps": [
       {"at": 0,   "deck": 2, "do": "on"},
       {"at": 0.5, "deck": 2, "do": "play"},
       {"at": 4,   "deck": 2, "do": "loop", "beats": 4},
       {"at": 8,   "deck": 2, "do": "load", "id": 205, "title": "Another track", "bpm": 124},
       {"at": 12,  "deck": 2, "do": "tempo", "bpm": 126},
       {"at": 14,  "deck": 3, "do": "silence", "seconds": 3},
       {"at": 18,  "do": "loss", "percent": 20},
       {"at": 20,  "do": "expect", "event": "fader_start", "within": 5, "match": {"deck": 2, "action": "stop"}}
     ]}

What a step does (`deck` is the player number where a deck is meant):

  on, off          the deck is switched on or off
  play, stop       it plays from the first beat of its bar, or stops
  sync, unsync     it syncs to the master, or not
  master, release  it takes the tempo master role (from the unit if the unit has it) or lets go of it
  loop, unloop     a loop of `beats` beats from the beat it is in, or none
  load             a track: `id` (rekordbox id), optionally `title` and `bpm` (its tempo; it starts from its first beat)
  tempo            the pitch fader: the deck plays at `bpm`
  unplug, plug     the cable is pulled: the deck says nothing and answers nothing, until it is plugged in again
  silence          unplug for `seconds`, then plug in
  loss             `percent` of the datagrams of all the decks are lost (0 for none)
  log              `text` goes to the log
  expect           an event of the device under test (see events.py) is there within `within` seconds (default 5):
                   `event` is its kind and `match` what it has (e.g. {"deck": 2}). Events since the scenario began count.

`Scenario.run` does the steps at their times and gives the results: a list of (step, ok, message). Only `expect` can fail.
"""
import json
import threading
import time

DECK_ACTIONS = ("on", "off", "play", "stop", "sync", "unsync", "master", "release", "loop", "unloop", "load", "tempo",
                "unplug", "plug", "silence")
ACTIONS = DECK_ACTIONS + ("loss", "log", "expect")


class ScenarioError(ValueError):
    pass


class Scenario:
    def __init__(self, data):
        self.name = data.get("name", "scenario")
        self.steps = sorted((dict(s) for s in data.get("steps", [])), key=lambda s: float(s.get("at", 0)))
        for step in self.steps:
            self.check(step)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    @staticmethod
    def check(step):
        do = step.get("do")
        if do not in ACTIONS:
            raise ScenarioError("step %r: no such action (%s)" % (step, ", ".join(ACTIONS)))
        if do in DECK_ACTIONS and "deck" not in step:
            raise ScenarioError("step %r: %s needs a deck" % (step, do))
        for key, kinds in (("loop", ("beats",)), ("load", ("id",)), ("tempo", ("bpm",)), ("silence", ("seconds",)),
                           ("loss", ("percent",)), ("log", ("text",)), ("expect", ("event",))):
            if do == key:
                for need in kinds:
                    if need not in step:
                        raise ScenarioError("step %r: %s needs %s" % (step, do, need))

    def run(self, world, clock=time.time, sleep=time.sleep, log=None, on_step=None, cancel=None):
        """Runs the steps against the World, at their times (`clock` and `sleep` can be replaced to test). The results.
        `on_step(step, ok, message)` is called after each step, and the run ends early when `cancel()` is true."""
        results = []
        begin = clock()
        first_event = len(world.events.items)
        for step in self.steps:
            while True:
                wait = begin + float(step.get("at", 0)) - clock()
                if cancel and cancel():
                    return results
                if wait <= 0:
                    break
                sleep(min(wait, 0.2))
            ok, message = self.do(world, step, first_event)
            results.append((step, ok, message))
            if on_step:
                on_step(step, ok, message)
            if log:
                log("%6.2f s  %s: %s%s" % (clock() - begin, step["do"], message or "ok", "" if ok else "  FAILED"))
        return results

    @staticmethod
    def describe(step):
        """A step in a few words, for a list."""
        extra = ", ".join("%s=%s" % (k, v) for k, v in step.items() if k not in ("at", "do", "deck"))
        return "%s%s%s" % (step["do"], " deck %s" % step["deck"] if "deck" in step else "", " (%s)" % extra if extra else "")

    @staticmethod
    def do(world, step, first_event=0):
        do = step["do"]
        deck = world.decks.get(int(step["deck"])) if "deck" in step else None
        if "deck" in step and deck is None:
            return False, "no deck %s" % step["deck"]
        if do == "on":
            return True, "" if world.set_enabled(deck, True) else "(left off)"
        if do == "off":
            world.set_enabled(deck, False)
        elif do == "play":
            world.set_play(deck, True)
        elif do == "stop":
            world.set_play(deck, False)
        elif do == "sync":
            world.set_sync(deck, True)
        elif do == "unsync":
            world.set_sync(deck, False)
        elif do == "master":
            world.set_master(deck, True)
        elif do == "release":
            world.set_master(deck, False)
        elif do == "loop":
            world.set_loop(deck, int(step["beats"]))
        elif do == "unloop":
            world.set_loop(deck, 0)
        elif do == "load":
            world.load_track(deck, int(step["id"]), step.get("title"), step.get("bpm"))
        elif do == "tempo":
            world.set_tempo(deck, float(step["bpm"]))
        elif do == "unplug":
            world.set_unplugged(deck, True)
        elif do == "plug":
            world.set_unplugged(deck, False)
        elif do == "silence":
            world.silence(deck, float(step["seconds"]))
        elif do == "loss":
            world.set_loss(float(step["percent"]))
        elif do == "log":
            from .core import log as write
            write(step["text"])
        elif do == "expect":
            found = world.events.wait(step["event"], float(step.get("within", 5)), first_event, **step.get("match", {}))
            if not found:
                return False, "no %s event %s within %s s" % (step["event"], step.get("match", {}), step.get("within", 5))
            return True, "%s at %.2f s" % (step["event"], found["t"])
        return True, ""


class Runner:
    """Plays one scenario at a time in a thread and keeps how far it is, for the page: `snapshot()`."""

    def __init__(self, world):
        self.world = world
        self.lock = threading.Lock()
        self.thread = None
        self.stopping = False
        self.state = {"running": False, "name": None, "total": 0, "results": [], "failed": 0, "stopped": False}

    def start(self, data):
        """Starts playing `data` (what a scenario file holds). ScenarioError if it is not one, RuntimeError if one plays."""
        scenario = Scenario(data)
        with self.lock:
            if self.state["running"]:
                raise RuntimeError("a scenario is playing")
            self.stopping = False
            self.state = {"running": True, "name": scenario.name, "total": len(scenario.steps), "results": [],
                          "failed": 0, "stopped": False}
        self.thread = threading.Thread(target=self._play, args=(scenario,), daemon=True)
        self.thread.start()

    def _on_step(self, step, ok, message):
        with self.lock:
            self.state["results"].append({"at": step.get("at", 0), "what": Scenario.describe(step), "ok": ok,
                                          "message": message})
            if not ok:
                self.state["failed"] += 1

    def _play(self, scenario):
        try:
            scenario.run(self.world, on_step=self._on_step, cancel=lambda: self.stopping)
        finally:
            with self.lock:
                self.state["running"] = False
                self.state["stopped"] = self.stopping

    def stop(self):
        self.stopping = True

    def snapshot(self):
        with self.lock:
            return dict(self.state, results=list(self.state["results"]))
