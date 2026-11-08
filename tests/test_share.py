# SPDX-License-Identifier: MIT OR Apache-2.0
"""Sharing the bench with phones from the page on its own machine (api/share): a second listener on a local network
address with a token of its own, which only that page can start, see and stop."""
import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from deckbench import phone
from deckbench.core import Deck, World
from deckbench.web import serve


def call(url, method="GET", headers=None):
    """(status, JSON body) of a request."""
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null"), dict(e.headers)


class PlayWhileCueHeld(unittest.TestCase):
    """play/1 while CUE is held plays on (the page's let go on PLAY), rather than doing nothing as for a playing deck."""

    def test_play_1_while_cue_is_held_plays_on(self):
        world = World()
        deck = world.decks[1] = Deck(world, 1, 120.0)
        deck.enabled = True
        server = serve(world, "127.0.0.1", 0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = "http://127.0.0.1:%d/" % server.server_address[1]
        self.assertEqual(call(base + "api/deck/1/cue/1", "POST")[0], 200)
        self.assertTrue(deck.cueing)
        self.assertEqual(call(base + "api/deck/1/play/1", "POST")[0], 200)
        self.assertEqual(call(base + "api/deck/1/cue/0", "POST")[0], 200)
        self.assertTrue(deck.playing and not deck.cueing)


class Share(unittest.TestCase):
    def setUp(self):
        self.address = phone.route_address()
        if not self.address:
            self.skipTest("this machine has no network address to share on")
        patcher = patch("deckbench.phone.interfaces", return_value=[])     # asking the system can take a while
        patcher.start()
        self.addCleanup(patcher.stop)
        self.world = World()
        self.world.decks[1] = Deck(self.world, 1, 120.0)
        self.server = serve(self.world, "127.0.0.1", 0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:%d/" % self.server.server_address[1]

    def test_the_page_here_shares_and_stops(self):
        status, body, _ = call(self.base + "api/share")
        self.assertEqual((status, body["on"], body["fixed"]), (200, False, False))
        self.assertEqual(body["addresses"][0], {"name": "", "address": self.address, "default": True})
        status, body, _ = call(self.base + "api/share/on?address=" + self.address, "POST")
        self.assertEqual((status, body["on"], body["address"]), (200, True, self.address))
        self.addCleanup(lambda: call(self.base + "api/share/off", "POST"))
        token = body["direct"].rpartition("#token=")[2]
        self.assertIn("token=" + token, body["url"])
        self.assertTrue(body["qr"] is None or body["qr"][0].strip("01") == "")
        shared = "http://%s:%d/" % (self.address, body["port"])
        self.assertEqual(call(shared + "api/state")[0], 401)                       # the phones' listener wants its token
        status, _, headers = call(shared + "api/state?token=" + token, headers={"Origin": phone.SITE})
        self.assertEqual((status, headers.get("Access-Control-Allow-Origin")), (200, phone.SITE))   # the hosted page may use it
        self.assertEqual(call(shared + "api/share?token=" + token)[0], 403)        # a phone does not see or change the sharing
        self.assertEqual(call(shared + "api/share/off?token=" + token, "POST")[0], 403)
        self.assertEqual(call(self.base + "api/state")[0], 200)                    # the page here is as it was
        status, body, _ = call(self.base + "api/share/off", "POST")
        self.assertEqual((status, body["on"]), (200, False))
        with self.assertRaises(OSError):
            urllib.request.urlopen(shared + "api/state?token=" + token, timeout=2)

    def test_only_this_machines_own_page_may_share(self):
        port = self.server.server_address[1]
        for headers in ({"Host": "rebound.example:%d" % port}, {"Origin": "https://elsewhere.example"},
                        {"Origin": phone.SITE}):
            self.assertEqual(call(self.base + "api/share/on", "POST", headers)[0], 403, headers)
        self.assertEqual(call(self.base + "api/share/on?address=127.0.0.1", "POST")[0], 400)   # not an address phones reach
        self.assertFalse(call(self.base + "api/share")[1]["on"])

    def test_a_bench_started_with_phone_shows_its_link_and_keeps_it(self):
        self.server.set_phone_link("https://example/app/#token=x", "http://10.0.0.2:8750/#token=x", "10.0.0.2", 8750)
        status, body, _ = call(self.base + "api/share")
        self.assertEqual((status, body["on"], body["fixed"], body["address"]), (200, True, True, "10.0.0.2"))
        self.assertEqual(call(self.base + "api/share/on", "POST")[0], 409)
        self.assertEqual(call(self.base + "api/share/off", "POST")[0], 409)


if __name__ == "__main__":
    unittest.main()
