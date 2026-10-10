# SPDX-License-Identifier: MIT OR Apache-2.0
"""rekordbox's database file, PIONEER/rekordbox/export.pdb: made and read.

What a deck has on its USB or SD drive: a track table with the titles, under the ids the
decks give in their status. This makes such a file from {id: title} (for tests of what
looks titles up in one) and reads one (the reference to check real files and the made
ones against). The layout is the one of the public analysis (Deep Symmetry's rekordbox
export analysis): pages of 4096 bytes, page 0 the header with the table pointers, a table
of tracks (type 0) as a list of pages, each with its rows from byte 0x28 and the row
offsets backwards from its end, in groups of 16. Checked on a real file of 3198 tracks.
"""
import struct

PAGE = 4096
PORTMAP, MOUNT, NFS = 100000, 100005, 100003


# ---- the database file ------------------------------------------------------

def device_string(text):
    """A DeviceSQL string: short ASCII, long ASCII or long UTF-16LE."""
    try:
        raw = text.encode("ascii")
        if len(raw) <= 126:
            return bytes([((len(raw) + 1) << 1) | 1]) + raw
        return struct.pack("<BHB", 0x40, 4 + len(raw), 0) + raw
    except UnicodeEncodeError:
        raw = text.encode("utf-16-le")
        return struct.pack("<BHB", 0x90, 4 + len(raw), 0) + raw


def track_row(track_id, title):
    """A track row: the fixed part (0x88 bytes) and the strings after it."""
    empty = device_string("")
    strings = empty + device_string(title)
    row = bytearray(0x88)
    struct.pack_into("<H", row, 0x00, 0x24)             # subtype
    struct.pack_into("<I", row, 0x48, track_id)
    struct.pack_into("<H", row, 0x5c, 3)                # the 3 before the offsets
    for i in range(21):
        struct.pack_into("<H", row, 0x5e + 2 * i, 0x88)         # the empty string
    struct.pack_into("<H", row, 0x5e + 2 * 17, 0x88 + len(empty))   # the title
    return bytes(row) + strings


def build_pdb(titles):
    """export.pdb for {rekordbox id: title}: the header page, an empty index page
    (the first page of a table is one), and the data pages of the tracks."""
    rows = [track_row(i, t) for i, t in sorted(titles.items())]
    data_pages = []
    page = []
    heap = 0
    for row in rows:
        count = len(page) + 1
        index = ((count + 15) // 16) * 4 + 2 * count
        if page and 0x28 + heap + len(row) + index > PAGE:
            data_pages.append(page)
            page, heap = [], 0
        page.append(row)
        heap += len(row)
    if page or not data_pages:
        data_pages.append(page)

    first, last = 1, 1 + len(data_pages)
    out = bytearray(PAGE * (last + 1))
    struct.pack_into("<II", out, 4, PAGE, 1)            # page size, number of tables
    struct.pack_into("<I", out, 0x0c, last + 1)         # next unused page
    struct.pack_into("<IIII", out, 0x1c, 0, 0, first, last)

    def header(n, flags, next_page):
        base = PAGE * n
        struct.pack_into("<IIII", out, base, 0, n, 0, next_page)
        out[base + 0x1b] = flags
        return base

    base = header(first, 0x64, 2)                       # the index page: no entries
    for n, rows_in_page in enumerate(data_pages, start=2):
        base = header(n, 0x24, n + 1 if n < last else n)
        pos = 0x28
        offsets = []
        for row in rows_in_page:
            offsets.append(pos - 0x28)
            out[base + pos:base + pos + len(row)] = row
            pos += len(row)
        count = len(rows_in_page)
        out[base + 0x18:base + 0x1b] = (count | (count << 13)).to_bytes(3, "little")   # 13 + 11 bits
        struct.pack_into("<HH", out, base + 0x1c, PAGE - pos - 4 * ((count + 15) // 16) - 2 * count,
                         pos - 0x28)
        for k, ofs in enumerate(offsets):
            group, bit = divmod(k, 16)
            group_base = base + PAGE - 36 * (group + 1)
            struct.pack_into("<H", out, group_base + 2 * (15 - bit), ofs)
            present = struct.unpack_from("<H", out, group_base + 32)[0] | (1 << bit)
            struct.pack_into("<H", out, group_base + 32, present)
    return bytes(out)


def parse_pdb(pdb):
    """{id: title} of the tracks of an export.pdb, read as the analysis describes (the
    table pointer, the list of pages, the row groups at the end of each data page, the
    18th string of a track row). A reference to check the files made here and real ones."""
    size, tables = struct.unpack_from("<II", pdb, 4)
    first = last = None
    for t in range(tables):
        kind, _, f, l = struct.unpack_from("<IIII", pdb, 0x1C + 16 * t)
        if kind == 0:
            first, last = f, l
    found = {}
    n = first
    while n is not None:
        page = pdb[n * size:(n + 1) * size]
        _, index, kind, nxt = struct.unpack_from("<IIII", page, 0)
        if index != n or kind != 0:
            break
        if not page[0x1B] & 0x40:
            offsets = (page[0x18] | page[0x19] << 8 | page[0x1A] << 16) & 0x1FFF
            for row in range(offsets):
                group, bit = divmod(row, 16)
                base = size - 36 * (group + 1)
                if struct.unpack_from("<H", page, base + 32)[0] >> bit & 1:
                    start = 0x28 + struct.unpack_from("<H", page, base + 2 * (15 - bit))[0]
                    at = start + struct.unpack_from("<H", page, start + 0x5E + 2 * 17)[0]
                    kind = page[at]
                    if kind & 1:
                        title = page[at + 1:at + (kind >> 1)].decode("ascii")
                    else:
                        length = struct.unpack_from("<H", page, at + 1)[0]
                        raw = page[at + 4:at + length]
                        title = raw.decode("utf-16-le") if kind == 0x90 else raw.decode("utf-8")
                    found[struct.unpack_from("<I", page, start + 0x48)[0]] = title
        if n == last:
            break
        n = nxt
    return found
