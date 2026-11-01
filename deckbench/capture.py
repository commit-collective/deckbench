# SPDX-License-Identifier: MIT OR Apache-2.0
"""Offline packet replay. This module never starts a network listener or sender.

    python -m deckbench.capture capture.json [--seed 1 --loss 5 --jitter-ms 20]
"""
import argparse
import ipaddress
import json
import math
import random

from .core import World
from .protocols.prolink import Ports, Prolink


def replay_packets(packets, shift=0, seed=0, loss=0, delay_ms=0, jitter_ms=0):
    """Replay bounded full-payload exports into an isolated decoder with a virtual clock."""
    if not isinstance(packets, list) or len(packets) > 10000:
        raise ValueError("capture must be a list of at most 10000 packets")
    if not 0 <= loss <= 100 or min(delay_ms, jitter_ms) < 0:
        raise ValueError("loss must be 0 to 100 and delays nonnegative")
    if not all(math.isfinite(x) for x in (loss, delay_ms, jitter_ms)):
        raise ValueError("impairments must be finite")
    rng, arrivals, total = random.Random(seed), [], 0
    ports = Ports.shifted(int(shift))
    for index, packet in enumerate(packets):
        if not isinstance(packet, dict):
            raise ValueError("packet %d is not an object" % index)
        try:
            at = float(packet["t"])
            address = str(ipaddress.IPv4Address(packet["src"]))
            port = int(packet["port"])
            data = bytes.fromhex(packet["hex"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("packet %d has invalid time, address, port or hex" % index) from error
        if not math.isfinite(at) or at < 0 or port not in (ports.announce, ports.beat, ports.update):
            raise ValueError("packet %d has invalid time or does not use the selected link ports" % index)
        if len(data) > 65507 or packet.get("len", len(data)) != len(data):
            raise ValueError("packet %d is truncated or too large" % index)
        total += len(data)
        if total > 16 * 1024 * 1024:
            raise ValueError("capture payload exceeds 16 MiB")
        if rng.random() * 100 >= loss:
            delay = max(0, delay_ms + rng.uniform(-jitter_ms, jitter_ms)) / 1000
            arrivals.append((at + delay, index, data, address, port))
    # Arrival ordering, including deterministic reordering caused by jitter.
    arrivals.sort(key=lambda p: (p[0], p[1]))
    net = Prolink(World(), ports=ports)
    net.mixer.address = ""              # offline records must not be mistaken for our simulated mixer
    clock = [0.0]
    net.monitor.clock = lambda: clock[0]
    net.monitor.began = 0.0
    for at, _, data, address, port in arrivals:
        clock[0] = at
        net.monitor.feed(data, address, port)
    return {"offline": True, "received": len(arrivals), "dropped": len(packets) - len(arrivals),
            "counts": dict(net.monitor.counts), "devices": net.monitor.snapshot(now=clock[0])}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("capture")
    parser.add_argument("--port-shift", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--loss", type=float, default=0)
    parser.add_argument("--delay-ms", type=float, default=0)
    parser.add_argument("--jitter-ms", type=float, default=0)
    args = parser.parse_args()
    try:
        with open(args.capture, encoding="utf-8") as stream:
            contents = stream.read(40 * 1024 * 1024 + 1)
            if len(contents) > 40 * 1024 * 1024:
                raise ValueError("capture file exceeds 40 MiB")
            packets = json.loads(contents)
        result = replay_packets(packets, args.port_shift, args.seed, args.loss, args.delay_ms, args.jitter_ms)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
