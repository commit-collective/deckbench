# SPDX-License-Identifier: MIT OR Apache-2.0
"""The decks, whatever protocol shows them to the network.

A Deck is what any player has: it is on or off, plays or not, is synced or
not, is the tempo master or not, and has a tempo and a place in its bar. The
World holds the decks and changes them together (the master is one, a synced
deck takes the master's tempo and beat). What goes on the wire is the
protocols' (deckbench.protocols), which are told what changes and may take
part in it: a protocol can handle who becomes the master (Pro DJ Link asks the
unit under test, for one), and can say what a deck shows besides this.
"""
import sys
import threading
import time

from .events import Events


def log(text):
    sys.stderr.write("deckbench: %s\n" % text)
    sys.stderr.flush()


class Deck:
    def __init__(self, world, number, bpm, name=None):
        self.world = world
        self.number = number
        self.name = name or "deck %d" % number
        self.base_bpm = bpm
        self.enabled = False
        self.playing = False
        self.sync = False
        self.master = False
        # Where the deck was in its bar, in beats (0.0 is the first beat), at
        # the time anchor_t: its place now is counted on from there.
        self.anchor_t = time.time()
        self.anchor_pos = 0.0
        # A loop: (the beat it starts at, its length in beats), or None. The
        # deck goes round it, so its place never passes the loop's end.
        self.loop = None
        # The cable is pulled: it says nothing and answers nothing (the protocols see to that).
        self.unplugged = False
        self.track = None                    # the track it has loaded: (rekordbox id, title), or None for its first

    def position(self, now):
        """Beats since the bar line, counted on from the anchor at the tempo
        the deck plays at (a stopped deck stays where it stopped), round the
        loop if there is one."""
        if not self.playing:
            return self.anchor_pos
        pos = self.anchor_pos + (now - self.anchor_t) * self.tempo() / 60.0
        if self.loop and pos >= self.loop[0] + self.loop[1]:
            pos = self.loop[0] + (pos - self.loop[0]) % self.loop[1]
        return pos

    def reanchor(self, now):
        self.anchor_pos = self.position(now)
        self.anchor_t = now

    @property
    def beat_in_bar(self):
        """1 to 4."""
        return int(self.position(time.time())) % 4 + 1

    def tempo(self):
        """The tempo it plays at: its own, or the master's if it is synced."""
        if self.master or not self.sync:
            return self.base_bpm
        return self.world.master_bpm() or self.base_bpm


class World:
    def __init__(self):
        self.decks = {}
        self.protocols = []
        self.lock = threading.RLock()
        self.listeners = []                  # called, with no argument, after a change
        self.events = Events()               # what the device under test did, to wait for and check (events.py)
        self.loss = 0.0                      # the share of the datagrams of all the decks that is lost, 0 to 1
        self.info = {}                       # how the bench was started (strict, sound...), for the page to say

    # -- what the decks are, together --
    def master_deck(self):
        for deck in self.decks.values():
            if deck.enabled and deck.master:
                return deck
        return None

    def master_bpm(self):
        """The tempo of the master, a deck or something on the network that
        a protocol knows of; None if there is none."""
        deck = self.master_deck()
        if deck:
            return deck.tempo()
        for protocol in self.protocols:
            bpm = protocol.external_master_bpm()
            if bpm:
                return bpm
        return None

    def settle(self, change):
        """Runs `change`, which alters what the decks are (who is the master,
        who syncs, who plays), keeping every deck's place in its bar through
        the change, and then putting the synced ones on the master's beat."""
        with self.lock:
            now = time.time()
            for deck in self.decks.values():
                deck.reanchor(now)
            change()
            now = time.time()
            master = self.master_deck()
            for deck in self.decks.values():
                if (deck.enabled and deck.playing and deck.sync and master
                        and master is not deck and master.playing):
                    deck.anchor_t = now
                    deck.anchor_pos = master.position(now)

    def changed(self):
        for listener in list(self.listeners):
            listener()

    def snapshot(self):
        """What the decks are, as JSON-able data. A deck's `phase` is, while it
        plays, [time, beats into its bar at that time, tempo]: a viewer counts
        on from it."""
        with self.lock:
            decks = {}
            for n, d in self.decks.items():
                entry = {"on": d.enabled, "play": d.playing, "sync": d.sync,
                         "master": d.master and d.enabled, "bpm": round(d.tempo(), 2),
                         "name": d.name, "loop": d.loop[1] if d.loop else 0, "loop_from": d.loop[0] if d.loop else 0,
                         "unplugged": d.unplugged,
                         "phase": [d.anchor_t, d.anchor_pos, round(d.tempo(), 2)]
                         if d.enabled and d.playing else None}
                for protocol in self.protocols:
                    entry.update(protocol.describe(d))
                decks[str(n)] = entry
            info = {p.name: p.info() for p in self.protocols}
        return {"now": time.time(), "decks": decks, "protocols": info, "loss": round(self.loss * 100, 1),
                "bench": dict(self.info)}

    # -- what is done to a deck --
    def set_enabled(self, deck, on):
        if on and not all(p.allow_enable(deck) for p in self.protocols):
            return False
        def change():
            deck.enabled = on
            if not on:
                deck.master = False
        self.settle(change)
        for protocol in self.protocols:
            protocol.deck_enabled(deck, on)
        log("%s %s" % (deck.name, "on" if on else "off"))
        self.changed()
        return True

    def set_play(self, deck, on):
        def change():
            deck.playing = on
            if on:                           # from the first beat of a bar
                deck.anchor_t = time.time()
                deck.anchor_pos = 0.0
        self.settle(change)
        log("%s %s" % (deck.name, "plays" if on else "stops"))
        self.changed()

    def set_loop(self, deck, beats):
        """Sets a loop of `beats` beats (a whole number) that starts at the
        beat the deck is in, or ends the loop (beats 0)."""
        def change():
            if beats:
                deck.loop = (float(int(deck.position(time.time()))), float(beats))
            else:
                deck.loop = None
        self.settle(change)
        log("%s %s" % (deck.name, "loops %d beats" % beats if beats else "leaves its loop"))
        self.changed()

    def set_tempo(self, deck, bpm):
        """The pitch fader: the deck plays at `bpm` (its place in its bar is kept)."""
        def change():
            deck.base_bpm = float(bpm)
        self.settle(change)
        log("%s plays at %.1f BPM" % (deck.name, deck.base_bpm))
        self.changed()

    def load_track(self, deck, rbid, title=None, bpm=None, source=None, slot=None):
        """The deck loads the track with that rekordbox id (from its own database unless `source`, the number of the
        player it comes from, says otherwise, in `slot` if one is given, with that title if one is given, and at that
        tempo): it starts from its first beat, as a loaded track does, and the protocols tell the network."""
        def change():
            deck.track = (int(rbid), title)
            if bpm:
                deck.base_bpm = float(bpm)
            deck.anchor_t = time.time()
            deck.anchor_pos = 0.0
            deck.loop = None
        self.settle(change)
        for protocol in self.protocols:
            protocol.track_loaded(deck, int(rbid), title, source, slot)
        log("%s loads track %d%s" % (deck.name, int(rbid), " (%s)" % title if title else ""))
        self.changed()

    def set_unplugged(self, deck, on):
        """Pulls the cable (the deck says nothing and answers nothing) or plugs it in again."""
        deck.unplugged = bool(on)
        log("%s %s" % (deck.name, "is unplugged" if on else "is plugged in"))
        self.changed()

    def silence(self, deck, seconds):
        """Unplugs the deck for `seconds`, then plugs it in."""
        self.set_unplugged(deck, True)
        timer = threading.Timer(float(seconds), self.set_unplugged, args=(deck, False))
        timer.daemon = True
        timer.start()

    def set_loss(self, percent):
        """`percent` of the datagrams of all the decks are lost (0 for none)."""
        self.loss = max(0.0, min(100.0, float(percent))) / 100.0
        log("%.0f %% of the datagrams are lost" % (self.loss * 100))
        self.changed()

    def set_sync(self, deck, on):
        def change():
            deck.sync = on
        self.settle(change)
        log("%s sync %s: %.1f BPM" % (deck.name, "on" if on else "off", deck.tempo()))
        self.changed()

    def set_master(self, deck, on):
        """Makes the deck the tempo master, or lets go of the role."""
        if not on:
            def release():
                deck.master = False
            self.settle(release)
            for protocol in self.protocols:
                protocol.master_released(deck)
            log("%s is no longer the master" % deck.name)
            self.changed()
            return
        for protocol in self.protocols:
            if protocol.take_master(deck):   # the protocol sees to it, and reports
                return

        def take():
            for other in self.decks.values():
                other.master = False
            deck.master = True
        self.settle(take)
        log("%s is now the master" % deck.name)
        self.changed()

    def toggle(self, deck, what):
        """What a click on a deck's switch does; False if there is no such."""
        if what == "on":
            self.set_enabled(deck, not deck.enabled)
        elif not deck.enabled:
            return what in ("play", "sync", "master")
        elif what == "play":
            self.set_play(deck, not deck.playing)
        elif what == "sync":
            self.set_sync(deck, not deck.sync)
        elif what == "master":
            self.set_master(deck, not deck.master)
        else:
            return False
        return True


class Protocol:
    """What a protocol gives the World to call. All do nothing here."""
    name = "protocol"

    def external_master_bpm(self):
        """The tempo of a master that is not one of the decks, or None."""
        return None

    def describe(self, deck):
        """More to show about a deck: a dict that goes in its snapshot."""
        return {}

    def info(self):
        """More to show about the protocol's side: a dict."""
        return {}

    def allow_enable(self, deck):
        """False if a deck must stay off (the protocol says why in the log)."""
        return True

    def deck_enabled(self, deck, on):
        pass

    def master_released(self, deck):
        pass

    def track_loaded(self, deck, rbid, title, source=None, slot=None):
        """The deck has loaded a track (its rekordbox id, its title if one was given, the player it comes from and the
        slot, if they were given: otherwise it is from the deck's own database)."""
        pass

    def settings(self):
        """What can be changed while the bench runs: a dict of name: value."""
        return {}

    def set_option(self, name, value):
        """Changes one of the settings. False if there is no such setting or the value is not one."""
        return False

    def take_master(self, deck):
        """Takes care of the deck becoming the master. True if it did (the
        World then does nothing more), False to leave it to the World."""
        return False
