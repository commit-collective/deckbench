"""The ports the tests run the bench on. Not the real ones (UDP 50000-50002, TCP 12523 and 1051): something else may hold
them (rekordbox, another bench) and Windows can keep them back. DECKBENCH_PORT_SHIFT picks the shift, else the first
that is free is used."""
import os
import socket

from deckbench.protocols.prolink import Ports


def free(ports):
    for kind, port in ((socket.SOCK_DGRAM, ports.announce), (socket.SOCK_DGRAM, ports.beat),
                       (socket.SOCK_DGRAM, ports.update), (socket.SOCK_STREAM, ports.query),
                       (socket.SOCK_STREAM, ports.db)):
        s = socket.socket(socket.AF_INET, kind)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return False
        finally:
            s.close()
    return True


def pick():
    if os.environ.get("DECKBENCH_PORT_SHIFT"):
        return Ports.shifted(int(os.environ["DECKBENCH_PORT_SHIFT"]))
    for shift in range(1000, 10000, 100):
        ports = Ports.shifted(shift)
        if free(ports):
            return ports
    raise RuntimeError("no free range of ports for the tests: set DECKBENCH_PORT_SHIFT")


PORTS = pick()
