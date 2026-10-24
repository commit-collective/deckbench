"""The ports the tests run the bench on. Not the real ones (UDP 50000-50002, TCP 12523 and 1051): something else may hold
them (rekordbox, another bench) and Windows can reserve them. Each test class that starts a bench in this process takes
a range of its own, since the threads of one keep its ports until the process ends.
DECKBENCH_PORT_SHIFT, if set, is the shift of the first range."""
import os

from deckbench.protocols.prolink import Ports, PortError, Prolink
from deckbench.testing import ports_free

_last = []


def fresh():
    if not _last and os.environ.get("DECKBENCH_PORT_SHIFT"):
        shift = int(os.environ["DECKBENCH_PORT_SHIFT"])
    else:
        shift = (_last[-1] + 100) if _last else 1000
        while not ports_free(Ports.shifted(shift)):
            shift += 100
    _last.append(shift)
    return Ports.shifted(shift)


_start = Prolink.start


def _start_again_on_a_taken_port(self, *args, **kwargs):
    """The range was free when fresh() looked, but the system hands out ports of that range to any socket that binds
    without one (a client's, a test's), so one may be taken by the time the bench binds. Takes another range then: the
    same Ports object is moved, so what the test holds follows."""
    for attempt in range(5):
        try:
            return _start(self, *args, **kwargs)
        except PortError:
            if attempt == 4 or self.ports not in _taken:
                raise
            Ports.__init__(self.ports, fresh().shift)


_taken = []
_fresh = fresh


def fresh():
    ports = _fresh()
    _taken.append(ports)
    return ports


Prolink.start = _start_again_on_a_taken_port
