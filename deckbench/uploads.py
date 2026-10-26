# SPDX-License-Identifier: MIT OR Apache-2.0
"""The folder of the sound files the page sends (Browse...), kept between runs.

A browser tells a page only a file's contents, never where it is, so the page sends the bytes and the bench keeps them in a folder of its own
on the machine it runs on: `~/.deckbench/tracks`, or $DECKBENCH_TRACKS, or `--tracks-dir`. A file is named by a hash of what is in it and its
name (`3f9a1c20bb-loop.wav`), so the same file sent twice is one file, and a path a session recorded (a journal, a REC) is still there the next
time the bench runs. Files that have not been used for a month are removed when the bench starts, and the oldest go if the folder passes 2 GB.
Nothing a deck has loaded is ever removed.
"""
import hashlib
import os
import re
import time

MAX_AGE = 30 * 86400                 # seconds a file may go unused
MAX_TOTAL = 2 << 30                  # bytes the folder may hold


def default_dir():
    return os.environ.get("DECKBENCH_TRACKS") or os.path.join(os.path.expanduser("~"), ".deckbench", "tracks")


def safe_name(name):
    return re.sub(r"[^\w.\- ]+", "_", os.path.basename(name.replace("\\", "/")))[:80] or "track"


def keep(folder, name, source, length):
    """Writes `length` bytes of `source` (a file object) to the folder, named by a hash of them and by `name`, and gives the path.
    OSError if the source stops short."""
    os.makedirs(folder, exist_ok=True)
    part = os.path.join(folder, ".part-%d-%d" % (os.getpid(), time.time_ns()))
    digest = hashlib.sha1()
    left = length
    try:
        with open(part, "wb") as f:
            while left > 0:
                chunk = source.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                left -= len(chunk)
        if left:                                     # the page went away half way
            raise OSError("the file did not come whole")
        path = os.path.join(folder, "%s-%s" % (digest.hexdigest()[:10], safe_name(name)))
        if os.path.exists(path):
            os.remove(part)
            touch(path)
        else:
            os.replace(part, path)
        return path
    finally:
        if os.path.exists(part):
            os.remove(part)


def touch(path):
    """A file is in use: it is not old."""
    try:
        os.utime(path)
    except OSError:
        pass


def files(folder):
    """[(path, bytes, seconds since it was last used)], oldest first. A half-sent file (.part) is not one."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    now = time.time()
    for name in names:
        path = os.path.join(folder, name)
        if name.startswith(".part-") or not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append((path, st.st_size, now - st.st_mtime))
    return sorted(out, key=lambda x: -x[2])


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def summary(folder):
    found = files(folder)
    return {"dir": folder, "files": len(found), "bytes": sum(f[1] for f in found)}


def remove(paths):
    count = size = 0
    for path, nbytes, _ in paths:
        try:
            os.remove(path)
        except OSError:
            continue
        count += 1
        size += nbytes
    return count, size


def clear(folder, busy=()):
    """Removes every file but those in `busy` (paths a deck has loaded). (how many, how many bytes)"""
    return remove([f for f in files(folder) if not any(_same(f[0], b) for b in busy)])


def trim(folder, busy=(), max_age=MAX_AGE, max_total=MAX_TOTAL):
    """Removes what has gone unused for `max_age` seconds, and then the oldest while the folder holds more than `max_total` bytes."""
    found = [f for f in files(folder) if not any(_same(f[0], b) for b in busy)]
    doomed = [f for f in found if f[2] > max_age]
    kept = [f for f in found if f[2] <= max_age]
    total = sum(f[1] for f in kept) + sum(f[1] for f in files(folder) if any(_same(f[0], b) for b in busy))
    while kept and total > max_total:
        oldest = kept.pop(0)
        doomed.append(oldest)
        total -= oldest[1]
    return remove(doomed)
