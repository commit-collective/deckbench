# SPDX-License-Identifier: MIT OR Apache-2.0
"""Documented remote commands, encoded independently from the public wire layout.

Reference: https://djl-analysis.deepsymmetry.org/djl-analysis/loading_tracks.html
"""
import struct


def load_track_packet(name, sender, target, source, slot, track):
    from .prolink import header
    if not all(isinstance(n, int) and 1 <= n <= 6 for n in (sender, target, source)):
        raise ValueError('player numbers must be 1 to 6')
    if slot not in (2, 3) or not isinstance(track, int) or not 1 <= track <= 0xFFFFFFFF:
        raise ValueError('use an analyzed SD or USB track with a positive 32-bit ID')
    packet = bytearray(0x58)
    packet[:0x1F] = header(0x19, name)
    packet[0x1F], packet[0x21], packet[0x24] = 1, sender, sender
    struct.pack_into('>H', packet, 0x22, 0x34)
    packet[0x28:0x2B] = bytes((source, slot, 1))
    struct.pack_into('>I', packet, 0x2C, track)
    packet[0x34], packet[0x40] = 0x32, target - 1
    return bytes(packet)
