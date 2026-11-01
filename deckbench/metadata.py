# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bounded read-only track metadata queries using the public dbserver protocol."""
import socket
import struct
import time


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def recv(self, size):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("metadata deadline expired")
        self.sock.settimeout(remaining)
        return self.sock.recv(size)


def read_track_metadata(address, source, number, slot, rbid, query_port=12523, timeout=4):
    from .protocols.prolink import message, num, read_exact, read_message
    if not 1 <= number <= 4 or slot not in (1, 2, 3, 4) or not 0 < rbid <= 0xFFFFFFFF:
        raise ValueError("invalid metadata player, slot or track ID")
    deadline = time.monotonic() + timeout

    def connect(port):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("metadata deadline expired")
        return socket.create_connection((address, port), timeout=remaining, source_address=(source, 0))

    with connect(query_port) as query:
        query.sendall(struct.pack(">I", 15) + b"RemoteDBServer\0")
        port = struct.unpack(">H", read_exact(DeadlineSocket(query, deadline), 2))[0]
    if not port:
        raise ValueError("source advertises no database service")
    with connect(port) as sock:
        reader = DeadlineSocket(sock, deadline)
        sock.sendall(num(1))
        if read_exact(reader, 5) != num(1):
            raise ValueError("unexpected database greeting")

        def exchange(txid, kind, args):
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            sock.sendall(message(txid, kind, args))
            got_txid, got_kind, got_args = read_message(reader)
            if got_txid != txid:
                raise ValueError("database transaction mismatch")
            return got_kind, got_args

        kind, args = exchange(0xFFFFFFFE, 0, [("n", number)])
        if kind != 0x4000:
            raise ValueError("source rejected the requesting player")
        dmst = number << 24 | 1 << 16 | slot << 8 | 1
        kind, args = exchange(1, 0x2002, [("n", dmst), ("n", rbid)])
        if kind != 0x4000 or len(args) < 2 or not 0 < args[1][1] <= 128:
            raise ValueError("source rejected the track metadata request")
        count = args[1][1]
        sock.sendall(message(2, 0x3000, [("n", dmst), ("n", 0), ("n", count), ("n", 0), ("n", count), ("n", 0)]))
        result = {"rbid": rbid, "slot": slot}
        labels = {4: "title", 7: "artist", 2: "album", 6: "genre", 0x0F: "key", 0x23: "comment"}
        for _ in range(count + 2):
            txid, kind, args = read_message(reader)
            if txid != 2:
                raise ValueError("database transaction mismatch")
            if kind == 0x4201:
                return result
            if kind == 0x4001:
                continue
            if kind != 0x4101 or len(args) < 7:
                raise ValueError("unexpected metadata menu message")
            item = args[6][1] & 0xFFFF
            if item in labels and args[3][0] == "s":
                result[labels[item]] = args[3][1]
            elif item == 0x0B:
                result["duration_s"] = args[1][1]
            elif item == 0x0D:
                result["bpm"] = args[1][1] / 100.0
        raise ValueError("metadata menu has no footer")
