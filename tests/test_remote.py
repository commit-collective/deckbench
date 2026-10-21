# SPDX-License-Identifier: MIT OR Apache-2.0
"""A page on another origin using the API: who may, and with what."""
import json
import unittest
import urllib.error
import urllib.request

from deckbench.core import Deck, World
from deckbench.web import serve

SITE = "https://commitcollective.cc"


def world_of(*numbers):
    world = World()
    for n in numbers:
        world.decks[n] = Deck(world, n, 128.0, "deck %d" % n)
    return world


def call(url, method="GET", headers=None):
    request = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class Open(unittest.TestCase):
    """No allowed origin and no token: as before, but a page of another origin is refused."""

    @classmethod
    def setUpClass(cls):
        cls.server = serve(world_of(2), "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_a_client_with_no_origin_is_served(self):
        self.assertEqual(call(self.url + "api/state")[0], 200)
        self.assertEqual(call(self.url + "api/deck/2/on/1", "POST")[0], 200)

    def test_the_page_itself_is_served_from_its_own_origin(self):
        origin = self.url.rstrip("/")
        self.assertEqual(call(self.url + "api/state", headers={"Origin": origin})[0], 200)
        self.assertEqual(call(self.url + "api/deck/2/play/1", "POST", {"Origin": origin})[0], 200)

    def test_another_site_cannot_drive_it(self):
        for method, path in (("GET", "api/state"), ("POST", "api/deck/2/on/0"), ("POST", "api/loss/50"), ("OPTIONS", "api/state")):
            status, headers, body = call(self.url + path, method, {"Origin": "https://evil.example"})
            self.assertEqual(status, 403, path)
            self.assertNotIn("Access-Control-Allow-Origin", headers)
            self.assertIn("--allow-origin", json.loads(body)["error"])
        self.assertEqual(call(self.url + "api/state")[0], 200)                    # and nothing was changed
        self.assertEqual(json.loads(call(self.url + "api/state")[2])["loss"], 0.0)

    def test_the_files_are_not_behind_the_check(self):
        self.assertEqual(call(self.url, headers={"Origin": "https://evil.example"})[0], 200)


class Remote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = world_of(2, 3)
        cls.server = serve(cls.world, "127.0.0.1", 0, allow_origins=[SITE + "/"], token="s3cret")
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_the_token_is_needed(self):
        for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic s3cret"}):
            self.assertEqual(call(self.url + "api/state", headers=headers)[0], 401, headers)
        self.assertEqual(call(self.url + "api/state?token=wrong")[0], 401)
        self.assertEqual(call(self.url + "api/deck/2/on/1", "POST")[0], 401)
        self.assertFalse(self.world.decks[2].enabled)

    def test_the_token_opens_it(self):
        self.assertEqual(call(self.url + "api/state?token=s3cret")[0], 200)
        self.assertEqual(call(self.url + "api/state", headers={"Authorization": "Bearer s3cret"})[0], 200)
        self.assertEqual(call(self.url + "api/deck/2/on/1?token=s3cret", "POST")[0], 200)
        self.assertTrue(self.world.decks[2].enabled)
        self.assertEqual(call(self.url + "api/deck/2/on/0", "POST", {"Authorization": "Bearer s3cret"})[0], 200)

    def test_the_files_need_no_token(self):
        self.assertEqual(call(self.url)[0], 200)
        self.assertEqual(call(self.url + "app.js")[0], 200)

    def test_an_allowed_page_gets_the_cors_headers(self):
        status, headers, _ = call(self.url + "api/state?token=s3cret", headers={"Origin": SITE})
        self.assertEqual((status, headers.get("Access-Control-Allow-Origin")), (200, SITE))
        status, headers, _ = call(self.url + "api/deck/3/on/1?token=s3cret", "POST", {"Origin": SITE})
        self.assertEqual((status, headers.get("Access-Control-Allow-Origin")), (200, SITE))

    def test_the_preflight(self):
        status, headers, _ = call(self.url + "api/state", "OPTIONS", {
            "Origin": SITE, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization",
            "Access-Control-Request-Private-Network": "true"})
        self.assertEqual(status, 204)                       # no token in a preflight: a browser sends none
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), SITE)
        self.assertEqual(headers.get("Access-Control-Allow-Private-Network"), "true")
        self.assertIn("Authorization", headers.get("Access-Control-Allow-Headers"))
        self.assertIn("POST", headers.get("Access-Control-Allow-Methods"))
        self.assertEqual(call(self.url + "api/state", "OPTIONS", {"Origin": "https://evil.example"})[0], 403)

    def test_a_page_that_is_not_allowed_is_refused_even_with_the_token(self):
        status, headers, _ = call(self.url + "api/state?token=s3cret", headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_the_stream_is_allowed_too(self):
        request = urllib.request.Request(self.url + "api/stream?token=s3cret", headers={"Origin": SITE})
        with urllib.request.urlopen(request, timeout=5) as r:
            self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), SITE)
            self.assertTrue(r.headers.get("Content-Type").startswith("text/event-stream"))
            self.assertTrue(r.readline().startswith(b"event:"))
        self.assertEqual(call(self.url + "api/stream")[0], 401)


if __name__ == "__main__":
    unittest.main()
