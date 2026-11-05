# SPDX-License-Identifier: MIT OR Apache-2.0
"""The identities the simulated devices have on the loopback, written once: their addresses and their MACs."""
import sys


def deck_address(number):
    return "127.0.0.%d" % number


def mixer_address(number):
    # On macOS the mixer has always been on 127.0.0.1.
    return "127.0.0.1" if sys.platform == "darwin" else "127.0.0.%d" % number


def deck_mac(number):
    return bytes([0x02, 0xFA, 0x4E, 0xDE, 0xC0, number])


def mixer_mac(number):
    return bytes([0x02, 0xFA, 0x4E, 0xDE, 0xC1, number])
