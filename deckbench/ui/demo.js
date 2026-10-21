/* The demo: a small bench made of JavaScript, that answers the page as a real one does (the same API), so the page can be
 * tried with no network and no Python. Decks, loops, tempo, the cable, a mixer with its on air and fader start, events and
 * scenarios. What needs a device under test (a unit, an adapter) is not here. It is not the bench: what it does on a
 * network is in the Python. */
"use strict";

const DEMO_EXAMPLES = [
  {file: "01-loop-and-stop.json", group: "Examples", name: "A loop and a stop", text: `{"name": "A loop and a stop", "steps": [
  {"at": 0, "deck": 2, "do": "on"},
  {"at": 0.5, "deck": 2, "do": "play"},
  {"at": 4, "deck": 2, "do": "loop", "beats": 4},
  {"at": 8, "deck": 2, "do": "unloop"},
  {"at": 10, "deck": 2, "do": "stop"}
]}
`},
  {file: "02-tempo-ride.json", group: "Examples", name: "A tempo ride", text: `{"name": "A tempo ride", "steps": [
  {"at": 0, "deck": 2, "do": "on"},
  {"at": 0.5, "deck": 2, "do": "play"},
  {"at": 4, "deck": 2, "do": "tempo", "bpm": 124},
  {"at": 8, "deck": 2, "do": "tempo", "bpm": 128},
  {"at": 12, "deck": 2, "do": "tempo", "bpm": 134},
  {"at": 16, "deck": 2, "do": "stop"}
]}
`},
  {file: "04-mixer-drives-the-decks.json", group: "Examples", name: "A mixer starts and stops the decks", text: `{"name": "A mixer starts and stops the decks",
 "steps": [
  {"at": 0, "do": "log", "text": "A DJM joins the link. No fader is open, so no deck is on air"},
  {"at": 0, "deck": 2, "do": "on"}, {"at": 0, "deck": 3, "do": "on"},
  {"at": 0, "do": "mixer", "on": true}, {"at": 0, "do": "mixer", "master": true},
  {"at": 0, "do": "mixer", "channel": 2, "fader": 0, "fader_start": true},
  {"at": 1, "do": "expect_deck", "deck": 2, "match": {"play": false, "on_air": false}, "within": 3},
  {"at": 2, "do": "log", "text": "The fader of channel 2 is opened, with fader start: deck 2 starts and is on air"},
  {"at": 2, "do": "mixer", "channel": 2, "fader": 100},
  {"at": 2, "do": "expect", "event": "fader_start", "within": 3, "match": {"deck": 2, "action": "start"}},
  {"at": 2, "do": "expect_deck", "deck": 2, "match": {"play": true, "on_air": true}, "within": 3},
  {"at": 8, "do": "log", "text": "The fader is closed: deck 2 stops"},
  {"at": 8, "do": "mixer", "channel": 2, "fader": 0},
  {"at": 8, "do": "expect_deck", "deck": 2, "match": {"play": false}, "within": 3}
 ]}
`},
];

const demoMatches = (value, want) => {
  if (want && typeof want === "object") {
    if ("near" in want) return Math.abs(Number(value) - want.near) <= (want.tol ?? 0.5);
    if ("in" in want) return want.in.includes(value);
    if ("not" in want) return !demoMatches(value, want.not);
    if ("min" in want || "max" in want) return Number(value) >= (want.min ?? -Infinity) && Number(value) <= (want.max ?? Infinity);
    return false;
  }
  return value === want;
};

class DemoBench {
  constructor(numbers = [2, 3, 4]) {
    this.began = Date.now() / 1000;
    this.decks = {};
    numbers.forEach((n, i) => {
      this.decks[n] = {number: n, on: false, play: false, sync: false, master: false, loop: null, base: 128 - 2 * i, unplugged: false,
        anchorT: this.now(), anchorPos: 0, on_air: null, track: {id: 100 + n, title: "Track of deck " + n, source: n, slot: 3}};
    });
    this.loss = 0;
    this.settings = {strict: false, refuse_db: false, claim: false, mixer: false, profile: "", model: ""};
    this.mixer = {on: false, master: true, name: "DJM-900NXS2", number: 33, channels: {}};
    for (const n of [1, 2, 3, 4]) this.mixer.channels[n] = {fader: 0, fader_start: false};
    this.events = [];
    this.generation = 0;
    this.scenario = {running: false, name: null, total: 0, results: [], failed: 0, stopped: false, skipped: null};
    this.timers = [];
    this.listeners = [];
  }

  now() { return Date.now() / 1000; }

  /* -- what a deck is -- */
  tempo(d) {
    const master = Object.values(this.decks).find((o) => o.on && o.master);
    return d.sync && master && master !== d ? master.base : d.base;
  }
  position(d, at = this.now()) {
    if (!d.play) return d.anchorPos;
    let pos = d.anchorPos + (at - d.anchorT) * this.tempo(d) / 60;
    if (d.loop && pos >= d.loop[0] + d.loop[1]) pos = d.loop[0] + ((pos - d.loop[0]) % d.loop[1]);
    return pos;
  }
  settle(change) {                                   /* keep every deck's place through a change of who is the master */
    const now = this.now();
    for (const d of Object.values(this.decks)) { d.anchorPos = this.position(d, now); d.anchorT = now; }
    change();
  }
  onAir(d) {
    if (this.settings.mixer && this.mixer.on) return this.mixer.master && this.mixer.channels[d.number] ? this.mixer.channels[d.number].fader > 0 : false;
    return d.play;
  }

  snapshot() {
    const decks = {};
    for (const d of Object.values(this.decks)) {
      const bpm = Math.round(this.tempo(d) * 100) / 100;
      decks[d.number] = {on: d.on, play: d.play, sync: d.sync, on_air: this.onAir(d), master: d.master && d.on, bpm,
        name: "deck " + d.number, loop: d.loop ? d.loop[1] : 0, loop_from: d.loop ? d.loop[0] : 0, unplugged: d.unplugged,
        phase: d.on && d.play ? [d.anchorT, d.anchorPos, bpm] : null,
        track: d.track.title, track_id: d.track.source + ":" + d.track.slot + ":" + d.track.id, track_source: d.track.source,
        track_slot: d.track.slot, track_rbid: d.track.id,
        model: this.settings.model || "CDJ-FAKE" + d.number, address: "127.0.0." + d.number};
    }
    const mixer = this.settings.mixer && this.mixer.on;
    const channels = {};
    for (const [n, c] of Object.entries(this.mixer.channels)) {
      channels[n] = {fader: c.fader, fader_start: c.fader_start, on_air: !!(mixer && this.mixer.master && c.fader > 0)};
    }
    return {now: this.now(), decks, loss: this.loss, unit_state: {heard: false}, adapters: [],
      protocols: {prolink: {unit: null, settings: Object.assign({}, this.settings, {mixer}), mixer: Object.assign({}, this.mixer, {on: mixer, channels, six: false})}},
      bench: {version: "demo", numbers: Object.keys(this.decks).map(Number), strict: this.settings.strict, broadcast: "127.255.255.255",
        profiles: {"cdj-2000": "CDJ-2000 (nexus)", "cdj-2000nxs2": "CDJ-2000NXS2", "xdj-1000mk2": "XDJ-1000MK2", "cdj-3000": "CDJ-3000"},
        http: "the demo in this page"}};
  }

  addEvent(kind, data) {
    const item = Object.assign({n: this.events.length, t: Math.round((this.now() - this.began) * 1000) / 1000, kind}, data);
    this.events.push(item);
    return item;
  }

  /* -- what is done to it -- */
  toggle(d, what, want) {
    if (what === "on") {
      this.settle(() => { d.on = want ?? !d.on; if (!d.on) { d.master = false; d.play = false; } });
    } else if (!d.on) {
      return;
    } else if (what === "play") {
      this.settle(() => { d.play = want ?? !d.play; if (d.play) { d.anchorT = this.now(); d.anchorPos = 0; } });
    } else if (what === "sync") {
      this.settle(() => { d.sync = want ?? !d.sync; });
    } else if (what === "master") {
      this.settle(() => {
        const on = want ?? !d.master;
        for (const o of Object.values(this.decks)) o.master = false;
        d.master = on;
      });
    }
  }
  mixerStart(channel, command) {
    const d = this.decks[channel];
    this.addEvent("fader_start", {deck: channel, action: command, sender: 33});
    if (d && d.on && !d.unplugged) this.toggle(d, "play", command === "start");
  }
  setFader(channel, level) {
    const c = this.mixer.channels[channel];
    const wasOpen = c.fader > 0;
    c.fader = Math.max(0, Math.min(100, Math.round(level)));
    if (this.settings.mixer && this.mixer.on && c.fader_start && wasOpen !== c.fader > 0) this.mixerStart(channel, c.fader > 0 ? "start" : "stop");
    this.noteAir();
  }
  noteAir() {                                          /* an event when a deck's on air changes */
    for (const d of Object.values(this.decks)) {
      const now = this.onAir(d);
      if (this.settings.mixer && d.on_air !== now) this.addEvent("on_air", {deck: d.number, on: now, sender: 33});
      d.on_air = this.settings.mixer ? now : null;
    }
  }

  /* -- the API -- */
  route(method, path, body) {
    const [route, queryString] = path.split("?");
    const query = new URLSearchParams(queryString || "");
    const parts = route.replace(/^\/+|\/+$/g, "").split("/");
    const ok = (data) => ({ok: true, status: 200, data: data ?? this.snapshot()});
    const fail = (status, error) => ({ok: false, status, data: {error}});
    if (method === "GET") {
      if (route === "api/state") return ok();
      if (route === "api/ready") return ok({ready: true, version: "demo", numbers: Object.keys(this.decks).map(Number)});
      if (route === "api/scenario") return ok(Object.assign({}, this.scenario, {results: this.scenario.results.slice()}));
      if (route === "api/events") return ok(this.events.slice(Number(query.get("since") || 0)));
      if (route === "api/examples") return ok(DEMO_EXAMPLES);
      if (route === "api/unit") return ok({heard: false});
      return fail(404, "not found");
    }
    if (parts[0] !== "api") return fail(404, "not found");
    if (parts[1] === "deck") {
      const d = this.decks[Number(parts[2])];
      if (!d) return fail(404, "no such deck");
      const what = parts[3], arg = parts[4];
      if (["on", "play", "sync", "master"].includes(what)) { this.toggle(d, what, arg === undefined ? undefined : arg === "1"); return ok(); }
      if (what === "loop") {
        const beats = Number(arg);
        if (!(beats >= 0 && beats <= 64)) return fail(400, "no such loop");
        if (d.on) this.settle(() => { d.loop = beats ? [Math.floor(this.position(d)), beats] : null; });
        return ok();
      }
      if (what === "tempo") { this.settle(() => { d.base = Number(arg); }); return ok(); }
      if (what === "load") {
        const title = query.get("title"), bpm = query.get("bpm");
        this.settle(() => {
          d.track = {id: Number(arg), title: title || "Track " + arg, source: Number(query.get("source") || d.number), slot: Number(query.get("slot") || d.track.slot)};
          if (bpm) d.base = Number(bpm);
          d.anchorT = this.now(); d.anchorPos = 0; d.loop = null;
        });
        return ok();
      }
      if (what === "unplug" || what === "plug") { d.unplugged = what === "unplug"; return ok(); }
      if (what === "silence") {
        d.unplugged = true;
        this.timers.push(setTimeout(() => { d.unplugged = false; }, Number(arg) * 1000));
        return ok();
      }
      return fail(400, "no such action");
    }
    if (parts[1] === "loss") { this.loss = Math.max(0, Math.min(100, Number(parts[2]))); return ok(); }
    if (parts[1] === "events" && parts[2] === "clear") { this.events = []; this.generation++; return ok({}); }
    if (parts[1] === "settings") {
      const name = parts[2], value = decodeURIComponent(parts[3] ?? "");
      if (["strict", "refuse_db", "claim", "mixer"].includes(name) && (value === "0" || value === "1")) {
        this.settings[name] = value === "1";
        if (name === "mixer") { this.mixer.on = this.settings.mixer; this.noteAir(); }
        return ok();
      }
      if (name === "profile") { this.settings.profile = value === "default" ? "" : value; return ok(); }
      if (name === "model" && value && value.length <= 20) { this.settings.model = value; return ok(); }
      return fail(400, "no such setting or value");
    }
    if (parts[1] === "mixer") return this.mixerRoute(parts.slice(2), ok, fail);
    if (parts[1] === "unit") return fail(400, "no adapter: the demo has no device under test");
    if (parts[1] === "scenario") {
      if (parts[2] === "stop") { this.stopping = true; return ok({}); }
      return this.startScenario(body, ok, fail);
    }
    return fail(404, "not found");
  }

  mixerRoute(rest, ok, fail) {
    const params = {};
    if (rest.length === 2 && (rest[0] === "on" || rest[0] === "master")) params[rest[0]] = rest[1];
    else if (rest.length === 4 && rest[0] === "channel") { params.channel = rest[1]; params[rest[2]] = rest[3]; }
    else return fail(404, "no such mixer control");
    const [good, why] = this.mixerDo(params);
    return good ? ok() : fail(400, why);
  }

  mixerDo(params) {
    const yes = (v) => v === true || v === 1 || v === "1" || v === "true" || v === "on";
    if ("on" in params) { this.settings.mixer = yes(params.on); this.mixer.on = this.settings.mixer; this.noteAir(); }
    if ("master" in params) { this.mixer.master = yes(params.master); this.noteAir(); }
    if (params.channel != null) {
      const channel = Number(params.channel);
      if (!this.mixer.channels[channel]) return [false, "no channel " + params.channel + " (the mixer has 1 to 4)"];
      if ("fader" in params) { if (Number.isNaN(Number(params.fader))) return [false, "a fader is a number from 0 to 100"]; this.setFader(channel, Number(params.fader)); }
      if ("fader_start" in params) this.mixer.channels[channel].fader_start = yes(params.fader_start);
      if ("command" in params) {
        if (!["start", "stop"].includes(params.command)) return [false, "a command is start or stop"];
        if (!(this.settings.mixer && this.mixer.on)) return [false, "the mixer is off"];
        this.mixerStart(channel, params.command);
      }
    }
    return [true, ""];
  }

  /* -- scenarios: the steps that need no device under test -- */
  startScenario(body, ok, fail) {
    if (this.scenario.running) return {ok: false, status: 409, data: {error: "a scenario is playing"}};
    let data;
    try { data = JSON.parse(body); } catch (e) { return fail(400, "not a scenario: " + e.message); }
    if (!data || !Array.isArray(data.steps)) return fail(400, "a scenario needs steps");
    const steps = data.steps.map((s) => Object.assign({}, s)).sort((a, b) => (a.at || 0) - (b.at || 0));
    for (const s of steps) if (typeof s.do !== "string") return fail(400, "step " + JSON.stringify(s) + " has no do");
    this.stopping = false;
    this.scenario = {running: true, name: data.name || "scenario", total: steps.length, results: [], failed: 0, stopped: false, skipped: null};
    if ((data.requires || []).length) {
      this.scenario.running = false;
      this.scenario.skipped = "it needs a " + data.requires.join(" and an ") + ", and the demo has none";
      return ok({});
    }
    this.runSteps(steps);
    return ok({});
  }

  describe(step) {
    const extra = Object.entries(step).filter(([k]) => !["at", "do", "deck"].includes(k)).map(([k, v]) => k + "=" + (typeof v === "object" ? JSON.stringify(v) : v)).join(", ");
    return step.do + ("deck" in step ? " deck " + step.deck : "") + (extra ? " (" + extra + ")" : "");
  }

  async runSteps(steps) {
    const begin = Date.now(), firstEvent = this.events.length;
    for (const step of steps) {
      while (Date.now() - begin < (step.at || 0) * 1000) {
        if (this.stopping) { this.scenario.running = false; this.scenario.stopped = true; return; }
        await new Promise((r) => setTimeout(r, 50));
      }
      const [good, message] = await this.doStep(step, firstEvent);
      this.scenario.results.push({at: step.at || 0, what: this.describe(step), ok: good, message});
      if (!good) this.scenario.failed++;
    }
    this.scenario.running = false;
  }

  async waitFor(read, match, within) {
    const end = Date.now() + within * 1000;
    for (;;) {
      const state = read();
      if (Object.entries(match).every(([k, v]) => k in state && demoMatches(state[k], v))) return [true, ""];
      if (Date.now() >= end) {
        return [false, "within " + within + " s: " + Object.entries(match).filter(([k, v]) => !(k in state && demoMatches(state[k], v)))
          .map(([k, v]) => k + " is " + (k in state ? state[k] : "not known") + " (wanted " + JSON.stringify(v) + ")").join(", ")];
      }
      await new Promise((r) => setTimeout(r, 50));
    }
  }

  async doStep(step, firstEvent) {
    const d = "deck" in step ? this.decks[Number(step.deck)] : null;
    if ("deck" in step && !d) return [false, "no deck " + step.deck];
    switch (step.do) {
      case "on": case "play": case "sync": case "master": this.toggle(d, step.do, true); return [true, ""];
      case "off": this.toggle(d, "on", false); return [true, ""];
      case "stop": this.toggle(d, "play", false); return [true, ""];
      case "unsync": this.toggle(d, "sync", false); return [true, ""];
      case "release": this.toggle(d, "master", false); return [true, ""];
      case "loop": this.route("POST", "api/deck/" + d.number + "/loop/" + step.beats); return [true, ""];
      case "unloop": this.route("POST", "api/deck/" + d.number + "/loop/0"); return [true, ""];
      case "tempo": this.route("POST", "api/deck/" + d.number + "/tempo/" + step.bpm); return [true, ""];
      case "load": this.route("POST", "api/deck/" + d.number + "/load/" + step.id + "?" + new URLSearchParams(Object.entries({title: step.title, bpm: step.bpm}).filter(([, v]) => v != null))); return [true, ""];
      case "unplug": case "plug": this.route("POST", "api/deck/" + d.number + "/" + step.do); return [true, ""];
      case "silence": this.route("POST", "api/deck/" + d.number + "/silence/" + step.seconds); return [true, ""];
      case "loss": this.loss = Number(step.percent); return [true, ""];
      case "log": return [true, step.text || ""];
      case "mixer": return this.mixerDo(step);
      case "expect": {
        const end = Date.now() + (step.within ?? 5) * 1000;
        for (;;) {
          const found = this.events.slice(firstEvent).find((e) => e.kind === step.event && Object.entries(step.match || {}).every(([k, v]) => e[k] === v));
          if (found) return [true, step.event + " at " + found.t.toFixed(2) + " s"];
          if (Date.now() >= end) return [false, "no " + step.event + " event " + JSON.stringify(step.match || {}) + " within " + (step.within ?? 5) + " s"];
          await new Promise((r) => setTimeout(r, 50));
        }
      }
      case "expect_deck": return this.waitFor(() => this.snapshot().decks[Number(step.deck)] || {}, step.match || {}, step.within ?? 2);
      default: return [false, step.do + " needs a device under test, and the demo has none"];
    }
  }

  /* -- what the page calls -- */
  async fetch(path, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const r = this.route(method, path, options.body);
    return {ok: r.ok, status: r.status, json: async () => r.data};
  }

  eventSource(path) {
    const source = {onopen: null, onerror: null, handlers: {}, closed: false,
      addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); },
      close() { this.closed = true; }};
    const emit = (type, data) => (source.handlers[type] || []).forEach((fn) => fn({data: JSON.stringify(data)}));
    let lastState = "", lastScenario = "", sent = 0, generation = this.generation, beat = 0;
    setTimeout(() => source.onopen && source.onopen(), 0);
    const tick = () => {
      if (source.closed) return;
      const snap = this.snapshot(), now = snap.now;
      const key = JSON.stringify(Object.assign({}, snap, {now: 0}));
      if (key !== lastState || Date.now() - beat > 1000) { lastState = key; beat = Date.now(); emit("state", snap); }
      if (generation !== this.generation) { generation = this.generation; sent = 0; emit("cleared", {}); }
      for (const item of this.events.slice(sent)) { sent = item.n + 1; emit("event", item); }
      const sc = JSON.stringify(this.scenario);
      if (sc !== lastScenario) { lastScenario = sc; emit("scenario", this.scenario); }
      void now;
      setTimeout(tick, 100);
    };
    setTimeout(tick, 0);                              /* after the page has added its handlers, as a real source would */
    return source;
  }
}

/* The page starts the demo with something going on: two decks playing, one the master, and a mixer. */
function livelyDemo() {
  const bench = new DemoBench();
  for (const n of [2, 3, 4]) bench.toggle(bench.decks[n], "on", true);
  bench.toggle(bench.decks[2], "play", true);
  bench.toggle(bench.decks[3], "play", true);
  bench.toggle(bench.decks[2], "master", true);
  bench.toggle(bench.decks[3], "sync", true);
  bench.route("POST", "api/mixer/on/1");
  bench.route("POST", "api/mixer/channel/2/fader/100");
  bench.route("POST", "api/mixer/channel/3/fader/70");
  bench.route("POST", "api/mixer/channel/4/fader_start/1");
  return bench;
}

transport.DemoBench = DemoBench;
transport.bench = livelyDemo();
