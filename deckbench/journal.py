# SPDX-License-Identifier: MIT OR Apache-2.0
"""A journal of what is done to the decks, so that a session can be played again.

`start` takes where the decks are (as requests to the API that would put them there: the baseline) and from then on every request
that changes something is kept with its time. `stop` gives both. The times are the bench's clock (time.time()), so a program that
began something of its own at a known time can place them. Playing it again is sending the baseline and then each request at its
second (a deck that plays begins from the first beat of its bar, as it does when it is started, so the phase of a deck that was playing
when the journal began is not the same).
"""
import threading
import time
from urllib.parse import quote

# the requests that are not changes of the decks: they are not kept
IGNORED = ("journal", "upload", "uploads", "packets", "events", "scenario")


def baseline(world):
    """The requests (paths with their query) that put a bench like this one's decks where they are now."""
    out = []
    with world.lock:
        decks = sorted(world.decks.items())
        for n, d in decks:
            if d.audio:                                   # a file of its own
                rbid, title = d.track or (1000 + n, None)
                path = "/api/deck/%d/load/%d?audio=%s&bpm=%s&offset=%s" % (n, rbid, quote(d.audio.path, safe=""), d.audio.bpm, d.audio.offset)
                if title:
                    path += "&title=" + quote(title, safe="")
                out.append(path)
            elif d.track:
                rbid, title = d.track
                path = "/api/deck/%d/load/%d?bpm=%s" % (n, rbid, d.base_bpm)
                if title:
                    path += "&title=" + quote(title, safe="")
                out.append(path)
        for n, d in decks:
            if d.unplugged:
                out.append("/api/deck/%d/unplug" % n)
            if d.enabled:
                out.append("/api/deck/%d/on/1" % n)
        for n, d in decks:
            if not d.enabled:
                continue
            if d.master:
                out.append("/api/deck/%d/master/1" % n)
            elif d.sync:
                out.append("/api/deck/%d/sync/1" % n)
            else:
                out.append("/api/deck/%d/tempo/%s" % (n, round(d.tempo(), 2)))
        for n, d in decks:
            if d.enabled and d.playing:
                out.append("/api/deck/%d/play/1" % n)
                if d.loop:
                    out.append("/api/deck/%d/loop/%d" % (n, d.loop[1]))
        if world.audio_decks and len(world.audio_decks) == 1:      # the deck the sound port plays
            out.append("/api/audio/source/%d" % next(iter(world.audio_decks)))
    return out


class Journal:
    def __init__(self):
        self.active = False
        self.began = 0.0
        self.baseline = []
        self.actions = []
        self._lock = threading.Lock()

    def start(self, world):
        with self._lock:
            self.baseline = baseline(world)
            self.actions = []
            self.began = time.time()
            self.active = True
            return {"began": self.began, "baseline": list(self.baseline)}

    def note(self, request):
        """A request (path and query) the bench has been asked."""
        if not self.active:
            return
        parts = request.split("?")[0].strip("/").split("/")
        if parts[:1] != ["api"] or parts[1:2] == [] or parts[1] in IGNORED:
            return
        path, _, query = request.partition("?")
        kept = "&".join(p for p in query.split("&") if p and not p.startswith("token="))      # a token is not part of what was done
        with self._lock:
            self.actions.append([round(time.time(), 3), path + ("?" + kept if kept else "")])

    def stop(self):
        with self._lock:
            self.active = False
            return {"began": self.began, "baseline": list(self.baseline), "actions": list(self.actions)}
