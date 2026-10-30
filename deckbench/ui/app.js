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

function lamps() {
  if (!S.state) return;
  const master = Strip.master(S.state), masterBeat = master ? beatOf(master) : 0;
  for (const row of document.querySelectorAll(".master-beats")) {
    const label = master ? "Master player " + master.number + ", beat " + masterBeat : "No master beat available";
    row.title = label;
    row.setAttribute("aria-label", label);
    row.querySelectorAll("i").forEach((square, k) => square.classList.toggle("lit", masterBeat === k + 1));
  }
  for (const d of devicesOf(S.state)) {
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
    const st = d.status;
    Strip.draw(canvas, Strip.layoutDevice(d.ip, d, now), {bars: !(st && st.track_beat != null)});
  }
}

function buildDevice(d) {
  const mixer = d.kind === "mixer";
  return h("article", {class: "deck device off", id: devId(d.ip), "aria-label": (d.model || "Device") + " on the link"},
    h("div", {class: "deck-head"},
      h("div", {class: "num", "aria-hidden": "true"}),
      h("div", {class: "deck-id"}, h("div", {class: "model"}), h("div", {class: "track"})),
      h("div", {class: "tags"}, h("div", {class: "unit-slot"}), h("div", {class: "flags", "aria-label": "State"}))),
    mixer ? h("div", {class: "airs", "aria-label": "Channels on air"}) : h("div", {class: "live"},
      beatIndicators(),
      h("div", {class: "lcd", "aria-label": "Tempo"}, h("b", {}, "--"), h("span", {}, "BPM"))),
    mixer ? null : h("canvas", {class: "strip", "aria-hidden": "true"}),
    h("div", {class: "facts"}));
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
    card.classList.toggle("online", d.online);
    card.classList.toggle("offline", !d.online);
    card.classList.toggle("off", false);
    q("num").textContent = d.number == null ? "?" : d.number;
    const model = q("model");
    model.textContent = d.model || d.ip;
    model.append(h("span", {class: "addr"}, d.ip));
    const track = q("track");
    track.textContent = "";
    if (d.kind === "mixer") track.textContent = "mixer";
    else if (st) {
      track.append(h("b", {}, st.state), st.rbid ? " \u00b7 player " + st.source + " \u00b7 " + (SLOTS[st.slot] || "slot " + st.slot) + " \u00b7 id " + st.rbid : "");
    } else track.textContent = d.online ? "no status yet" : "gone quiet";
    /* the tags are a column at the right of the header, the height of the number's box: the unit tag at the top and the state (side by side, wrapping onto
       a row under when there are too many for the width) at the bottom. The column is always there: a flag that comes or goes does not change the card's height */
    const slot = q("unit-slot"), flags = q("flags");
    slot.textContent = "";
    if (d.unit && (S.state.adapters || []).some((a) => a.name === "djs1000-emu")) {
      slot.append(h("span", {class: "tag unit"}, "UNIT UNDER TEST"));
    }
    flags.textContent = "";
    if (!d.online) flags.append(h("span", {class: "tag offline"}, "OFFLINE"));
    if (st && d.online) {
      if (st.master) flags.append(h("span", {class: "tag master"}, "MASTER"));
      if (st.sync) flags.append(h("span", {class: "tag sync"}, "SYNC"));
      if (st.on_air) flags.append(h("span", {class: "tag air-tag"}, "ON AIR"));
      if (st.loop) flags.append(h("span", {class: "tag loop"}, "LOOP"));
    }
    const facts = q("facts");
    facts.textContent = "";
    if (d.kind === "mixer") {
      const airs = q("airs");
      airs.textContent = "";
      for (const [channel, on] of Object.entries(d.air || {})) airs.append(h("span", {class: "air" + (on ? " lit" : "")}, "CH " + channel));
      if (!d.air) airs.append(h("span", {class: "hint"}, "no on-air report heard"));
      if (d.fader) facts.append(h("span", {}, "fader start: " + Object.entries(d.fader).map(([p, c]) => "player " + p + " " + c).join(", ")));
    } else {
      const bpm = st ? st.bpm : d.phase ? d.phase[2] : null;
      q("lcd").firstChild.textContent = bpm != null && d.online ? bpm.toFixed(1) : "--";
      if (st && st.pitch) facts.append(h("span", {}, "pitch " + (st.pitch > 0 ? "+" : "") + st.pitch + " %"));
      if (d.firmware) facts.append(h("span", {}, "firmware " + d.firmware));
    }
    if (d.peers != null) facts.append(h("span", {}, "knows " + d.peers + " device" + (d.peers === 1 ? "" : "s")));
    if (d.mac) facts.append(h("span", {}, d.mac));
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

    const model = q("model");
    model.textContent = d.model || d.name;
    if (d.address) model.append(h("span", {class: "addr"}, d.address));
    const track = q("track");
    track.textContent = "";
    if (d.track) {
      const own = d.track_source === Number(n);
      track.append(h("b", {}, d.track), " · " + (own ? "own database" : "deck " + d.track_source) + " · " +
                   (SLOTS[d.track_slot] || "slot " + d.track_slot) + " · id " + d.track_rbid);
    } else track.textContent = "no track";
    const tags = q("tags");
    tags.textContent = "";
    if (d.on && d.loop) tags.append(h("span", {class: "tag loop"}, "LOOP " + d.loop));
    if (d.unplugged) tags.append(h("span", {class: "tag cable"}, "UNPLUGGED"));
    const mixer = mixerOf(s);
    if (mixer && mixer.on && d.on) tags.append(h("span", {class: "tag " + (d.on_air ? "air-tag" : "off-air")}, d.on_air ? "ON AIR" : "OFF AIR"));

    q("lcd").firstChild.textContent = d.on ? d.bpm.toFixed(1) : "--";
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
      if (what === "play") b.textContent = d.play ? "PAUSE" : "PLAY";
    }
    const range = q("tempo-range"), num = q("tempo-num");
    if (active !== range) range.value = d.bpm;
    if (active !== num) num.value = d.bpm.toFixed(1);
    for (const b of card.querySelectorAll(".seg button")) {
      b.setAttribute("aria-pressed", String(!!d.on && d.loop === Number(b.dataset.beats)));
      b.disabled = !d.on;
    }
    q("unplug").textContent = d.unplugged ? "Plug in" : "Unplug";
    q("silence").disabled = !!d.unplugged;
  }
  renderChips();
  renderNetwork();
  renderSettings();
  renderMixer();
  renderDevices();
  $("version").textContent = s.bench && s.bench.version ? (/^\d/.test(s.bench.version) ? "v" : "") + s.bench.version : "";
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
  return Object.entries(e).filter(([k]) => !["n", "t", "kind"].includes(k)).map(([k, v]) => k + "=" + v).join(" ");
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

for (const name of ["strict", "refuse_db", "claim"]) {
  $(name).addEventListener("click", () => act("api/settings/" + name + "/" + ($(name).getAttribute("aria-checked") === "true" ? 0 : 1)));
}
$("profile").addEventListener("change", (e) => act("api/settings/profile/" + (e.target.value || "default")));
$("modelset").addEventListener("click", () => act("api/settings/model/" + encodeURIComponent($("model").value.trim())));
$("model").addEventListener("keydown", (e) => { if (e.key === "Enter") $("modelset").click(); });

function renderSettings() {
  const s = S.state, set = settingsOf(s), b = s.bench || {};
  for (const name of ["strict", "refuse_db", "claim"]) $(name).setAttribute("aria-checked", String(!!set[name]));
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
  $("mixmaster").setAttribute("aria-checked", String(!!mixer.master));
  const active = document.activeElement;
  for (const [n, c] of Object.entries(mixer.channels)) {
    const strip = $("strip" + n), fader = strip.querySelector(".mixfader");
    if (active !== fader) { fader.value = c.fader; $("mixout" + n).textContent = c.fader; }
    strip.querySelector(".air").classList.toggle("lit", !!c.on_air);
    strip.querySelector(".switch").setAttribute("aria-checked", String(!!c.fader_start));
    for (const b of strip.querySelectorAll(".btn")) b.disabled = !mixer.on;
  }
  $("mixhint").textContent = mixer.on ? "Channel N is player N. The decks' on-air flag follows what the mixer says, and a unit that picks the deck to sync to looks at it."
    : "Simulation off. A discovered physical mixer can still report which channels are on air.";
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

function start() {
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
