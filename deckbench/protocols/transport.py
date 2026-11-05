# SPDX-License-Identifier: MIT OR Apache-2.0
"""Button presses for players that take them over Pro DJ Link instead of fader start (the CDJ-3000).

Experimental. A remote controller connects, presses and releases a button, then disconnects: four short datagrams
sent to the player's UDP 50001 from the bench's own 50001. Seen working on CDJ-3000 firmware (in cdj3k-emu), and
ignored by a CDJ-2000NXS2. Nothing comes back: a sent press is not a confirmed one.

PLAY/PAUSE is the button, a toggle. CUE is held for the press's length, as a finger would. The bytes are the ones
that worked in that test, the controller's name included.
"""
import struct

from .startup import MAGIC

BUTTONS = {"play-pause": 20, "cue": 21}
CONTROLLER = 54                     # the controller's number in the packets: refused if a device on the link has it
NAME = b"deckbench probe"           # as tested
CONNECT, DISCONNECT = 1, 2
HOLD = 0.1                          # seconds a button is held
SETTLE = 0.25                       # after the connect, before the press


def packet(subtype, button=None, pressed=False):
    """A connect (1) or disconnect (2), or a button going down or up (subtype 0)."""
    data = bytearray(42 if button is None else 48)
    data[:10] = MAGIC
    data[10] = 7
    data[11:11 + len(NAME)] = NAME
    data[31] = 1
    data[33] = CONTROLLER
    struct.pack_into(">H", data, 34, len(data))
    struct.pack_into(">H", data, 36, subtype)
    if button is not None:
        if subtype != 0 or button not in BUTTONS.values():
            raise ValueError("unsupported button event")
        struct.pack_into(">HHBBH", data, 40, 1, button, 0, int(pressed), 0)
    elif subtype not in (CONNECT, DISCONNECT):
        raise ValueError("unsupported controller event")
    return bytes(data)


def down(send, button, pause):
    """Connect, then the button goes down, through send(datagram). pause(seconds) waits. If the press cannot be sent,
    it is let go at once (up), so nothing is left held."""
    send(packet(CONNECT))
    pause(SETTLE)
    try:
        send(packet(0, BUTTONS[button], True))
    except OSError:
        up(send, button)
        raise


def up(send, button):
    """The button goes up, then the disconnect. Both are tried, whatever happens to the first."""
    errors = []
    for data in (packet(0, BUTTONS[button]), packet(DISCONNECT)):
        try:
            send(data)
        except OSError as error:
            errors.append(error)
    if errors:
        raise errors[0]


def press(send, button, pause):
    """One press: down, held for HOLD, up. The up is sent even if the hold was cut short."""
    down(send, button, pause)
    try:
        pause(HOLD)
    finally:
        up(send, button)
