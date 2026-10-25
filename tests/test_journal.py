# SPDX-License-Identifier: MIT OR Apache-2.0
"""The journal: what is done to the decks is kept, and sent again to another bench it puts that one where the first was."""
import json
import time
import unittest
import urllib.request

from deckbench.core import Deck, World
from deckbench.web import serve


def bench():
    world = World()
    for n in (1, 2):
        world.decks[n] = Deck(world, n, 120.0 + n)
    server = serve(world, "127.0.0.1", 0)
    return world, server, "http://127.0.0.1:%d" % server.server_address[1]


def post(base, path):
    with urllib.request.urlopen(urllib.request.Request(base + path, method="POST"), timeout=5) as r:
        return json.loads(r.read())


class Journal(unittest.TestCase):
    def test_a_session_is_kept_and_plays_again(self):
        world, server, base = bench()
        other, other_server, other_base = bench()
        try:
            post(base, "/api/deck/1/on/1")                            # where it begins: deck 1 on and playing
            post(base, "/api/deck/1/play/1")
            began = post(base, "/api/journal/start")
            self.assertIn("/api/deck/1/on/1", began["baseline"])
            self.assertIn("/api/deck/1/play/1", began["baseline"])
            time.sleep(0.05)
            post(base, "/api/deck/2/on/1?token=secret")
            post(base, "/api/deck/2/tempo/130")
            post(base, "/api/deck/2/play/1")
            post(base, "/api/deck/1/play/0")
            got = post(base, "/api/journal/stop")
            post(base, "/api/deck/2/on/0")                            # after the end: not kept
            self.assertEqual([r for _, r in got["actions"]], ["/api/deck/2/on/1", "/api/deck/2/tempo/130", "/api/deck/2/play/1",
                                                              "/api/deck/1/play/0"])
            self.assertTrue(all(t >= got["began"] for t, _ in got["actions"]))
            for request in got["baseline"] + [r for _, r in got["actions"]]:       # played again on another bench
                post(other_base, request)
            a, b = other.decks[1], other.decks[2]
            self.assertTrue(a.enabled and not a.playing)
            self.assertTrue(b.enabled and b.playing)
            self.assertAlmostEqual(b.tempo(), 130.0)
        finally:
            for s in (server, other_server):
                s.shutdown()
                s.server_close()

    def test_nothing_is_kept_before_it_starts_or_after_it_stops(self):
        world, server, base = bench()
        try:
            post(base, "/api/deck/1/on/1")
            got = post(base, "/api/journal/stop")
            self.assertEqual(got["actions"], [])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
