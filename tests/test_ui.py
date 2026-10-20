# SPDX-License-Identifier: MIT OR Apache-2.0
"""The page's files, the settings and the stream behind it."""
import glob
import json
import os
import re
import unittest
import urllib.error
import urllib.request

from _ports import fresh
from deckbench.core import Deck, World
from deckbench.protocols.prolink import Prolink
from deckbench.scenario import Scenario
from deckbench.web import serve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()
        for n in (2, 3):
            cls.world.decks[n] = Deck(cls.world, n, 128.0, "deck %d" % n)
        cls.ports = fresh()
        cls.prolink = Prolink(cls.world, ports=cls.ports)
        cls.prolink.start()
        cls.server = serve(cls.world, "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def api(self, path, post=True):
        request = urllib.request.Request(self.url + path, method="POST" if post else "GET")
        with urllib.request.urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def test_the_files_are_served(self):
        for path, kind in (("", "text/html"), ("app.css", "text/css"), ("app.js", "text/javascript")):
            status, content_type, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertTrue(content_type.startswith(kind), content_type)
            self.assertTrue(body)

    def test_the_page_has_its_controls(self):
        page = self.get("")[2].decode("utf-8")
        for words in ("Events", "Scenario", "Network", "Settings", "Datagrams lost", "Strict decks", "Refuse the database",
                      'src="app.js"', 'href="app.css"'):
            self.assertIn(words, page)
        script = self.get("app.js")[2].decode("utf-8")
        for call in ("api/stream", "api/deck/", "api/scenario", "api/events/clear", "api/loss/", "api/settings/", "api/examples"):
            self.assertIn(call, script)

    def test_every_id_the_script_uses_is_in_the_page(self):
        page = self.get("")[2].decode("utf-8")
        script = self.get("app.js")[2].decode("utf-8")
        ids = set(re.findall(r'\$\("([\w-]+)"\)', script)) | {"tab-" + t + "" for t in ("events", "scenario", "network", "settings")}
        for name in ids:
            self.assertIn('id="%s"' % name, page, name)

    def test_nothing_else_is_served(self):
        for path in ("../web.py", "web.py", "..%2fweb.py", "nothing.js", "%2e%2e/cli.py"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, 404, path)

    def test_the_examples_are_scenarios(self):
        listed = self.api("api/examples", post=False)
        files = glob.glob(os.path.join(ROOT, "deckbench", "examples", "*.json")) \
            + glob.glob(os.path.join(ROOT, "deckbench", "examples", "unit", "*.json"))
        self.assertEqual(len(listed), len(files))
        self.assertGreaterEqual(len(listed), 10)
        self.assertEqual({e["group"] for e in listed}, {"Examples", "Unit under test"})
        for example in listed:
            Scenario(json.loads(example["text"]))                   # raises if it is not one
            self.assertEqual(json.loads(example["text"])["name"], example["name"])

    def test_settings(self):
        state = self.api("api/settings/strict/1")
        self.assertTrue(state["protocols"]["prolink"]["settings"]["strict"])
        self.assertTrue(all(l.strict for l in self.prolink.decks.values()))
        state = self.api("api/settings/strict/0")
        self.assertFalse(state["protocols"]["prolink"]["settings"]["strict"])
        self.assertTrue(self.api("api/settings/refuse_db/1")["protocols"]["prolink"]["settings"]["refuse_db"])
        self.api("api/settings/refuse_db/0")
        state = self.api("api/settings/model/XDJ-1000MK2")
        self.assertEqual(state["decks"]["2"]["model"], "XDJ-1000MK2")
        self.api("api/settings/model/CDJ-FAKE%d" % 2)
        for bad in ("strict/maybe", "model/" + "x" * 21, "nothing/1", "model/%20"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.api("api/settings/" + bad)
            self.assertEqual(error.exception.code, 400, bad)

    def test_a_track_from_another_decks_database(self):
        self.api("api/deck/2/on/1")
        self.api("api/deck/3/on/1")
        state = self.api("api/deck/2/load/321?title=Caf%C3%A9%20%25%20mix&source=3&slot=2")
        deck = state["decks"]["2"]
        self.assertEqual((deck["track_source"], deck["track_slot"], deck["track_rbid"]), (3, 2, 321))
        self.assertEqual(deck["track"], "Café % mix")                # once decoded, not twice
        self.assertEqual(self.prolink.decks[3].titles[(2, 321)], "Café % mix")
        state = self.api("api/deck/2/load/322")                       # back to its own database, in the same slot
        self.assertEqual(state["decks"]["2"]["track_source"], 2)
        self.assertEqual(state["decks"]["2"]["track"], "Track 322")

    def test_the_stream(self):
        self.api("api/events/clear")
        request = urllib.request.Request(self.url + "api/stream")
        seen = {}
        with urllib.request.urlopen(request, timeout=5) as r:
            self.assertTrue(r.headers.get("Content-Type").startswith("text/event-stream"))
            self.world.events.add("test_event", deck=2)
            kind = None
            while len(seen) < 3:
                line = r.readline().decode("utf-8").rstrip("\r\n")
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: ") and kind:
                    seen[kind] = json.loads(line[6:])
        self.assertEqual(set(seen), {"state", "event", "scenario"})
        self.assertIn("decks", seen["state"])
        self.assertEqual((seen["event"]["kind"], seen["event"]["deck"]), ("test_event", 2))
        self.assertIn("running", seen["scenario"])


if __name__ == "__main__":
    unittest.main()
