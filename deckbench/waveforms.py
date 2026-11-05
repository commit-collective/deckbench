# SPDX-License-Identifier: MIT OR Apache-2.0
"""Waveforms and beat grids of a real player's track, read from the player that hosts its media.

Read-only, through the public dbserver protocol, in one bounded session (metadata.session): the RGB overview
(PWV4), the RGB detail (PWV5) and the beat grid. Tried on a CDJ-2000NXS2 (firmware 1.84), for a track on its own
USB and on a linked one. Other models and the three-band style of the CDJ-3000 are not asked for yet.
"""
import struct

OVERVIEW, DETAIL, GRID = 0x2C04, 0x2C04, 0x2204       # the requests
EXT_REPLY, GRID_REPLY = 0x4F02, 0x4602                  # their answers
RATE = 150                                              # detail samples a second
LIMIT = 1024 * 1024                                     # bytes a blob may have (read_exact's cap too)


class Unavailable(ValueError):
    """The source has no such data for the track (not analyzed, another style, gone)."""


def tag(text):
    """An analysis tag or file extension as the request names it: its ASCII bytes read backwards."""
    return int.from_bytes(text.encode("ascii").ljust(4, b"\0"), "little")


def requests(number, slot, rbid):
    """The three requests of a session, as (name, kind, arguments, answer)."""
    def rmst(menu):
        return number << 24 | menu << 16 | slot << 8 | 1
    return [("overview", OVERVIEW, [("n", rmst(1)), ("n", rbid), ("n", tag("PWV4")), ("n", tag("EXT"))], EXT_REPLY),
            ("detail", DETAIL, [("n", rmst(1)), ("n", rbid), ("n", tag("PWV5")), ("n", tag("EXT"))], EXT_REPLY),
            ("grid", GRID, [("n", rmst(8)), ("n", rbid)], GRID_REPLY)]


def blob(name, request, expected, kind, args):
    """The blob of an answer, checked: [request, ?, length, blob] and, for the extended ones, one more number. The
    NXS2 answers the beat grid with a fifth argument, a numeric zero, which the public description does not have."""
    if kind != expected:
        raise Unavailable("no %s for this track (answer %#x)" % (name, kind))
    extended = expected == EXT_REPLY
    if not (len(args) == 5 if extended else len(args) in (4, 5)):
        raise ValueError("%s answer has %d arguments" % (name, len(args)))
    if (args[0] != ("n", request) or args[2][0] != "n" or args[3][0] != "b" or args[2][1] != len(args[3][1])
            or (not extended and len(args) == 5 and args[4] != ("n", 0))):
        raise ValueError("%s answer is malformed" % name)
    if not args[3][1]:
        raise Unavailable("no %s for this track" % name)
    return args[3][1]


def envelope(data, name, width, most):
    """The columns of a PWV4 or PWV5 answer: after a four-byte prefix, the tag, its header length (24), its total
    length, the bytes of a column and their count, all checked against the blob's size."""
    if len(data) < 28 or data[4:8] != name.encode():
        raise ValueError("not a %s answer" % name)
    header, total, size, count = struct.unpack_from(">IIII", data, 8)
    if header != 24 or size != width or not 0 < count <= most:
        raise ValueError("%s has unexpected dimensions" % name)
    if total != 24 + width * count or len(data) != 4 + total:
        raise ValueError("%s size mismatch" % name)
    return data[28:]


def decode_overview(data):
    """1200 (or so) columns of six bytes: bytes 3 to 5 are its red, green and blue heights, 0 to 127."""
    return envelope(data, "PWV4", 6, 4096)


def decode_detail(data):
    """Packed 16-bit samples, big-endian, RATE a second: bits 13-15 red, 10-12 blue, 7-9 green, 2-6 the height."""
    return envelope(data, "PWV5", 2, (LIMIT - 28) // 2)


def decode_grid(data):
    """The beats, from byte 20, 16 bytes each: their place in the bar (1 to 4), the tempo times 100 and the time in
    the track in milliseconds, little-endian. As [ms, bar, bpm * 100], the times only increasing."""
    if len(data) < 36 or (len(data) - 20) % 16:
        raise ValueError("beat grid has an unexpected length")
    beats, previous = [], -1
    for offset in range(20, len(data), 16):
        bar, bpm100, ms = struct.unpack_from("<HHI", data, offset)
        if bar not in (1, 2, 3, 4) or not bpm100 or ms <= previous:
            raise ValueError("beat grid has an invalid beat")
        beats.append([ms, bar, bpm100])
        previous = ms
    return beats


def read_track_waveforms(address, source, number, slot, rbid, query_port=12523, timeout=10):
    """The overview, detail and beat grid of a track on the player at `address`, asked from `source` as player
    `number` (1 to 4). Returns {"overview": bytes, "detail": bytes, "grid": [[ms, bar, bpm100]...]}. Raises
    Unavailable, ValueError, OSError or TimeoutError."""
    from .metadata import session
    if slot not in (2, 3):
        raise Unavailable("waveforms are read for SD and USB tracks only")
    found = {}
    with session(address, source, number, query_port, timeout) as exchange:
        for txid, (name, kind, args, answer) in enumerate(requests(number, slot, rbid), 1):
            got, reply = exchange(txid, kind, args)
            found[name] = blob(name, kind, answer, got, reply)
        from .protocols.prolink import message
        exchange.sock.sendall(message(len(found) + 1, 0x0100, []))     # the end of the session, as tested
    overview, detail, grid = decode_overview(found["overview"]), decode_detail(found["detail"]), decode_grid(found["grid"])
    if grid[-1][0] > len(detail) // 2 * 1000 / RATE + 1000:
        raise ValueError("beat grid runs past the waveform")
    return {"overview": overview, "detail": detail, "grid": grid}
