# SPDX-License-Identifier: MIT OR Apache-2.0
"""The bench's page and its API, served over HTTP with the standard library.

    GET  /                       the page: a row for each deck
    GET  /api/state              what the decks are (core.World.snapshot())
    POST /api/deck/<n>/<what>    a click on switch <what> of deck <n>: on,
                                 play, sync or master; answers the new state
    POST /api/deck/<n>/<what>/<0|1>
                                 sets the switch instead of toggling it
    POST /api/deck/<n>/loop/<beats>  a loop of that many beats from the beat the
                                 deck is in (0 ends it)

The page polls /api/state and counts the beat squares on from each deck's
phase, so it needs nothing but a browser, on the machine or any that can reach
the port (by default it listens on 127.0.0.1 only).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import log

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>deckbench</title>
<style>
:root {
  --bg: #101114; --panel: #1a1b1f; --edge: #2c2e34; --text: #e1e4e8; --dim: #969aa2;
  --off: #28292d; --on: #96dc78; --play: #78d278; --sync: #6eaaf0; --master: #f0a03c; --loop: #c88cf0;
  --beat1: #eb2828; --beat: #3c82eb; --unlit: #1e1f23;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #f4f5f7; --panel: #ffffff; --edge: #d5d8de; --text: #1b1d21; --dim: #626874;
    --off: #e6e8ec; --unlit: #e3e5ea; color-scheme: light;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 18px; margin: 0 0 4px; font-weight: 600; }
.sub { color: var(--dim); margin: 0 0 20px; }
.deck { background: var(--panel); border: 1px solid var(--edge); border-radius: 10px;
  padding: 12px; margin-bottom: 10px; }
.deck.off { opacity: .8; }
.line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.title { color: var(--dim); font-size: 12px; margin-bottom: 8px; }
.title b { color: var(--text); font-weight: 600; }
button { font: inherit; min-width: 64px; height: 30px; border: 0; border-radius: 6px;
  background: var(--off); color: var(--dim); cursor: pointer; }
button.on { color: #0a0a0a; }
button[data-what=on].on { background: var(--on); }
button[data-what=play].on { background: var(--play); }
button[data-what=sync].on { background: var(--sync); }
button[data-what=master].on { background: var(--master); }
button[data-what=loop].on { background: var(--loop); }
button.n { min-width: 36px; }
.loops { margin-top: 6px; }
.loops .lbl { color: var(--dim); font-size: 12px; min-width: 64px; }
button:disabled { opacity: .45; cursor: default; }
button:focus-visible { outline: 2px solid var(--sync); outline-offset: 2px; }
.beats { display: flex; gap: 4px; margin-left: 10px; }
.beats i { width: 22px; height: 22px; border-radius: 4px; background: var(--unlit);
  border: 1px solid var(--edge); }
.beats i.lit { background: var(--beat); border-color: var(--beat); }
.beats i.lit.first { background: var(--beat1); border-color: var(--beat1); }
.bpm { margin-left: 10px; color: var(--dim); font-variant-numeric: tabular-nums; min-width: 80px; }
.unit { margin-top: 18px; color: var(--dim); font-size: 13px; }
.unit b { color: var(--text); font-weight: 600; }
.err { color: var(--master); }
</style>
</head>
<body>
<main>
  <h1>deckbench</h1>
  <p class="sub" id="sub">connecting&hellip;</p>
  <div id="decks"></div>
  <p class="unit" id="unit"></p>
</main>
<script>
const WHAT = [["on", "ON"], ["play", "PLAY"], ["sync", "SYNC"], ["master", "MASTER"]];
const LOOPS = [1, 2, 4, 8, 16, 32];
let offset = 0, state = null, built = "";

function build() {
  const keys = Object.keys(state.decks);
  if (keys.join() === built) return;
  built = keys.join();
  const root = document.getElementById("decks");
  root.textContent = "";
  for (const n of keys) {
    const d = document.createElement("section");
    d.className = "deck"; d.id = "deck" + n;
    d.innerHTML = '<div class="title"></div><div class="line"></div>';
    const line = d.querySelector(".line");
    for (const [what, label] of WHAT) {
      const b = document.createElement("button");
      b.dataset.what = what; b.dataset.n = n; b.textContent = label;
      b.addEventListener("click", () => click(n, what));
      line.appendChild(b);
    }
    const beats = document.createElement("div");
    beats.className = "beats";
    for (let k = 0; k < 4; k++) beats.appendChild(document.createElement("i"));
    line.appendChild(beats);
    const bpm = document.createElement("span");
    bpm.className = "bpm";
    line.appendChild(bpm);
    const loops = document.createElement("div");
    loops.className = "line loops";
    loops.innerHTML = '<span class="lbl">LOOP</span>';
    for (const beats of LOOPS) {
      const b = document.createElement("button");
      b.dataset.what = "loop"; b.dataset.beats = beats; b.className = "n";
      b.textContent = beats; b.title = beats + " beats from where the deck is; again to end it";
      b.addEventListener("click", () => loop(n, beats));
      loops.appendChild(b);
    }
    d.appendChild(loops);
    root.appendChild(d);
  }
}

function beat(d) {
  if (!d.phase) return 0;
  const [t, pos, bpm] = d.phase;
  const now = Date.now() / 1000 + offset;
  let at = pos + (now - t) * bpm / 60;
  if (d.loop && at >= d.loop_from + d.loop) at = d.loop_from + (at - d.loop_from) % d.loop;
  return Math.floor(at) % 4 + 1;
}

function render() {
  if (!state) return;
  build();
  for (const [n, d] of Object.entries(state.decks)) {
    const el = document.getElementById("deck" + n);
    if (!el) continue;
    el.classList.toggle("off", !d.on);
    const track = d.track ? ' &middot; ' + esc(d.track) : "";
    el.querySelector(".title").innerHTML = '<b>' + esc(d.name) + '</b>' + track +
      (d.model ? ' &middot; ' + esc(d.model) : "") +
      (d.address ? ' &middot; ' + esc(d.address) : "");
    for (const b of el.querySelectorAll("button")) {
      const what = b.dataset.what;
      b.classList.toggle("on", what === "loop" ? d.on && d.loop === +b.dataset.beats
                                               : !!d[what] && (what === "on" || d.on));
      b.disabled = what !== "on" && !d.on;
    }
    el.querySelector(".bpm").textContent = d.on ? d.bpm.toFixed(1) + " BPM" : "";
  }
  beats();
  const sub = document.getElementById("sub");
  sub.textContent = "Pro DJ Link decks on this machine's loopback; click a switch.";
  sub.classList.remove("err");
  const link = state.protocols.prolink, unit = link && link.unit, u = document.getElementById("unit");
  u.innerHTML = unit
    ? 'Unit under test: <b>player ' + unit.number + '</b>' + (unit.master ? ', tempo master' : '') +
      (unit.bpm ? ', ' + unit.bpm.toFixed(1) + ' BPM' : '') + ' (' + esc(unit.ip || "?") + ')'
    : 'No DJS-1000 heard on the network yet.';
}

function beats() {
  if (!state) return;
  for (const [n, d] of Object.entries(state.decks)) {
    const el = document.getElementById("deck" + n);
    if (!el) continue;
    const cur = d.on ? beat(d) : 0;
    el.querySelectorAll(".beats i").forEach((s, k) => {
      s.classList.toggle("lit", cur === k + 1);
      s.classList.toggle("first", k === 0);
    });
  }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
}

async function load(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(r.status);
  state = await r.json();
  offset = state.now - Date.now() / 1000;
}

async function click(n, what) {
  try { await load("api/deck/" + n + "/" + what, {method: "POST"}); render(); } catch (e) { fail(); }
}

async function loop(n, beats) {
  const d = state.decks[n], now = d && d.loop === beats ? 0 : beats;     // again: ends it
  try { await load("api/deck/" + n + "/loop/" + now, {method: "POST"}); render(); } catch (e) { fail(); }
}

function fail() {
  const sub = document.getElementById("sub");
  sub.textContent = "The bench does not answer.";
  sub.classList.add("err");
}

async function poll() {
  try { await load("api/state"); render(); } catch (e) { fail(); }
  setTimeout(poll, 300);
}

function frame() { beats(); requestAnimationFrame(frame); }
poll();
requestAnimationFrame(frame);
</script>
</body>
</html>
"""


def serve(world, host="127.0.0.1", port=8750):
    """Starts the server in a thread; returns it."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self.send(200, PAGE, "text/html")
            elif path == "/api/state":
                self.send(200, json.dumps(world.snapshot()))
            else:
                self.send(404, '{"error": "not found"}')

        def do_POST(self):
            parts = self.path.split("?")[0].strip("/").split("/")
            if len(parts) in (4, 5) and parts[:2] == ["api", "deck"]:
                try:
                    deck = world.decks[int(parts[2])]
                except (ValueError, KeyError):
                    return self.send(404, '{"error": "no such deck"}')
                what = parts[3]
                if what == "loop" and len(parts) == 5:      # the loop's length in beats, 0 for none
                    try:
                        beats = int(parts[4])
                    except ValueError:
                        beats = -1
                    if not 0 <= beats <= 64:
                        return self.send(400, '{"error": "no such loop"}')
                    if deck.enabled:
                        world.set_loop(deck, beats)
                    return self.send(200, json.dumps(world.snapshot()))
                if len(parts) == 5:             # set, not toggle
                    want = parts[4] == "1"
                    current = {"on": deck.enabled, "play": deck.playing, "sync": deck.sync,
                               "master": deck.master}.get(what)
                    if current is None:
                        return self.send(400, '{"error": "no such switch"}')
                    ok = current == want or world.toggle(deck, what)
                else:
                    ok = world.toggle(deck, what)
                if not ok:
                    return self.send(400, '{"error": "no such switch"}')
                return self.send(200, json.dumps(world.snapshot()))
            self.send(404, '{"error": "not found"}')

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log("page and API on http://%s:%d/" % (host, server.server_address[1]))
    return server
