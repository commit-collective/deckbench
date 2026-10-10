# SPDX-License-Identifier: MIT OR Apache-2.0
"""The rekordbox database file that deckbench makes (export.pdb) and its reader."""
import struct
import unittest

from deckbench.protocols.pdb import PAGE, build_pdb, parse_pdb


def parse_independent(pdb):
    """A second reading of the same layout, written the other way round: the title is
    found from the row's 18th string offset, with the string kinds spelled out."""
    size, tables = struct.unpack_from("<II", pdb, 4)
    assert size == PAGE
    first = last = None
    for t in range(tables):
        kind, _, f, l = struct.unpack_from("<IIII", pdb, 0x1C + 16 * t)
        if kind == 0:
            first, last = f, l
    found = {}
    n = first
    while True:
        page = pdb[n * size:(n + 1) * size]
        _, index, kind, nxt = struct.unpack_from("<IIII", page, 0)
        assert index == n and kind == 0
        if not page[0x1B] & 0x40:                           # a data page, not an index page
            offsets = (page[0x18] | page[0x19] << 8 | page[0x1A] << 16) & 0x1FFF
            for row in range(offsets):
                group, bit = divmod(row, 16)
                base = size - 36 * (group + 1)
                present = struct.unpack_from("<H", page, base + 32)[0]
                if present >> bit & 1:
                    start = 0x28 + struct.unpack_from("<H", page, base + 2 * (15 - bit))[0]
                    at = start + struct.unpack_from("<H", page, start + 0x5E + 2 * 17)[0]
                    kind = page[at]
                    if kind & 1:
                        title = page[at + 1:at + (kind >> 1)].decode("ascii")
                    else:
                        length = struct.unpack_from("<H", page, at + 1)[0]
                        raw = page[at + 4:at + length]
                        title = raw.decode("utf-16-le") if kind == 0x90 else raw.decode("ascii")
                    found[struct.unpack_from("<I", page, start + 0x48)[0]] = title
        if n == last:
            return found
        n = nxt


class Pdb(unittest.TestCase):
    def test_round_trip_many_pages(self):
        titles = {1000 + i: "Track %d" % i for i in range(700)}
        titles[5] = "Café del Mar"
        titles[6] = "Sonata \U0001d11e in D"
        titles[7] = "x" * 200
        pdb = build_pdb(titles)
        self.assertEqual(len(pdb) % PAGE, 0)
        self.assertGreater(len(pdb) // PAGE, 10)
        self.assertEqual(parse_pdb(pdb), titles)
        self.assertEqual(parse_independent(pdb), titles)

    def test_empty(self):
        self.assertEqual(parse_pdb(build_pdb({})), {})


if __name__ == "__main__":
    unittest.main()
