# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small things about sockets that differ between systems."""
import socket
import sys


def share(sock):
    """Lets other sockets of this machine bind the same UDP port as this one: the decks, the sniffer and the mixer all listen on the
    link's ports. SO_REUSEADDR does it on Linux and Windows. macOS wants SO_REUSEPORT as well, and Linux must not get it here:
    there it would hand each datagram to one of the sockets instead of to all."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if sys.platform == "darwin" and hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    return sock
