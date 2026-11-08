# SPDX-License-Identifier: MIT OR Apache-2.0
"""Reading a file from a player's SD or USB, as a player reads a linked track: ONC RPC over UDP, the portmapper, MOUNT
version 1 and NFS version 2, read only.

What players accept, as Deep Symmetry's Crate Digger found it: no authentication, the SD mounted as /B/ and the USB as
/C/, the names in UTF-16LE, one lookup for each part of a path (they do not take a path whole), and reads of 2048
bytes. The wire format is RFC 1057 (RPC) and RFC 1094 (NFS and MOUNT), encoded here independently.
"""
import random
import socket
import struct
import time

PORTMAP_PORT = 111
PORTMAP, MOUNT, NFS = 100000, 100005, 100003
MOUNTS = {2: "/B/", 3: "/C/"}               # the slots a file can be read from: SD and USB
CHUNK = 2048                                # bytes a read
WINDOW = 8                                  # reads in flight at once
NOENT = 2


class NfsError(Exception):
    """A player refused, or answered what this does not read."""


class NotFound(NfsError):
    """No such file or folder."""


def _opaque(raw):
    return struct.pack(">I", len(raw)) + raw + b"\0" * (-len(raw) % 4)


def _name(text):
    return _opaque(text.encode("utf-16-le"))


def _attributes(data, at):
    """The size and the modification time of NFS version 2 file attributes (17 words) at `at`."""
    words = struct.unpack_from(">17I", data, at)
    return {"type": words[0], "size": words[5], "mtime": (words[13], words[14])}


class Client:
    """A conversation with one player's NFS server, from a socket on `bind` (an address of the bench on the players'
    network, so the answers come back to it)."""

    def __init__(self, address, bind=None, portmap_port=PORTMAP_PORT, timeout=0.25, tries=6):
        self.address = address
        self.portmap_port = portmap_port
        self.timeout, self.tries = timeout, tries
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind or "0.0.0.0", 0))
        self.xid = random.getrandbits(31)
        self.ports = {}

    def close(self):
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- RPC --
    def packet(self, xid, prog, vers, proc, args):
        """A call with no credentials (AUTH_NONE), as the players take them."""
        return struct.pack(">IIIIIIIIII", xid, 0, 2, prog, vers, proc, 0, 0, 0, 0) + args

    def next_xid(self):
        self.xid = (self.xid + 1) & 0xFFFFFFFF
        return self.xid

    @staticmethod
    def results(data):
        """The results of an accepted reply. NfsError if it was refused."""
        if len(data) < 24:
            raise NfsError("a short reply")
        _, kind, stat = struct.unpack_from(">III", data)
        if kind != 1 or stat != 0:
            raise NfsError("the call was refused")
        length = struct.unpack_from(">I", data, 16)[0]
        at = 20 + length + (-length % 4)
        if struct.unpack_from(">I", data, at)[0] != 0:
            raise NfsError("the call was not accepted (%d)" % struct.unpack_from(">I", data, at)[0])
        return data[at + 4:]

    def calls(self, port, prog, vers, proc, many):
        """Makes the calls of `many` (their arguments), WINDOW at a time, sent again while they go unanswered: their
        results, in order. TimeoutError if one is never answered."""
        out, waiting, todo = [None] * len(many), {}, list(range(len(many)))[::-1]
        tries = {}
        while todo or waiting:
            now = time.monotonic()
            while todo and len(waiting) < WINDOW:
                i = todo.pop()
                xid = self.next_xid()
                waiting[xid] = (i, self.packet(xid, prog, vers, proc, many[i]), now + self.timeout)
                tries[i] = 1
                self.sock.sendto(waiting[xid][1], (self.address, port))
            for xid, (i, packet, due) in list(waiting.items()):
                if due <= now:
                    if tries[i] >= self.tries:
                        raise TimeoutError("%s does not answer" % self.address)
                    tries[i] += 1
                    waiting[xid] = (i, packet, now + min(self.timeout * 2 ** (tries[i] - 1), 2.0))
                    self.sock.sendto(packet, (self.address, port))
            self.sock.settimeout(max(0.001, min(due for _, _, due in waiting.values()) - time.monotonic()))
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            if len(data) < 4:
                continue
            entry = waiting.pop(struct.unpack_from(">I", data)[0], None)
            if entry:
                out[entry[0]] = self.results(data)
        return out

    def call(self, port, prog, vers, proc, args):
        return self.calls(port, prog, vers, proc, [args])[0]

    # -- the services --
    def port(self, prog, vers):
        """The UDP port of a service, from the portmapper."""
        if (prog, vers) not in self.ports:
            got = self.call(self.portmap_port, PORTMAP, 2, 3, struct.pack(">IIII", prog, vers, 17, 0))
            port = struct.unpack_from(">I", got)[0]
            if not port:
                raise NfsError("%s has no service %d version %d" % (self.address, prog, vers))
            self.ports[(prog, vers)] = port
        return self.ports[(prog, vers)]

    def mount(self, path):
        """The handle of an exported folder (/B/, /C/)."""
        got = self.call(self.port(MOUNT, 1), MOUNT, 1, 1, _name(path))
        status = struct.unpack_from(">I", got)[0]
        if status:
            raise NotFound("%s does not export %s (%d)" % (self.address, path, status)) if status == NOENT else \
                NfsError("%s refused to mount %s (%d)" % (self.address, path, status))
        return got[4:36]

    def lookup(self, folder, name):
        """(handle, attributes) of `name` in the folder."""
        got = self.call(self.port(NFS, 2), NFS, 2, 4, folder + _name(name))
        status = struct.unpack_from(">I", got)[0]
        if status:
            raise NotFound(name) if status == NOENT else NfsError("looking up %s: error %d" % (name, status))
        return got[4:36], _attributes(got, 36)

    def open(self, slot, path):
        """(handle, attributes) of the file at `path` on the slot's media. A media formatted HFS+ hides PIONEER as
        .PIONEER: that is tried when PIONEER is not there."""
        if slot not in MOUNTS:
            raise NfsError("files are read from SD and USB only")
        handle = self.mount(MOUNTS[slot])
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise NfsError("no file")
        attributes = None
        for n, part in enumerate(parts):
            try:
                handle, attributes = self.lookup(handle, part)
            except NotFound:
                if n or part != "PIONEER":
                    raise NotFound("%s is not on the %s" % (path, "SD" if slot == 2 else "USB"))
                handle, attributes = self.lookup(handle, ".PIONEER")
        return handle, attributes

    def read(self, handle, size, write, progress=None, limit=None):
        """Reads `size` bytes of the file and gives them to `write`, in order. `progress(done)` is told along the way."""
        if limit is not None and size > limit:
            raise NfsError("the file has %d MB, over %d MB" % (size >> 20, limit >> 20))
        done, batch = 0, CHUNK * WINDOW * 16
        nfs = self.port(NFS, 2)
        while done < size:
            offsets = range(done, min(size, done + batch), CHUNK)
            answers = self.calls(nfs, NFS, 2, 6, [handle + struct.pack(">III", o, CHUNK, 0) for o in offsets])
            for offset, got in zip(offsets, answers):
                status = struct.unpack_from(">I", got)[0]
                if status:
                    raise NfsError("reading the file: error %d" % status)
                length = struct.unpack_from(">I", got, 72)[0]
                data = got[76:76 + length]
                want = min(CHUNK, size - offset)
                if len(data) < want:
                    raise NfsError("a read came back short (%d of %d bytes)" % (len(data), want))
                write(data[:want])
            done = min(size, done + batch)
            if progress:
                progress(done)


def read_file(address, slot, path, bind=None, portmap_port=PORTMAP_PORT, limit=None):
    """The whole file at `path` on the player's SD (2) or USB (3), as bytes."""
    parts = []
    with Client(address, bind, portmap_port) as client:
        handle, attributes = client.open(slot, path)
        client.read(handle, attributes["size"], parts.append, limit=limit)
    return b"".join(parts)
