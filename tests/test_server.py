# SPDX-License-Identifier: MIT OR Apache-2.0
"""The page's server under a burst of connections: none is refused or held back."""
import concurrent.futures
import time
import unittest
import urllib.request

from deckbench.core import Deck, World
from deckbench.web import Server, serve


class Burst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()
        cls.world.decks[1] = Deck(cls.world, 1, 120.0)
        cls.server = serve(cls.world, "127.0.0.1", 0)
        cls.base = "http://127.0.0.1:%d/" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_the_queue_of_connections_is_long_enough_for_a_page(self):
        # A page opens an event stream and a dozen requests at once, and a program asking for the state besides. With the default queue of
        # 5 a connection could be held back a second, or refused through WSL's forwarding, and the page said the bench did not answer.
        self.assertGreaterEqual(Server.request_queue_size, 64)

    def test_sixty_requests_at_once_all_answer_quickly(self):
        def get(_):
            began = time.perf_counter()
            with urllib.request.urlopen(self.base + "api/state", timeout=5) as r:
                r.read()
            return time.perf_counter() - began
        with concurrent.futures.ThreadPoolExecutor(60) as pool:
            took = list(pool.map(get, range(180)))
        self.assertLess(max(took), 0.9, "the slowest answered in %.2f s" % max(took))


if __name__ == "__main__":
    unittest.main()
