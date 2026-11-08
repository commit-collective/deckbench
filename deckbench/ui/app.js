/* deckbench's page: no packages, no build step. It follows /api/stream (server-sent events), and falls back on polling. */
"use strict";

const $ = (id) => document.getElementById(id);
const SLOTS = {1: "CD", 2: "SD", 3: "USB", 4: "rekordbox"};
const LOOPS = [1, 2, 4, 8, 16, 32];
/* The moves in the track, in beats (4 to a bar): [label, request, title] */
const MOVES = [["|◀", "seek/0", "To the first beat of the track"], ["◀◀", "jump/-16", "Back 4 bars"],
               ["◀", "jump/-4", "Back a bar"], ["▶", "jump/4", "Forward a bar"], ["▶▶", "jump/16", "Forward 4 bars"]];
/* A request for the moment the page was clicked, in the bench's time: a request that is slow to arrive acts where the playhead was then */
const clicked = (path) => path + (path.includes("?") ? "&" : "?") + "at=" + (Date.now() / 1000 + S.offset).toFixed(3);
const SWITCHES = [["play", "PLAY"], ["cue", "CUE"], ["sync", "SYNC"], ["master", "MASTER"]];      /* the deck's number is its on / off switch */

const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private window, or blocked: it works without */ } },
};

/* Builds an element. Text goes in as text, never as HTML: a track's title is anyone's string. */
function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid);
  return node;
}

/* The page is drawn again several times a second. Text written again, even the same, ends a selection in it, so a
   reader could not select and copy. These change a node only when what it shows changed. */
function setText(node, text) {
  text = text == null ? "" : String(text);
  if (node.textContent !== text) node.textContent = text;
}
function fill(node, ...kids) {
  kids = kids.flat().filter((k) => k != null && k !== false && k !== "");
  const key = kids.map((k) => typeof k === "string" ? k : k.outerHTML).join("\u0000");
  if (node.dataset.fill === key) return;
  node.dataset.fill = key;
  node.replaceChildren(...kids);
}

const S = {state: null, offset: 0, events: [], paused: false, frozen: 0, hidden: new Set(), kinds: new Map(),
           scenario: null, connected: false, examples: []};

/* ---- talking to the bench ---- */

/* kind: none is an error (red), "ok" went through (green), "warn" went through with a caveat (yellow), "info" is neutral */
function toast(text, kind) {
  const t = h("div", {class: "toast" + (kind ? " " + kind : "")}, text);
  $("toasts").append(t);
  setTimeout(() => t.remove(), 6000);
}

async function api(path, options) {
  let r;
  try { r = await transport.fetch(path, Object.assign({method: "POST"}, options)); }
  catch (e) { toast("The bench does not answer."); throw e; }
  let body = null;
  try { body = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) {
    const message = (body && body.error) || "The bench refused (" + r.status + ").";
    toast(message);
    throw new Error(message);
  }
  if (body && body.decks) apply(body);
  return body;
}

/* a click: errors are said by a toast already */
const act = (path, options) => api(path, options).catch(() => {});

function apply(state) {
  const previous = S.state && S.state.bench, current = state.bench;
  if (previous && current && (previous.session !== current.session || previous.event_generation !== current.event_generation)) clearEvents();
  S.state = state;
  S.offset = S.clock = Strip.followClock(S.clock, state.now - Date.now() / 1000);
  render();
}

function connect() {
  if (!window.EventSource && !transport.demo) return poll();
  const es = transport.eventSource("api/stream");
  es.onopen = () => { S.connected = true; renderChips(); };
  es.onerror = () => { S.connected = false; renderChips(); };
  es.addEventListener("state", (e) => apply(JSON.parse(e.data)));
  es.addEventListener("event", (e) => addEvent(JSON.parse(e.data)));
  es.addEventListener("cleared", () => clearEvents());
  es.addEventListener("scenario", (e) => { S.scenario = JSON.parse(e.data); renderScenario(); });
}

/* for a browser with no EventSource */
async function poll() {
  let seen = 0;
  const once = async () => {
    try {
      apply(await (await transport.fetch("api/state")).json());
      seen = S.events.length ? S.events[S.events.length - 1].n + 1 : 0;
      S.scenario = await (await transport.fetch("api/scenario")).json();
      for (const e of await (await transport.fetch("api/events?since=" + seen)).json()) { addEvent(e); seen = e.n + 1; }
      S.connected = true;
    } catch (e) { S.connected = false; }
    renderChips(); renderScenario();
    setTimeout(once, 500);
  };
  once();
}

/* ---- the top bar ---- */

function unitOf(state) {
  const link = state && state.protocols && state.protocols.prolink;
  return link && link.unit;
}

function settingsOf(state) {
  const link = state && state.protocols && state.protocols.prolink;
  return (link && link.settings) || {};
}

function mixerOf(state) {
  const link = state && state.protocols && state.protocols.prolink;
  return link && link.mixer;
}

function chip(text, kind, strong, title) {
  return h("span", {class: "chip " + (kind || ""), title: title || null}, kind ? h("i", {class: "dot"}) : null, strong ? h("b", {}, strong) : null, text);
}

function renderChips() {
  const box = $("chips"), s = S.state;
  box.textContent = "";
  box.append(S.connected ? chip("connected", "ok") : chip(S.state ? "reconnecting…" : "connecting…", "bad"));
  if (!s) return;
  const unit = unitOf(s);
  if ((s.adapters || []).some((a) => a.name === "djs1000-emu")) box.append(unit
    ? chip(" " + (unit.master ? "tempo master" : "") + (unit.bpm ? (unit.master ? ", " : "") + unit.bpm.toFixed(1) + " BPM" : ""),
           "ok", "Unit: player " + unit.number)
    : chip("no unit heard yet", "warn"));
  const set = settingsOf(s), info = s.bench || {};
  if (set.observer) box.append(chip("observer", null));
  /* how the bench is on the link with no deck on: what number it claimed, or that it is still listening */
  const presence = s.protocols && s.protocols.prolink && s.protocols.prolink.presence;
  if (presence) {
    const tip = "The bench on the link at " + presence.address + ": " + presence.why;
    if (presence.state === "listening") box.append(chip("listening " + Math.ceil(presence.seconds) + " s", "warn", null, tip));
    else if (presence.state === "silent") box.append(chip("number " + presence.number + " in use, silent", "warn", null, tip));
    else box.append(chip(presence.number <= 4 ? "player " + presence.number : "number " + presence.number, "ok", "on the link as ", tip));
  }
  const errors = s.protocols && s.protocols.prolink && s.protocols.prolink.errors || [];
  if (errors.length) box.append(chip("network warning", "warn", null, errors.join("\n")));
  if (set.strict) box.append(chip("strict decks"));
  if (set.refuse_db) box.append(chip("database refused"));
  const mixer = mixerOf(s);
  if (mixer && mixer.on) box.append(chip(mixer.name, "ok", "simulated mixer "));
  if (set.claim) box.append(chip("claims its number"));
  if (info.ports && info.ports.announce !== 50000) box.append(chip("ports +" + (info.ports.announce - 50000)));
  if (info.audio) box.append(chip(info.audio + (info.audio_source ? " · deck " + info.audio_source : ""), null, "unit input ",
    "The decks' sound is served on this port, for a unit's input (the emulator's --input-tcp). The Listen button plays it in this browser instead"));
  if (info.recording) box.append(chip("recording a session", "bad", null, "A program (the emulator's REC) is keeping what is done to the decks, to play it back"));
}

/* ---- the decks ---- */

let built = "";

function buildDecks() {
  const numbers = Object.keys(S.state.decks);
  if (numbers.join() === built) return;
  built = numbers.join();
  const root = $("decks");
  root.textContent = "";
  if (!numbers.length) root.append(h("div", {class: "empty"}, "No decks. Start the bench with --decks or --numbers."));
  for (const n of numbers) root.append(buildDeck(n, numbers));
}

function beatIndicators() {
  return h("div", {class: "beat-stack"},
    h("div", {class: "master-beats", role: "img", "aria-label": "No master beat available"}, h("i"), h("i"), h("i"), h("i")),
    h("div", {class: "beats", "aria-hidden": "true"}, h("i"), h("i"), h("i"), h("i")));
}

function buildDeck(n, numbers) {
  const q = (cls) => card.querySelector("." + cls);
  const card = h("article", {class: "deck off", id: "deck" + n, "aria-label": "Deck " + n},
    h("div", {class: "deck-head"},
      h("button", {class: "num", type: "button", "aria-pressed": "false", title: "Switch deck " + n + " on or off",
        "aria-label": "Deck " + n + " on", onclick: () => act("api/deck/" + n + "/on")}, n),
      h("div", {class: "deck-id"}, h("div", {class: "model"}), h("div", {class: "track"})),
      h("div", {class: "tags"})),
    h("div", {class: "live"},
      beatIndicators(),
      h("div", {class: "lcd", "aria-label": "Tempo"}, h("b", {}, "--"), h("span", {}, "BPM"))),
    h("canvas", {class: "strip", "aria-hidden": "true"}),
    h("div", {class: "switches", role: "group", "aria-label": "Deck " + n + " switches"},
      SWITCHES.map(([what, label]) => what === "cue"
        /* CUE is held: down plays from the cue point when the deck is paused on it, and up goes back */
        ? h("button", {class: "sw", "data-what": what, "aria-pressed": "false",
            title: "Playing: back to the cue point. Paused on it: plays while held. Paused elsewhere: sets the cue point",
            onpointerdown: (e) => { e.currentTarget.setPointerCapture(e.pointerId); act(clicked("api/deck/" + n + "/cue/1")); },
            onpointerup: () => act("api/deck/" + n + "/cue/0"),
            onpointercancel: () => act("api/deck/" + n + "/cue/0"),
            onkeydown: (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); act(clicked("api/deck/" + n + "/cue/1")); } },
            onkeyup: (e) => { if (e.key === " " || e.key === "Enter") act("api/deck/" + n + "/cue/0"); }}, label)
        : h("button", {class: "sw", "data-what": what, "aria-pressed": "false",
            onclick: () => act(clicked("api/deck/" + n + "/" + what))}, label))),
    h("div", {class: "row"}, h("label", {for: "tempo" + n}, "Tempo"),
      h("input", {type: "range", id: "tempo" + n, class: "tempo-range", min: 60, max: 200, step: 0.1,
        "aria-label": "Tempo of deck " + n}),
      h("input", {type: "number", class: "tempo-num", min: 40, max: 220, step: 0.1, "aria-label": "BPM of deck " + n})),
    h("div", {class: "row"}, h("span", {class: "lbl"}, "Loop"),
      h("div", {class: "seg", role: "group", "aria-label": "Loop of deck " + n},
        LOOPS.map((beats) => h("button", {"data-beats": beats, "aria-pressed": "false",
          title: beats + " beats from where the deck is. Again to end it",
          onclick: () => { const d = S.state.decks[n]; act(clicked("api/deck/" + n + "/loop/" + (d.loop === beats ? 0 : beats))); }}, beats)))),
    h("div", {class: "row"}, h("span", {class: "lbl"}, "Move"),
      h("div", {class: "seg moves", role: "group", "aria-label": "Move deck " + n + " in its track"},
        MOVES.map(([label, what, title]) => h("button", {title, "data-move": what,
          onclick: () => act(clicked("api/deck/" + n + "/" + what))}, label)))),
    h("div", {class: "row"}, h("span", {class: "lbl"}, "Cable"),
      h("button", {class: "btn small unplug", title: "Pull the cable: the deck says nothing and answers nothing",
        onclick: () => act("api/deck/" + n + "/" + (S.state.decks[n].unplugged ? "plug" : "unplug"))}, "Unplug"),
      h("button", {class: "btn small silence", title: "Pull the cable for a while, then plug it in",
        onclick: () => act("api/deck/" + n + "/silence/" + q("silence-secs").value)}, "Silence for"),
      h("select", {class: "silence-secs", "aria-label": "Seconds"},
        [2, 5, 10, 30].map((s) => h("option", {value: s, selected: s === 5}, s + " s")))),
    h("details", {class: "fold"},
      h("summary", {}, "Load a track"),
      h("div", {class: "fields"},
        h("label", {}, "Rekordbox id", h("input", {type: "number", class: "t-id", min: 1, placeholder: String(100 + Number(n))})),
        h("label", {}, "BPM", h("input", {type: "number", class: "t-bpm", step: 0.1, min: 40, max: 220, placeholder: "keep"})),
        h("label", {class: "wide"}, "Title", h("input", {type: "text", class: "t-title", placeholder: "Track of deck " + n})),
        transport.demo ? null : h("label", {class: "wide", title: "A WAV (or anything ffmpeg reads). Browse sends one from this computer to the bench, or give a path on the machine the bench runs on. The BPM above is the one it was made at"},
          "Sound file",
          h("span", {class: "pick"},
            h("input", {type: "text", class: "t-audio", placeholder: "none: its drum loop"}),
            h("button", {class: "btn small t-browse", type: "button", onclick: () => card.querySelector(".t-file").click()}, "Browse\u2026"),
            h("input", {type: "file", class: "t-file", hidden: true, accept: "audio/*,.wav,.mp3,.flac,.aif,.aiff,.ogg,.m4a",
              onchange: (e) => sendFile(card, e.target.files[0])}))),
        transport.demo ? null : h("label", {title: "Seconds of the file before its first beat"}, "First beat at", h("input", {type: "number", class: "t-offset", step: 0.01, min: 0, placeholder: "0"})),
        h("label", {}, "From the database of",
          h("select", {class: "t-source"}, numbers.map((m) => h("option", {value: m, selected: m === n}, "deck " + m + (m === n ? " (itself)" : ""))))),
        h("label", {}, "Slot", h("select", {class: "t-slot"},
          Object.entries(SLOTS).map(([k, v]) => h("option", {value: k, selected: k === "3"}, v)))),
        h("button", {class: "btn primary wide", onclick: () => loadTrack(n, card)}, "Load it from its first beat"))));
  let tempoSent = 0, tempoLater = null;                       /* the fader is followed as it moves, a request every 60 ms at most */
  const sendTempo = (value) => { tempoSent = Date.now(); act("api/deck/" + n + "/tempo/" + value); };
  card.querySelector(".tempo-range").addEventListener("input", (e) => {
    const value = e.target.value;
    q("tempo-num").value = Number(value).toFixed(1);
    clearTimeout(tempoLater);
    const wait = 60 - (Date.now() - tempoSent);
    if (wait <= 0) sendTempo(value);
    else tempoLater = setTimeout(() => sendTempo(value), wait);
  });
  card.querySelector(".tempo-range").addEventListener("change", (e) => { clearTimeout(tempoLater); sendTempo(e.target.value); });
  card.querySelector(".tempo-num").addEventListener("change", (e) => {
    if (e.target.value) act("api/deck/" + n + "/tempo/" + e.target.value);
  });
  return card;
}

/* Browse: the file goes to the bench (the browser's file picker finds it on this computer, which may not be the bench's), which keeps it
   and says where: that path is what a load asks for. The title and the BPM are guessed from the name if they are empty. */
async function sendFile(card, file) {
  if (!file) return;
  const button = card.querySelector(".t-browse");
  button.disabled = true;
  button.textContent = "Sending\u2026";
  try {
    const sent = await api("api/upload?name=" + encodeURIComponent(file.name), {body: file});
    card.querySelector(".t-audio").value = sent.path;
    const title = card.querySelector(".t-title"), bpm = card.querySelector(".t-bpm");
    if (!title.value) title.value = file.name.replace(/\.[^.]+$/, "");
    const guess = /(\d{2,3}(?:\.\d+)?)\s*bpm/i.exec(file.name);
    if (!bpm.value && guess) bpm.value = guess[1];
    toast("Sent " + file.name + " (" + (file.size / 1048576).toFixed(1) + " MB). Set the BPM it was made at, then load it.", "ok");
  } catch (e) { /* a toast said why */ }
  button.disabled = false;
  button.textContent = "Browse\u2026";
  card.querySelector(".t-file").value = "";
}

function loadTrack(n, card) {
  const v = (cls) => card.querySelector("." + cls).value.trim();
  const id = v("t-id") || String(100 + Number(n));
  const params = new URLSearchParams();
  if (v("t-title")) params.set("title", v("t-title"));
  if (v("t-bpm")) params.set("bpm", v("t-bpm"));
  params.set("source", v("t-source"));
  params.set("slot", v("t-slot"));
  if (v("t-audio")) {
    params.set("audio", v("t-audio"));
    if (v("t-offset")) params.set("offset", v("t-offset"));
  }
  act("api/deck/" + n + "/load/" + encodeURIComponent(id) + "?" + params);
}

function beatOf(d) {
  return Strip.beatOf(d, Date.now() / 1000, S.offset);
}

/* A player as the lamps take it. Held on CUE (cue playing), it sends no beats: its beat is the strip's (cueRun), in the
   bar its status gives. */
function lampsOf(d) {
  const st = d.status, seen = beatSeen[d.ip];
  if (d.phase || !d.online || !st || st.state !== "cue playing" || !st.bar || !seen || !seen.running) return d;
  const bpm = st.bpm || st.track_bpm || 120;
  return Object.assign({}, d, {phase: [seen.t, seen.at, bpm], bar_phase: [seen.t, st.bar - 1 + seen.at - seen.beat, bpm]});
}

function lamps() {
  if (!S.state) return;
  const master = Strip.master(S.state) ||
    devicesOf(S.state).map(lampsOf).find((d) => d.online && d.status && d.status.master && d.phase) || null;
  const masterBeat = master ? beatOf(master) : 0;
  for (const row of document.querySelectorAll(".master-beats")) {
    const label = master ? "Master player " + master.number + ", beat " + masterBeat : "No master beat available";
    row.title = label;
    row.setAttribute("aria-label", label);
    row.querySelectorAll("i").forEach((square, k) => square.classList.toggle("lit", masterBeat === k + 1));
  }
  for (const d of devicesOf(S.state).map(lampsOf)) {
    const card = $(devId(d.ip));
    if (!card || d.kind === "mixer") continue;
    const now = d.online && d.phase ? beatOf(d) : 0;
    card.querySelectorAll(".beats i").forEach((square, k) => {
      square.classList.toggle("lit", now === k + 1);
      square.classList.toggle("first", k === 0);
    });
  }
  for (const [n, d] of Object.entries(S.state.decks)) {
    const card = $("deck" + n);
    if (!card) continue;
    const now = d.on ? beatOf(d) : 0;
    card.querySelectorAll(".beats i").forEach((square, k) => {
      square.classList.toggle("lit", now === k + 1);
      square.classList.toggle("first", k === 0);
    });
  }
}

/* ---- the strips, and the other devices on the link ---- */

function devicesOf(state) {
  const link = state && state.protocols && state.protocols.prolink;
  return (link && link.devices) || [];
}

const devId = (ip) => "dev-" + ip.replace(/[^\w]/g, "-");

/* The waveform of a deck's sound file, got from the bench once for each file: null while it comes, or when the deck has none. */
const waves = {};
function waveOf(n, d) {
  if (!d.audio || transport.demo) return null;
  const id = n + "/" + d.audio.file + "/" + d.audio.seconds;
  if (!(id in waves)) {
    waves[id] = null;
    transport.fetch("api/deck/" + n + "/waveform")
      .then((r) => { if (!r.ok) throw new Error("none"); return r.json(); })
      .then((w) => { waves[id] = {peaks: Strip.smooth(w.peaks), rate: w.rate}; })
      .catch(() => { waves[id] = false; });                       /* not got: not asked for again until the file changes */
  }
  const w = waves[id];
  return w ? Object.assign({offset: d.audio.offset, bpm: d.audio.bpm}, w) : null;
}

/* A real player's waveform, read by the bench from the player that hosts the track (api/player/IP/waveform), once it says it
   is ready: by address, for the track it was read for. A new track drops the old one at once. */
const realWaves = {};                   // address: {key, peaks, overview, beatTime, beatOf, bars, duration}, or {key, failed}
function realWaveOf(d) {
  const wf = d.waveform || {}, have = realWaves[d.ip];
  if (have && have.key !== wf.key) delete realWaves[d.ip];
  if (wf.state !== "ready" || transport.demo) return null;
  if (!realWaves[d.ip]) {
    realWaves[d.ip] = {key: wf.key, pending: true};
    transport.fetch("api/player/" + d.ip + "/waveform")
      .then((r) => { if (!r.ok) throw new Error("none"); return r.json(); })
      .then((data) => { if (realWaves[d.ip] && realWaves[d.ip].key === data.key) realWaves[d.ip] = Strip.realWave(data); })
      .catch(() => { if (realWaves[d.ip] && realWaves[d.ip].key === wf.key) realWaves[d.ip] = {key: wf.key, failed: true}; });
  }
  const w = realWaves[d.ip];
  return w && w.peaks ? w : null;
}

/* A real player's strip, with its waveform once the bench has read it. A precise position (a CDJ-3000's, many a second)
   places it at every frame, playing or not. Without one, the beats as they came while it plays, and its beat while it is
   paused, which is then marked as an estimate. */
/* address: the strip of a player that plays with no beat packets (cue playing): {beat, t, at, running}, its reported
   beat and an anchor (beat `at` at bench time t) */
const beatSeen = {};

/* Where such a player is: run on at its tempo from the anchor, and move it only when the reports rule it out. The bench
   says when a reported beat changed (status.beat_window: after the last status with the old beat, before the first with
   the new): the strip is kept where that puts it, so it neither steps on each status nor jumps by the status interval.
   Started from a stop (CUE held), it starts from the cue the bench followed, else from the beat after the reported one,
   as a stopped strip is drawn. */
function cueRun(d, st, running, now) {
  const b = st.track_beat - 1, rate = (st.bpm || st.track_bpm || 120) / 60;
  let seen = beatSeen[d.ip];
  if (!seen || !running || !seen.running) {
    /* from a stop, PLAY or CUE held: where the stopped strip stood (where the bench followed it, else the beat after
       the one it reported while stopped), from when the bench saw it start (status.since). The first statuses of a
       start report the beat before the cue, then the cue's within a few hundredths of a second, and a player sends
       no beat for the beat it starts on: the strip must not start from whichever of those the page saw first */
    const near = (at) => at != null && at >= b - 1.001 && at <= b + 1.001;
    if (running && seen && !seen.running && near(seen.stood)) {
      const since = st.since != null && st.since <= now && now - st.since < 1 ? st.since : now;
      return beatSeen[d.ip] = {beat: b, t: since, at: seen.stood, running};
    }
    return beatSeen[d.ip] = {beat: b, t: now, at: running ? b : null, running,
                             stood: running ? null : (d.held != null ? d.held : b + 1)};
  }
  let at = seen.at + (now - seen.t) * rate;
  const win = st.beat_window;
  if (b === seen.beat + 1 && win) at = Math.min(Math.max(at, b + (now - win[1]) * rate), b + (now - win[0]) * rate);
  else if (b !== seen.beat) at = b;
  else at = Math.min(at, b + 1);
  return Object.assign(seen, {beat: b, t: now, at});
}

function devicePlan(d, wave, now) {
  const st = d.status, moving = () => {
    const plan = Strip.layoutDevice(d.ip, d, now);
    if (wave) for (const t of plan.ticks) if (wave.bars[t.at] != null) t.beat = wave.bars[t.at];      /* the grid's bars */
    return {plan, place: null};
  };
  if (!st || st.track_beat == null) return moving();
  /* without a precise position, moving while its beats come: a beat in the last two, whatever its play flag says */
  const beating = d.phase && d.phase[2] > 0 && now + S.offset - d.phase[0] < 2 * 60 / d.phase[2];
  /* playing with no beat packets, as while CUE is held (cue playing): from the moment its reported beat changed, at its
     tempo, so the strip runs on and does not step once a beat */
  const running = Strip.moving(st) && !beating && !(d.precise && wave);
  const seen = cueRun(d, st, running, now + S.offset);
  if (running) {
    const plan = Strip.layout({phase: [seen.t, seen.at, st.bpm || st.track_bpm || 120], loop: 0, loop_from: 0}, now, S.offset);
    if (wave) for (const tick of plan.ticks) if (wave.bars[tick.at] != null) tick.beat = wave.bars[tick.at];
    return {plan, place: null};
  }
  if (!wave) return moving();
  const place = Strip.trackPlace(d, wave, now + S.offset);
  if (!place || (place.estimated && (Strip.moving(st) || beating))) return moving();
  const plan = Strip.layout({at: wave.beatOf(place.seconds), bpm: st.bpm || st.track_bpm || 120}, now, S.offset);
  for (const t of plan.ticks) if (wave.bars[t.at] != null) t.beat = wave.bars[t.at];
  plan.stopped = !st.play;
  return {plan, place};
}

function strips() {
  if (!S.state) return;
  const now = Date.now() / 1000;
  for (const [n, d] of Object.entries(S.state.decks)) {
    const card = $("deck" + n), canvas = card && card.querySelector(".strip");
    if (canvas && d.on) Strip.draw(canvas, Strip.layout(d, now, S.offset), {wave: waveOf(n, d)});
    else if (canvas) canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  }
  for (const d of devicesOf(S.state)) {
    const card = $(devId(d.ip)), canvas = card && card.querySelector(".strip");
    if (!canvas) continue;
    const st = d.status, known = !!(st && st.track_beat != null), wave = known ? realWaveOf(d) : null;
    const {plan, place} = devicePlan(d, wave, now);
    Strip.draw(canvas, plan, {bars: !known, wave, label: place && place.estimated ? "paused, place estimated" : ""});
    const overview = card.querySelector(".overview");
    if (overview) {
      if (overview.hidden !== !wave) overview.hidden = !wave;
      if (wave) Strip.drawOverview(overview, wave, Strip.trackPlace(d, wave, now + S.offset));
    }
  }
}

/* CUE held on real players: the bench presses it down and lets it go (api/player/IP/command/cue-down and cue-up). One down
   and one up per hold, and an up as the page goes away. While the finger stays down the page says so each second
   (cue-hold): the bench lets go by itself a few seconds after the last, so a page that went away leaves nothing held. */
const heldCues = new Map();             // player address: its number, while CUE is held from this page
const cuePresses = new Map();           // player address: the cue-down on its way, which a cue-up waits for
const cueKeeps = new Map();             // player address: the timer that says each second CUE is still held
function cueHold(d, button, down, play = null) {
  if (down ? heldCues.has(d.ip) || button.disabled : !heldCues.has(d.ip)) return;
  const number = down ? button.dataset.number : heldCues.get(d.ip);
  if (down) heldCues.set(d.ip, number); else heldCues.delete(d.ip);
  clearInterval(cueKeeps.get(d.ip));
  cueKeeps.delete(d.ip);
  if (down) cueKeeps.set(d.ip, setInterval(() =>
    api("api/player/" + d.ip + "/command/cue-hold?number=" + number).catch(() => {}), 1000));
  button.setAttribute("aria-pressed", String(down));
  const send = () => api("api/player/" + d.ip + "/command/cue-" + (down ? "down" : "up") + "?number=" + number).catch(() => {});
  /* a quick tap: the up goes after the down was answered, so it cannot overtake it. Let go on PLAY/PAUSE: it is pressed
     first, while CUE is still down, as on the player, which then plays on */
  const pressPlay = () => play && api("api/player/" + d.ip + "/command/play-pause?number=" + play.dataset.number).catch(() => {});
  if (down) cuePresses.set(d.ip, send());
  else (cuePresses.get(d.ip) || Promise.resolve()).then(pressPlay).then(send);
}

/* CUE keeps the pointer (a finger or the mouse) until it is let go, wherever it goes. While it is held, the card's
   PLAY/PAUSE is marked as a place to let go on, and lit when the pointer is over it */
const playOf = (cue) => cue.closest(".player-switches").querySelector('[data-command="play-pause"]');
function cueOver(cue, e) {
  const play = playOf(cue), at = document.elementFromPoint(e.clientX, e.clientY);
  const over = !!play && !play.disabled && !play.hidden && !!at && play.contains(at);
  if (play) play.classList.toggle("drop-over", over);
  return over ? play : null;
}
function cueLetGo(d, cue, e) {
  const play = e && heldCues.has(d.ip) ? cueOver(cue, e) : null;
  const target = playOf(cue);
  if (target) target.classList.remove("drop-ready", "drop-over");
  cueHold(d, cue, false, play);
}
window.addEventListener("pagehide", () => {
  if (transport.demo) return;
  for (const [ip, number] of heldCues)
    fetch(transport.url("api/player/" + ip + "/command/cue-up?number=" + number), {method: "POST", keepalive: true}).catch(() => {});
});

function playerCommand(d, button, command) {
  api("api/player/" + d.ip + "/command/" + command + "?number=" + button.dataset.number).catch(() => {});
}

function buildPlayerLoad(d) {
  const field = (text, node) => h('label', {}, text, node);
  return h('details', {class: 'player-load'}, h('summary', {}, 'Load a linked track (experimental)'),
    h('p', {class: 'hint'}, 'Analyzed SD/USB tracks only. Use the source player, slot and track ID shown on a player card. The destination must be stopped.'),
    h('div', {class: 'fields'},
      field('Source player', h('input', {class: 'load-source', type: 'number', min: 1, max: 6, value: d.number || 1})),
      field('Media', h('select', {class: 'load-slot'}, h('option', {value: 3}, 'USB'), h('option', {value: 2}, 'SD'))),
      field('Track ID', h('input', {class: 'load-id', type: 'number', min: 1, max: 4294967295, step: 1}))),
    h('button', {class: 'btn small player-load-send', disabled: true, onclick: (event) => {
      const button = event.currentTarget, form = button.closest('.player-load');
      if (![...form.querySelectorAll('input')].every(input => input.reportValidity()) || !form.querySelector('.load-id').value) return;
      const source = form.querySelector('.load-source').value, slot = form.querySelector('.load-slot').value;
      const track = form.querySelector('.load-id').value;
      if (!window.confirm('Replace the stopped track on player ' + button.dataset.number + ' with track ' + track + ' from player ' + source + '?')) return;
      api('api/player/' + d.ip + '/load/' + encodeURIComponent(track) + '?number=' + button.dataset.number + '&source=' + encodeURIComponent(source) + '&slot=' + encodeURIComponent(slot))
        .then(() => toast('Load request sent, not confirmed. Check the real player.', 'info')).catch(() => {});
    }}, 'Request load'));
}

function buildDevice(d) {
  const mixer = d.kind === "mixer";
  return h("article", {class: "deck device off", id: devId(d.ip), "aria-label": (d.model || "Device") + " on the link"},
    h("div", {class: "deck-head"},
      h("div", {class: "num", "aria-hidden": "true"}),
      h("details", {class: "deck-id"}, h("summary", {class: "identity", title: "Show full player and track information"},
        h("span", {class: "model"}), h("span", {class: "track"}), h("span", {class: "track where", hidden: true}))),
      h("div", {class: "tags"}, h("div", {class: "unit-slot"}), h("div", {class: "flags", "aria-label": "State"}))),
    mixer ? h("div", {class: "airs", "aria-label": "Channels on air"}) : h("div", {class: "live"},
      beatIndicators(),
      h("div", {class: "lcd", "aria-label": "Tempo"}, h("b", {}, "--"), h("span", {}, "BPM"))),
    mixer ? null : h("canvas", {class: "strip", "aria-hidden": "true"}),
    mixer ? null : h("canvas", {class: "overview", "aria-hidden": "true", hidden: true}),
    /* the player's own switches, as a bench deck's: pressed on the player once control is enabled, and lit from what it reports */
    /* the player's own switches, as a bench deck's: pressed on the player while player control is on (Settings), and lit
       from what it reports. A model that takes no presses has fader start's START and STOP instead */
    mixer ? null : h("div", {class: "switches player-switches", role: "group", "aria-label": "Player switches", hidden: true},
      h("button", {class: "sw", "data-command": "play-pause", "data-method": "buttons", "aria-pressed": "false",
        onclick: (e) => playerCommand(d, e.currentTarget, "play-pause")}, "PLAY/PAUSE"),
      /* CUE follows the finger, as the player's own: down while pressed, up when let go (the bench lets go by itself if
         this page stops saying it is held). Let go on PLAY/PAUSE, it presses PLAY first and the player plays on */
      h("button", {class: "sw", "data-command": "cue", "data-method": "buttons", "aria-pressed": "false", oncontextmenu: (e) => e.preventDefault(),
        onpointerdown: (e) => {
          const cue = e.currentTarget;
          cue.setPointerCapture(e.pointerId);
          cueHold(d, cue, true);
          const play = playOf(cue);
          if (play && heldCues.has(d.ip) && !play.disabled) play.classList.add("drop-ready");
        },
        onpointermove: (e) => { if (heldCues.has(d.ip)) cueOver(e.currentTarget, e); },
        onpointerup: (e) => cueLetGo(d, e.currentTarget, e),
        onpointercancel: (e) => cueLetGo(d, e.currentTarget, null),
        onkeydown: (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); cueHold(d, e.currentTarget, true); } },
        onkeyup: (e) => { if (e.key === " " || e.key === "Enter") cueHold(d, e.currentTarget, false); }}, "CUE"),
      h("button", {class: "sw", "data-command": "start", "data-method": "fader", "aria-pressed": "false", hidden: true,
        "data-tip": "Fader start: plays a track paused at its cue point",
        onclick: (e) => playerCommand(d, e.currentTarget, "start")}, "START"),
      h("button", {class: "sw", "data-command": "stop", "data-method": "fader", "aria-pressed": "false", hidden: true,
        "data-tip": "Fader stop: back to the cue point. Nothing while paused",
        onclick: (e) => playerCommand(d, e.currentTarget, "stop")}, "STOP"),
      h("button", {class: "sw", "data-command": "sync", "aria-pressed": "false",
        onclick: (e) => playerCommand(d, e.currentTarget, e.currentTarget.getAttribute("aria-pressed") === "true" ? "sync-off" : "sync-on")}, "SYNC"),
      h("button", {class: "sw", "data-command": "master", "aria-pressed": "false",
        onclick: (e) => playerCommand(d, e.currentTarget, "master")}, "MASTER")),
    h("div", {class: "facts"}),
    mixer ? null : h("div", {class: "player-control", hidden: true},
      h("button", {class: "btn small player-read", onclick: (e) => {
        const button = e.currentTarget;
        button.dataset.pending = "1";
        button.disabled = true;
        api("api/player/" + d.ip + "/metadata/refresh?number=" + button.dataset.number)
          .then(() => toast("Track information read.", "ok")).catch(() => {}).finally(() => { delete button.dataset.pending; renderDevices(); });
      }}, "Read track info"), buildPlayerLoad(d)));
}

function renderDevices() {
  const list = devicesOf(S.state), box = $("devices");
  $("others").hidden = !list.length;
  const keep = new Set();
  for (const d of list) {
    Strip.observe(d.ip, d.phase, S.offset, d.bar_phase);
    keep.add(devId(d.ip));
    let card = $(devId(d.ip));
    if (!card || card.dataset.kind !== d.kind) {
      if (card) card.remove();
      card = buildDevice(d);
      card.dataset.kind = d.kind;
      box.append(card);
    }
    const st = d.status, q = (cls) => card.querySelector("." + cls);
    const control = q("player-control");
    if (control) {
      control.hidden = !d.transport_available;
      const set = settingsOf(S.state), usable = d.transport_armed && d.online && S.connected, live = st && d.online;
      /* what this model takes: the button presses, or else fader start (START and STOP), or neither */
      const takes = {buttons: d.transport_method === "buttons", fader: !!d.fader_start_supported && d.transport_method !== "buttons"};
      const switches = q("player-switches");
      switches.hidden = !d.transport_available;
      const lit = {"play-pause": !!(live && st.play), cue: heldCues.has(d.ip), start: false, stop: false,
                   sync: !!(live && st.sync), master: !!(live && st.master)};
      const why = usable ? "" : !set.player_control && !d.transport_armed ? "Player control is off in Settings" : "";
      for (const button of switches.querySelectorAll("button")) {
        const method = button.dataset.method, shown = !method || takes[method];
        if (button.hidden !== !shown) button.hidden = !shown;
        button.disabled = !usable;
        button.dataset.number = d.number;
        const pressed = String(lit[button.dataset.command]);
        if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed", pressed);
        const tip = why || button.dataset.tip || "";
        if (button.title !== tip) button.title = tip;
      }
      const read = q("player-read");
      read.hidden = !!set.auto_track_info;
      read.disabled = !!read.dataset.pending || !d.metadata_available || !S.connected;
      read.dataset.number = d.number;
      read.title = d.metadata_reason || "Read the loaded track's title and artist";
      const send = q("player-load-send");
      send.disabled = !usable || !d.load_allowed;          // the bench's rule
      send.dataset.number = d.number;
      /* loading needs player control too: its fields look as off as its button */
      const locked = !usable, load = q("player-load");
      if (load.classList.contains("locked") !== locked) {
        load.classList.toggle("locked", locked);
        for (const field of load.querySelectorAll("input, select")) field.disabled = locked;
        load.querySelector("summary").title = locked ? why || "The player is offline" : "";
      }
    }
    card.classList.toggle("online", d.online);
    card.classList.toggle("offline", !d.online);
    card.classList.toggle("off", false);
    setText(q("num"), d.number == null ? "?" : d.number);
    fill(q("model"), d.model || d.ip, h("span", {class: "addr"}, d.ip));
    const track = q("track");
    /* the track: its title once read, then always its state and where it is loaded from (source, slot, ID), as a
       load asks for them */
    const ids = st && st.rbid ? " \u00b7 player " + st.source + " \u00b7 " + (SLOTS[st.slot] || "slot " + st.slot) + " \u00b7 id " + st.rbid : "";
    const where = q("where"), titled = !!(d.metadata && d.metadata.title && st);
    if (titled) fill(track, h("b", {}, d.metadata.title), d.metadata.artist ? " \u00b7 " + d.metadata.artist : "");
    else if (d.kind === "mixer") fill(track, "mixer");
    else if (st) fill(track, h("b", {}, st.state), ids);
    else fill(track, d.online ? "no status yet" : "gone quiet");
    if (titled) fill(where, st.state, ids); else fill(where);
    if (where.hidden !== !titled) where.hidden = !titled;
    const tip = [d.model, d.ip].filter(Boolean).join(" · ") + "\n" + track.textContent + (titled ? "\n" + where.textContent : "") +
      "\nClick or press Enter to expand";
    if (q("identity").title !== tip) q("identity").title = tip;
    /* the tags are a column at the right of the header, the height of the number's box: the unit tag at the top and the state (side by side, wrapping onto
       a row under when there are too many for the width) at the bottom. The column is always there: a flag that comes or goes does not change the card's height */
    fill(q("unit-slot"), d.unit && (S.state.adapters || []).some((a) => a.name === "djs1000-emu") ? h("span", {class: "tag unit"}, "UNIT UNDER TEST") : null);
    const live = st && d.online;
    fill(q("flags"), !d.online ? h("span", {class: "tag offline"}, "OFFLINE") : null,
         live && st.master ? h("span", {class: "tag master"}, "MASTER") : null,
         live && st.sync ? h("span", {class: "tag sync"}, "SYNC") : null,
         live && st.on_air ? h("span", {class: "tag air-tag"}, "ON AIR") : null,
         live && st.loop ? h("span", {class: "tag loop"}, "LOOP") : null);
    const facts = [];
    if (d.kind === "mixer") {
      const airs = Object.entries(d.air || {}).map(([channel, on]) => h("span", {class: "air" + (on ? " lit" : "")}, "CH " + channel));
      fill(q("airs"), airs, d.air ? null : h("span", {class: "hint"}, "no on-air report heard"));
      if (d.fader) facts.push(h("span", {}, "fader start: " + Object.entries(d.fader).map(([p, c]) => "player " + p + " " + c).join(", ")));
    } else {
      const bpm = st ? st.bpm : d.phase ? d.phase[2] : null;
      setText(q("lcd").firstChild, bpm != null && d.online ? bpm.toFixed(1) : "--");
      if (st && st.pitch) facts.push(h("span", {}, "pitch " + (st.pitch > 0 ? "+" : "") + st.pitch.toFixed(2) + " %"));
      if (d.firmware) facts.push(h("span", {}, "firmware " + d.firmware));
      if (d.precise) facts.push(h("span", {}, "position " + (d.precise.position_ms / 1000).toFixed(3) + " s"));
    }
    if (d.peers != null) facts.push(h("span", {}, "knows " + d.peers + " device" + (d.peers === 1 ? "" : "s")));
    if (d.mac) facts.push(h("span", {}, d.mac));
    fill(q("facts"), facts);
  }
  for (const card of Array.from(box.children)) if (!keep.has(card.id)) card.remove();
}

function render() {
  const s = S.state;
  if (!s) return;
  buildDecks();
  const unit = unitOf(s), active = document.activeElement;
  for (const [n, d] of Object.entries(s.decks)) {
    const card = $("deck" + n);
    if (!card) continue;
    const q = (cls) => card.querySelector("." + cls);
    card.classList.toggle("on", !!d.on);
    card.classList.toggle("off", !d.on);
    card.classList.toggle("unplugged", !!d.unplugged);

    fill(q("model"), d.model || d.name, d.address ? h("span", {class: "addr"}, d.address) : null);
    if (d.track) {
      const own = d.track_source === Number(n);
      fill(q("track"), h("b", {}, d.track), " · " + (own ? "own database" : "deck " + d.track_source) + " · " +
                       (SLOTS[d.track_slot] || "slot " + d.track_slot) + " · id " + d.track_rbid);
    } else fill(q("track"), "no track");
    const mixer = mixerOf(s);
    fill(q("tags"), d.on && d.loop ? h("span", {class: "tag loop"}, "LOOP " + d.loop) : null,
         d.unplugged ? h("span", {class: "tag cable"}, "UNPLUGGED") : null,
         mixer && mixer.on && d.on ? h("span", {class: "tag " + (d.on_air ? "air-tag" : "off-air")}, d.on_air ? "ON AIR" : "OFF AIR") : null);

    setText(q("lcd").firstChild, d.on ? d.bpm.toFixed(1) : "--");
    const power = q("num");                  /* the number: the deck's on / off switch */
    if (power.tagName === "BUTTON") {
      const clash = !!unit && unit.number === Number(n) && !d.on;
      power.setAttribute("aria-pressed", String(!!d.on));
      power.disabled = clash;
      power.title = clash ? "This is the unit's own number: a deck here is a clash" : "Switch deck " + n + (d.on ? " off" : " on");
    }
    for (const b of card.querySelectorAll(".sw")) {
      const what = b.dataset.what;
      b.setAttribute("aria-pressed", String(!!d[what] && d.on));
      b.disabled = !d.on;
      if (what === "play") setText(b, d.play ? "PAUSE" : "PLAY");
    }
    const range = q("tempo-range"), num = q("tempo-num");
    if (active !== range) range.value = d.bpm;
    if (active !== num) num.value = d.bpm.toFixed(1);
    for (const b of card.querySelectorAll(".seg button")) {
      b.setAttribute("aria-pressed", String(!!d.on && d.loop === Number(b.dataset.beats)));
      b.disabled = !d.on;
    }
    setText(q("unplug"), d.unplugged ? "Plug in" : "Unplug");
    q("silence").disabled = !!d.unplugged;
  }
  renderChips();
  renderNetwork();
  renderSettings();
  renderMixer();
  renderDevices();
  setText($("version"), s.bench && s.bench.version ? (/^\d/.test(s.bench.version) ? "v" : "") + s.bench.version : "");
  lamps();
}

/* ---- events ---- */

function addEvent(e) {
  S.events.push(e);
  if (S.events.length > 2000) S.events.shift();
  S.kinds.set(e.kind, (S.kinds.get(e.kind) || 0) + 1);
  renderEvents();
}

function clearEvents() {
  S.events = []; S.kinds = new Map(); S.frozen = 0;
  renderEvents();
}

let evTimer = null;
function renderEvents() {
  if (evTimer) return;
  evTimer = setTimeout(() => { evTimer = null; drawEvents(); }, 120);
}

function describe(e) {
  return Object.entries(e).filter(([k]) => !["n", "t", "kind", "session", "generation"].includes(k))
    .map(([k, v]) => k + "=" + (v && typeof v === "object" ? JSON.stringify(v) : v)).join(" ");
}

function drawEvents() {
  const total = S.paused ? S.frozen : S.events.length;
  const list = S.events.slice(0, total).filter((e) => !S.hidden.has(e.kind)).slice(-300).reverse();
  const box = $("events");
  box.textContent = "";
  if (!S.events.length) box.append(h("div", {}, h("span", {class: "d dim"},
    "Nothing yet. An event appears when the device under test sends a deck something: a fader start, a sync command, a request for a title.")));
  for (const e of list) box.append(h("div", {}, h("span", {class: "t"}, e.t.toFixed(1) + " s"), h("span", {class: "k", title: e.kind}, e.kind),
    h("span", {class: "d"}, describe(e))));
  $("evcount").textContent = S.events.length ? "(" + S.events.length + ")" : "";
  $("evstatus").textContent = S.paused ? "paused, " + (S.events.length - S.frozen) + " more" : "";
  const filters = $("evfilters");
  filters.textContent = "";
  for (const [kind, count] of S.kinds) {
    filters.append(h("button", {"aria-pressed": String(!S.hidden.has(kind)), title: "Show or hide " + kind,
      onclick: () => { S.hidden.has(kind) ? S.hidden.delete(kind) : S.hidden.add(kind); drawEvents(); }}, kind + " " + count));
  }
}

$("evpause").addEventListener("click", () => {
  S.paused = !S.paused;
  S.frozen = S.events.length;
  $("evpause").textContent = S.paused ? "Resume" : "Pause";
  drawEvents();
});
$("evclear").addEventListener("click", async () => { await act("api/events/clear"); clearEvents(); });
$("evexport").addEventListener("click", () => download("deckbench-events-" + stamp() + ".json", JSON.stringify(S.events, null, 1)));

function stamp() { return new Date().toISOString().replace(/[:T]/g, "-").slice(0, 19); }

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], {type: "application/json"}));
  const a = h("a", {href: url, download: name});
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---- scenarios ---- */

function savedScenarios() {
  try { return JSON.parse(store.get("deckbench.scenarios", "{}")) || {}; } catch (e) { return {}; }
}

function fillSaved() {
  const sel = $("scsaved");
  sel.textContent = "";
  sel.append(h("option", {value: ""}, "Saved…"));
  for (const name of Object.keys(savedScenarios()).sort()) sel.append(h("option", {value: name}, name));
}

async function loadExamples() {
  try {
    S.examples = await (await transport.fetch("api/examples")).json();
    const groups = {};
    for (const [i, ex] of S.examples.entries()) {
      if (!groups[ex.group]) { groups[ex.group] = h("optgroup", {label: ex.group}); $("scexample").append(groups[ex.group]); }
      groups[ex.group].append(h("option", {value: i}, ex.name));
    }
    if (!$("scenario").value && S.examples.length) setScenario(S.examples[0].text);
  } catch (e) { /* no examples */ }
}

function setScenario(text) {
  $("scenario").value = text;
  validate();
}

/* what is wrong with the text, in words, with the line: null if it is a scenario as far as this page can tell */
function check(text) {
  let data;
  try { data = JSON.parse(text); }
  catch (e) {
    const m = /position (\d+)/.exec(e.message), l = /line (\d+)/.exec(e.message);
    const line = l ? Number(l[1]) : m ? text.slice(0, Number(m[1])).split("\n").length : null;
    return {error: (line ? "line " + line + ": " : "") + e.message};
  }
  if (!data || !Array.isArray(data.steps)) return {error: 'it needs "steps": [ ... ]'};
  const bad = data.steps.findIndex((s) => !s || typeof s !== "object" || typeof s.do !== "string");
  if (bad >= 0) return {error: "step " + (bad + 1) + ' has no "do"'};
  const last = Math.max(0, ...data.steps.map((s) => Number(s.at) || 0));
  return {data, steps: data.steps.length, seconds: last};
}

function validate() {
  const r = check($("scenario").value), box = $("scvalid");
  box.classList.toggle("note", false);
  box.textContent = r.error ? r.error : (r.data.name ? r.data.name + " · " : "") + r.steps + " steps, the last at " + r.seconds + " s";
  box.style.color = r.error ? "var(--danger)" : "";
  return r;
}

function renderScenario() {
  const s = S.scenario;
  if (!s) return;
  $("scrun").disabled = s.running;
  $("scstop").disabled = !s.running;
  $("sccopy").disabled = s.running || !s.name;
  const done = s.results.length, bar = $("scbar");
  bar.firstChild.style.width = s.total ? Math.round(100 * done / s.total) + "%" : "0";
  bar.classList.toggle("failed", !s.running && s.failed > 0);
  bar.classList.toggle("done", !s.running && !!s.name && s.failed === 0 && !s.stopped && !s.skipped);
  const note = $("scstatus");
  note.className = "note" + (!s.running && s.name ? (s.failed ? " bad" : s.stopped ? "" : " good") : "");
  if (s.skipped) { note.className = "note"; note.textContent = s.name + ": skipped, " + s.skipped; return renderResults(s); }
  note.textContent = !s.name ? "Steps and what they do: docs/scenarios.md" :
    s.name + ": " + (s.running ? "playing, " : s.stopped ? "stopped, " : "done, ") + done + " of " + s.total + " steps" +
    (s.failed ? ", " + s.failed + " expectation" + (s.failed > 1 ? "s" : "") + " failed" : !s.running && !s.stopped ? ", all expectations met" : "");
  renderResults(s);
}

function renderResults(s) {
  const box = $("scresults");
  box.textContent = "";
  for (const r of s.results) box.append(h("div", {class: r.ok ? "" : "bad"}, h("span", {class: "t"}, r.at.toFixed(1) + " s"),
    h("span", {class: "k", title: r.what}, r.what), h("span", {class: "d"}, (r.message || "") + (r.ok ? "" : " FAILED"))));
  box.scrollTop = box.scrollHeight;
}

$("scenario").addEventListener("input", validate);
$("scenario").addEventListener("keydown", (e) => {          // Tab indents, as in an editor
  if (e.key !== "Tab" || e.shiftKey) return;
  e.preventDefault();
  const t = e.target, a = t.selectionStart;
  t.value = t.value.slice(0, a) + "  " + t.value.slice(t.selectionEnd);
  t.selectionStart = t.selectionEnd = a + 2;
});
$("scexample").addEventListener("change", (e) => {
  const ex = S.examples[e.target.value];
  if (ex) setScenario(ex.text);
  e.target.value = "";
});
$("scsaved").addEventListener("change", (e) => {
  const text = savedScenarios()[e.target.value];
  if (text) setScenario(text);
  $("scdelete").hidden = !e.target.value;
});
$("scdelete").addEventListener("click", () => {
  const all = savedScenarios();
  delete all[$("scsaved").value];
  store.set("deckbench.scenarios", JSON.stringify(all));
  fillSaved();
  $("scdelete").hidden = true;
});
$("scsave").addEventListener("click", () => {
  const r = validate();
  if (r.error || !r.data.name) return toast(r.error ? "Not a scenario yet: " + r.error : 'Give it a "name" to keep it under.');
  const all = savedScenarios();
  all[r.data.name] = $("scenario").value;
  store.set("deckbench.scenarios", JSON.stringify(all));
  fillSaved();
  $("scsaved").value = r.data.name;
  $("scdelete").hidden = false;
  toast("Kept in this browser as “" + r.data.name + "”.", "ok");
});
$("scdownload").addEventListener("click", () => {
  const r = validate();
  download(((r.data && r.data.name) || "scenario").replace(/[^\w.-]+/g, "-") + ".json", $("scenario").value);
});
$("scopen").addEventListener("click", () => $("scfile").click());
$("scfile").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => setScenario(reader.result);
  reader.readAsText(file);
  e.target.value = "";
});
$("scrun").addEventListener("click", async () => {
  const r = validate();
  if (r.error) return toast("Not a scenario yet: " + r.error);
  await act("api/scenario", {body: $("scenario").value});
});
$("scstop").addEventListener("click", () => act("api/scenario/stop"));
$("sccopy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(JSON.stringify(S.scenario, null, 1)); toast("Result copied.", "ok"); }
  catch (e) { toast("The browser would not let the page copy."); }
});

/* ---- network ---- */

for (const p of [0, 5, 20, 50]) {
  $("lossquick").append(h("button", {onclick: () => act("api/loss/" + p)}, p + " %"));
}
$("loss").addEventListener("input", (e) => { $("lossout").textContent = e.target.value + " %"; });
$("loss").addEventListener("change", (e) => act("api/loss/" + e.target.value));

function kv(rows) {
  return rows.map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v)));
}

function renderNetwork() {
  const s = S.state, loss = $("loss");
  if (document.activeElement !== loss) loss.value = s.loss;
  $("lossout").textContent = s.loss + " %";
  const unit = unitOf(s), box = $("unit"), seen = s.unit_state || {}, yes = (v) => (v ? "yes" : "no");
  box.textContent = "";
  if (unit) {
    const rows = [["Player", String(unit.number)], ["Address", unit.ip || "?"], ["Tempo master", yes(seen.master)],
      ["Synced", yes(seen.synced)], ["Playing", yes(seen.playing)],
      ["Tempo", unit.bpm ? unit.bpm.toFixed(1) + " BPM" + (seen.pitch_percent ? " (pitch " + (seen.pitch_percent > 0 ? "+" : "") + seen.pitch_percent + " %)" : "") : "-"]];
    if ("lamp.sync" in seen) rows.push(["SYNC lamp", seen["lamp.sync"] ? "lit" : "off"], ["MASTER lamp", seen["lamp.master"] ? "lit" : "off"]);
    box.append(h("table", {class: "kv"}, kv(rows)));
  } else box.append(h("p", {class: "hint"}, "No device has announced itself with a player number yet. A DJS-1000 on this network shows here, with its address and whether it is the tempo master."));
  const adapters = s.adapters || [], pad = $("unitpress");
  pad.textContent = "";
  for (const a of adapters) {
    pad.append(h("span", {class: "hint"}, a.name + (a.connected ? " connected" : " not connected") + (a.controls.length ? ". Press: " : "")));
    for (const control of a.controls) {
      pad.append(h("button", {class: "btn small", disabled: !a.connected, title: "Press " + control + " on the device under test",
        onclick: () => act("api/unit/press/" + control)}, control.toUpperCase()));
    }
  }
  const table = $("nettable");
  table.textContent = "";
  table.append(...kv(Object.entries(s.decks).map(([n, d]) => ["Deck " + n,
    (d.address || "?") + " · " + (d.unplugged ? "cable pulled" : d.on ? "on" : "off")])));
  const b = (s.bench || {});
  if (b.broadcast) table.append(...kv([["Broadcast", b.broadcast]]));
}

/* ---- settings ---- */

for (const name of ["strict", "refuse_db", "claim", "player_control", "auto_track_info", "auto_waveforms"]) {
  $(name).addEventListener("click", () => act("api/settings/" + name + "/" + ($(name).getAttribute("aria-checked") === "true" ? 0 : 1)));
}
$("profile").addEventListener("change", (e) => act("api/settings/profile/" + (e.target.value || "default")));
$("modelset").addEventListener("click", () => act("api/settings/model/" + encodeURIComponent($("model").value.trim())));
$("model").addEventListener("keydown", (e) => { if (e.key === "Enter") $("modelset").click(); });

function renderSettings() {
  const s = S.state, set = settingsOf(s), b = s.bench || {};
  for (const name of ["strict", "refuse_db", "claim", "player_control", "auto_track_info", "auto_waveforms"]) $(name).setAttribute("aria-checked", String(!!set[name]));
  if (document.activeElement !== $("model")) $("model").value = set.model || "";
  const profile = $("profile"), titles = b.profiles || {};
  if (profile.options.length !== Object.keys(titles).length + 1) {
    for (const [key, title] of Object.entries(titles)) profile.append(h("option", {value: key}, title));
  }
  if (document.activeElement !== profile) profile.value = set.profile || "";
  const ports = b.ports || {};
  const about = $("about");
  about.textContent = "";
  about.append(...kv([["Version", b.version || "?"], ["Process", b.pid ? String(b.pid) : "?"], ["Page", b.http || location.href],
    ["Decks", (b.numbers || []).join(", ")],
    ["UDP", ports.announce ? [ports.announce, ports.beat, ports.update].join(", ") + " (keep-alive, beat, status)" : "?"],
    ["TCP", ports.query ? ports.query + ", " + ports.db + " (port query, database)" : "?"],
    ["Sound port", b.audio || "off"]]));
}

function theme(value) {
  if (value === "dark" || value === "light") document.documentElement.setAttribute("data-theme", value);
  else document.documentElement.removeAttribute("data-theme");
}
$("theme").value = store.get("deckbench.theme", "auto");
theme($("theme").value);
$("theme").addEventListener("change", (e) => { store.set("deckbench.theme", e.target.value); theme(e.target.value); });

/* the look: commit (commitcollective.cc) or classic, which is the first look of the page */
function look(value) {
  if (value === "classic") document.documentElement.setAttribute("data-style", value);
  else document.documentElement.removeAttribute("data-style");
}
$("look").value = store.get("deckbench.look", "commit");
look($("look").value);
$("look").addEventListener("change", (e) => { store.set("deckbench.look", e.target.value); look(e.target.value); });

/* ---- the files this page sends ---- */

if ($("clearuploads")) $("clearuploads").addEventListener("click", async () => {
  try {
    const got = await api("api/uploads/clear");
    toast("Removed " + got.removed + " sent file" + (got.removed === 1 ? "" : "s") + " (" + (got.bytes / 1048576).toFixed(1) + " MB).", "ok");
  } catch (e) { /* a toast said why */ }
});

/* ---- sound ---- */

$("sound").addEventListener("click", async () => {
  try {
    const on = await Sound.toggle();
    $("sound").setAttribute("aria-pressed", String(on));
    $("sound").textContent = on ? "Listening" : "Listen";
    if (on && S.state && !Sound.sources(S.state, Sound.options).length) {
      toast("No audible decks yet. Check playback, Sound settings and mixer on-air state.", "warn");
    }
  } catch (e) {
    toast(e.message || "The browser would not start the sound.");
  }
});

/* ---- the link log ---- */

const P = {next: 0, items: [], counts: {}, paused: false, noisy: false, ours: false, follow: true, hidden: new Set(), open: new Set(), busy: false};
const NOISY = ["status", "beat", "position"];

function pktLine(p) {
  const who = (p.number != null ? "#" + p.number + " " : "") + p.src;
  const line = h("div", {class: "pkt" + (p.ours ? " ours" : ""), title: p.src + " to " + p.to + ", port " + p.port + ", " + p.len + " bytes. Click for the bytes",
    onclick: () => {
      if (!window.getSelection().isCollapsed) return;
      if (P.open.has(p.n)) {
        P.open.delete(p.n);
        line.nextSibling.remove();
      } else {
        P.open.add(p.n);
        line.after(h("div", {class: "hex"}, p.hex));
      }
    }},
    h("span", {class: "t"}, p.t.toFixed(2)), h("span", {class: "dir"}, p.to !== "*" && p.to !== "" && p.ours ? "\u2192" : "\u2190"),
    h("span", {class: "src"}, who), h("span", {class: "kind"}, p.kind), h("span", {class: "what"}, p.text));
  return P.open.has(p.n) ? [line, h("div", {class: "hex"}, p.hex)] : [line];
}

function shownPackets() {
  return P.items.filter((p) => (P.ours || !p.ours) && !P.hidden.has(p.kind) && (P.noisy || !NOISY.includes(p.kind)));
}

let pktTimer = null;
let pktRefresh = false, pktRendered = [];
function drawPackets(refresh = false) {
  pktRefresh = pktRefresh || refresh;
  if (pktTimer) return;
  pktTimer = setTimeout(() => {
    pktTimer = null;
    const refresh = pktRefresh;
    pktRefresh = false;
    if (!refresh && (!P.follow || P.paused)) return;
    const box = $("pktlog"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
    const scrollTop = box.scrollTop;
    box.textContent = "";
    const list = shownPackets().slice(-400);
    pktRendered = list;
    if (!list.length) box.append(h("div", {class: "pkt"}, h("span", {class: "what"}, "Nothing heard yet. Packets of the other devices on the link appear here as they come.")));
    for (const p of list) box.append(...pktLine(p));
    if (P.follow && (atEnd || P.fresh)) box.scrollTop = box.scrollHeight;
    else box.scrollTop = scrollTop;
    P.fresh = false;
    $("pktcount").textContent = "(" + list.length + " of " + P.items.length + " kept)";
    const filters = $("pktfilters");
    filters.textContent = "";
    for (const [kind, count] of Object.entries(P.counts).sort()) {
      if (!P.noisy && NOISY.includes(kind)) continue;
      filters.append(h("button", {"aria-pressed": String(!P.hidden.has(kind)), title: "Show or hide " + kind,
        onclick: () => { P.hidden.has(kind) ? P.hidden.delete(kind) : P.hidden.add(kind); drawPackets(true); }}, kind + " " + count));
    }
  }, 150);
}

async function pollPackets() {
  const visible = !$("p-network").hidden;
  if (visible && !P.paused && !P.busy) {
    P.busy = true;
    try {
      const r = await transport.fetch("api/packets?since=" + P.next + "&noisy=" + (P.noisy ? 1 : 0) + "&limit=800");
      if (r.ok) {
        const data = await r.json();
        if (P.session && data.session && P.session !== data.session) { resetPackets(); data.packets = []; data.next = 0; }
        P.session = data.session;
        if (data.next < P.next) { P.items = []; P.open.clear(); }
        P.next = data.next;
        P.counts = data.counts;
        if (data.packets.length) { P.items = P.items.concat(data.packets).slice(-3000); P.fresh = true; }
        drawPackets();
      }
    } catch (e) { /* the state's stream says so */ }
    P.busy = false;
  }
  setTimeout(pollPackets, 500);
}

function resetPackets() { P.items = []; P.next = 0; P.open.clear(); drawPackets(true); }

$("pktpause").addEventListener("click", () => {
  P.paused = !P.paused;
  if (P.paused) pktRefresh = false;
  $("pktpause").textContent = P.paused ? "Resume" : "Pause";
});
$("pktclear").addEventListener("click", async () => { await act("api/packets/clear"); resetPackets(); P.counts = {}; });
$("pktexport").addEventListener("click", () => download("deckbench-link-" + stamp() + ".json", JSON.stringify(P.follow && !P.paused ? shownPackets() : pktRendered, null, 1)));
$("pktcapture").addEventListener("click", async () => {
  try {
    const r = await transport.fetch("api/packets?since=0&noisy=1&limit=20000");
    if (!r.ok) throw new Error("Capture export failed (HTTP " + r.status + ")");
    const data = await r.json();
    download("deckbench-link-" + stamp() + ".json", JSON.stringify(data.packets, null, 1));
  } catch (e) { toast(e.message); }
});
$("pktmark").addEventListener("click", () => {
  const label = window.prompt("Describe this moment for the Events log", "");
  if (label && label.trim()) act("api/mark?text=" + encodeURIComponent(label.trim()));
});
for (const [id, key] of [["pktnoisy", "noisy"], ["pktours", "ours"], ["pktfollow", "follow"]]) {
  $(id).addEventListener("click", () => {
    P[key] = !P[key];
    if (key === "follow" && !P.follow) pktRefresh = false;
    $(id).setAttribute("aria-pressed", String(P[key]));
    if (key === "noisy" && P.noisy) resetPackets();                 /* the statuses and beats were not asked for: fetch all again */
    P.fresh = true;
    if (key !== "follow" || P.follow) drawPackets(true);
  });
}

/* ---- sound options ---- */

(function soundOptions() {
  let saved = {};
  try { saved = JSON.parse(store.get("deckbench.sound", "{}")) || {}; } catch (e) { saved = {}; }
  Sound.options.own = saved.own !== false;
  Sound.options.other = saved.other !== false;
  if (typeof saved.volume === "number") Sound.setVolume(saved.volume); else Sound.volume = 0.4;
  const keep = () => store.set("deckbench.sound", JSON.stringify({own: Sound.options.own, other: Sound.options.other, volume: Sound.volume}));
  for (const [id, key] of [["soundown", "own"], ["soundother", "other"]]) {
    $(id).setAttribute("aria-checked", String(Sound.options[key]));
    $(id).addEventListener("click", () => {
      Sound.options[key] = !Sound.options[key];
      $(id).setAttribute("aria-checked", String(Sound.options[key]));
      keep();
    });
  }
  $("soundvol").value = Math.round(Sound.volume * 100);
  $("soundvol").addEventListener("input", (e) => { Sound.setVolume(e.target.value / 100); keep(); });
})();

/* ---- all on, all off ---- */

async function everyDeck(on) {
  const unit = unitOf(S.state);
  for (const [n, d] of Object.entries(S.state.decks)) {
    if (!!d.on === on || (on && unit && unit.number === Number(n))) continue;
    await act("api/deck/" + n + "/on/" + (on ? 1 : 0));
  }
}
$("allon").addEventListener("click", () => everyDeck(true));
$("alloff").addEventListener("click", () => everyDeck(false));

/* ---- tabs ---- */

/* ---- the mixer ---- */

let stripKey = "";

function buildStrips(mixer) {
  const key = Object.keys(mixer.channels).join();
  if (key === stripKey) return;
  stripKey = key;
  const box = $("mixstrips");
  box.textContent = "";
  for (const n of Object.keys(mixer.channels)) {
    const out = h("output", {id: "mixout" + n}, "0");
    box.append(h("div", {class: "chan", id: "strip" + n},
      h("span", {class: "ch"}, "CH " + n),
      h("input", {type: "range", min: 0, max: 100, step: 1, value: 0, class: "mixfader", "aria-label": "Fader of channel " + n,
        oninput: (e) => { out.textContent = e.target.value; },
        onchange: (e) => act("api/mixer/channel/" + n + "/fader/" + e.target.value)}),
      out,
      h("div", {class: "row2"},
        h("span", {class: "air"}, "ON AIR"),
        h("button", {class: "switch", role: "switch", "aria-checked": "false", "aria-label": "Fader start of channel " + n,
          title: "Opening the fader starts the player, closing it stops it",
          onclick: (e) => act("api/mixer/channel/" + n + "/fader_start/" + (e.currentTarget.getAttribute("aria-checked") === "true" ? 0 : 1))}),
        h("span", {class: "hint"}, "fader start"),
        h("span", {style: "flex:1"}),
        h("button", {class: "btn small", title: "Tell player " + n + " to start", onclick: () => act("api/mixer/channel/" + n + "/command/start")}, "Start"),
        h("button", {class: "btn small", title: "Tell player " + n + " to stop", onclick: () => act("api/mixer/channel/" + n + "/command/stop")}, "Stop"))));
  }
}

function renderMixer() {
  const mixer = mixerOf(S.state);
  if (!mixer) return;
  buildStrips(mixer);
  $("mixname").textContent = "Simulated mixer " + mixer.name + " (player " + mixer.number + ")";
  $("mixon").setAttribute("aria-checked", String(!!mixer.on));
  $("mixon").disabled = !!mixer.unavailable;
  $("mixmaster").setAttribute("aria-checked", String(!!mixer.master));
  const active = document.activeElement;
  for (const [n, c] of Object.entries(mixer.channels)) {
    const strip = $("strip" + n), fader = strip.querySelector(".mixfader");
    if (active !== fader) { fader.value = c.fader; $("mixout" + n).textContent = c.fader; }
    strip.querySelector(".air").classList.toggle("lit", !!c.on_air);
    strip.querySelector(".switch").setAttribute("aria-checked", String(!!c.fader_start));
    for (const b of strip.querySelectorAll(".btn")) b.disabled = !mixer.on;
  }
  $("mixhint").textContent = mixer.unavailable || (mixer.on ? "Channel N is player N. The decks' on-air flag follows what the mixer says, and a unit that picks the deck to sync to looks at it."
    : "Simulation off. A discovered physical mixer can still report which channels are on air.");
}

$("mixon").addEventListener("click", () => act("api/mixer/on/" + ($("mixon").getAttribute("aria-checked") === "true" ? 0 : 1)));
$("mixmaster").addEventListener("click", () => act("api/mixer/master/" + ($("mixmaster").getAttribute("aria-checked") === "true" ? 0 : 1)));

const TABS = ["events", "scenario", "mixer", "network", "settings"];
function showTab(name) {
  for (const t of TABS) {
    $("tab-" + t).setAttribute("aria-selected", String(t === name));
    $("p-" + t).hidden = t !== name;
  }
  store.set("deckbench.tab", name);
}
for (const t of TABS) {
  $("tab-" + t).addEventListener("click", () => showTab(t));
  $("tab-" + t).addEventListener("keydown", (e) => {
    const i = TABS.indexOf(t) + (e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0);
    if (i === TABS.indexOf(t) || i < 0 || i >= TABS.length) return;
    showTab(TABS[i]);
    $("tab-" + TABS[i]).focus();
  });
}
const tabInAddress = () => location.hash.slice(1).split("&").find((part) => TABS.includes(part)) || "";    // page#scenario opens that tab
showTab(tabInAddress() || (TABS.includes(store.get("deckbench.tab")) ? store.get("deckbench.tab") : "events"));
window.addEventListener("hashchange", () => { if (tabInAddress()) showTab(tabInAddress()); });

/* ---- start ---- */

function frame() { lamps(); strips(); requestAnimationFrame(frame); }

function updateNetworkReconnect() {
  const option = $("djinterface").selectedOptions[0];
  $("djreconnect").disabled = transport.demo || !option || option.disabled;
}
$("djinterface").onchange = updateNetworkReconnect;

async function loadNetworkSetup() {
  const select = $("djinterface"), status = $("djnetworkstatus");
  $("djreconnect").disabled = true;
  if (transport.demo) {
    select.disabled = $("djrefresh").disabled = true;
    status.textContent = "The demo has no network adapter. Connect to a running bench to choose one.";
    return;
  }
  try {
    const data = await api("api/network", {method: "GET"});
    select.replaceChildren(h("option", {value: ""}, "Local testing (loopback)"));
    for (const row of data.interfaces) select.append(h("option", {value: row.name, disabled: row.ready === false},
      row.name + " · " + row.addresses.join(", ") + (row.default_route ? " · default route" : "") +
      (row.ready === false ? " · not usable yet (Windows says " + (row.state || "not ready") + ")" : "")));
    const chosen = data.current.interface || data.remembered || "";
    if (chosen && ![...select.options].some(option => option.value === chosen)) {
      select.append(h("option", {value: chosen, disabled: true}, chosen + " · unavailable"));
    }
    select.value = chosen;
    status.textContent = "Current: " + Object.entries(data.current.addresses).map(([n, ip]) => "#" + n + " at " + ip).join(", ") +
      ". Broadcast " + data.current.broadcast + ". " + data.endpoints + " endpoint(s), each needs its own configured IPv4 address. " + data.error;
    updateNetworkReconnect();
  } catch (error) {
    status.textContent = "Network setup is unavailable: " + error.message;
  }
}
$("djrefresh").onclick = loadNetworkSetup;
$("djreconnect").onclick = async () => {
  if (!window.confirm("Reconnect the DJ network? Discovery and armed player controls will reset. All simulated decks and the mixer must be off.")) return;
  $("djreconnect").disabled = true;
  try {
    const result = await api("api/network", {headers: {"Content-Type": "application/json"},
      body: JSON.stringify({interface: $("djinterface").value, remember: $("djremember").checked})});
    toast(result.warning || "DJ network reconnected. Simulated decks remain off.", result.warning ? "warn" : "ok");
    await loadNetworkSetup();
  } catch (error) { updateNetworkReconnect(); }
};

function start() {
  loadNetworkSetup();
  pollPackets();
  fillSaved();
  drawEvents();
  loadExamples();
  connect();
  requestAnimationFrame(frame);
  const change = $("changebench");
  if (transport.demo || transport.remote()) {
    change.hidden = false;
    change.textContent = transport.demo ? "Leave the demo" : "Change bench";
    change.title = transport.demo ? "Back to connecting to a bench" : "Connect to another bench";
    change.onclick = () => {
      if (transport.demo) location.href = location.pathname;
      else { transport.forget(); location.href = location.pathname; }
    };
  }
  if (transport.demo) {
    const note = h("div", {class: "demo-note"}, "Demo: a bench made of JavaScript in this page. It shows the page, not a network. The real one runs on a machine cabled to your players.");
    document.body.prepend(note);
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => { document.head.append(h("script", {src, onload: resolve, onerror: reject})); });
}

function showConnect(message) {
  $("connect").hidden = false;
  $("connaddr").value = $("connaddr").value || (transport.base || "").replace(/\/$/, "");
  $("conntoken").value = $("conntoken").value || transport.token;
  $("connmsg").textContent = message || "";
  $("connhow").textContent = "python -m deckbench --http-host 0.0.0.0 --allow-origin " + location.origin + " --token auto";
  $("connaddr").focus();
}

$("connok").addEventListener("click", async () => {
  const base = transport.normalise($("connaddr").value), token = $("conntoken").value.trim();
  if (!base) return ($("connmsg").textContent = "Give the address of the bench.");
  $("connmsg").textContent = "Looking for it\u2026";
  const r = await transport.probe(base, token);
  if (!r.ok) return ($("connmsg").textContent = r.message);
  transport.base = base;
  transport.token = token;
  transport.remember(base, token);
  $("connect").hidden = true;
  start();
});
$("conndemo").addEventListener("click", () => { location.search = "?demo"; });
for (const id of ["connaddr", "conntoken"]) $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") $("connok").click(); });

(async function boot() {
  if (transport.demo) await loadScript("demo.js");
  if (transport.hosted && !transport.demo) {
    if (!transport.base) return showConnect();
    const r = await transport.probe(transport.base, transport.token);
    if (!r.ok) return showConnect(r.message);
  }
  start();
})();
