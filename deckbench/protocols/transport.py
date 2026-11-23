# SPDX-License-Identifier: MIT OR Apache-2.0
"""Button presses for players that take them over Pro DJ Link (the CDJ-3000, and the CDJ-2000NXS2 in its own format).

Experimental. A remote controller connects, presses and releases a button, then disconnects: four short datagrams
sent to the player's UDP 50001 from the bench's own 50001. Seen working on CDJ-3000 firmware (in cdj3k-emu) and on a
physical CDJ-2000NXS2. The XDJ-1000MK2 shares the NXS2's format. The player sends no acknowledgement.

The two formats differ after the header. The CDJ-3000's fields are big-endian with no slot. The NXS2's are
little-endian and name a controller slot, 1 to 4: the tested one is the player's own number, which its receiver
prefers. The models supported by each format are listed in Prolink.

PLAY/PAUSE is the button, a toggle. CUE is held for the press's length, as a finger would. The bytes are the ones
that worked in those tests, the controller's name included.
"""
import struct
import time

from .startup import MAGIC

BUTTONS = {"play-pause": 20, "cue": 21}
BEAT_LOOP_LENGTHS = ("0.25", "0.5", "1", "2", "4", "8", "16", "32")
BEAT_JUMP_SIZES = (1, 2, 4, 8, 16)
BEAT_LOOPS = {f"beat-loop-{beats}": 0x3C + pad for pad, beats in enumerate(BEAT_LOOP_LENGTHS)}
HOT_CUES = {f"hot-cue-{pad}": 0x45 + pad for pad in range(1, 9)}
HOT_CUE_DELETES = {f"hot-cue-delete-{pad}": 0x4F + pad for pad in range(1, 9)}
BEAT_JUMPS = {
    f"beat-jump-{direction}{f'-{beats}' if beats != 1 else ''}": 0x5A + 2 * pad + side
    for pad, beats in enumerate((*BEAT_JUMP_SIZES, 32, 64))
    for side, direction in enumerate(("back", "forward"))
}
COMMON_EXTRA_BUTTONS = {
    "quantize": 0x0A, "slip": 0x0B,
    "loop-in": 0x1E, "loop-out": 0x1F, "reloop-exit": 0x20, "four-beat-loop": 0x24,
    **BEAT_LOOPS, **HOT_CUES,
}
NXS2_EXTRA_BUTTONS = {
    **COMMON_EXTRA_BUTTONS, **HOT_CUE_DELETES,
    **{name: code for name, code in BEAT_JUMPS.items() if code <= 0x63},
}
CDJ3000_EXTRA_BUTTONS = {
    **COMMON_EXTRA_BUTTONS, "loop-half": 0x23, "loop-double": 0x22, **BEAT_JUMPS,
}
EXTRA_COMMANDS = NXS2_EXTRA_BUTTONS.keys() | CDJ3000_EXTRA_BUTTONS.keys()
LEGACY_BUTTONS = {**BUTTONS, **NXS2_EXTRA_BUTTONS}
CDJ3000_BUTTONS = {**BUTTONS, **CDJ3000_EXTRA_BUTTONS}
CONTROLLER = 54                     # the controller's number in the packets: refused if a device on the link has it
NAME = b"deckbench probe"           # as tested
CONNECT, DISCONNECT = 1, 2
HOLD = 0.1                          # seconds a button is held
SETTLE = 0.1                        # time to connect before PLAY/PAUSE or CUE
EXTRA_SETTLE = 0.25                 # connect time used in the physical NXS2 pad tests


def packet(subtype, button=None, pressed=False, slot=None):
    """A connect (1) or disconnect (2), or a button going down or up (subtype 0). With a slot (1 to 4), in the
    CDJ-2000NXS2's little-endian format, otherwise in the CDJ-3000's."""
    if slot is not None and slot not in (1, 2, 3, 4):
        raise ValueError("a controller slot is 1 to 4")
    order = ">" if slot is None else "<"
    data = bytearray(42 if button is None else 48)
    data[:10] = MAGIC
    data[10] = 7
    data[11:11 + len(NAME)] = NAME
    data[31] = 1
    data[33] = CONTROLLER
    struct.pack_into(">H", data, 34, len(data))
    struct.pack_into(order + "HH", data, 36, subtype, slot or 0)
    if button is not None:
        buttons = CDJ3000_BUTTONS if slot is None else LEGACY_BUTTONS
        if subtype != 0 or button not in buttons.values():
            raise ValueError("unsupported button event")
        struct.pack_into(order + "HHBBH", data, 40, 1, button, 0, int(pressed), 0)
    elif subtype not in (CONNECT, DISCONNECT):
        raise ValueError("unsupported controller event")
    return bytes(data)


def down(send, button, pause, slot=None):
    """Connect, then the button goes down, through send(datagram). pause(seconds) waits. If the press cannot be sent,
    it is let go at once (up), so nothing is left held. slot: see packet."""
    key = (CDJ3000_BUTTONS if slot is None else LEGACY_BUTTONS)[button]
    pressed = packet(0, key, True, slot)
    send(packet(CONNECT, slot=slot))
    pause(EXTRA_SETTLE if button in EXTRA_COMMANDS else SETTLE)
    try:
        at = time.time()
        send(pressed)
    except OSError:
        up(send, button, slot)
        raise
    return at


def up(send, button, slot=None):
    """The button goes up, then the disconnect. Both are tried, whatever happens to the first."""
    errors = []
    key = (CDJ3000_BUTTONS if slot is None else LEGACY_BUTTONS)[button]
    for data in (packet(0, key, slot=slot), packet(DISCONNECT, slot=slot)):
        try:
            send(data)
        except OSError as error:
            errors.append(error)
    if errors:
        raise errors[0]


def press(send, button, pause, slot=None, on_press=None):
    """One press: down, held for HOLD, up. The up is sent even if the hold was cut short. Never retried: PLAY/PAUSE
    is a toggle, and a second press would undo the first."""
    at = down(send, button, pause, slot)
    try:
        if on_press is not None:
            on_press(at)
        pause(HOLD)
    finally:
        up(send, button, slot)
