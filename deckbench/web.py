# SPDX-License-Identifier: MIT OR Apache-2.0
"""The bench's page and its API, served over HTTP with the standard library.

    GET  /                       the page: a row for each deck
    GET  /api/state              what the decks are (core.World.snapshot())
    GET  /api/ready              {"ready": true} and how the bench was started (version, ports, pid)
    POST /api/deck/<n>/<what>    a click on switch <what> of deck <n>: on,
                                 play, sync or master; answers the new state
    POST /api/deck/<n>/<what>/<0|1>
                                 sets the switch instead of toggling it
    POST /api/deck/<n>/seek/<beat>   the deck goes to that beat of its track (0 is the first), on the grid. A loop that is set stays: waited for when it is ahead, gone round when the deck is in it, left behind when the deck is past it
    POST /api/deck/<n>/jump/<beats>  and that many beats from the beat it is at (negative: back)
                                     Any of the switches, cue, loop, seek and jump may have `?at=<bench time>`: the moment the page was clicked
                                     (the page knows the bench's clock). The action is made where the deck was then, not where it is when
                                     the request arrives (a pause stops right at the playhead), if that was within 5 s.
    POST /api/deck/<n>/cue[/<1|0>]   CUE: pressed (1) and let go (0), or a tap. Playing: back to the cue point, paused. Paused on it: plays
                                     while held. Paused elsewhere: that is the cue point (play pauses and plays on from where it is)
    POST /api/deck/<n>/loop/<beats>  a loop of that many beats from the beat the
                                 deck is in (0 ends it)
    POST /api/deck/<n>/tempo/<bpm>   the pitch fader: the deck plays at that tempo
    POST /api/deck/<n>/load/<id>     the deck loads that track (optional ?title=...&bpm=...)
    POST /api/deck/<n>/unplug        the cable is pulled (plug: plugged in; silence/<seconds>: unplugged for a while)
    POST /api/loss/<percent>         that share of the datagrams is lost (0 for none)
    POST /api/scenario               plays the scenario in the body (JSON, see scenario.py); 409 if one plays
    POST /api/scenario/stop          ends it
    POST /api/scenario/clear         forgets the last one's results (409 while one plays)
    GET  /api/scenario               how far it is: running, name, total, results, failed, stopped
    GET  /api/events?since=<n>       what the device under test did, from the n-th event on (see events.py)
    POST /api/events/clear           forget them
    GET  /api/examples               the scenarios that come with the bench: [{file, group, name, text}]
    GET  /api/stream                 the same as server-sent events: `state` (when the decks change, and every second),
                                     `event` (each event of the device under test), `scenario` (how far it is)
    POST /api/mixer/on/<0|1>          the simulated mixer on or off (also master/<0|1>)
    POST /api/mixer/channel/<n>/fader/<0-100>, .../fader_start/<0|1>, .../command/<start|stop>
    GET  /api/packets?since=<n>&noisy=0|1   the packets heard on the link (the statuses and beats too unless noisy=0), from the n-th on
    POST /api/packets/clear          forget them
    GET  /api/unit                   what is known of the device under test: the network's word and the adapters' (lamps...)
    POST /api/unit/press/<control>   press a control of the device under test through an adapter (sync, master)
    POST /api/settings/<name>/<value>  strict and refuse_db (0 or 1), model (the name the decks announce)
    POST /api/deck/<n>/load/<id>     also ?source=<player>&slot=<n>: the track is in that player's database. A real player's SD or USB
                                     track: the bench reads its grid, title and waveform from that player, and the deck plays on the grid
    GET  /api/deck/<n>/track-waveform  that real track's waveform and grid, as /api/player/<ip>/waveform has a player's (404 until read)
    POST /api/deck/<n>/load/<id>     also ?audio=<a path on the bench's machine>&bpm=<what it was made at>&offset=<seconds>: the deck plays
                                     that sound file (a WAV, or what ffmpeg reads) at its tempo instead of its drum loop. 400 and
                                     {"error": ...} if the file will not do
    POST /api/deck/<n>/audio/clear   the deck's drum loop again
    GET  /api/deck/<n>/waveform      the deck's sound file's loudness, {"rate": values a second, "peaks": [0 to 100 ...]}, for the page to draw
                                     (404 if it has none)
    GET  /api/deck/<n>/audio.wav     the deck's sound file as a 16-bit stereo 44.1 kHz WAV (404 if it plays its drum loop): what the
                                     page plays for it, as it plays the drum loop for the others
    POST /api/journal/start          starts keeping every request that changes the decks, with its time, after a baseline (the requests
                                     that would put the decks where they are): answers {"began", "baseline"}
    POST /api/journal/stop           ends it, and answers {"began", "baseline", "actions": [[time, "/api/..."], ...]} (see journal.py)
    POST /api/upload?name=<file name>   the body is a sound file, which the bench keeps in a folder of its own on its machine (~/.deckbench/tracks,
                                     see uploads.py: named by a hash of the file, so the same file is one, kept between runs and removed when unused
                                     for a month): the answer is {"path", "name", "bytes"}, the path to give a deck's ?audio=. It is how a page
                                     picks a file from the machine the browser is on (413 above 300 MB)
    POST /api/audio/source/<n|all>   the sound port plays only deck n (the unit's input is one CDJ), or all the decks again: the state's
                                     bench.audio_source says which. The emulator's deck does it when the INPUT SOURCE knob is turned
    GET  /api/uploads                the folder and what it holds: {"dir", "files", "bytes"}
    GET  /api/share                  sharing the bench with phones on this network: {"on", "fixed", "url", "direct", "address", "port",
                                     "addresses", "qr"}. Only for a page on this machine (403 elsewhere)
    POST /api/share/on?address=<IPv4>  listen on that address too (default: the one the phone is likely to reach), with a token of its own,
                                     for the hosted page: answers as GET. 409 when the bench was started with --phone, which shares already
    POST /api/share/off              stop: the phones' connections close and the token is forgotten
    POST /api/uploads/clear          removes the sent files (not one a deck has loaded): {"removed", "bytes"}

The page (deckbench/ui: index.html, app.css, app.js, no build step and no packages) follows /api/stream and counts the
beat squares on from each deck's phase, so it needs nothing but a browser, on the machine or any that can reach the port
(by default it listens on 127.0.0.1 only).
"""
import hmac
import ipaddress
import json
import os
import re
import secrets
import subprocess
import threading
import sys
import time
from urllib.parse import parse_qs, unquote, urlparse
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .audio import AudioError
from . import uploads as upload_store
from .core import log
from .journal import Journal
from .scenario import Runner, ScenarioError

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UPLOAD_LIMIT = 300 * 1024 * 1024          # bytes of one uploaded sound file
KINDS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon"}


def examples():
    """The scenarios that come with the bench (deckbench/examples, its folder `unit` for a device under test and
    `players` for real players on the network):
    [{file, group, name, text}]."""
    out = []
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")
    for group, folder in (("Examples", base), ("Unit under test", os.path.join(base, "unit")),
                          ("Real players", os.path.join(base, "players"))):
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name.endswith(".json"):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    text = f.read()
                out.append({"file": name, "group": group, "name": json.loads(text).get("name", name[:-5]), "text": text})
    return out


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # The queue of connections waiting to be accepted. The default, 5, overflows when a page opens (its event stream and a dozen requests
    # at once, with other programs asking too): the connection that does not fit is held back a second (or, through WSL's forwarding of
    # localhost, refused), and the page says the bench does not answer.
    request_queue_size = 128
    # each listener's own: the token it wants, the other origins it allows, whether it is the phones' and has been stopped
    token, allowed, shared, closed = None, frozenset(), False, False

    def server_bind(self):
        """As HTTPServer's, without the reverse lookup of the address (socket.getfqdn), which can take many seconds on a machine
        whose DNS is slow, a macOS runner for one, and holds up the start."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        """A page that went away before its answer (closed, reloaded, gave up) is normal: no traceback for that. Anything
        else is printed as socketserver does."""
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(world, host="127.0.0.1", port=8750, allow_origins=(), token=None, tracks=None, network=None, phone_address=None):
    """Starts the server in a thread; returns it.

    A request to the API that comes from a page (it has an Origin header) is refused unless that page is the bench's own
    or its origin is in `allow_origins` (for a page hosted elsewhere, such as https://commitcollective.cc), which is
    then given the CORS headers it needs, a preflight for a private network included. With a `token` the API wants it,
    as `?token=...` or `Authorization: Bearer ...`. The page's own files are served to anyone who can reach the port. The files the page
    sends are kept in the folder `tracks` (default uploads.default_dir()).

    A page on this machine can share the bench with phones (/api/share): a second listener on an address of the local
    network, with a token of its own and the hosted page allowed, which stops when asked. `phone_address` is the address
    it offers first. The returned server's set_phone_link(url, direct, address, port) says the bench already shares
    (started with --phone): the page then shows that link and cannot stop it."""
    allowed = {o.rstrip("/") for o in allow_origins}
    # sharing with phones: the second listener, or the link of a bench started with --phone (fixed)
    share = {"server": None, "url": None, "direct": None, "address": None, "port": None, "fixed": False}
    share_lock = threading.Lock()
    runner = Runner(world)
    journal = Journal()
    mutation_lock = threading.RLock()
    folder = tracks or upload_store.default_dir()

    def loaded():
        """The files the decks play now."""
        with world.lock:
            return [d.audio.path for d in world.decks.values() if d.audio]

    removed, freed = upload_store.trim(folder)
    if removed:
        log("removed %d unused file%s (%.1f MB) from %s" % (removed, "" if removed == 1 else "s", freed / 1048576.0, folder))

    def keep_upload(name, source, length):
        """Writes `length` bytes of `source` (a file object) to the bench's folder of sent files and gives its path."""
        return upload_store.keep(folder, name, source, length)
    STATIC = set(os.listdir(UI)) if os.path.isdir(UI) else set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def cors(self):
            """The headers that let an allowed page read the answer."""
            origin = self.headers.get("Origin")
            if origin and origin.rstrip("/") in self.server.allowed:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def send(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.cors()
            self.end_headers()
            self.wfile.write(data)

        def guard(self, preflight=False):
            """False (after answering) if this request to the API must not be done: from a page that is not allowed,
            or without the token."""
            if self.server.closed:                  # sharing stopped: a request that was on its way
                self.send(503, json.dumps({"error": "the bench no longer shares on this address"}))
                return False
            origin = self.headers.get("Origin")
            if origin and origin.rstrip("/") not in self.server.allowed and origin != "http://" + (self.headers.get("Host") or ""):
                self.send(403, json.dumps({"error": "this page may not use the bench: start it with --allow-origin %s" % origin}))
                return False
            token = self.server.token
            if token and not preflight:             # a browser sends no credentials with a preflight
                given = (self.headers.get("Authorization") or "")[7:] if (self.headers.get("Authorization") or "").startswith("Bearer ") \
                    else parse_qs(urlparse(self.path).query).get("token", [""])[0]
                if not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
                    self.send(401, json.dumps({"error": "the bench wants its token (?token=... or Authorization: Bearer ...)"}))
                    return False
            return True

        def do_OPTIONS(self):
            """The preflight of a page on another origin."""
            if not self.guard(preflight=True):
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.cors()
            self.end_headers()

        def stream(self):
            """Server-sent events until the page goes away."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.cors()
            self.end_headers()
            def send_event(kind, data):
                body = data if isinstance(data, str) else json.dumps(data)
                self.wfile.write(("event: %s\ndata: %s\n\n" % (kind, body)).encode("utf-8"))

            try:
                last = {"state": None, "scenario": None}
                sent_events, beat, generation = 0, 0.0, world.events.generation
                send_event("cleared", "{}")   # a reconnect replays the current server history
                while not self.server.closed:
                    snap = world.snapshot()
                    now = snap.pop("now")
                    key = json.dumps(snap, sort_keys=True)
                    if key != last["state"] or time.time() - beat > 1.0:    # also a clock now and then, for the beats
                        last["state"], beat = key, time.time()
                        send_event("state", dict(snap, now=now))
                    if generation != world.events.generation:                # cleared
                        generation, sent_events = world.events.generation, 0
                        send_event("cleared", "{}")
                    for item in world.events.since(sent_events):
                        sent_events = item["n"] + 1
                        send_event("event", item)
                    sc = json.dumps(runner.snapshot(), sort_keys=True)
                    if sc != last["scenario"]:
                        last["scenario"] = sc
                        send_event("scenario", sc)
                    self.wfile.flush()
                    time.sleep(0.1)
            except (OSError, ValueError):
                pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith("/api/") and not self.guard():
                return
            if path == "/api/stream":
                self.stream()
            elif path == "/" or path[1:] in STATIC:
                name = "index.html" if path == "/" else path[1:]
                with open(os.path.join(UI, name), "rb") as f:
                    self.send(200, f.read(), KINDS.get(os.path.splitext(name)[1], "application/octet-stream"))
            elif path == "/api/state":
                self.send(200, json.dumps(world.snapshot()))
            elif path == "/api/network":
                self.send(200 if network else 404, json.dumps(network.snapshot() if network else
                          {'error': 'Network setup is not enabled for this embedded bench'}))
            elif path == "/api/uploads":
                self.send(200, json.dumps(upload_store.summary(folder)))
            elif path == "/api/share":
                if not self.local_page():
                    return self.send(403, json.dumps({"error": "only a page on the bench's own machine sees how it is shared"}))
                self.send(200, json.dumps(share_state(listing=True)))
            elif re.fullmatch(r"/api/player/[\d.]+/waveform", path):
                answer = next((p.waveform_asset(path.split("/")[3]) for p in world.protocols
                               if hasattr(p, "waveform_asset")), (404, {"error": "no link protocol here"}))
                self.send(answer[0], json.dumps(answer[1]))
            elif re.fullmatch(r"/api/deck/\d+/track-waveform", path):
                answer = next((p.linked_waveform(int(path.split("/")[3])) for p in world.protocols
                               if hasattr(p, "linked_waveform")), (404, {"error": "no link protocol here"}))
                self.send(answer[0], json.dumps(answer[1]))
            elif re.fullmatch(r"/api/deck/\d+/waveform", path):
                deck = world.decks.get(int(path.split("/")[3]))
                track = deck.audio if deck else None
                if track:
                    self.send(200, json.dumps(dict(track.peaks(), file=os.path.basename(track.path))))
                else:
                    self.send(404, '{"error": "that deck has no sound file"}')
            elif re.fullmatch(r"/api/deck/\d+/audio\.wav", path):
                deck = world.decks.get(int(path.split("/")[3]))
                track = deck.audio if deck else None
                if track:
                    self.send(200, track.wav(), "audio/wav")
                else:
                    self.send(404, '{"error": "that deck has no sound file"}')
            elif path == "/api/packets":
                query = parse_qs(urlparse(self.path).query)
                try:
                    since, limit = int(query.get("since", ["0"])[0]), int(query.get("limit", ["400"])[0])
                except ValueError:
                    since, limit = 0, 400
                found = [p for p in world.protocols if hasattr(p, "monitor")]
                if not found:
                    self.send(200, json.dumps({"packets": [], "next": 0, "counts": {}}))
                else:
                    self.send(200, json.dumps(found[0].monitor.since(since, query.get("noisy", ["1"])[0] != "0", max(1, min(limit, 20000)))))
            elif path == "/api/unit":
                self.send(200, json.dumps(world.unit_state()))
            elif path == "/api/examples":
                self.send(200, json.dumps(examples()))
            elif path == "/api/ready":
                self.send(200, json.dumps(dict(world.info, ready=True)))
            elif path == "/api/scenario":
                self.send(200, json.dumps(runner.snapshot()))
            elif path == "/api/events":
                try:
                    since = int(parse_qs(urlparse(self.path).query).get("since", ["0"])[0])
                except ValueError:
                    since = 0
                self.send(200, json.dumps(world.events.since(since)))
            else:
                self.send(404, '{"error": "not found"}')

        def local_page(self):
            """A request from a page on the bench's own machine, through its own address: only such a page may share the bench
            with phones, or see the link (which has the token). Not through the phones' listener, not from another page's origin,
            and not through a name that only points here (the Host is the loopback)."""
            host = (self.headers.get("Host") or "").rpartition(":")[0] or (self.headers.get("Host") or "")
            origin = self.headers.get("Origin")
            return (not self.server.shared and self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
                    and host.strip("[]") in ("127.0.0.1", "localhost", "::1")
                    and (not origin or origin == "http://" + (self.headers.get("Host") or "")))

        def do_POST(self):
            if not self.guard():
                return
            if self.path.split("?")[0] in ("/api/share/on", "/api/share/off"):
                if not self.local_page():
                    return self.send(403, json.dumps({"error": "only a page on the bench's own machine can share it"}))
                address = parse_qs(urlparse(self.path).query).get("address", [""])[0].strip()
                code, body = answer(share_on(address) if self.path.split("?")[0].endswith("/on") else share_off())
                return self.send(code, json.dumps(body))
            if self.path.split('?')[0] == '/api/upload':
                return self.post()
            with mutation_lock:
                self.post()

        def post(self):
            parts = self.path.split("?")[0].strip("/").split("/")
            query = parse_qs(urlparse(self.path).query)
            if parts == ['api', 'network']:
                if not network:
                    return self.send(404, json.dumps({'error': 'Network setup is unavailable'}))
                if runner.snapshot().get('running') or world.info.get('recording') or world.info.get('cli_scenarios'):
                    return self.send(409, json.dumps({'error': 'Stop the scenario or action recording before reconnecting'}))
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 4096:
                        raise ValueError('network settings must be a JSON object smaller than 4 KB')
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict) or set(data) - {'interface', 'remember'}:
                        raise ValueError('expected interface and optional remember')
                    result = network.apply(data.get('interface'), data.get('remember', False))
                except RuntimeError as error:
                    return self.send(409, json.dumps({'error': str(error)}))
                except (OSError, ValueError, TypeError, KeyError) as error:
                    return self.send(400, json.dumps({'error': str(error)}))
                return self.send(200, json.dumps(result))
            if parts == ["api", "journal", "start"]:
                got = journal.start(world)
                world.info["recording"] = True                    # the page says so
                world.changed()
                return self.send(200, json.dumps(got))
            if parts == ["api", "journal", "stop"]:
                got = journal.stop()
                world.info["recording"] = False
                world.changed()
                return self.send(200, json.dumps(got))
            journal.note(self.path)
            if parts == ["api", "mark"]:
                label = query.get("text", [""])[0].strip()
                if not label or len(label) > 500:
                    return self.send(400, json.dumps({"error": "marker text must contain 1 to 500 characters"}))
                return self.send(200, json.dumps(world.events.add("marker", text=label)))
            if parts[:2] in (["api", "mixer"], ["api", "player"]):
                for protocol in world.protocols:
                    result = protocol.handle_api(parts[1:], query)
                    if result is not None:
                        world.changed()
                        return self.send(result[0], json.dumps(result[1] if result[0] != 200 else world.snapshot()))
                return self.send(404, '{"error": "no matching link protocol here"}')
            if parts == ["api", "upload"]:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                if length <= 0:
                    return self.send(400, json.dumps({"error": "the body is the sound file, and has a length"}))
                if length > UPLOAD_LIMIT:
                    self.close_connection = True
                    return self.send(413, json.dumps({"error": "that file is over %d MB" % (UPLOAD_LIMIT >> 20)}))
                try:
                    path = keep_upload(query.get("name", ["track"])[0], self.rfile, length)
                except OSError as e:
                    return self.send(400, json.dumps({"error": str(e)}))
                return self.send(200, json.dumps({"path": path, "name": os.path.basename(path), "bytes": length}))
            if len(parts) == 4 and parts[:3] == ["api", "audio", "source"]:
                number = None if parts[3] == "all" else int(parts[3]) if parts[3].isdigit() else -1
                if not world.set_audio_source(number):
                    return self.send(404, '{"error": "no such deck"}')
                return self.send(200, json.dumps(world.snapshot()))
            if parts == ["api", "uploads", "clear"]:
                count, size = upload_store.clear(folder, loaded())
                return self.send(200, json.dumps({"removed": count, "bytes": size}))
            if parts == ["api", "packets", "clear"]:
                for protocol in world.protocols:
                    if hasattr(protocol, "monitor"):
                        protocol.monitor.clear()
                return self.send(200, "{}")
            if len(parts) == 4 and parts[:3] == ["api", "unit", "press"]:
                ok, why = world.press_unit(control=unquote(parts[3]))
                if not ok:
                    return self.send(409 if "not connected" in why else 400, json.dumps({"error": why}))
                return self.send(200, json.dumps({"ok": True}))
            if len(parts) == 4 and parts[:2] == ["api", "settings"]:
                value = unquote(parts[3])
                if not any(p.set_option(parts[2], value) for p in world.protocols):
                    return self.send(400, json.dumps({"error": "no such setting or value"}))
                world.changed()
                return self.send(200, json.dumps(world.snapshot()))
            if parts == ["api", "scenario"]:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    data = json.loads(self.rfile.read(length).decode("utf-8"))
                    runner.start(data)
                except (ValueError, UnicodeDecodeError) as e:
                    return self.send(400, json.dumps({"error": "not a scenario: %s" % e}))
                except ScenarioError as e:
                    return self.send(400, json.dumps({"error": str(e)}))
                except RuntimeError as e:
                    return self.send(409, json.dumps({"error": str(e)}))
                return self.send(200, json.dumps(runner.snapshot()))
            if parts == ["api", "scenario", "stop"]:
                runner.stop()
                return self.send(200, json.dumps(runner.snapshot()))
            if parts == ["api", "scenario", "clear"]:
                try:
                    runner.clear()
                except RuntimeError as e:
                    return self.send(409, json.dumps({"error": str(e)}))
                return self.send(200, json.dumps(runner.snapshot()))
            if parts == ["api", "events", "clear"]:
                world.events.clear()
                return self.send(200, "[]")
            if len(parts) == 3 and parts[:2] == ["api", "loss"]:
                try:
                    world.set_loss(float(parts[2]))
                except ValueError:
                    return self.send(400, '{"error": "no such share"}')
                return self.send(200, json.dumps(world.snapshot()))
            if len(parts) in (4, 5) and parts[:2] == ["api", "deck"] and parts[3] in (
                    "tempo", "load", "unplug", "plug", "silence", "audio"):
                try:
                    deck = world.decks[int(parts[2])]
                except (ValueError, KeyError):
                    return self.send(404, '{"error": "no such deck"}')
                what = parts[3]
                try:
                    if what == "tempo" and len(parts) == 5:
                        world.set_tempo(deck, float(parts[4]))
                    elif what == "load" and len(parts) == 5:
                        bpm = query.get("bpm", [None])[0]
                        source, slot = query.get("source", [None])[0], query.get("slot", [None])[0]
                        audio, offset = query.get("audio", [None])[0], query.get("offset", [None])[0]
                        if audio:
                            world.load_audio(deck, audio, float(bpm) if bpm else None, query["title"][0] if "title" in query else None,
                                             int(parts[4]), float(offset) if offset else 0.0,
                                             int(source) if source else None, int(slot) if slot else None)
                            upload_store.touch(audio)             # a file of the folder that is in use is not old
                        else:
                            world.load_track(deck, int(parts[4]), query["title"][0] if "title" in query else None,
                                             float(bpm) if bpm else None, int(source) if source else None,
                                             int(slot) if slot else None)
                    elif what == "audio" and len(parts) == 5 and parts[4] == "clear":
                        world.clear_audio(deck)
                    elif what == "unplug" and len(parts) == 4:
                        world.set_unplugged(deck, True)
                    elif what == "plug" and len(parts) == 4:
                        world.set_unplugged(deck, False)
                    elif what == "silence" and len(parts) == 5:
                        world.silence(deck, float(parts[4]))
                    else:
                        return self.send(400, '{"error": "no such action"}')
                except AudioError as e:
                    return self.send(400, json.dumps({"error": str(e)}))
                except ValueError:
                    return self.send(400, '{"error": "no such value"}')
                return self.send(200, json.dumps(world.snapshot()))
            if len(parts) in (4, 5) and parts[:2] == ["api", "deck"]:
                try:
                    deck = world.decks[int(parts[2])]
                except (ValueError, KeyError):
                    return self.send(404, '{"error": "no such deck"}')
                what = parts[3]
                try:
                    at = float(query["at"][0]) if "at" in query else None       # when the page was clicked, in bench time
                except ValueError:
                    at = None
                if what == "cue":                       # CUE: down (cue/1) and up (cue/0), or a tap
                    if deck.enabled:
                        if len(parts) == 5:
                            world.set_cue(deck, parts[4] == "1", at)
                        else:
                            world.toggle(deck, "cue", at)
                    return self.send(200, json.dumps(world.snapshot()))
                if what in ("seek", "jump") and len(parts) == 5:      # seek/<beat>: to that beat. jump/<beats>: that far from here (negative: back)
                    try:
                        beats = int(parts[4])
                    except ValueError:
                        return self.send(400, '{"error": "no such place"}')
                    if deck.enabled:
                        world.seek(deck, beats, what == "jump", at)
                    return self.send(200, json.dumps(world.snapshot()))
                if what == "loop" and len(parts) == 5:      # the loop's length in beats, 0 for none
                    try:
                        beats = int(parts[4])
                    except ValueError:
                        beats = -1
                    if not 0 <= beats <= 64:
                        return self.send(400, '{"error": "no such loop"}')
                    if deck.enabled:
                        world.set_loop(deck, beats, at)
                    return self.send(200, json.dumps(world.snapshot()))
                if len(parts) == 5:             # set, not toggle
                    want = parts[4] == "1"
                    # a deck held on CUE is not playing for PLAY: play/1 then plays on, as on a CDJ
                    current = {"on": deck.enabled, "play": deck.playing and not deck.cueing, "sync": deck.sync,
                               "master": deck.master}.get(what)
                    if current is None:
                        return self.send(400, '{"error": "no such switch"}')
                    ok = current == want or world.toggle(deck, what, at)
                else:
                    ok = world.toggle(deck, what, at)
                if not ok:
                    return self.send(400, '{"error": "no such switch"}')
                return self.send(200, json.dumps(world.snapshot()))
            self.send(404, '{"error": "not found"}')

    def share_state(listing=False):
        """What the page on this machine is told of sharing. With `listing`, the addresses it can share on (asking the system
        can take a moment) and the QR of the link."""
        from . import phone
        with share_lock:
            out = {"on": bool(share["fixed"] or share["server"]), "fixed": share["fixed"], "url": share["url"],
                   "direct": share["direct"], "address": share["address"], "port": share["port"]}
        if listing:
            route = phone_address or phone.route_address()
            try:
                found = [(name, str(ip.ip)) for name, ip in phone.interfaces() if not ip.ip.is_loopback]
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
                found = []
            addresses = [{"name": name, "address": address, "default": address == route} for name, address in found]
            if route and not any(a["address"] == route for a in addresses):
                addresses.insert(0, {"name": "", "address": route, "default": True})
            out["addresses"] = sorted(addresses, key=lambda a: not a["default"])
            out["qr"] = phone.qr_matrix(out["url"]) if out["url"] else None
        return out

    def share_on(address):
        """Shares the bench on `address` (default: the one phones are likely to reach): (status, body)."""
        from . import phone
        with share_lock:
            if share["fixed"]:
                return 409, {"error": "the bench was started with --phone: it shares until it stops"}
            if share["server"]:
                return 200, None
        address = address or phone_address or phone.route_address() or ""
        try:
            ip = ipaddress.IPv4Address(address)
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
                raise ValueError()
        except ValueError:
            return 400, {"error": "give an IPv4 address of this machine that phones can reach, not %r" % address}
        try:
            try:
                shared = Server((str(ip), server.server_address[1]), Handler)   # the same port, if it is free there
            except OSError:
                shared = Server((str(ip), 0), Handler)
        except OSError as e:
            return 400, {"error": "cannot listen on %s: %s" % (ip, e.strerror or e)}
        shared.token, shared.allowed, shared.shared, shared.closed = (secrets.token_urlsafe(12), allowed | {phone.SITE},
                                                                     True, False)
        shared.daemon_threads = True
        threading.Thread(target=shared.serve_forever, daemon=True).start()
        port_ = shared.server_address[1]
        with share_lock:
            share.update(server=shared, address=str(ip), port=port_, url=phone.pairing_url(str(ip), port_, shared.token),
                         direct="http://%s:%d/#token=%s" % (ip, port_, shared.token))
        world.info["phone"] = {"address": str(ip), "port": port_}
        log("phone: shared on http://%s:%d/ with a token of its own, until it is stopped" % (ip, port_))
        world.changed()
        return 200, None

    def share_off():
        with share_lock:
            if share["fixed"]:
                return 409, {"error": "the bench was started with --phone: it shares until it stops"}
            shared = share["server"]
            share.update(server=None, url=None, direct=None, address=None, port=None)
        if shared:
            shared.closed = True                    # the phones' event streams end, and their next requests are refused
            shared.shutdown()
            shared.server_close()
            world.info["phone"] = None
            log("phone: no longer shared")
            world.changed()
        return 200, None

    def answer(result):
        code, body = result
        return code, body if body is not None else share_state(listing=True)

    def set_phone_link(url, direct, address, port_):
        with share_lock:
            share.update(fixed=True, url=url, direct=direct, address=address, port=port_)
        world.info["phone"] = {"address": address, "port": port_, "fixed": True}     # the page lights its Phone button
        world.changed()

    server = Server((host, port), Handler)
    server.token, server.allowed, server.shared, server.closed = token, allowed, False, False
    server.set_phone_link = set_phone_link
    server.runner = runner
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log("page and API on http://%s:%d/" % (host, server.server_address[1]))
    return server
