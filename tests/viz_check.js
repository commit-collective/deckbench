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

// The device's reported bar, not its absolute track count, drives comparison lamps and grid accents.
const shifted = {phase: [100, 9, 120], bar_phase: [100, 0, 120]};
check("reported downbeat overrides a track count one beat ahead", Strip.beatOf(shifted, 100, 0) === 1);
check("reported bar advances on the browser clock", Strip.beatOf(shifted, 100.5, 0) === 2);
check("negative positions still have a valid beat", Strip.beatOf({phase: [100, -1, 120]}, 100, 0) === 4);
Strip.observe("shifted", shifted.phase, 0, shifted.bar_phase);
const shiftedGrid = Strip.layoutDevice("shifted", {status: null}, 100);
check("passive grid uses the reported downbeat", shiftedGrid.ticks[0].beat === 1 && shiftedGrid.ticks[0].at === 9);
check("future grid follows the reported bar", shiftedGrid.ticks[1].beat === 2);
const physicalMaster = {...shifted, number: 1, online: true, status: {master: true}};
const mixed = {decks: {}, protocols: {prolink: {devices: [physicalMaster]}}};
check("master reference can come from a physical player", Strip.master(mixed).number === 1);

// A bench deck on a real track's grid that starts on beat 3 of a bar (bar_shift 2): its bars are the grid's.
const onGrid = {on: true, phase: [100, 0, 120], bar_shift: 2, loop: 0, loop_from: 0};
check("a shifted deck's first beat is beat 3", Strip.beatOf(onGrid, 100, 0) === 3);
const gridTicks = Strip.layout(onGrid, 100, 0).ticks.filter((t) => t.at >= 0 && t.at <= 2);
check("its ticks are counted from the grid", gridTicks.map((t) => t.beat).join() === "3,4,1", gridTicks.map((t) => t.beat));
const gridStopped = Strip.layout({on: true, at: 0, bpm: 120, bar_shift: 2}, 100, 0).ticks.filter((t) => t.at >= 0 && t.at <= 2);
check("and stopped too", gridStopped.map((t) => t.beat).join() === "3,4,1", gridStopped.map((t) => t.beat));
mixed.decks[3] = {on: true, master: true, phase: [100, 0, 120]};
check("virtual master takes over the reference", String(Strip.master(mixed).number) === "3");
mixed.decks[3].on = false;
physicalMaster.online = false;
check("offline masters leave the reference dark", Strip.master(mixed) === null);

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

// just started: the track's beats before the first one told of, so the past is not empty
Strip.observe("started", [200 + offset, 40, 120], offset);
const started = Strip.layoutDevice("started", {status: {loop: false, track_beat: 41}}, 200.1).ticks.filter((t) => t.dt < 0);
check("the beats before PLAY are drawn", started.length >= 4 && started.map((t) => t.at).slice(-4).join() === "37,38,39,40"
  && near(started[started.length - 2].dt, -0.6), started.map((t) => [t.at, t.dt]));

// played again soon after a jump back (CUE, then PLAY): the past is the new place's, not the beats before the jump
for (const [t, pos] of [[300, 60], [300.5, 61], [301, 62], [302, 10]]) Strip.observe("jumped", [t + offset, pos, 120], offset);
const jumped = Strip.layoutDevice("jumped", {status: {loop: false, track_beat: 11}}, 302.1).ticks.filter((t) => t.dt < 0);
check("the past after a jump is the new place's", jumped.length >= 5 && jumped.every((t, i) => t.at === 10 - (jumped.length - 1 - i)), jumped.map((t) => t.at));

// A two-beat loop on beats 93 and 94 (places 92, 93), as a CDJ-2000NXS2 played it: the beat it jumps back to is a bar's
// first ahead of the playhead too, a beat whose packet did not come is drawn, and before the first jump back what comes
// is not known
const twoLoop = {status: {loop: true, track_beat: 94}, online: true};
[[92, 1], [93, 2], [92, 1], [93, 2], [92, 1]].forEach(([pos, bar], i) => {               // the second 92 never came
  if (i !== 2) Strip.observe("two", [400 + i * 0.47 + offset, pos, 127.7], offset, [400 + i * 0.47 + offset, bar - 1, 127.7]);
});
const two = Strip.layoutDevice("two", twoLoop, 402.0).ticks;
check("a two-beat loop's first beat is a bar's first ahead too", two.filter((t) => t.at === 92).every((t) => t.beat === 1)
  && two.filter((t) => t.at === 93).every((t) => t.beat === 2), two.map((t) => [t.at, t.beat]));
const twoPast = two.filter((t) => t.dt < 0).map((t) => t.at);
check("a beat whose packet did not come is drawn", twoPast.slice(-5).join() === "92,93,92,93,92", twoPast);
Strip.observe("fresh", [500 + offset, 40, 120], offset);
const fresh = Strip.layoutDevice("fresh", {status: {loop: true, track_beat: 41}, online: true}, 500.1);
const freshAt = fresh.ticks.map((t) => t.at);
check("before its first jump back a loop is drawn as the player plays, its past too", fresh.loop === 0
  && freshAt.every((at, i) => !i || at === freshAt[i - 1] + 1) && fresh.ticks.filter((t) => t.dt < 0).length >= 4
  && fresh.ticks.every((t) => !t.inLoop), freshAt);

// An eight-beat loop outlasts the visible history. Its tint must survive at every beat, including the wrap.
const longLoop = {status: {loop: true, source: 1, slot: 3, rbid: 10}};
for (let k = 0; k <= 24; k++) {
  const t = 300 + k * 0.5;
  Strip.observe("eight", [t, 16 + k % 8, 120], 0);
  const p = Strip.layoutDevice("eight", longLoop, t + 0.1);
  if (k >= 8) {
    check("eight-beat loop keeps its length at sample " + k, p.loop === 8, p.loop);
    check("eight-beat loop stays tinted at sample " + k, p.ticks.every((tick) => tick.inLoop));
    check("predicted wrap is at the loop's first beat at sample " + k,
          p.ticks.filter((tick) => tick.wrap).every((tick) => tick.at === 16));
  }
}
// Remembered bounds also survive eviction from the bounded observation buffer.
Strip.history.eight = Strip.history.eight.slice(-3);
plan = Strip.layoutDevice("eight", longLoop, 312.1);
check("loop bounds survive loss of the original wrap observation", plan.loop === 8);
longLoop.status.loop = false;
plan = Strip.layoutDevice("eight", longLoop, 312.1);
check("leaving a loop clears its tint and length", plan.loop === 0 && !plan.ticks.some((tick) => tick.inLoop));
longLoop.status.loop = true;
check("re-entering a loop does not reuse old bounds", Strip.layoutDevice("eight", longLoop, 312.1).loop === 0);
Strip.observe("eight", [312.5, 17, 120], 0);
Strip.layoutDevice("eight", longLoop, 312.6);
Strip.observe("eight", [313, 16, 120], 0);
check("a changed loop learns its new length", Strip.layoutDevice("eight", longLoop, 313.1).loop === 2);
longLoop.status.rbid = 11;
check("a new track clears inferred loop bounds", Strip.layoutDevice("eight", longLoop, 313.1).loop === 0);
Strip.observe("repeat", [400, 16, 120], 0);
Strip.observe("repeat", [400.5, 16, 120], 0);
check("a repeated position is not a one-beat loop", Strip.layoutDevice("repeat", device, 400.6).loop === 0);

// Status arrives after the wrap beat and corrects its old extrapolated track count.
for (let k = 0; k < 8; k++) Strip.observe("late-status", [500 + k * 0.5, 16 + k, 120], 0);
Strip.observe("late-status", [504, 24, 120], 0);
Strip.layoutDevice("late-status", device, 504.05);
Strip.observe("late-status", [504, 16, 120], 0);
plan = Strip.layoutDevice("late-status", device, 504.15);
check("a corrected beat replaces its provisional observation", Strip.history["late-status"].length === 9);
check("late status learns eight beats rather than nine", plan.loop === 8, plan.loop);
check("the wrap is shown at the original beat, not one beat later",
      plan.ticks.some((t) => near(t.dt, -0.15) && t.at === 16 && t.wrap && t.inLoop));
for (let k = 1; k < 8; k++) Strip.observe("late-status", [504 + k * 0.5, 16 + k, 120], 0);
Strip.observe("late-status", [508, 24, 120], 0);
plan = Strip.layoutDevice("late-status", device, 508.05);
check("known bounds cover the wrap before its status arrives", plan.loop === 8 && plan.ticks.every((t) => t.inLoop));
check("the provisional end beat is drawn at the known loop start",
      plan.ticks.some((t) => near(t.dt, -0.05) && t.at === 16 && t.wrap));

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
  // the answer to a click can come 100 ms quicker than the stream: the strip must not jump forward by it
  check("a quicker message moves the clock by 5 ms at most", near(Strip.followClock(1000, 1000.1), 1000.005) && near(Strip.followClock(1000, 1000.004), 1000.002));
  check("and a slower one hardly at all", Math.abs(Strip.followClock(1000, 999.9) - 1000) <= 0.002 + 1e-9);
}

// a loop that is set is seen coming, and when the deck is stopped
{
  const ahead = Strip.layout({phase: [1000, 6.6, 120], loop: 4, loop_from: 8}, 0, 1000);
  check("a loop ahead of the playhead is marked ahead: its beats, where it goes back", ahead.ticks.filter((t) => t.inLoop).map((t) => t.at).slice(0, 4).join() === "8,9,10,11"
    && ahead.ticks.some((t) => t.wrap), ahead.ticks.map((t) => t.at + (t.inLoop ? "L" : "") + (t.wrap ? "W" : "")));
  check("and the strip says it is coming", near(ahead.loopAhead, 1.4, 1e-6), ahead.loopAhead);
  const inside = Strip.layout({phase: [1000, 9.5, 120], loop: 4, loop_from: 8}, 0, 1000);
  check("inside it, nothing is ahead", inside.loopAhead === 0);
  const stopped = Strip.layout({at: 6.0, bpm: 120, loop: 4, loop_from: 8}, 0, 1000);
  check("a stopped deck with a loop set shows it", stopped.stopped && stopped.loop === 4 && stopped.loopAhead === 2
    && stopped.ticks.filter((t) => t.inLoop).length > 4 && stopped.ticks.some((t) => t.wrap));
  const behind = Strip.layout({phase: [1000, 25.0, 120], loop: 4, loop_from: 20}, 0, 1000);
  check("a loop the deck was moved past is behind it: marked, with no jump back", behind.ticks.filter((t) => t.inLoop).every((t) => t.at >= 20 && t.at < 24)
    && !behind.ticks.some((t) => t.wrap), behind.ticks.map((t) => t.at + (t.inLoop ? "L" : "") + (t.wrap ? "W" : "")));
  const plain = Strip.layout({at: 6.0, bpm: 120, loop: 0, loop_from: 0}, 0, 1000);
  check("a stopped deck without one shows none", !plain.ticks.some((t) => t.inLoop || t.wrap) && plain.loopAhead === 0);
}

// a real player's beats come when they arrive: two close together must not hide every number of the strip
{
  sandbox.getComputedStyle = () => ({getPropertyValue: () => ""});
  let texts = 0;
  const g = new Proxy({}, {get: (o, k) => k === "fillText" ? () => { texts++; } : k === "measureText" ? () => ({width: 10}) : k in o ? o[k] : () => {},
                           set: (o, k, value) => { o[k] = value; return true; }});
  const canvas = {clientWidth: 400, clientHeight: 60, width: 0, height: 0, getContext: () => g};
  for (const [t, pos] of [[49.0, 1], [49.1, 2], [49.5, 3], [50.0, 4]]) Strip.observe("jitter", [t, pos, 120], 0);
  Strip.draw(canvas, Strip.layoutDevice("jitter", {status: null}, 50.0), {bars: true});
  check("numbers stay when two beats come close together", texts > 5, texts);
}

// a real player's track: its grid maps beats to seconds with the beats' own times, not one tempo for the whole track
{
  sandbox.atob = atob;
  const b64 = (bytes) => Buffer.from(bytes).toString("base64");
  const detail = [];
  for (let i = 0; i < 1500; i++) detail.push(i % 101);                      // ten seconds at 150 a second, heights 0 to 100
  const over = [];
  for (let i = 0; i < 1200; i++) over.push(100);
  const grid = [[1000, 1, 12000], [1500, 2, 12000], [2000, 3, 12000], [3000, 4, 6000], [4000, 1, 6000]];
  const wave = Strip.realWave({key: "k", rate: 150, detail: b64(detail), overview: b64(over), grid});
  check("the detail's heights", wave.peaks.length === 1500 && Math.abs(wave.duration - 10) < 1e-9);
  check("the overview's heights", wave.overview.length === 1200 && Math.abs(wave.overview[0] - 100) < 1e-9);
  check("a beat is its grid time", near(wave.beatTime(0), 1.0) && near(wave.beatTime(3), 3.0) && near(wave.beatTime(4), 4.0));
  check("between beats, in proportion to their own interval", near(wave.beatTime(2.5), 2.5) && near(wave.beatTime(0.5), 1.25));
  check("past the ends, the last interval", near(wave.beatTime(5), 5.0) && near(wave.beatTime(-1), 0.5));
  check("the inverse", [0, 0.5, 2.5, 3.25, 4.5].every((b) => near(wave.beatOf(wave.beatTime(b)), b)));

  // A CDJ-3000's loop, from its status: beats 1 to 3 of this grid (1500 to 3000 ms), two beats.
  const cdj3000 = {loop: true, loop_ms: [1500.4, 3000.2], loop_beats: 2};
  const found = Strip.deviceLoop(cdj3000, wave);
  check("a CDJ-3000's loop is placed on the grid", found && found.from === 1 && found.length === 2, found);
  check("its length from its ends when it gives no beats", Strip.deviceLoop({...cdj3000, loop_beats: 0}, wave).length === 2);
  check("no loop when the player does not loop, or under a beat",
    Strip.deviceLoop({...cdj3000, loop: false}, wave) === null &&
    Strip.deviceLoop({loop: true, loop_ms: [1500, 1600], loop_beats: 0}, wave) === null &&
    Strip.deviceLoop({loop: true}, wave) === null && Strip.deviceLoop(cdj3000, null) === null);
  const inLoop = Strip.layout({at: 2.5, bpm: 120, loop: found.length, loop_from: found.from}, 100, 0);
  check("drawn as a loop", inLoop.loop === 2 && inLoop.ticks.some((t) => t.inLoop) && inLoop.ticks.some((t) => t.wrap) &&
    inLoop.ticks.filter((t) => t.dt > 0).every((t) => t.at >= 1 && t.at < 3), inLoop.ticks.map((t) => t.at));

  // where it is: a CDJ-3000's precise position, else the last beat and the tempo since (an estimate), paused the beat it waits on
  const precise = Strip.trackPlace({status: {play: true}, precise: {at: 100, position_ms: 2000, pitch: 10}}, wave, 100.5);
  check("precise position, at its pitch", near(precise.seconds, 2.55) && !precise.estimated, precise);
  const cueHeld = Strip.trackPlace({status: {play: false, state: "cue playing"}, precise: {at: 100, position_ms: 2000}}, wave, 100.5);
  check("held on CUE it runs on between positions, its play flag off", near(cueHeld.seconds, 2.5), cueHeld);
  const scratched = Strip.trackPlace({status: {play: false, state: "cue scratching"}, precise: {at: 100, position_ms: 2000}}, wave, 100.5);
  check("scratched it stays where the jog put it", near(scratched.seconds, 2.0), scratched);
  const stale = Strip.trackPlace({status: {play: true, track_beat: 2}, precise: {at: 90, position_ms: 2000}, phase: [100, 1, 120]}, wave, 100.25);
  check("else from the beat, estimated", near(stale.seconds, wave.beatTime(1.5)) && stale.estimated, stale);
  const paused = Strip.trackPlace({status: {play: false, track_beat: 3}}, wave, 100);
  check("paused: the beat after the reported one, where it waits", near(paused.seconds, 3.0) && paused.estimated);
  const firstBeat = Strip.trackPlace({status: {play: false, state: "cued", track_beat: 1, bar: 1, stands: 0}}, wave, 100);
  check("cued on the first beat: where the bench says it stands", near(firstBeat.seconds, wave.beatTime(0)), firstBeat);
  const held = Strip.trackPlace({status: {play: false, track_beat: 3}, held: 2.5}, wave, 100);
  check("paused where the bench followed it", near(held.seconds, wave.beatTime(2.5)) && !held.estimated, held);
  check("nothing known", Strip.trackPlace({status: null}, wave, 100) === null);

  // a bench deck's waveform is drawn as it was: one tempo, linear over each run of beats
  const tops = [];
  const g = new Proxy({}, {get: (o, k) => k === "lineTo" ? (px, y) => tops.push([px, y]) : k in o ? o[k] : () => {},
                           set: (o, k, value) => { o[k] = value; return true; }});
  const peaks = Array.from({length: 2000}, (_, i) => (i * 7) % 100), sim = {peaks, rate: 100, offset: 0.2, bpm: 120};
  const ticks = [0, 1, 2, 3].map((k) => ({dt: k * 0.5, at: 4 + k})), x = (dt) => 40 + dt * 50;
  Strip.waveform(g, sim, ticks, x, 25, 600, 40, "#fff");
  const level = (i) => { const k = Math.floor(i); return peaks[k] + (peaks[Math.min(k + 1, peaks.length - 1)] - peaks[k]) * (i - k); };
  const x0 = x(0), x1 = x(1.5) + 25, top = tops.slice(0, tops.length / 2);
  check("a bench deck's waveform is unchanged", top.every(([px, y]) => px < x0 ||
    Math.abs(20 - y - Math.max(0.4, level((0.2 + 4 * 0.5 + (px - x0) / (x1 - x0) * 2.0) * 100) * 40 * 0.42 / 100)) < 1e-6), top.slice(0, 3));
}

console.log(failures ? failures + " failed" : "ok");
process.exit(failures ? 1 : 0);
