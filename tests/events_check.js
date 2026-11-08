// Exercise session transitions and reconnect replay using the app's real code.
"use strict";
const assert = require("assert"), fs = require("fs"), path = require("path"), vm = require("vm");
const S = {state: null, events: [], connected: false};
let handlers, last;
const context = vm.createContext({S, Date, JSON, window: {EventSource: true},
  Strip: {followClock: () => 0}, render() {}, renderChips() {}, renderScenario() {},
  clearEvents: () => { S.events = []; }, addEvent: e => S.events.push(e),
  transport: {eventSource() { handlers = {}; return last = {addEventListener: (kind, fn) => { handlers[kind] = fn; }, close() { this.closed = true; }}; }}});
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
// a stream the browser closed (a phone that suspended the page) does not retry by itself: the page opens a new one
let scheduled = null;
context.setTimeout = (fn) => { scheduled = fn; return 1; };
context.clearTimeout = () => {};
const closed = last;
closed.readyState = 2;
closed.onerror();
assert.ok(scheduled && !S.connected, "A closed stream must be opened again");
scheduled();
assert.ok(closed.closed && last !== closed, "The new stream replaces the closed one");
handlers.state({data: JSON.stringify(state("second", 1))});
assert.ok(S.connected, "The new stream's state says connected");
vm.runInContext("function describe(e) {" + script.split("function describe(e) {")[1].split("function drawEvents()")[0], context);
const description = context.describe({n: 1, t: 2, kind: "player_state", session: "hidden", generation: 0, changes: {play: false}});
assert.strictEqual(description, 'changes={"play":false}');
console.log("ok");
