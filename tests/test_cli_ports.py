# SPDX-License-Identifier: MIT OR Apache-2.0
"""A busy port is said in one line, not a traceback."""
import os
import socket
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BusyPorts(unittest.TestCase):
    def run_with(self, *args):
        held = socket.socket()
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        self.addCleanup(held.close)
        port = held.getsockname()[1]
        result = subprocess.run([sys.executable, "-m", "deckbench", "--numbers", "4", "--port-shift", "300",
                                 *[a.replace("PORT", str(port)) for a in args]],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        return result, port

    def test_page_port_in_use(self):
        result, port = self.run_with("--http-port", "PORT")
        self.assertEqual(result.returncode, 2)
        self.assertIn("the page cannot listen on 127.0.0.1:%d" % port, result.stderr)
        self.assertIn("--http-port", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_sound_port_in_use(self):
        result, port = self.run_with("--http-port", "-1", "--audio-port", "PORT")
        self.assertEqual(result.returncode, 2)
        self.assertIn("the sound cannot listen on 127.0.0.1:%d" % port, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
