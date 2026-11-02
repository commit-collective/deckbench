// Exercise session transitions and reconnect replay using the app's real code.
"use strict";
const assert = require("assert"), fs = require("fs"), path = require("path"), vm = require("vm");
const S = {state: null, events: [], connected: false};
let handlers;
const context = vm.createContext({S, Date, JSON, window: {EventSource: true},
  Strip: {followClock: () => 0}, render() {}, renderChips() {}, renderScenario() {},
  clearEvents: () => { S.events = []; }, addEvent: e => S.events.push(e),
  transport: {eventSource() { handlers = {}; return {addEventListener: (kind, fn) => { handlers[kind] = fn; }}; }}});
const script = fs.readFileSync(path.join(__dirname, "..", "deckbench", "ui", "app.js"), "utf8");
vm.runInContext("function apply(state) {" + script.split("function apply(state) {")[1].split("/* ---- the top bar ---- */")[0], context);
const state = (session, generation) => ({now: 0, bench: {session, event_generation: generation}});
context.apply(state("first", 0));
S.events.push({n: 0});
context.apply(state("first", 0));
assert.strictEqual(S.events.length, 1);
context.apply(state("second", 0));
assert.strictEqual(S.events.length, 0, "Backend restart must clear old events even if numbering has grown");
S.events.push({n: 0});
context.apply(state("second", 1));
assert.strictEqual(S.events.length, 0, "Clear must reset polling clients too");
context.connect();
const event = {data: JSON.stringify({n: 0, session: "second"})};
handlers.event(event);
handlers.cleared();
handlers.event(event);
assert.strictEqual(S.events.length, 1, "Reconnect replay must not duplicate old browser history");
vm.runInContext("function describe(e) {" + script.split("function describe(e) {")[1].split("function drawEvents()")[0], context);
const description = context.describe({n: 1, t: 2, kind: "player_state", session: "hidden", generation: 0, changes: {play: false}});
assert.strictEqual(description, 'changes={"play":false}');
console.log("ok");
