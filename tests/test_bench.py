# SPDX-License-Identifier: MIT OR Apache-2.0
"""The bench in a process of its own, as a test of something else starts it (deckbench.testing)."""
import os
import shutil
import subprocess
import sys
import time
import unittest

from deckbench.testing import Bench, BenchError, free_shift

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Started(unittest.TestCase):
    def test_comes_up_and_says_so(self):
        with Bench(numbers=[2, 3], on=True) as bench:
            ready = bench.get("api/ready")
            self.assertTrue(ready["ready"])
            self.assertEqual(ready["numbers"], [2, 3])
            self.assertEqual(ready["ports"]["announce"], 50000 + bench.shift)
            self.assertEqual(ready["http"], bench.url)
            self.assertTrue(all(d["on"] for d in bench.state()["decks"].values()))
            self.assertIn("deck 2", bench.output())

    def test_drives_and_waits(self):
        with Bench(numbers=[2], on=True) as bench:
            self.assertFalse(bench.state()["decks"]["2"]["play"])
            bench.post("api/deck/2/play/1")
            self.assertTrue(bench.state()["decks"]["2"]["play"])
            self.assertIsNone(bench.wait_event("fader_start", timeout=0.3))

    def test_runs_a_scenario(self):
        steps = [{"at": 0, "deck": 2, "do": "on"}, {"at": 0.2, "do": "expect", "event": "nothing", "within": 0.3}]
        with Bench(numbers=[2]) as bench:
            result = bench.run_scenario({"name": "x", "steps": steps})
            self.assertEqual(result["failed"], 1)

    def test_stops_and_frees_its_ports(self):
        bench = Bench(numbers=[2]).start()
        pid = bench.info["pid"]
        bench.stop()
        self.assertIsNone(bench.proc)
        time.sleep(0.2)
        with Bench(numbers=[2], shift=bench.shift) as again:         # the same ports again
            self.assertNotEqual(again.info["pid"], pid)

    def test_says_why_it_did_not_come_up(self):
        with Bench(numbers=[2], timeout=5) as first:
            second = Bench(numbers=[2], shift=first.shift, timeout=5)
            with self.assertRaises(BenchError) as error:
                second.start()
            self.assertIn("--port-shift", str(error.exception))


class Command(unittest.TestCase):
    def test_leaves_when_its_parent_goes(self):
        """With --exit-on-eof the bench ends when standard input does: a parent that dies takes it along."""
        out = subprocess.Popen([sys.executable, "-m", "deckbench", "--numbers", "2", "--http-port", "-1", "--port-shift",
                                str(free_shift()), "--exit-on-eof"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, cwd=ROOT)
        time.sleep(1.5)
        self.assertIsNone(out.poll())
        out.stdin.close()
        self.assertEqual(out.wait(10), 0)
        self.assertIn(b"standard input closed", out.stdout.read())

    def test_port_in_use_exits_with_a_message(self):
        with Bench(numbers=[2]) as first:
            out = subprocess.run([sys.executable, "-m", "deckbench", "--numbers", "2", "--http-port", "-1",
                                  "--port-shift", str(first.shift)], capture_output=True, text=True, timeout=20,
                                 cwd=ROOT)
            self.assertEqual(out.returncode, 2)
            self.assertIn("--port-shift", out.stderr)


@unittest.skipUnless(os.name == "nt" and shutil.which("wsl.exe"), "needs Windows with WSL")
class InWsl(unittest.TestCase):
    def test_runs_in_wsl_and_stops_there(self):
        with Bench(numbers=[2, 3], on=True, init={2: "play"}, wsl=True) as bench:
            self.assertEqual(bench.shift, 0)                          # WSL's own ports: the real ones
            self.assertTrue(bench.state()["decks"]["2"]["play"])
            bench.post("api/deck/2/tempo/121")
            self.assertEqual(bench.state()["decks"]["2"]["bpm"], 121.0)
            pid = bench.info["pid"]
        gone = subprocess.run(["wsl.exe", "--", "bash", "-c", "kill -0 %d 2> /dev/null && echo alive" % pid],
                              capture_output=True, text=True, timeout=30)
        self.assertNotIn("alive", gone.stdout)


if __name__ == "__main__":
    unittest.main()
