# SPDX-License-Identifier: MIT OR Apache-2.0
"""The page's demo bench (deckbench/ui/demo.js), run in node."""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(shutil.which("node"), "needs node")
class Demo(unittest.TestCase):
    def test_the_demo_bench_answers_as_the_real_one_does(self):
        out = subprocess.run(["node", os.path.join(ROOT, "tests", "demo_check.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "ok")

    def test_the_beats_of_a_deck_for_the_sound(self):
        out = subprocess.run(["node", os.path.join(ROOT, "tests", "sound_check.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "ok")

    def test_the_page_scripts_are_valid(self):
        for name in ("app.js", "transport.js", "demo.js", "sound.js"):
            out = subprocess.run(["node", "--check", os.path.join(ROOT, "deckbench", "ui", name)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, name + out.stderr)

    def test_grid_and_master_reference(self):
        out = subprocess.run(["node", os.path.join(ROOT, "tests", "viz_check.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
