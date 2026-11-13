# SPDX-License-Identifier: MIT OR Apache-2.0
"""A database reply that does not parse says what arrived."""
import socket
import struct
import threading
import unittest

from deckbench.metadata import session
from deckbench.protocols.prolink import num


def serve(reply):
    """A player's database server on the loopback: the port query, the greeting, then `reply` to the first request."""
    query, db = socket.socket(), socket.socket()
    for s in (query, db):
        s.bind(("127.0.0.1", 0))
        s.listen(1)

    def run():
        c, _ = query.accept()
        c.recv(64)
        c.sendall(struct.pack(">H", db.getsockname()[1]))
        c.close()
        c, _ = db.accept()
        c.recv(5)
        c.sendall(num(1))
        c.recv(4096)
        c.sendall(reply)
        c.close()
        query.close()
        db.close()
    threading.Thread(target=run, daemon=True).start()
    return query.getsockname()[1]


MAGIC = b"\x11\x87\x23\x49\xae"


def setup_reply(table):
    """The reply to the session's first request: type 0x4000, two numbers, and an argument table of the given bytes."""
    return (MAGIC + b"\x11\xff\xff\xff\xfe" + b"\x10\x40\x00" + b"\x0f\x02" + b"\x14" + len(table).to_bytes(4, "big") + table
            + b"\x11\x00\x00\x00\x03" + b"\x11\x00\x00\x00\x01")


class Errors(unittest.TestCase):
    def test_an_argument_table_shorter_than_the_arguments_shows_the_bytes(self):
        reply = setup_reply(b"\x06")                    # two arguments, one type
        port = serve(reply)
        with self.assertRaises(ValueError) as caught:
            with session("127.0.0.1", "127.0.0.1", 3, port, 3):
                pass
        text = str(caught.exception)
        self.assertIn("invalid protocol argument table", text)
        self.assertIn("received", text)
        self.assertIn(reply[:20].hex(), text)

    def test_a_table_as_long_as_the_arguments_is_read(self):
        """A CDJ-3000 (EP122) answers with a 2 byte table for 2 arguments, not the 12 bytes the others send."""
        port = serve(setup_reply(b"\x06\x06"))
        with session("127.0.0.1", "127.0.0.1", 3, port, 3) as exchange:
            self.assertTrue(callable(exchange))

    def test_a_table_of_twelve_bytes_is_read(self):
        port = serve(setup_reply(b"\x06\x06" + bytes(10)))
        with session("127.0.0.1", "127.0.0.1", 3, port, 3) as exchange:
            self.assertTrue(callable(exchange))

    def test_a_table_longer_than_twelve_bytes_is_not(self):
        port = serve(setup_reply(b"\x06\x06" + bytes(11)))
        with self.assertRaises(ValueError):
            with session("127.0.0.1", "127.0.0.1", 3, port, 3):
                pass


if __name__ == "__main__":
    unittest.main()
