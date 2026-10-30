// Exercise the app's actual packet controls with a small DOM test double.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const nodes = new Map(), timers = [];
let exported, selected = false;
function node() {
  return {children: [], events: {}, scrollTop: 12, clientHeight: 100, scrollHeight: 1000,
    append(...children) { this.children.push(...children); },
    addEventListener(name, fn) { this.events[name] = fn; },
    setAttribute() {},
    set textContent(value) { this.children = []; this.text = value; },
    get textContent() { return this.text; }};
}
const $ = id => {
  if (!nodes.has(id)) nodes.set(id, node());
  return nodes.get(id);
};
const context = vm.createContext({$, window: {getSelection: () => ({isCollapsed: !selected})},
  h: (tag, attrs, ...children) => ({tag, attrs, children}),
  setTimeout: fn => { timers.push(fn); return timers.length; },
  download: (name, text) => { exported = JSON.parse(text); }, stamp: () => "test"});
const script = fs.readFileSync(path.join(__dirname, "..", "deckbench", "ui", "app.js"), "utf8");
vm.runInContext(script.split("/* ---- the link log ---- */")[1].split("/* ---- sound options ---- */")[0], context);
const run = code => vm.runInContext(code, context);
const flush = () => { while (timers.length) timers.shift()(); };
run('P.items = [{n: 1, t: 1, src: "test", kind: "on air", text: "one", hex: "00"}]; drawPackets();');
flush();
const original = $("pktlog").children[0];
$("pktfollow").events.click();
run('P.items = [{n: 2, t: 2, src: "test", kind: "on air", text: "two", hex: "01"}]; drawPackets();');
flush();
assert.strictEqual($("pktlog").children[0], original, "Follow off must preserve selected DOM nodes even after buffer eviction");
$("pktexport").events.click();
assert.strictEqual(exported[0].n, 1, "Export must match the held view");
selected = true;
original.attrs.onclick();
assert.strictEqual(run("P.open.size"), 0, "Selecting text must not toggle packet expansion");
selected = false;
// A queued poll must not redraw after the user switches Follow off.
$("pktfollow").events.click();
$("pktfollow").events.click();
flush();
assert.strictEqual($("pktlog").children[0], original);
$("pktfollow").events.click();
flush();
assert.notStrictEqual($("pktlog").children[0], original);
assert.strictEqual($("pktlog").children[0].children[4].children[0], "two");
$("pktpause").events.click();
const paused = $("pktlog").children[0];
run("drawPackets();");
flush();
assert.strictEqual($("pktlog").children[0], paused, "Pause must hold an in-flight poll too");
console.log("ok");
