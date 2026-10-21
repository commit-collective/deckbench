// Checks what the strips draw (deckbench/ui/viz.js): the ticks of a bench deck, a stopped deck, a looping one and a device on the link.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sandbox = {window: {}, document: {}, setInterval, clearInterval, Math, Number, Array, Object, Date, console, String, Set, Map};
vm.createContext(sandbox);
for (const file of ["sound.js", "viz.js"]) vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "deckbench", "ui", file), "utf8"), sandbox);
vm.runInContext("globalThis.Strip = Strip;", sandbox);
const Strip = sandbox.Strip;

let failures = 0;
function check(what, ok, detail) {
  if (!ok) { failures++; console.log("FAIL: " + what + (detail === undefined ? "" : " (" + JSON.stringify(detail) + ")")); }
}
const near = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;

// a bench deck: 120 BPM, at beat 6 at the bench's time 1000 (the page is 1000 s behind the bench: offset 1000), now = 0.25 s later
const now = 0.25, offset = 1000;
let plan = Strip.layout({phase: [1000, 6.0, 120], loop: 0, loop_from: 0}, now, offset);
const next = plan.ticks.find((t) => t.dt > 0), past = plan.ticks.filter((t) => t.dt < 0);
check("a beat every half second, on one scale", plan.ticks.slice(1).every((t, i) => near(t.dt - plan.ticks[i].dt, 0.5)));
check("the next beat is 0.25 s ahead, and it is beat 7 of the track", near(next.dt, 0.25) && next.at === 7, next);
check("its place in the bar", next.beat === 4 && plan.ticks.find((t) => t.at === 8).beat === 1);
check("the window: before the playhead and ahead", plan.ticks[0].dt >= -Strip.BEHIND - 1 - 0.5 && plan.ticks[plan.ticks.length - 1].dt <= Strip.AHEAD + 1.5);
check("it is not stopped, and has no loop", !plan.stopped && plan.loop === 0 && !plan.ticks.some((t) => t.inLoop || t.wrap));

// two decks synced to one grid have their ticks at the same moments
const master = Strip.layout({phase: [1000, 6.0, 120]}, now, offset), synced = Strip.layout({phase: [1000, 6.0, 120]}, now, offset);
check("synced decks line up", master.ticks.every((t, i) => near(t.dt, synced.ticks[i].dt)));

// a loop of 4 beats from beat 8: the beats before it are not in it, then it goes round, with a mark where it goes back
plan = Strip.layout({phase: [1000, 6.0, 120], loop: 4, loop_from: 8}, now, offset);
const ats = plan.ticks.map((t) => t.at);
check("the track beats go back at the loop's end", ats.join(",").includes("8,9,10,11,8,9,10,11"), ats);
check("the loop is tinted from its start", plan.ticks.filter((t) => t.inLoop).every((t) => t.dt >= 0.5) && plan.ticks.some((t) => t.inLoop));
const wraps = plan.ticks.filter((t) => t.wrap);
check("and marked where it goes back, every 4 beats", wraps.length >= 2 && near(wraps[1].dt - wraps[0].dt, 2.0) && wraps.every((t) => t.at === 8), wraps.map((t) => t.dt));
check("it says how long the loop is", plan.loop === 4);

// a stopped deck: its beats around its place, the way they would go
plan = Strip.layout({phase: null, at: 9.5, bpm: 120}, now, offset);
check("a stopped deck is drawn where it stands", plan.stopped && plan.ticks.some((t) => t.at === 10 && near(t.dt, 0.25)) && plan.ticks.some((t) => t.at === 9 && near(t.dt, -0.25)), plan.ticks.slice(0, 3));
check("no place, no ticks", Strip.layout({phase: null}, now, offset).ticks.length === 0);

// a device on the link: beats it was told of, in the page's time. Looping 17 to 20 (places 16 to 19), a beat every half second
const device = {status: {loop: true}};
let t0 = 100;
for (const pos of [16, 17, 18, 19, 16, 17]) { Strip.observe("a", [t0 + offset, pos, 120], offset); t0 += 0.5; }   // the beats came at 100, 100.5 ...
Strip.observe("a", [t0 - 0.5 + offset, 17, 120], offset);                                                          // the same again: nothing new
const nowDev = 102.9;
plan = Strip.layoutDevice("a", device, nowDev);
const told = plan.ticks.filter((t) => t.dt < 0.01);
check("the beats it was told of", told.map((t) => t.at).join() === "16,17,18,19,16,17", told.map((t) => t.at));
check("the same beat told twice is one", Strip.history.a.length === 6, Strip.history.a.length);
check("a jump back is a loop", plan.ticks.filter((t) => t.wrap && t.dt < 0.01).length === 1 && plan.loop === 4, plan.ticks.filter((t) => t.wrap).map((t) => t.dt));
const future = plan.ticks.filter((t) => t.dt > 0.01).map((t) => t.at);
check("and it goes on going back, as it has", future.slice(0, 6).join() === "18,19,16,17,18,19", future.slice(0, 6));
check("the future is on its tempo", near(plan.ticks.filter((t) => t.dt > 0.01)[0].dt, 102.5 + 0.5 - nowDev + 0 - 0, 0.6));

// a device that does not loop is not told to
Strip.observe("b", [200 + offset, 4, 100], offset); Strip.observe("b", [200.6 + offset, 5, 100], offset);
plan = Strip.layoutDevice("b", {status: {loop: false}}, 200.7);
check("a device that plays on", !plan.looping && plan.ticks.every((t) => !t.wrap && !t.inLoop) && plan.ticks[plan.ticks.length - 1].at > 8, plan.ticks.map((t) => t.at));
check("nothing heard, nothing drawn", Strip.layoutDevice("c", {status: null}, 5).ticks.length === 0);

console.log(failures ? failures + " failed" : "ok");
process.exit(failures ? 1 : 0);
