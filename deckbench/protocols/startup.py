# SPDX-License-Identifier: MIT OR Apache-2.0
"""The packets a device sends on UDP 50000 when it comes onto a Pro DJ Link network, and to stay there.

Layouts from Deep Symmetry's analysis (startup.html, the NXS2-era packets of the hardware captures, subtype 02) and
checked against Beat Link's `VirtualCdj`. A device comes online with, at 300 ms:

    hello         x3   type 0x0a, 0x25 bytes
    claim stage 1 x3   type 0x00, 0x2c bytes: the packet counter, the kind of device, the MAC
    claim stage 2 x3   type 0x02, 0x32 bytes: the address, the MAC, the number it claims, the counter, auto-assign or not
    claim stage 3 x3   type 0x04, 0x26 bytes: the number, the counter

and then a keep-alive (type 0x06, 0x36 bytes) every 2 s (a mixer: 1.5 s). A device that already has the number sends a
"number in use" packet (type 0x08, 0x29 bytes) to the one that claims it.
"""
import socket
import struct

MAGIC = bytes([0x51, 0x73, 0x70, 0x74, 0x31, 0x57, 0x6D, 0x4A, 0x4F, 0x4C])
CDJ, MIXER = 1, 2                       # the kind of device

HELLO, STAGE1, STAGE2, STAGE3, KEEPALIVE, IN_USE = 0x0A, 0x00, 0x02, 0x04, 0x06, 0x08


def head(ptype, name, length):
    """A packet of `length` bytes with its header: the magic, the type, the name (from 0x0c), 01 at 0x20, the subtype 02
    and the length."""
    p = bytearray(length)
    p[0:10] = MAGIC
    p[0x0A] = ptype
    p[0x0C:0x0C + len(name)] = name
    p[0x20], p[0x21] = 0x01, 0x02
    p[0x22:0x24] = struct.pack(">H", length)
    return p


def hello(name, kind=CDJ):
    p = head(HELLO, name, 0x25)
    p[0x24] = kind
    return bytes(p)


def stage1(name, mac, n, kind=CDJ):
    p = head(STAGE1, name, 0x2C)
    p[0x24], p[0x25] = n, kind
    p[0x26:0x2C] = mac
    return bytes(p)


def stage2(name, address, mac, number, n, kind=CDJ, auto=False):
    p = head(STAGE2, name, 0x32)
    p[0x24:0x28] = socket.inet_aton(address)
    p[0x28:0x2E] = mac
    p[0x2E], p[0x2F], p[0x30] = number, n, kind
    p[0x31] = 1 if auto else 2
    return bytes(p)


def stage3(name, number, n):
    p = head(STAGE3, name, 0x26)
    p[0x24], p[0x25] = number, n
    return bytes(p)


def keepalive(name, number, address, mac, peers=1, alone=False, kind=CDJ):
    """`peers`: the devices it knows on the network, itself included. `alone`: it was the first device there when it
    came online (byte 0x25 holds 02, else 01: latched at startup and kept for the whole session)."""
    p = head(KEEPALIVE, name, 0x36)
    p[0x24] = number
    p[0x25] = 0x02 if alone else 0x01
    p[0x26:0x2C] = mac
    p[0x2C:0x30] = socket.inet_aton(address)
    p[0x30] = peers
    p[0x34] = kind
    return bytes(p)


def in_use(name, number, address):
    p = head(IN_USE, name, 0x29)
    p[0x24] = number
    p[0x25:0x29] = socket.inet_aton(address)
    return bytes(p)


def claimed_number(data):
    """The device number a packet on 50000 claims or announces, or None: stage 2, stage 3 and keep-alive packets."""
    if len(data) < 0x26 or data[:10] != MAGIC:
        return None
    kind = data[0x0A]
    if kind == STAGE2 and len(data) >= 0x2F:
        return data[0x2E]
    if kind in (STAGE3, KEEPALIVE):
        return data[0x24]
    return None
