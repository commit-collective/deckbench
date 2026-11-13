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


class Errors(unittest.TestCase):
    def test_an_argument_table_of_the_wrong_length_shows_the_bytes(self):
        magic = b"\x11\x87\x23\x49\xae"
        reply = magic + b"\x11\xff\xff\xff\xfe" + b"\x10\x40\x00" + b"\x0f\x01" + b"\x14\x00\x00\x00\x03\x06\x06\x06"
        port = serve(reply)
        with self.assertRaises(ValueError) as caught:
            with session("127.0.0.1", "127.0.0.1", 3, port, 3):
                pass
        text = str(caught.exception)
        self.assertIn("invalid protocol argument table", text)
        self.assertIn("received", text)
        self.assertIn(reply.hex(), text)


if __name__ == "__main__":
    unittest.main()
