// Runs the page's demo bench (deckbench/ui/demo.js) in node and checks what it answers: node tests/demo_check.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const transport = {};
const sandbox = {transport, setTimeout, clearTimeout, console, Date, JSON, Object, Math, Promise, URLSearchParams, encodeURIComponent,
  decodeURIComponent, Number, Array, String, Infinity};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "deckbench", "ui", "demo.js"), "utf8"), sandbox);
const bench = new transport.DemoBench();                      // the page's own starts with something going on

let failures = 0;
function check(what, ok, detail) {
  if (!ok) { failures++; console.log("FAIL: " + what + (detail === undefined ? "" : " (" + JSON.stringify(detail) + ")")); }
}
const get = async (p) => (await bench.fetch(p)).json();
const post = async (p, body) => { const r = await bench.fetch(p, {method: "POST", body}); return {status: r.status, data: await r.json()}; };
const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));

(async () => {
  let state = await get("api/state");
  check("four decks, off", Object.keys(state.decks).join() === "1,2,3,4" && !state.decks[2].on && !state.decks[1].on);
  check("ready", (await get("api/ready")).ready === true);

  state = (await post("api/deck/2/on/1")).data;
  state = (await post("api/deck/2/play/1")).data;
  check("deck 2 plays with a phase", state.decks[2].play && Array.isArray(state.decks[2].phase), state.decks[2]);
  check("on air while it plays, with no mixer", state.decks[2].on_air === true);
  await post("api/deck/3/on/1");
  await post("api/deck/2/master/1");
  await post("api/deck/3/play/1");
  await sleep(0.3);                                    // deck 3 is on its own first beats, the master well into its bar
  await post("api/deck/3/sync/1");
  await post("api/deck/2/tempo/131");
  state = await get("api/state");
  check("a synced deck follows the master's tempo", state.decks[3].bpm === 131 && state.decks[2].master, [state.decks[3].bpm, state.decks[2].master]);
  // synced, a deck is on the master's beat and not only at its tempo: both places match, and go on matching
  const placeOf = (n) => { const d = bench.decks[n]; return bench.position(d); };
  check("a synced deck is at the master's place", Math.abs(placeOf(3) - placeOf(2)) < 0.02, [placeOf(2), placeOf(3)]);
  await sleep(0.4);
  check("and stays there", Math.abs(placeOf(3) - placeOf(2)) < 0.02, [placeOf(2), placeOf(3)]);
  await post("api/deck/2/master/0");
  state = await get("api/state");
  check("it follows no more when there is no master", state.decks[3].bpm === 124, state.decks[3].bpm);   // its own tempo again

  state = (await post("api/deck/2/loop/4")).data;
  check("a loop", state.decks[2].loop === 4);
  state = (await post("api/deck/2/loop/0")).data;
  check("no loop", state.decks[2].loop === 0);
  check("a loop of 99 is refused", (await post("api/deck/2/loop/99")).status === 400);
  check("no such deck", (await post("api/deck/9/on")).status === 404);

  state = (await post("api/deck/4/load/321?title=Caf%C3%A9%20%25&bpm=119&source=2&slot=2")).data;
  const d4 = state.decks[4];
  check("a track from another deck", d4.track === "Café %" && d4.track_source === 2 && d4.track_slot === 2 && d4.track_rbid === 321, d4);

  await post("api/deck/2/unplug");
  check("the cable", (await get("api/state")).decks[2].unplugged);
  await post("api/deck/2/plug");
  await post("api/loss/20");
  check("loss", (await get("api/state")).loss === 20);
  await post("api/loss/0");

  const settings = (await post("api/settings/strict/1")).data.protocols.prolink.settings;
  check("a setting", settings.strict === true);
  check("a bad setting", (await post("api/settings/strict/maybe")).status === 400);
  check("no adapter", (await post("api/unit/press/sync")).status === 400);

  // the mixer
  await post("api/deck/2/play/0");
  await post("api/mixer/on/1");
  await post("api/mixer/channel/2/fader_start/1");
  state = (await post("api/mixer/channel/2/fader/80")).data;
  check("the fader opened: on air, started", state.decks[2].on_air && state.decks[2].play, state.decks[2]);
  check("the other is off the air", state.decks[3].on_air === false);
  state = (await post("api/mixer/channel/2/fader/0")).data;
  check("the fader closed: stopped", !state.decks[2].play && !state.decks[2].on_air);
  check("a bad channel", (await post("api/mixer/channel/9/fader/1")).status === 400);
  check("a bad command", (await post("api/mixer/channel/2/command/jump")).status === 400);
  const events = await get("api/events?since=0");
  check("events", events.some((e) => e.kind === "fader_start" && e.action === "start") && events.some((e) => e.kind === "on_air" && e.deck === 2 && e.on), events.map((e) => e.kind));
  await post("api/mixer/on/0");
  check("with no mixer a deck is on air while it plays", (await get("api/state")).decks[3].on_air === (await get("api/state")).decks[3].play);

  // a scenario
  const examples = await get("api/examples");
  check("examples", examples.length >= 3 && examples.every((e) => JSON.parse(e.text).steps.length > 0));
  const scenario = {name: "quick", steps: [{at: 0, do: "log", text: "hi"}, {at: 0, do: "mixer", on: true}, {at: 0, do: "mixer", channel: 3, fader: 100},
    {at: 0.2, do: "expect_deck", deck: 3, match: {on_air: true}, within: 1}, {at: 0.4, do: "expect_deck", deck: 3, match: {bpm: {near: 999}}, within: 0.3},
    {at: 0.5, do: "unit_thing"}]};
  check("a scenario starts", (await post("api/scenario", JSON.stringify(scenario))).status === 200);
  check("only one at a time", (await post("api/scenario", JSON.stringify(scenario))).status === 409);
  await sleep(2);
  const done = await get("api/scenario");
  check("it ended", !done.running && done.results.length === 6, done);
  check("what failed", done.failed === 2 && done.results[4].ok === false && /bpm is/.test(done.results[4].message) && /needs a device under test/.test(done.results[5].message), done.results);
  check("one that needs a unit is skipped", (await post("api/scenario", JSON.stringify({name: "s", requires: ["unit"], steps: []}))).status === 200
    && /demo has none/.test((await get("api/scenario")).skipped || ""));
  check("a bad scenario", (await post("api/scenario", "{nope")).status === 400);

  // the stream
  const seen = {};
  const source = bench.eventSource("api/stream");
  for (const type of ["state", "event", "scenario"]) source.addEventListener(type, (e) => { seen[type] = JSON.parse(e.data); });
  await sleep(0.5);
  source.close();
  check("the stream sends state, events and the scenario", seen.state && seen.state.decks && seen.event && seen.scenario, Object.keys(seen));

  await post("api/events/clear");
  check("events cleared", (await get("api/events?since=0")).length === 0);
  console.log(failures ? failures + " failed" : "ok");
  process.exit(failures ? 1 : 0);
})();
