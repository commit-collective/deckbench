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
  expect_unit      what is known of the device under test (the network's word and an adapter's: `heard`, `master`,
                   `synced`, `playing`, `bpm`, `lamp.sync`...) matches `match` within `within` seconds (default 5).
                   With `for`, it must then go on matching for that many seconds. See matching.py for the values.
  expect_deck      the same for a deck's own state (`on`, `play`, `sync`, `master`, `bpm`, `loop`, `unplugged`, `track_rbid`),
                   within `within` seconds (default 2)
  unit             press a control of the device under test through the adapter: `press` (its name) or `send` (a raw line)
  mixer            do something with the simulated mixer: `on` (true or false), `master` (its master level), and for a
                   `channel`: its `fader` (0 to 100), `fader_start` (true or false), or a `command` (start or stop)

Any step can have `when`, a match against the device under test (as in `expect_unit`): the step is done only if it holds
at that moment, so a scenario can bring a device that keeps its state to where it starts: {"do": "unit", "press": "sync",
"when": {"synced": false}}.

A scenario can say what it `requires`: "unit" (the device has announced itself on the link, waited for up to `unit_wait`
seconds, 10 by default) and "adapter" (an adapter is connected, waited for just as long). If one is missing the scenario is
skipped, not failed.

`Scenario.run` does the steps at their times and gives the results: a list of (step, ok, message). Only the expectations and
`unit` can fail.
"""
import json
import threading
import time

from .matching import explain, matches

DECK_ACTIONS = ("on", "off", "play", "stop", "sync", "unsync", "master", "release", "loop", "unloop", "load", "tempo",
                "unplug", "plug", "silence")
ACTIONS = DECK_ACTIONS + ("loss", "log", "expect", "expect_unit", "expect_deck", "unit", "mixer")
REQUIRES = ("unit", "adapter")


class ScenarioError(ValueError):
    pass


class Scenario:
    def __init__(self, data):
        self.name = data.get("name", "scenario")
        self.requires = list(data.get("requires", []))
        for need in self.requires:
            if need not in REQUIRES:
                raise ScenarioError("requires %r: there is only %s" % (need, ", ".join(REQUIRES)))
        self.unit_wait = float(data.get("unit_wait", 10))
        self.skipped = None                 # why it was not run, if it was not
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
        if "when" in step and not isinstance(step["when"], dict):
            raise ScenarioError("step %r: when is a match, like {\"synced\": true}" % (step,))
        if do in DECK_ACTIONS and "deck" not in step:
            raise ScenarioError("step %r: %s needs a deck" % (step, do))
        for key, kinds in (("loop", ("beats",)), ("load", ("id",)), ("tempo", ("bpm",)), ("silence", ("seconds",)),
                           ("loss", ("percent",)), ("log", ("text",)), ("expect", ("event",)),
                           ("expect_unit", ("match",)), ("expect_deck", ("match", "deck"))):
            if do == key:
                for need in kinds:
                    if need not in step:
                        raise ScenarioError("step %r: %s needs %s" % (step, do, need))

    def run(self, world, clock=time.time, sleep=time.sleep, log=None, on_step=None, cancel=None):
        """Runs the steps against the World, at their times (`clock` and `sleep` can be replaced to test). The results.
        `on_step(step, ok, message)` is called after each step, and the run ends early when `cancel()` is true."""
        results = []
        self.skipped = self.unmet(world, clock, sleep, cancel)
        if self.skipped:
            return results
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

    def unmet(self, world, clock=time.time, sleep=time.sleep, cancel=None):
        """What the scenario requires that is not there (a sentence), or None."""
        end = clock() + self.unit_wait
        while True:
            if "adapter" in self.requires and not any(a.connected() for a in world.adapters):
                missing = "it needs an adapter that is connected (--adapter), and none was in %g s" % self.unit_wait
            elif "unit" in self.requires and not world.unit_state().get("heard"):
                missing = "it needs the device under test to be on the link, and none announced itself in %g s" % self.unit_wait
            else:
                return None
            if clock() >= end or (cancel and cancel()):
                return missing
            sleep(0.1)

    @staticmethod
    def wait_for(read, match, within, hold=0.0, clock=time.time, sleep=time.sleep):
        """Waits until `read()` (a dict) matches, for `within` seconds, and then, if `hold`, for that long more.
        (True, message) or (False, what is wrong)."""
        end = clock() + within
        state = read()
        while not matches(state, match):
            if clock() >= end:
                return False, "within %g s: %s" % (within, explain(state, match))
            sleep(0.05)
            state = read()
        began = clock()
        while clock() - began < hold:
            sleep(0.05)
            state = read()
            if not matches(state, match):
                return False, "held %.1f of %g s: %s" % (clock() - began, hold, explain(state, match))
        return True, "after %.2f s" % (clock() - (end - within)) if not hold else "held %g s" % hold

    @staticmethod
    def describe(step):
        """A step in a few words, for a list."""
        extra = ", ".join("%s=%s" % (k, v) for k, v in step.items() if k not in ("at", "do", "deck"))
        return "%s%s%s" % (step["do"], " deck %s" % step["deck"] if "deck" in step else "", " (%s)" % extra if extra else "")

    @staticmethod
    def do(world, step, first_event=0):
        do = step["do"]
        if "when" in step and not matches(world.unit_state(), step["when"]):
            return True, "(not done: %s)" % (explain(world.unit_state(), step["when"]) or "the condition does not hold")
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
            world.load_track(deck, int(step["id"]), step.get("title"), step.get("bpm"), step.get("source"), step.get("slot"))
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
        elif do == "mixer":
            return world.protocol_action("mixer", step)
        elif do == "unit":
            if "press" in step:
                return world.press_unit(control=step["press"])
            if "send" in step:
                return world.press_unit(line=step["send"])
            return False, "unit needs press or send"
        elif do == "expect_unit":
            return Scenario.wait_for(world.unit_state, step["match"], float(step.get("within", 5)), float(step.get("for", 0)))
        elif do == "expect_deck":
            def read():
                state = {}
                snap = world.snapshot()["decks"].get(str(step["deck"]), {})
                state.update(snap)
                return state
            return Scenario.wait_for(read, step["match"], float(step.get("within", 2)), float(step.get("for", 0)))
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
        self.state = {"running": False, "name": None, "total": 0, "results": [], "failed": 0, "stopped": False,
                      "skipped": None}

    def start(self, data):
        """Starts playing `data` (what a scenario file holds). ScenarioError if it is not one, RuntimeError if one plays."""
        scenario = Scenario(data)
        with self.lock:
            if self.state["running"]:
                raise RuntimeError("a scenario is playing")
            self.stopping = False
            self.state = {"running": True, "name": scenario.name, "total": len(scenario.steps), "results": [],
                          "failed": 0, "stopped": False, "skipped": None}
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
                self.state["skipped"] = scenario.skipped

    def stop(self):
        self.stopping = True

    def snapshot(self):
        with self.lock:
            return dict(self.state, results=list(self.state["results"]))
