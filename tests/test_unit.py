# SPDX-License-Identifier: MIT OR Apache-2.0
"""What the bench knows of the device under test, and the scenarios that expect things of it."""
import json
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

from _ports import fresh
from deckbench.adapters import make
from deckbench.adapters.djs1000_emu import Djs1000Emulator, lamp_level
from deckbench.core import Deck, World
from deckbench.matching import explain, matches, matches_value
from deckbench.protocols.prolink import Prolink
from deckbench.scenario import Scenario, ScenarioError
from deckbench.testing import FakeUnit
from deckbench.web import serve

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))


class Matching(unittest.TestCase):
    def test_values(self):
        self.assertTrue(matches_value(3, 3))
        self.assertFalse(matches_value(3, 4))
        self.assertTrue(matches_value(128.2, {"near": 128, "tol": 0.3}))
        self.assertFalse(matches_value(128.4, {"near": 128, "tol": 0.3}))
        self.assertTrue(matches_value(128.4, {"near": 128}))                      # 0.5 by default
        self.assertTrue(matches_value(5, {"min": 5}) and matches_value(5, {"max": 5}))
        self.assertFalse(matches_value(4, {"min": 5}))
        self.assertTrue(matches_value(2, {"in": [1, 2]}))
        self.assertTrue(matches_value(2, {"not": 3}))
        self.assertFalse(matches_value(None, {"near": 1}))
        self.assertFalse(matches_value("x", {"min": 1}))
        self.assertFalse(matches_value(1, {"nothing": 1}))

    def test_states(self):
        state = {"master": True, "bpm": 126.0}
        self.assertTrue(matches(state, {"master": True, "bpm": {"near": 126}}))
        self.assertFalse(matches(state, {"synced": True}))                         # not known: no match
        self.assertTrue(matches(state, {"synced": {"not": True}}))                  # except under "not"
        self.assertEqual(explain(state, {"master": False, "synced": True, "bpm": {"near": 126}}),
                         "master is True (wanted False), synced is not known (wanted True)")


class Heard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()
        for n in (2, 3):
            cls.world.decks[n] = Deck(cls.world, n, 128.0, "deck %d" % n)
        cls.ports = fresh()
        Prolink(cls.world, ports=cls.ports).start()
        cls.unit = FakeUnit(cls.ports)

    @classmethod
    def tearDownClass(cls):
        cls.unit.close()

    def send(self, **status):
        for _ in range(3):
            self.unit.announce()
            self.unit.status(**status)
            time.sleep(0.05)

    def test_01_nothing_is_heard_at_first(self):
        self.assertEqual(self.world.unit_state(), {"heard": False})

    def test_02_what_the_unit_says(self):
        self.send(master=True, synced=False, playing=True, bpm=100.0, pitch=0x100000 + 0x100000 // 10, beat=3)
        state = self.world.unit_state()
        self.assertTrue(state["heard"])
        self.assertEqual((state["number"], state["ip"]), (1, "127.0.0.1"))
        self.assertEqual((state["master"], state["synced"], state["playing"]), (True, False, True))
        self.assertEqual((state["track_bpm"], state["bpm"], state["beat"]), (100.0, 110.0, 3))   # the pitch is +10 %
        self.assertAlmostEqual(state["pitch_percent"], 10.0, places=1)
        kinds = [e["kind"] for e in self.world.events.since(0)]
        self.assertIn("unit_seen", kinds)
        self.assertIn("unit_master", kinds)
        self.assertIn("unit_play", kinds)
        self.assertNotIn("unit_sync", kinds)

    def test_03_changes_are_events(self):
        before = len(self.world.events.items)
        self.send(master=False, synced=True, playing=False, bpm=100.0)
        kinds = [(e["kind"], e["on"]) for e in self.world.events.since(before) if "on" in e]
        self.assertIn(("unit_sync", True), kinds)
        self.assertIn(("unit_play", False), kinds)
        self.assertIn(("unit_master", False), kinds)

    def test_04_the_snapshot_leaves_out_what_changes_all_the_time(self):
        snap = self.world.snapshot()
        self.assertIn("synced", snap["unit_state"])
        self.assertNotIn("beat", snap["unit_state"])
        self.assertNotIn("age", snap["unit_state"])

    def test_05_expect_unit(self):
        self.send(master=True, synced=True, playing=True, bpm=126.0)
        ok = Scenario.do(self.world, {"do": "expect_unit", "match": {"master": True, "bpm": {"near": 126, "tol": 0.1}}, "within": 1})
        self.assertTrue(ok[0], ok)
        bad = Scenario.do(self.world, {"do": "expect_unit", "match": {"master": False, "bpm": {"near": 130}}, "within": 0.3})
        self.assertFalse(bad[0])
        self.assertIn("master is True (wanted False)", bad[1])
        self.assertIn("bpm is 126.0 (wanted near 130 +-0.5)", bad[1])

    def test_06_expect_unit_for(self):
        def change():
            time.sleep(0.4)
            self.send(master=False, synced=True, playing=True, bpm=126.0)
        self.send(master=True, synced=True, playing=True, bpm=126.0)
        threading.Thread(target=change).start()
        held = Scenario.do(self.world, {"do": "expect_unit", "match": {"master": True}, "within": 1, "for": 1.5})
        self.assertFalse(held[0])
        self.assertIn("held", held[1])

    def test_07_expect_deck(self):
        self.world.set_enabled(self.world.decks[2], True)
        self.assertTrue(Scenario.do(self.world, {"do": "expect_deck", "deck": 2, "match": {"on": True, "bpm": {"near": 128}}})[0])
        bad = Scenario.do(self.world, {"do": "expect_deck", "deck": 2, "match": {"play": True}, "within": 0.2})
        self.assertFalse(bad[0])
        self.assertIn("play is False (wanted True)", bad[1])
        self.assertEqual(Scenario.do(self.world, {"do": "expect_deck", "deck": 9, "match": {"on": True}}),
                         (False, "no deck 9"))

    def test_08_a_scenario_that_needs_a_unit_runs_when_there_is_one(self):
        scenario = Scenario({"name": "x", "requires": ["unit"], "steps": [{"at": 0, "do": "log", "text": "hi"}]})
        results = scenario.run(self.world, log=None)
        self.assertEqual((len(results), scenario.skipped), (1, None))


class Skipped(unittest.TestCase):
    def test_a_missing_unit_skips_the_scenario(self):
        world = World()
        scenario = Scenario({"name": "x", "requires": ["unit"], "unit_wait": 0.3, "steps": [{"at": 0, "do": "log", "text": "hi"}]})
        self.assertEqual(scenario.run(world), [])
        self.assertIn("none announced itself in 0.3 s", scenario.skipped)

    def test_a_missing_adapter_skips_it(self):
        scenario = Scenario({"name": "x", "requires": ["adapter"], "unit_wait": 0.2, "steps": []})
        scenario.run(World())
        self.assertIn("adapter", scenario.skipped)

    def test_the_requirements_are_checked(self):
        with self.assertRaises(ScenarioError):
            Scenario({"requires": ["magic"], "steps": []})
        with self.assertRaises(ScenarioError):
            Scenario({"steps": [{"do": "expect_deck", "match": {"on": True}}]})        # no deck
        with self.assertRaises(ScenarioError):
            Scenario({"steps": [{"do": "expect_unit"}]})                                # no match


class FakeShim:
    """What the emulator's link is, as far as the adapter is concerned: it sends lamp frames and takes lines."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.lines, self.conn, self.frame = [], None, bytearray(128)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        try:
            self.conn, _ = self.srv.accept()
            self.show()
            buf = b""
            while True:
                data = self.conn.recv(4096)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self.lines.append(line.decode())
        except OSError:
            pass

    def show(self, sync=0, master=0):
        """sync and master: the lamp's bits (0 off, 3 dim, 1 bright)."""
        self.frame[0x6A] = (self.frame[0x6A] & ~0x0F) | sync | master << 2
        screen = b"S" + bytes(1) + struct.pack("<HHH", 0, 1, 2) + bytes(8)        # a row of 2 pixels, to be read past
        sound = b"A" + bytes(1) + struct.pack("<HHH", 1, 0, 0) + bytes(8)
        lamps = b"L" + bytes(1) + struct.pack("<HHH", 0, 0, 0) + bytes(self.frame)
        if self.conn:
            self.conn.sendall(screen + sound + lamps)

    def close(self):
        self.srv.close()
        if self.conn:
            self.conn.close()


class Adapter(unittest.TestCase):
    def setUp(self):
        self.shim = FakeShim()
        self.adapter = Djs1000Emulator("127.0.0.1:%d" % self.shim.port)
        self.adapter.start(World())
        end = time.time() + 5
        while not self.adapter.connected() and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(self.adapter.connected())

    def tearDown(self):
        self.adapter.stop()
        self.shim.close()

    def wait(self, check):
        end = time.time() + 3
        while time.time() < end:
            if check(self.adapter.state()):
                return True
            time.sleep(0.05)
        return False

    def test_the_lamps(self):
        self.assertTrue(self.wait(lambda s: s.get("lamp.sync_level") == 0))
        self.shim.show(sync=1, master=3)                        # SYNC bright, MASTER dim
        self.assertTrue(self.wait(lambda s: s.get("lamp.sync") is True))
        state = self.adapter.state()
        self.assertEqual((state["lamp.sync_level"], state["lamp.master_level"], state["lamp.master"]), (2, 1, False))
        self.shim.show(sync=3, master=1)
        self.assertTrue(self.wait(lambda s: s.get("lamp.master") is True and s.get("lamp.sync") is False))

    def test_pressing(self):
        self.assertEqual(self.adapter.press("sync"), (True, ""))
        self.assertEqual(self.adapter.press("master"), (True, ""))
        self.assertEqual(self.adapter.send("tap 1 2"), (True, ""))
        ok, why = self.adapter.press("shift")
        self.assertFalse(ok)
        self.assertIn("sync, master", why)
        end = time.time() + 3
        while len(self.shim.lines) < 3 and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(self.shim.lines, ["tap 6 5", "tap 6 6", "tap 1 2"])

    def test_a_scenario_presses_and_expects_through_it(self):
        world = World()
        world.adapters.append(self.adapter)
        self.shim.show(sync=1)
        scenario = Scenario({"name": "x", "requires": ["adapter"], "steps": [
            {"at": 0, "do": "unit", "press": "sync"},
            {"at": 0, "do": "expect_unit", "match": {"lamp.sync": True, "lamp.master": False}, "within": 3},
            {"at": 0, "do": "unit", "press": "nothing"}]})
        results = scenario.run(world)
        self.assertEqual([ok for _, ok, _ in results], [True, True, False])
        self.assertIsNone(scenario.skipped)
        end = time.time() + 3
        while not self.shim.lines and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(self.shim.lines[:1], ["tap 6 5"])

    def test_it_says_when_the_emulator_is_gone(self):
        self.shim.close()
        self.adapter.stop()
        self.assertFalse(self.adapter.press("sync")[0])
        self.assertEqual(lamp_level(bytes([0] * 128), "sync"), 0)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shim = FakeShim()
        cls.world = World()
        cls.world.decks[2] = Deck(cls.world, 2, 128.0, "deck 2")
        cls.adapter = make("djs1000-emu:127.0.0.1:%d" % cls.shim.port)
        cls.world.adapters.append(cls.adapter)
        cls.adapter.start(cls.world)
        cls.server = serve(cls.world, "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]
        end = time.time() + 5
        while not cls.adapter.connected() and time.time() < end:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.adapter.stop()
        cls.shim.close()
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, post=False):
        request = urllib.request.Request(self.url + path, method="POST" if post else "GET")
        with urllib.request.urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def test_unit_state(self):
        state = self.call("api/unit")
        self.assertIn("lamp.sync", state)
        snap = self.call("api/state")
        self.assertEqual(snap["adapters"], [{"name": "djs1000-emu", "connected": True, "controls": ["sync", "master"]}])
        self.assertIn("lamp.master", snap["unit_state"])

    def test_press(self):
        self.assertEqual(self.call("api/unit/press/master", post=True), {"ok": True})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call("api/unit/press/play", post=True)
        self.assertEqual(error.exception.code, 400)

    def test_no_adapter_is_said(self):
        world = World()
        self.assertEqual(world.press_unit(control="sync"), (False, "no adapter: start the bench with --adapter"))


class Command(unittest.TestCase):
    def test_no_such_adapter(self):
        out = subprocess.run([sys.executable, "-m", "deckbench", "--adapter", "nothing", "--http-port", "-1"],
                             capture_output=True, text=True, timeout=20, cwd=ROOT)
        self.assertEqual(out.returncode, 2)
        self.assertIn("no adapter 'nothing' (there is: djs1000-emu)", out.stderr)        # before it touches any port

    def test_a_skipped_scenario_exits_with_3(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "s.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": "x", "requires": ["adapter"], "steps": [{"at": 0, "do": "log", "text": "x"}]}, f)
        out = subprocess.run([sys.executable, "-m", "deckbench", "--numbers", "2", "--http-port", "-1", "--port-shift",
                              str(fresh().shift), "--scenario", path, "--then-exit"], capture_output=True, text=True,
                             timeout=30, cwd=ROOT)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertIn("skipped", out.stderr)

    def run_scenarios(self, *scenarios):
        import os
        import tempfile
        folder = tempfile.mkdtemp()
        for name, data in scenarios:
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                json.dump(data, f)
        return subprocess.run([sys.executable, "-m", "deckbench", "--numbers", "2", "--http-port", "-1", "--port-shift",
                               str(fresh().shift), "--scenario", folder, "--then-exit"], capture_output=True, text=True,
                              timeout=60, cwd=ROOT)

    def test_a_folder_is_a_suite(self):
        ok = {"name": "fine", "steps": [{"at": 0, "do": "log", "text": "x"}]}
        out = self.run_scenarios(("1.json", ok), ("2.json", {"name": "needs", "requires": ["adapter"], "unit_wait": 0.2, "steps": []}))
        self.assertEqual(out.returncode, 3, out.stderr)
        self.assertIn("2 scenarios: 1 passed, 0 failed, 1 skipped", out.stderr)

    def test_a_failed_expectation_is_status_1(self):
        bad = {"name": "bad", "steps": [{"at": 0, "do": "expect_deck", "deck": 2, "match": {"on": True}, "within": 0.2}]}
        ok = {"name": "fine", "steps": []}
        out = self.run_scenarios(("1.json", bad), ("2.json", ok), ("3.json", {"name": "s", "requires": ["adapter"], "unit_wait": 0.1, "steps": []}))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("3 scenarios: 1 passed, 1 failed, 1 skipped", out.stderr)
        self.assertIn("on is False (wanted True)", out.stderr)


if __name__ == "__main__":
    unittest.main()
