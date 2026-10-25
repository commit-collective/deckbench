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

// the waveform of a deck's file: a shape for each run of beats, from where they are in the file, between values in proportion
{
  const paths = [];
  const g = {fillStyle: "", globalAlpha: 1, pts: null,
    beginPath() { this.pts = []; }, moveTo(px, y) { this.pts.push([px, y]); }, lineTo(px, y) { this.pts.push([px, y]); },
    closePath() {}, fill() { paths.push({pts: this.pts, alpha: this.globalAlpha}); }};
  const wave = {peaks: new Array(1000).fill(0).map((_, i) => (i < 500 ? 80 : 20)), rate: 100, offset: 0, bpm: 120};   // 10 s: loud for the first 5
  const x = (dt) => 100 + dt * 50;                                                                              // 25 px a beat at 120 BPM
  // beats 0 and 1 follow each other (one run), beat 10 and then 22 do not (a run each)
  Strip.waveform(g, wave, [{dt: 0, at: 0}, {dt: 0.5, at: 1}, {dt: 5.0, at: 10}, {dt: 8.0, at: 22}], x, 25, 600, 40, "#fff");
  check("a shape for each run of beats", paths.length === 3, paths.length);
  const top = (path, px) => 20 - path.pts.find((q) => q[0] === px)[1];                 // the height above the middle at a pixel
  check("a run of two beats is one shape over 50 pixels", paths[0].pts[0][0] === 100 && paths[0].pts.some((q) => q[0] === 150), paths[0].pts.slice(0, 2));
  check("loud where the file is loud, and quiet where it is not", top(paths[0], 120) > 4 * top(paths[1], 360), [top(paths[0], 120), top(paths[1], 360)]);
  const at120 = paths[0].pts.filter((q) => q[0] === 120).map((q) => q[1]);                  // its top and its bottom at a pixel
  check("mirrored round the middle", at120.length >= 2 && near(Math.min(...at120) + Math.max(...at120), 40), at120);
  check("and faint, behind the grid", paths.every((p) => p.alpha < 0.5));
  check("nothing past the file's end (beat 22 is 11 s in)", paths[2].pts.every((q) => Math.abs(q[1] - 20) < 0.5), paths[2].pts.slice(0, 3));
  // smooth: moving the strip a fraction of a pixel changes the height at a pixel a little, not by a jump
  const heights = [0, 0.1, 0.2, 0.3, 0.4, 0.5].map((shift) => {
    paths.length = 0;
    Strip.waveform(g, {peaks: Strip.smooth(new Array(400).fill(0).map((_, i) => (i % 7 < 2 ? 90 : 10))), rate: 100, offset: 0, bpm: 120},
                   [{dt: 0, at: 0}, {dt: 0.5, at: 1}], (dt) => 100 + dt * 50 + shift, 25, 600, 40, "#fff");
    return top(paths[0], 120);
  });
  const steps = heights.slice(1).map((v, i) => Math.abs(v - heights[i]));
  check("moving a tenth of a pixel changes it by a little, not a jump", Math.max(...steps) < 2.5, steps);
  paths.length = 0;
  Strip.waveform(g, {peaks: [], rate: 100, offset: 0, bpm: 120}, [{dt: 0, at: 0}], x, 25, 600, 40, "#fff");
  Strip.waveform(g, {peaks: [50], rate: 100, offset: 0, bpm: 0}, [{dt: 0, at: 0}], x, 25, 600, 40, "#fff");
  check("no peaks, or no tempo, draws nothing", paths.length === 0);
  const smooth = Strip.smooth([0, 100, 0, 0]);
  check("smoothing spreads a peak to its neighbours", near(smooth[0], 25) && near(smooth[1], 50) && near(smooth[2], 25) && near(smooth[3], 0), smooth);
}

// the clock: samples that are late by different delays do not move the strips
{
  let seed = 7;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const truth = 1000, floor = 0.004;                                  // the bench is 1000 s ahead, and the quickest message takes 4 ms
  let est = null, rawSteps = [], steps = [], prevRaw = null;
  for (let i = 0; i < 300; i++) {
    const sample = truth - (floor + (rnd() < 0.2 ? rnd() * 0.06 : rnd() * 0.01));      // a few messages are slow
    if (prevRaw != null) rawSteps.push(Math.abs(sample - prevRaw));
    prevRaw = sample;
    const next = Strip.followClock(est, sample);
    if (est != null && i > 20) steps.push(Math.abs(next - est));
    est = next;
  }
  check("the estimate is near the quickest message", Math.abs(est - (truth - floor)) < 0.004, est - truth);
  check("and it moves less than the samples do", Math.max(...steps) < Math.max(...rawSteps) / 3, [Math.max(...steps), Math.max(...rawSteps)]);
  check("a new clock (the bench started again) is taken at once", Strip.followClock(1000, 5) === 5 && Strip.followClock(null, 7) === 7);
}

console.log(failures ? failures + " failed" : "ok");
process.exit(failures ? 1 : 0);
