// Exercise the actual discovered-player controls without sending packets.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const calls = [];
const context = vm.createContext({
  h: (tag, attrs, ...children) => ({tag, attrs, children: children.flat().filter(Boolean)}),
  devId: ip => ip, beatIndicators: () => null,
  act: url => calls.push(url),
  api: url => { calls.push(url); return Promise.resolve({}); }, toast: () => {},
  buildPlayerLoad: () => null,
});
const script = fs.readFileSync(path.join(__dirname, "..", "deckbench", "ui", "app.js"), "utf8");
vm.runInContext("function playerCommand(" + script.split("function playerCommand(")[1].split("function buildPlayerLoad")[0], context);
vm.runInContext("function buildDevice(d) {" + script.split("function buildDevice(d) {")[1].split("function renderDevices()")[0], context);
const card = context.buildDevice({ip: "127.0.0.9", kind: "player", model: "CDJ-2000NXS2"});
const find = (node, predicate) => predicate(node) ? node : (node.children || []).map(child => find(child, predicate)).find(Boolean);
const control = find(card, node => node.attrs && node.attrs.class === "player-control");
assert.strictEqual(control.attrs.hidden, true, "Controls stay hidden until the backend reports eligibility");
const arm = find(control, node => node.tag === "input");
const identity = find(card, node => node.tag === "details" && node.attrs.class === "deck-id");
assert(identity, "Player identity can expand with native touch and keyboard controls");
assert(find(identity, node => node.tag === "summary" && node.attrs.title), "Identity has a full-value tooltip");
assert(find(control, node => node.tag === "p" && node.children[0] === "Fader start: Start only works at cue. Stop returns playback to cue and does nothing while paused."), "Explain the observed transport restrictions");
assert.strictEqual(calls.length, 0, "Building controls must never send a command");
arm.attrs.onchange({target: {checked: true, dataset: {number: "2"}}});
assert.strictEqual(calls.pop(), "api/player/127.0.0.9/arm/1?number=2");
for (const [label, command] of [["Start cued track", "start"], ["Stop playing track", "stop"]]) {
  const button = find(control, node => node.tag === "button" && node.children[0] === label);
  assert.strictEqual(button.attrs.disabled, true, "Commands start disabled");
  button.attrs.onclick({currentTarget: {dataset: {number: "2"}}});
  assert.strictEqual(calls.pop(), "api/player/127.0.0.9/command/" + command + "?number=2");
}
// the switches, as a bench deck's: SYNC asks for the opposite of what it shows
const switches = find(card, node => node.attrs && node.attrs.class === "switches player-switches");
assert.strictEqual(switches.attrs.hidden, true, "Switches stay hidden until the backend reports eligibility");
for (const [label, command, pressed] of [["PLAY/PAUSE", "play-pause", "false"], ["SYNC", "sync-on", "false"],
  ["SYNC", "sync-off", "true"], ["MASTER", "master", "false"]]) {
  const button = find(switches, node => node.tag === "button" && node.children[0] === label);
  button.attrs.onclick({currentTarget: {dataset: {number: "2"}, getAttribute: () => pressed}});
  assert.strictEqual(calls.pop(), "api/player/127.0.0.9/command/" + command + "?number=2");
}
const cue = find(switches, node => node.tag === "button" && node.children[0] === "CUE");
assert(cue.attrs.onpointerdown && cue.attrs.onpointerup && cue.attrs.onkeyup, "CUE follows the finger");
const mixer = context.buildDevice({ip: "127.0.0.33", kind: "mixer"});
assert.strictEqual(find(mixer, node => node.attrs && node.attrs.class === "player-control"), undefined);
console.log("ok");
