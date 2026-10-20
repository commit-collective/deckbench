# SPDX-License-Identifier: MIT OR Apache-2.0
"""The bench's page and its API, served over HTTP with the standard library.

    GET  /                       the page: a row for each deck
    GET  /api/state              what the decks are (core.World.snapshot())
    GET  /api/ready              {"ready": true} and how the bench was started (version, ports, pid)
    POST /api/deck/<n>/<what>    a click on switch <what> of deck <n>: on,
                                 play, sync or master; answers the new state
    POST /api/deck/<n>/<what>/<0|1>
                                 sets the switch instead of toggling it
    POST /api/deck/<n>/loop/<beats>  a loop of that many beats from the beat the
                                 deck is in (0 ends it)
    POST /api/deck/<n>/tempo/<bpm>   the pitch fader: the deck plays at that tempo
    POST /api/deck/<n>/load/<id>     the deck loads that track (optional ?title=...&bpm=...)
    POST /api/deck/<n>/unplug        the cable is pulled (plug: plugged in; silence/<seconds>: unplugged for a while)
    POST /api/loss/<percent>         that share of the datagrams is lost (0 for none)
    POST /api/scenario               plays the scenario in the body (JSON, see scenario.py); 409 if one plays
    POST /api/scenario/stop          ends it
    GET  /api/scenario               how far it is: running, name, total, results, failed, stopped
    GET  /api/events?since=<n>       what the device under test did, from the n-th event on (see events.py)
    POST /api/events/clear           forget them

The page polls /api/state and counts the beat squares on from each deck's
phase, so it needs nothing but a browser, on the machine or any that can reach
the port (by default it listens on 127.0.0.1 only).
"""
import json
import threading
from urllib.parse import parse_qs, unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import log
from .scenario import Runner, ScenarioError

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
.tools { margin-top: 8px; gap: 8px 14px; }
.tools .lbl { color: var(--dim); font-size: 12px; min-width: 64px; }
.tools label { color: var(--dim); font-size: 12px; display: flex; align-items: center; gap: 4px; }
input[type=number], input[type=text] { font: inherit; height: 28px; border: 1px solid var(--edge); border-radius: 6px;
  background: var(--bg); color: var(--text); padding: 0 6px; }
input[type=number] { width: 72px; }
input[type=text] { width: 150px; }
button.warn.on { background: var(--master); color: #0a0a0a; }
.panel { background: var(--panel); border: 1px solid var(--edge); border-radius: 10px; padding: 12px; margin-top: 10px; }
.panel h2 { font-size: 13px; margin: 0 0 8px; font-weight: 600; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; }
.panel input[type=range] { width: 220px; vertical-align: middle; }
.events { font: 12px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace; max-height: 220px; overflow: auto; }
.events div { white-space: nowrap; }
.events .t { color: var(--dim); display: inline-block; min-width: 56px; }
.events .k { color: var(--sync); display: inline-block; min-width: 130px; }
.bench { color: var(--dim); font-size: 12px; margin-top: 4px; }
textarea { width: 100%; font: 12px/1.4 ui-monospace, "SF Mono", Menlo, Consolas, monospace; background: var(--bg);
  color: var(--text); border: 1px solid var(--edge); border-radius: 6px; padding: 6px; resize: vertical; }
.events .bad { color: var(--master); }
</style>
</head>
<body>
<main>
  <h1>deckbench</h1>
  <p class="sub" id="sub">connecting&hellip;</p>
  <div id="decks"></div>
  <section class="panel">
    <h2>Network</h2>
    <label for="loss">Datagrams lost</label>
    <input type="range" id="loss" min="0" max="100" step="5" value="0">
    <output id="lossout">0 %</output>
    <div class="bench" id="bench"></div>
  </section>
  <section class="panel">
    <h2>Scenario <span style="float:right"><input type="file" id="scfile" accept=".json,application/json" style="display:none">
      <button id="scload" class="n" style="min-width:60px;height:24px">OPEN</button>
      <button id="scrun" class="n" style="min-width:52px;height:24px">RUN</button>
      <button id="scstop" class="n warn" style="min-width:52px;height:24px" disabled>STOP</button></span></h2>
    <textarea id="scenario" spellcheck="false" rows="7">{"name": "a loop and a stop", "steps": [
  {"at": 0,   "deck": 2, "do": "on"},
  {"at": 0.5, "deck": 2, "do": "play"},
  {"at": 4,   "deck": 2, "do": "loop", "beats": 4},
  {"at": 8,   "deck": 2, "do": "stop"}
]}</textarea>
    <div class="bench" id="scstatus">Steps and what they do: docs/scenarios.md</div>
    <div class="events" id="scresults"></div>
  </section>
  <section class="panel">
    <h2>What the unit did <button id="clear" class="n" style="float:right;min-width:52px;height:24px">CLEAR</button></h2>
    <div class="events" id="events"><div class="t">nothing yet</div></div>
  </section>
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
    const tempo = document.createElement("div");
    tempo.className = "line tools";
    tempo.innerHTML = '<span class="lbl">TEMPO</span><input type="number" step="0.1" min="40" max="220" class="tempo" ' +
      'title="the pitch fader: the BPM the deck plays at (a synced deck follows the master)">' +
      '<span class="lbl" style="margin-left:8px">TRACK</span>' +
      '<label>id <input type="number" min="1" class="tid" style="width:84px"></label>' +
      '<label>title <input type="text" class="ttitle"></label>' +
      '<label>BPM <input type="number" step="0.1" min="40" max="220" class="tbpm"></label>' +
      '<button class="n load" style="min-width:56px" title="load that track: it starts from its first beat">LOAD</button>';
    d.appendChild(tempo);
    const cable = document.createElement("div");
    cable.className = "line tools";
    cable.innerHTML = '<span class="lbl">CABLE</span>' +
      '<button class="warn unplug" data-what="cable" title="pull the cable: the deck says nothing and answers nothing">UNPLUG</button>' +
      '<button class="n silence" data-what="silence" title="pull the cable for 5 seconds">SILENCE 5 s</button>';
    d.appendChild(cable);
    tempo.querySelector(".tempo").addEventListener("change", e => send(n, "tempo/" + e.target.value));
    tempo.querySelector(".load").addEventListener("click", () => {
      const id = tempo.querySelector(".tid").value;
      if (!id) return;
      const title = tempo.querySelector(".ttitle").value, bpm = tempo.querySelector(".tbpm").value;
      send(n, "load/" + id + "?" + (title ? "title=" + encodeURIComponent(title) + "&" : "") + (bpm ? "bpm=" + bpm : ""));
    });
    cable.querySelector(".unplug").addEventListener("click", () => send(n, state.decks[n].unplugged ? "plug" : "unplug"));
    cable.querySelector(".silence").addEventListener("click", () => send(n, "silence/5"));
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
    const link = state.protocols.prolink, unit = link && link.unit;
    el.classList.toggle("off", !d.on);
    const track = d.track ? ' &middot; ' + esc(d.track) : "";
    el.querySelector(".title").innerHTML = '<b>' + esc(d.name) + '</b>' + track +
      (d.model ? ' &middot; ' + esc(d.model) : "") +
      (d.address ? ' &middot; ' + esc(d.address) : "");
    for (const b of el.querySelectorAll("button")) {
      const what = b.dataset.what;
      b.classList.toggle("on", what === "loop" ? d.on && d.loop === +b.dataset.beats
                                               : !!d[what] && (what === "on" || d.on));
      if (what === "cable" || what === "silence" || b.classList.contains("load")) continue;
      b.disabled = what !== "on" && !d.on;
      if (what === "on") {                        // the unit's own number: a clash, left off
        const mine = !!unit && unit.number === +el.id.slice(4);
        b.disabled = mine && !d.on;
        b.title = mine && !d.on ? "this is the unit's own number: a deck here is a clash" : "";
      }
    }
    el.querySelector(".bpm").textContent = d.on ? d.bpm.toFixed(1) + " BPM" : "";
    const tempo = el.querySelector(".tempo");
    if (document.activeElement !== tempo) tempo.value = d.bpm.toFixed(1);
    const cable = el.querySelector(".unplug");
    cable.classList.toggle("on", !!d.unplugged);
    cable.textContent = d.unplugged ? "PLUG IN" : "UNPLUG";
    cable.disabled = false;
    el.querySelector(".silence").disabled = !!d.unplugged;
  }
  const loss = document.getElementById("loss");
  if (document.activeElement !== loss) loss.value = state.loss;
  document.getElementById("lossout").textContent = state.loss + " %";
  const info = state.bench || {};
  document.getElementById("bench").textContent = [info.strict ? "strict: players 1 to 4 only" : "",
    info.audio ? "sound on " + info.audio : ""].filter(Boolean).join("  \u00b7  ");
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

async function send(n, path) {
  try { await load("api/deck/" + n + "/" + path, {method: "POST"}); render(); } catch (e) { fail(); }
}

let seen = 0, listed = [];

function describe(e) {
  const rest = Object.entries(e).filter(([k]) => !["n", "t", "kind"].includes(k)).map(([k, v]) => k + "=" + v);
  return rest.join(" ");
}

async function pollEvents() {
  try {
    const r = await fetch("api/events?since=" + seen);
    if (r.ok) {
      const items = await r.json();
      if (items.length) {
        seen = items[items.length - 1].n + 1;
        listed = listed.concat(items).slice(-60);
        const box = document.getElementById("events");
        box.innerHTML = listed.slice().reverse().map(e => '<div><span class="t">' + e.t.toFixed(1) + ' s</span>' +
          '<span class="k">' + esc(e.kind) + '</span>' + esc(describe(e)) + '</div>').join("");
      }
    }
  } catch (e) { /* the state's poll says it */ }
  setTimeout(pollEvents, 1000);
}

let scTimer = null;

async function pollScenario() {
  let s = null;
  try { const r = await fetch("api/scenario"); if (r.ok) s = await r.json(); } catch (e) { /* the state's poll says it */ }
  if (s) {
    document.getElementById("scrun").disabled = s.running;
    document.getElementById("scstop").disabled = !s.running;
    document.getElementById("scstatus").textContent = !s.name ? "Steps and what they do: docs/scenarios.md" :
      s.name + ": " + (s.running ? "playing, " + s.results.length + " of " + s.total + " steps" :
      (s.stopped ? "stopped" : "done") + ", " + s.results.length + " of " + s.total + " steps" +
      (s.failed ? ", " + s.failed + " expectation" + (s.failed > 1 ? "s" : "") + " failed" : ""));
    document.getElementById("scresults").innerHTML = s.results.map(r => '<div class="' + (r.ok ? "" : "bad") + '"><span class="t">' +
      r.at.toFixed(1) + ' s</span>' + esc(r.what) + (r.message ? ' &middot; ' + esc(r.message) : "") + (r.ok ? "" : " FAILED") + '</div>').join("");
    if (!s.running) { scTimer = null; return; }
  }
  scTimer = setTimeout(pollScenario, 500);
}

document.getElementById("scrun").addEventListener("click", async () => {
  const box = document.getElementById("scstatus");
  try {
    const r = await fetch("api/scenario", {method: "POST", body: document.getElementById("scenario").value});
    const s = await r.json();
    if (!r.ok) { box.textContent = s.error || "not accepted"; return; }
  } catch (e) { return fail(); }
  if (!scTimer) pollScenario();
});
document.getElementById("scstop").addEventListener("click", async () => {
  try { await fetch("api/scenario/stop", {method: "POST"}); } catch (e) { fail(); }
});
document.getElementById("scload").addEventListener("click", () => document.getElementById("scfile").click());
document.getElementById("scfile").addEventListener("change", e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => { document.getElementById("scenario").value = reader.result; };
  reader.readAsText(file);
});

document.getElementById("loss").addEventListener("input", e => {
  document.getElementById("lossout").textContent = e.target.value + " %";
});
document.getElementById("loss").addEventListener("change", async e => {
  try { await load("api/loss/" + e.target.value, {method: "POST"}); render(); } catch (x) { fail(); }
});
document.getElementById("clear").addEventListener("click", async () => {
  try { await fetch("api/events/clear", {method: "POST"}); } catch (e) { return; }
  seen = 0; listed = [];
  document.getElementById("events").innerHTML = '<div class="t">nothing yet</div>';
});

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
pollEvents();
pollScenario();
requestAnimationFrame(frame);
</script>
</body>
</html>
"""


def serve(world, host="127.0.0.1", port=8750):
    """Starts the server in a thread; returns it."""
    runner = Runner(world)

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

        def do_POST(self):
            parts = self.path.split("?")[0].strip("/").split("/")
            query = parse_qs(urlparse(self.path).query)
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
                    "tempo", "load", "unplug", "plug", "silence"):
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
                        world.load_track(deck, int(parts[4]), unquote(query["title"][0]) if "title" in query else None,
                                         float(bpm) if bpm else None)
                    elif what == "unplug" and len(parts) == 4:
                        world.set_unplugged(deck, True)
                    elif what == "plug" and len(parts) == 4:
                        world.set_unplugged(deck, False)
                    elif what == "silence" and len(parts) == 5:
                        world.silence(deck, float(parts[4]))
                    else:
                        return self.send(400, '{"error": "no such action"}')
                except ValueError:
                    return self.send(400, '{"error": "no such value"}')
                return self.send(200, json.dumps(world.snapshot()))
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
    server.runner = runner
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log("page and API on http://%s:%d/" % (host, server.server_address[1]))
    return server
