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
});
const script = fs.readFileSync(path.join(__dirname, "..", "deckbench", "ui", "app.js"), "utf8");
vm.runInContext("function buildDevice(d) {" + script.split("function buildDevice(d) {")[1].split("function renderDevices()")[0], context);
const card = context.buildDevice({ip: "127.0.0.9", kind: "player", model: "CDJ-2000NXS2"});
const find = (node, predicate) => predicate(node) ? node : (node.children || []).map(child => find(child, predicate)).find(Boolean);
const control = find(card, node => node.attrs && node.attrs.class === "player-control");
assert.strictEqual(control.attrs.hidden, true, "Controls stay hidden until the backend reports eligibility");
const arm = find(control, node => node.tag === "input");
assert(find(control, node => node.tag === "p" && node.children[0].includes("not a paused track")), "Explain the observed fader-stop restriction");
assert.strictEqual(calls.length, 0, "Building controls must never send a command");
arm.attrs.onchange({target: {checked: true, dataset: {number: "2"}}});
assert.strictEqual(calls.pop(), "api/player/127.0.0.9/arm/1?number=2");
for (const [label, command] of [["Start from cue", "start"], ["Stop / return to cue", "stop"]]) {
  const button = find(control, node => node.tag === "button" && node.children[0] === label);
  assert.strictEqual(button.attrs.disabled, true, "Commands start disabled");
  button.attrs.onclick({currentTarget: {dataset: {number: "2"}}});
  assert.strictEqual(calls.pop(), "api/player/127.0.0.9/command/" + command + "?number=2");
}
const mixer = context.buildDevice({ip: "127.0.0.33", kind: "mixer"});
assert.strictEqual(find(mixer, node => node.attrs && node.attrs.class === "player-control"), undefined);
console.log("ok");
