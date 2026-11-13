# SPDX-License-Identifier: MIT OR Apache-2.0
"""Waveforms and beat grids of a real player's track, read from the player that hosts its media.

Read-only, through the public dbserver protocol, in one bounded session (metadata.session): the overview, the detail
and the beat grid. The RGB style (PWV4 and PWV5 of the track's EXT analysis) is asked first. A track that has none,
as one analysed for older players can be, gets the original blue style instead, overview and detail each on its
own. Both are turned into heights only, 0 to 100, which is all the bench draws. Tried on a CDJ-2000NXS2 (firmware
1.84) for a track on its own USB and on a linked one, and answered by an XDJ-1000MK2. The three-band style of the
CDJ-3000 is not asked for yet.
"""
import struct

EXT, EXT_REPLY = 0x2C04, 0x4F02                         # an analysis tag of the EXT file, and its answer
PREVIEW, PREVIEW_REPLY = 0x2004, 0x4402                 # the blue overview
BLUE_DETAIL, BLUE_DETAIL_REPLY = 0x2904, 0x4A02         # the blue detail
GRID, GRID_REPLY = 0x2204, 0x4602
MAIN, DATA = 1, 8                                       # menu contexts of the requests
RATE = 150                                              # detail samples a second, in both styles
LIMIT = 1024 * 1024                                     # bytes a blob may have (read_exact's cap too)
BLUE_SKIP = 19                                          # bytes before the blue detail's samples, as served


class Unavailable(ValueError):
    """The source has no such data for the track (not analyzed, another style, gone)."""


def tag(text):
    """An analysis tag or file extension as the request names it: its ASCII bytes read backwards."""
    return int.from_bytes(text.encode("ascii").ljust(4, b"\0"), "little")


def rmst(number, menu, slot):
    return number << 24 | menu << 16 | slot << 8 | 1


def requests(number, slot, rbid):
    """The requests of a session, as {name: (kind, arguments, answer)}: each style's overview and detail, and the grid."""
    return {"rgb overview": (EXT, [("n", rmst(number, MAIN, slot)), ("n", rbid), ("n", tag("PWV4")), ("n", tag("EXT"))], EXT_REPLY),
            "rgb detail": (EXT, [("n", rmst(number, MAIN, slot)), ("n", rbid), ("n", tag("PWV5")), ("n", tag("EXT"))], EXT_REPLY),
            "blue overview": (PREVIEW, [("n", rmst(number, DATA, slot)), ("n", 1), ("n", rbid), ("n", 0)], PREVIEW_REPLY),
            "blue detail": (BLUE_DETAIL, [("n", rmst(number, MAIN, slot)), ("n", rbid), ("n", 0)], BLUE_DETAIL_REPLY),
            "grid": (GRID, [("n", rmst(number, DATA, slot)), ("n", rbid)], GRID_REPLY)}


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


def envelope(data, name, width, most, notes=None):
    """The columns of a PWV4 or PWV5 answer: after a four-byte prefix, the tag and its 24-byte header (its length,
    its total length, the bytes of a column, their count, four more bytes), then the columns. A blob may end with up
    to three bytes of padding: an NXS2 was seen to round a detail up to a multiple of four. A blob that has fewer
    columns than its count says, or more than padding past them, gives the whole columns it has, and a note in
    `notes` says so with the numbers."""
    if len(data) < 28 or data[4:8] != name.encode():
        raise ValueError("not a %s answer" % name)
    header, total, size, count = struct.unpack_from(">IIII", data, 8)
    if header != 24 or size != width or not 0 < count <= most:
        raise ValueError("%s has unexpected dimensions (header %d, column %d bytes, %d columns)" % (name, header, size, count))
    have = (len(data) - 28) // width
    padded = total == 24 + width * count and 0 <= len(data) - (4 + total) <= 3
    if not padded:
        if notes is not None:
            notes.append("%s says %d columns (tag length %d) and has %d bytes, %d columns used"
                         % (name, count, total, len(data), min(have, count)))
        if not min(have, count):
            raise ValueError("%s has no columns" % name)
    return data[28:28 + width * min(have, count)]


def decode_overview(data, notes=None):
    """1200 (or so) columns of six bytes: bytes 3 to 5 are its red, green and blue heights, 0 to 127."""
    return envelope(data, "PWV4", 6, 4096, notes)


def decode_detail(data, notes=None):
    """Packed 16-bit samples, big-endian, RATE a second: bits 13-15 red, 10-12 blue, 7-9 green, 2-6 the height."""
    return envelope(data, "PWV5", 2, (LIMIT - 28) // 2, notes)


def rgb_heights(overview=None, detail=None):
    """The heights, 0 to 100, of an RGB overview's columns (the highest of its three) or of its detail's samples."""
    if overview is not None:
        return bytes(round(max(overview[i + 3] & 127, overview[i + 4] & 127, overview[i + 5] & 127) * 100 / 127)
                     for i in range(0, len(overview) - 5, 6))
    return bytes(round((value >> 2 & 31) * 100 / 31) for (value,) in struct.iter_unpack(">H", detail))


def blue_overview(data):
    """The blue overview: 400 columns of two bytes, the height (0 to 31) and how white it is, then a tiny preview of
    100 bytes. As heights, 0 to 100."""
    if len(data) < 800:
        raise ValueError("blue overview has %d bytes, not 900" % len(data))
    return bytes(round((data[i] & 31) * 100 / 31) for i in range(0, 800, 2))


def blue_detail(data):
    """The blue detail: after BLUE_SKIP bytes, one byte a sample, RATE a second, its height in the five low bits (the
    three high ones how white it is). As heights, 0 to 100."""
    if len(data) <= BLUE_SKIP:
        raise ValueError("blue detail has no samples")
    return bytes(round((value & 31) * 100 / 31) for value in data[BLUE_SKIP:])


def decode_grid(data):
    """The beats, from byte 20, 16 bytes each: their place in the bar (1 to 4), the tempo times 100 and the time in
    the track in milliseconds, little-endian. As [ms, bar, bpm * 100], the times only increasing."""
    if len(data) < 36 or (len(data) - 20) % 16:
        raise ValueError("beat grid has an unexpected length (%d bytes, start %s, end %s)"
                         % (len(data), data[:48].hex(), data[-16:].hex()))
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
    `number` (1 to 4). Returns {"overview": heights, "detail": heights (RATE a second), "grid": [[ms, bar, bpm100]...],
    "style": {"overview": "rgb" or "blue", "detail": ...}, "notes": [...]}, heights being bytes of 0 to 100. Raises
    Unavailable, ValueError, OSError or TimeoutError."""
    from .metadata import session
    from .protocols.prolink import message
    if slot not in (2, 3):
        raise Unavailable("waveforms are read for SD and USB tracks only")
    asked = requests(number, slot, rbid)
    notes, found, style, txid = [], {}, {}, 0
    with session(address, source, number, query_port, timeout) as exchange:
        def ask(name):
            nonlocal txid
            txid += 1
            kind, args, answer = asked[name]
            got, reply = exchange(txid, kind, args)
            return blob(name, kind, answer, got, reply)
        for part, rgb, blue in (("overview", lambda d: rgb_heights(overview=decode_overview(d, notes)), blue_overview),
                                ("detail", lambda d: rgb_heights(detail=decode_detail(d, notes)), blue_detail)):
            try:
                found[part], style[part] = rgb(ask("rgb " + part)), "rgb"
            except Unavailable:                     # no colour analysis: the blue style, which every analysis has
                found[part], style[part] = blue(ask("blue " + part)), "blue"
        grid = decode_grid(ask("grid"))
        exchange.sock.sendall(message(txid + 1, 0x0100, []))        # the end of the session, as tested
    if grid[-1][0] > 4 * 3600 * 1000:
        raise ValueError("beat grid is longer than four hours")
    return {"overview": found["overview"], "detail": found["detail"], "grid": grid, "style": style, "notes": notes}
