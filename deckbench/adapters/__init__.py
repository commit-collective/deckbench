# SPDX-License-Identifier: MIT OR Apache-2.0
"""Adapters: what a device under test shows beyond the network.

The bench sees a device by what it sends on the link (its keep-alives and statuses: `Protocol.unit_state`). An adapter
adds what is only known from the device itself: a lamp that is lit, a screen that changed, a button to press. It is
how a scenario can expect "the MASTER lamp is lit" and press a control of the device.

An adapter is a class with a `name`, a `start(world)`, a `state()` (a flat dict of what it knows, keys like "lamp.sync",
which a scenario matches against with `expect_unit`), `press(control)` and `stop()`. Name it in `ADAPTERS` to use it
as `--adapter NAME[:ARGUMENTS]`.
"""


class Adapter:
    name = "adapter"
    controls = ()                       # the names `press` takes, for the page and the error messages

    def start(self, world):
        """Starts whatever it needs (a thread, a connection). It must not block."""

    def connected(self):
        return True

    def state(self):
        """What it knows now: a flat dict of key: value. Keys the adapter cannot tell (not connected) are left out."""
        return {}

    def press(self, control):
        """Presses a control of the device. (True, "") if it did, (False, why) if not."""
        return False, "this adapter has no controls"

    def send(self, line):
        """A raw command in the device's own words, for what `press` does not name. (True, "") or (False, why)."""
        return False, "this adapter takes no raw commands"

    def stop(self):
        pass


def make(spec):
    """An adapter from `NAME` or `NAME:ARGUMENTS`. ValueError if there is no such adapter."""
    from .djs1000_emu import Djs1000Emulator
    registry = {Djs1000Emulator.name: Djs1000Emulator}
    name, _, args = spec.partition(":")
    if name not in registry:
        raise ValueError("no adapter %r (there is: %s)" % (name, ", ".join(sorted(registry))))
    return registry[name](args)
