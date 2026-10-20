# SPDX-License-Identifier: MIT OR Apache-2.0
"""A bench to start from a test, in a process of its own, and to drive over its API.

    from deckbench.testing import Bench

    with Bench(numbers=[2, 3], on=True, init={2: "play,loop4"}) as bench:
        # point the device under test at bench.ports (shifted from the real ones unless shift=0), then:
        bench.post("api/deck/2/tempo/126")
        event = bench.wait_event("fader_start", timeout=5, deck=2)
        assert bench.state()["decks"]["2"]["playing"]

It takes the first free range of ports (`free_shift`), starts `python -m deckbench` and waits for it to say it is ready
(`--ready-file`), so there is no sleep to guess. What the bench printed is in `bench.output()`, to read when a test fails.
"""
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from .protocols.prolink import Ports


def ports_free(ports, address="0.0.0.0"):
    """True if every port of `ports` can be bound."""
    for kind, port in ((socket.SOCK_DGRAM, ports.announce), (socket.SOCK_DGRAM, ports.beat),
                       (socket.SOCK_DGRAM, ports.update), (socket.SOCK_STREAM, ports.query),
                       (socket.SOCK_STREAM, ports.db)):
        s = socket.socket(socket.AF_INET, kind)
        try:
            s.bind((address, port))
        except OSError:
            return False
        finally:
            s.close()
    return True


def free_shift(start=1000, stop=10000, step=100):
    """The first shift (see Ports) at which every port is free. RuntimeError if there is none.
    DECKBENCH_PORT_SHIFT, when set, is used as it is."""
    if os.environ.get("DECKBENCH_PORT_SHIFT"):
        return int(os.environ["DECKBENCH_PORT_SHIFT"])
    for shift in range(start, stop, step):
        if ports_free(Ports.shifted(shift)):
            return shift
    raise RuntimeError("no free range of ports: set DECKBENCH_PORT_SHIFT")


class BenchError(RuntimeError):
    pass


class Bench:
    """A bench in a process of its own. `numbers`: the players. `on`: start them on. `init`: {deck: "play,sync,loop4"}.
    `shift`: the ports' shift (None: the first free, 0: the real ones). `args`: more command line arguments.

    `wsl`: run the bench inside WSL (on Windows), for a device that lives there, such as an emulator on the Linux loopback:
    True for the default distribution or the name of one. The page and the API are then reached through WSL's localhost
    forwarding. The ports are WSL's own, so shift 0 is the real ones of a device that listens there."""

    def __init__(self, numbers=(1, 2, 3, 4), on=False, init=None, shift=None, args=(), timeout=15.0, wsl=None):
        self.numbers = list(numbers)
        self.shift = free_shift() if shift is None and not wsl else (0 if shift is None else shift)
        self.timeout = timeout
        self.wsl = [] if not wsl else ["wsl.exe"] + (["-d", wsl] if isinstance(wsl, str) else []) + ["--"]
        self.args = ["--numbers", ",".join(map(str, self.numbers)), "--http-port", "0", "--port-shift", str(self.shift),
                     "--exit-on-eof"]            # the bench goes with the process that started it, even if that is killed
        if self.wsl:
            self.args += ["--http-host", "0.0.0.0"]               # WSL forwards localhost to what listens on any address
        if on:
            self.args.append("--on")
        for deck, what in (init or {}).items():
            self.args += ["--init", "%d=%s" % (deck, what)]
        self.args += list(args)
        self.proc = None
        self.printed = ""
        self.info = {}
        self.url = None
        self.ports = Ports.shifted(self.shift)

    # -- life --
    def in_wsl(self, path):
        """A Windows path as WSL sees it."""
        out = subprocess.run(self.wsl + ["wslpath", "-a", path.replace("\\", "/")], capture_output=True, text=True, timeout=30)
        if out.returncode or not out.stdout.strip():
            raise BenchError("WSL did not answer (%s)" % (out.stdout + out.stderr).strip())
        return out.stdout.strip().splitlines()[-1]

    def start(self):
        self.dir = tempfile.mkdtemp(prefix="deckbench-")
        ready = os.path.join(self.dir, "ready.json")
        self.log = open(os.path.join(self.dir, "output.txt"), "w+b")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if self.wsl:
            script = "cd %s && exec python3 -m deckbench %s --ready-file %s" % (
                shlex.quote(self.in_wsl(root)), " ".join(shlex.quote(a) for a in self.args), shlex.quote(self.in_wsl(ready)))
            self.proc = subprocess.Popen(self.wsl + ["bash", "-lc", script], stdin=subprocess.PIPE, stdout=self.log,
                                         stderr=subprocess.STDOUT)
        else:
            self.proc = subprocess.Popen([sys.executable, "-m", "deckbench"] + self.args + ["--ready-file", ready],
                                         stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT, cwd=root)
        end = time.time() + self.timeout
        while time.time() < end:
            if os.path.exists(ready):
                with open(ready, encoding="utf-8") as f:
                    self.info = json.load(f)
                self.url = self.info["http"].replace("//0.0.0.0:", "//127.0.0.1:")
                return self
            if self.proc.poll() is not None:
                break
            time.sleep(0.05)
        out = self.output()
        self.stop()
        raise BenchError("the bench did not come up in %.0f s:\n%s" % (self.timeout, out))

    def stop(self):
        if self.proc is None:                                  # not started, or stopped already
            return
        if self.wsl:                                           # ending wsl.exe would leave the bench running in WSL
            if self.info.get("pid"):
                subprocess.run(self.wsl + ["kill", str(self.info["pid"])], capture_output=True, timeout=30)
            else:                                              # it never said it was ready: find it by its ready file
                name = os.path.basename(self.dir)
                subprocess.run(self.wsl + ["pkill", "-f", "[%s]%s/ready.json" % (name[0], name[1:])], capture_output=True, timeout=30)
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None
        self.output()                       # reads what it printed, to keep it after the file is closed
        self.log.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def output(self):
        """What the bench printed."""
        if self.log.closed:
            return self.printed
        self.log.flush()
        self.log.seek(0)
        self.printed = self.log.read().decode("utf-8", "replace")
        return self.printed

    # -- the API --
    def request_in_wsl(self, path, post, data):
        """The same through curl in WSL: where the bench lives, so it does not depend on WSL's localhost forwarding,
        which was seen to refuse after a while when an emulator ran beside the bench."""
        port = self.info["http"].rsplit(":", 1)[1].strip("/")
        curl = ["curl", "-s", "-m", "10", "-w", "<<%{http_code}", "-X", "POST" if post or data else "GET"]
        if data is not None:
            curl += ["--data-binary", "@-"]
        curl.append("http://127.0.0.1:%s/%s" % (port, path.lstrip("/")))
        # wsl.exe hands its arguments to a shell: a script of its own keeps the odd characters (%, {) as they are
        out = subprocess.run(self.wsl + ["bash", "-c", " ".join(shlex.quote(x) for x in curl)], input=data,
                             capture_output=True, timeout=30)
        text, _, code = out.stdout.decode("utf-8", "replace").rpartition("<<")
        if code != "200":
            raise BenchError("%s: %s %s" % (path, code or "no answer", text or out.stderr.decode("utf-8", "replace")))
        return json.loads(text)

    def request(self, path, post=False, body=None):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
        if self.wsl:
            return self.request_in_wsl(path, post, data)
        req = urllib.request.Request(self.url + path.lstrip("/"), data=data, method="POST" if post or data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise BenchError("%s: %d %s" % (path, e.code, e.read().decode("utf-8", "replace"))) from None

    def get(self, path):
        return self.request(path)

    def post(self, path, body=None):
        return self.request(path, post=True, body=body)

    def state(self):
        return self.get("api/state")

    def events(self, since=0):
        return self.get("api/events?since=%d" % since)

    def wait_event(self, kind, timeout=5.0, since=0, **match):
        """The first event of that kind with all of `match`, from event `since` on. None after `timeout` seconds."""
        end = time.time() + timeout
        while True:
            for item in self.events(since):
                if item["kind"] == kind and all(item.get(k) == v for k, v in match.items()):
                    return item
            if time.time() >= end:
                return None
            time.sleep(0.1)

    def run_scenario(self, scenario, timeout=60.0):
        """Plays a scenario (a dict) to its end and gives how far it got: `failed` lists the expectations that failed."""
        self.post("api/scenario", scenario)
        end = time.time() + timeout
        while time.time() < end:
            state = self.get("api/scenario")
            if not state.get("running"):
                return state
            time.sleep(0.2)
        raise BenchError("the scenario did not end in %.0f s" % timeout)


class FakeUnit:
    """A device that calls itself DJS-1000 on the link, to test the bench's side of a unit under test (what it hears of it,
    and the scenarios that expect things of it) with no emulator. `ports` is a Ports. It sends to the loopback's broadcast."""

    def __init__(self, ports, number=1, address="127.0.0.1", broadcast="127.255.255.255", name=b"DJS-1000"):
        self.ports, self.number, self.address, self.broadcast, self.name = ports, number, address, broadcast, name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.counter = 0

    def announce(self):
        from .protocols.prolink import header
        p = bytearray(0x36)
        p[:0x1F] = header(0x06, self.name)
        p[0x24] = self.number
        p[0x2C:0x30] = bytes(int(x) for x in self.address.split("."))
        self.sock.sendto(bytes(p), (self.broadcast, self.ports.announce))

    def status(self, master=False, synced=False, playing=False, bpm=120.0, pitch=0x100000, beat=1, on_air=False):
        """One status packet, as the unit's flags say: bit 6 plays, bit 5 master, bit 4 sync, bit 3 on air."""
        import struct
        from .protocols.prolink import header
        p = bytearray(0x124)
        p[:0x1F] = header(0x0A, self.name)
        p[0x21] = self.number
        self.counter += 1
        p[0x84:0x88] = struct.pack(">I", self.counter)
        p[0x89] = 0x84 | (0x40 if playing else 0) | (0x20 if master else 0) | (0x10 if synced else 0) | (0x08 if on_air else 0)
        p[0x8C:0x90] = struct.pack(">I", pitch)
        p[0x92:0x94] = struct.pack(">H", int(round(bpm * 100)))
        p[0x9F] = 0xFF
        p[0xA6] = beat
        self.sock.sendto(bytes(p), (self.broadcast, self.ports.update))

    def close(self):
        self.sock.close()
