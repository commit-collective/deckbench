# SPDX-License-Identifier: MIT OR Apache-2.0
"""What the bench saw the device under test do, in order, to wait for and to check.

A protocol adds an event for each thing it sees (a fader start packet, a sync command, a request for a track's title, the
unit becoming the master) and the tests, a scenario or a person read them: `GET /api/events`, `--events FILE` (one JSON
object a line), or in Python:

    world.events.wait("fader_start", timeout=2, deck=2, action="stop")

An event is a dict: `n` (its place in the list, from 0), `t` (seconds since the bench started), `kind`, and what the
kind adds.
"""
import json
import threading
import time


class Events:
    def __init__(self, path=None):
        self.items = []
        self.cond = threading.Condition()
        self.began = time.time()
        self.generation = 0                  # counts the times they were cleared
        self.file = open(path, "a", encoding="utf-8") if path else None

    def add(self, kind, **data):
        with self.cond:
            item = {"n": len(self.items), "t": round(time.time() - self.began, 3), "kind": kind}
            item.update(data)
            self.items.append(item)
            if self.file:
                self.file.write(json.dumps(item) + "\n")
                self.file.flush()
            self.cond.notify_all()
        return item

    def since(self, n=0):
        """The events from place n on."""
        with self.cond:
            return list(self.items[n:])

    def find(self, kind, start=0, **match):
        """The first event of that kind, from place `start` on, that has all of `match`; None if there is none."""
        with self.cond:
            return self._find(kind, start, match)

    def _find(self, kind, start, match):
        for item in self.items[start:]:
            if item["kind"] == kind and all(item.get(k) == v for k, v in match.items()):
                return item
        return None

    def wait(self, kind, timeout=5.0, start=0, **match):
        """Waits until such an event is there, and gives it; None if `timeout` seconds pass first."""
        end = time.time() + timeout
        with self.cond:
            while True:
                item = self._find(kind, start, match)
                if item or time.time() >= end:
                    return item
                self.cond.wait(min(0.2, max(0.0, end - time.time())))

    def clear(self):
        with self.cond:
            self.items = []
            self.generation += 1
            self.began = time.time()
