"""Waiting for the bench to have taken in what was sent, not for a moment that is long enough.

The bench listens on several sockets at once, each in a thread of its own, and a device is built from packets on more than one of them:
the keep-alive that says who it is, the status that says what it does, the beats that say where it is. Packets sent one after the other
are not taken in that order, and a test that sends and then waits for one of them can look at a device that is only half there.

`flush` is the barrier: it sends a marker on each port and waits until each is in the log. The packets of one socket are taken in the
order they came, so when the marker of a port is there, what was sent on that port before it is. Then it waits for the monitor to be
idle: a broadcast reaches several of the bench's sockets, and the thread that logged a packet may be one that is still reading another.
"""
import itertools
import time

_counter = itertools.count(1)


def flush(monitor, sender, ports, seconds=10.0):
    """True once everything `sender` sent to `ports` before is in the monitor. `ports`: the ports the test sent to."""
    tokens = []
    for port in ports:
        token = b"deckbench-flush-%d-%d-%d" % (port, next(_counter), int(time.time() * 1000) % 100000)
        sender.send(token, port)
        tokens.append(token.hex())
    end = time.time() + seconds
    while time.time() < end:
        packets = monitor.since(0, limit=100000)["packets"]
        if all(any(token in p["hex"] for p in packets) for token in tokens):
            break
        time.sleep(0.01)
    else:
        return False
    while time.time() < end:
        with monitor.lock:
            idle = monitor.busy == 0
        if idle:
            return True
        time.sleep(0.005)
    return False
