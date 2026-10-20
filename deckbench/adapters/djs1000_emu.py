# SPDX-License-Identifier: MIT OR Apache-2.0
"""The DJS-1000 emulator (djs1000-emu), through its virtual deck's link: the shim's TCP port (127.0.0.1:7310).

    python -m deckbench --adapter djs1000-emu                 # 127.0.0.1:7310
    python -m deckbench --adapter djs1000-emu:127.0.0.1:7310

The shim sends each client, with an 8-byte header (kind, output, and three little-endian 16-bit numbers), the rows of the
screen that changed ('S'), the 128-byte frame the app sends its panel, which holds the lamps ('L'), and the sound ('A').
It takes command lines. This adapter reads the lamps and sends `tap <byte> <bit>`, which is a button of the panel pressed
and released. The frame's layout and the buttons' bits are those of the emulator's `app/layout.py`, which found them by
pressing the controls.

It reports: `connected`, `lamp.sync` and `lamp.master` (True when lit), `lamp.sync_level` and `lamp.master_level` (0 off,
1 dim, 2 bright: the app writes dim for a lamp that is off, and a lamp that is lit is bright).
"""
import socket
import struct
import threading
import time

from . import Adapter

# Two-level lamps in the app's frame: name -> (byte, shift). 0x1B and 0x1C of the emulator's table.
LAMPS = {"sync": (0x6A, 0), "master": (0x6A, 2)}
# Buttons: name -> (byte, bit) of the panel's frame, as `tap` takes them.
BUTTONS = {"sync": (6, 5), "master": (6, 6)}


def lamp_level(frame, lamp):
    """0 off, 1 dim, 2 bright. The frame holds 0 for off, 3 for dim and 1 for bright (the emulator's table)."""
    byte, shift = LAMPS[lamp]
    return (0, 2, 2, 1)[(frame[byte] >> shift) & 3]


class Djs1000Emulator(Adapter):
    name = "djs1000-emu"
    controls = tuple(BUTTONS)

    def __init__(self, args=""):
        host, _, port = (args or "127.0.0.1:7310").partition(":")
        self.address = (host or "127.0.0.1", int(port or 7310))
        self.frame = None                   # the last lamp frame
        self.sock = None
        self.lock = threading.Lock()        # one sender at a time
        self.stopping = False

    def start(self, world):
        threading.Thread(target=self.run, daemon=True).start()

    def connected(self):
        return self.sock is not None and self.frame is not None

    def state(self):
        frame = self.frame
        state = {"adapter.connected": self.connected()}
        if frame is not None and self.sock is not None:
            for lamp in LAMPS:
                level = lamp_level(frame, lamp)
                state["lamp.%s_level" % lamp] = level
                state["lamp.%s" % lamp] = level == 2
        return state

    def press(self, control):
        if control not in BUTTONS:
            return False, "no control %r (there is: %s)" % (control, ", ".join(BUTTONS))
        return self.send("tap %d %d" % BUTTONS[control])

    def send(self, line):
        sock = self.sock
        if sock is None:
            return False, "the emulator is not connected (%s:%d)" % self.address
        try:
            with self.lock:
                sock.sendall(line.encode("utf-8") + b"\n")
            return True, ""
        except OSError as e:
            return False, "the emulator did not take it: %s" % e

    def stop(self):
        self.stopping = True
        sock = self.sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def read(sock, n):
        buf = bytearray()
        while len(buf) < n:
            part = sock.recv(min(n - len(buf), 1 << 20))
            if not part:
                raise ConnectionError("closed")
            buf += part
        return bytes(buf)

    def run(self):
        while not self.stopping:
            try:
                sock = socket.create_connection(self.address, timeout=2)
            except OSError:
                time.sleep(1)
                continue
            sock.settimeout(None)
            self.sock = sock
            try:
                while True:
                    kind, _, y, rows, width = struct.unpack("<BBHHH", self.read(sock, 8))
                    if kind == ord("S"):
                        self.read(sock, rows * width * 4)           # the screen: not needed, but it must be read
                    elif kind == ord("L"):
                        self.frame = self.read(sock, 128)
                    elif kind == ord("A"):
                        self.read(sock, y * 8)
                    else:
                        raise ConnectionError("unknown message")
            except (OSError, ConnectionError, struct.error):
                pass
            self.sock, self.frame = None, None
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(1)
