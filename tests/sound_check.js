// Checks the timing of the page's sound (deckbench/ui/sound.js): which beats of a deck fall in a time, and which decks are heard.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sandbox = {window: {}, setInterval, clearInterval, Math, Number, Array, Object, Date, console};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "deckbench", "ui", "sound.js"), "utf8") + "\n;globalThis.Sound = Sound;", sandbox);
const Sound = sandbox.Sound;

let failures = 0;
function check(what, ok, detail) {
  if (!ok) { failures++; console.log("FAIL: " + what + (detail === undefined ? "" : " (" + JSON.stringify(detail) + ")")); }
}
const near = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;

// 120 BPM is two beats a second. The bench's clock is 1000 s ahead of the page's (offset 1000). The deck was at beat 2.0 at the bench's time 1000.
const deck = {on: true, play: true, phase: [1000, 2.0, 120], loop: 0, loop_from: 0};
let beats = Sound.beats(deck, 0, 1.2, 1000);
check("two beats a second: beats 2, 3 and 4 within 1.2 s", beats.map((b) => b.k).join() === "2,3,4", beats.map((b) => b.k));
check("the time of a beat is on the page's clock", near(beats[0].time, 0) && near(beats[1].time, 0.5) && near(beats[2].time, 1), beats.map((b) => b.time));
check("the place in the bar", beats.map((b) => b.beat).join() === "3,4,1", beats.map((b) => b.beat));
check("half a beat", near(beats[0].half, 0.25));

beats = Sound.beats(deck, 0.01, 0.49, 1000);
check("no beat between two beats", beats.length === 0, beats);
beats = Sound.beats(deck, 0.5, 0.5, 1000);
check("a beat on the edge counts once", beats.length === 1 && beats[0].k === 3, beats);

check("a deck that does not play has none", Sound.beats({phase: null}, 0, 5, 0).length === 0);
check("a tempo of 0 has none", Sound.beats({phase: [0, 0, 0]}, 0, 5, 0).length === 0);

// beats before the phase began are the same line, going back
beats = Sound.beats(deck, -1.2, -0.4, 1000);
check("before the anchor", beats.map((b) => b.k).join() === "0,1" && beats.map((b) => b.beat).join() === "1,2", beats);

// a loop of 4 beats from beat 4 (the unwrapped line goes on, the place in the bar goes round the loop)
const looped = {on: true, play: true, phase: [1000, 4.0, 120], loop: 4, loop_from: 4};
beats = Sound.beats(looped, 0, 4.2, 1000);
check("in the loop the place goes round it", beats.map((b) => b.k).join() === "4,5,6,7,8,9,10,11,12" && beats.map((b) => b.beat).join() === "1,2,3,4,1,2,3,4,1", beats.map((b) => b.beat));

// who is heard
check("a deck that plays", Sound.audible({on: true, play: true}, false));
check("a stopped deck", !Sound.audible({on: true, play: false}, false));
check("a deck that is off", !Sound.audible({on: false, play: true}, false));
check("a cable pulled", !Sound.audible({on: true, play: true, unplugged: true}, false));
check("with a mixer, off the air", !Sound.audible({on: true, play: true, on_air: false}, true));
check("with a mixer, on the air", Sound.audible({on: true, play: true, on_air: true}, true));
check("with no mixer, on air does not matter", Sound.audible({on: true, play: true, on_air: false}, false));

// the sources of sound: the bench's decks that play, and never a real player on the link
const state = {
  decks: {1: {on: true, play: true, on_air: true, phase: [0, 0, 120]}, 2: {on: true, play: false, on_air: false}, 3: {on: true, play: true, on_air: true, phase: [0, 0, 120]}},
  protocols: {prolink: {mixer: {on: false}, devices: [
    {ip: "10.0.0.5", number: 5, kind: "player", online: true, status: {play: true, on_air: false}, phase: [0, 0, 124]},
    {ip: "10.0.0.6", number: 6, kind: "player", online: true, status: {play: false}, phase: null},
    {ip: "10.0.0.7", number: 7, kind: "player", online: false, status: {play: true, on_air: true}, phase: [0, 0, 124]}]}},
};
const keys = () => Sound.sources(state).map((x) => x.key).join();
check("the bench's decks that play, and not the real player that plays", keys() === "1,3", keys());
check("a deck keeps its number for its voice", Sound.sources(state)[1].number === 3);
state.decks[3].on_air = false;                                  // a mixer said deck 3 is off the air
check("a real mixer's word does not silence a bench deck", keys() === "1,3", keys());
state.protocols.prolink.mixer.on = true;
check("the bench's own mixer does", keys() === "1", keys());
state.protocols.prolink.devices[0].status.on_air = true;
check("a real player on air is still not heard", keys() === "1", keys());
beats = Sound.beats({phase: [1000, 10.0, 120], loop: 0, loop_from: 0}, 0, 0.6, 1000);
check("a beat knows its place in the track", beats[0].at === 10 && beats[1].at === 11, beats.map((b) => b.at));
beats = Sound.beats(looped, 0, 4.2, 1000);
check("and a loop sends it back", beats.slice(0, 5).map((b) => b.at).join() === "4,5,6,7,4", beats.slice(0, 5).map((b) => b.at));

// a deck with a file of its own: where in the file, how fast, and the loop (made at 100 BPM, its first beat 0.5 s in)
const filed = {on: true, play: true, phase: [1000, 4.0, 100], loop: 0, loop_from: 0, audio: {file: "x.wav", bpm: 100, offset: 0.5, seconds: 30}};
let plan = Sound.filePlan(filed, 5, 1000);              // the bench's clock is 1000 s ahead: it is 1005 there, 5 s after the phase: 4 + 5 * 100 / 60 beats
check("the file's place follows the deck's beats", near(plan.from, 0.5 + (4 + 5 * 100 / 60) * 0.6, 1e-6), plan);
check("at the tempo it was made at, the file plays as it is", near(plan.rate, 1) && plan.loop === null, plan);
filed.phase = [1000, 4.0, 125];
plan = Sound.filePlan(filed, 5, 1000);
check("a faster deck plays it faster", near(plan.rate, 1.25) && near(plan.from, 0.5 + (4 + 5 * 125 / 60) * 0.6, 1e-6), plan);
filed.loop = 4; filed.loop_from = 4;
plan = Sound.filePlan(filed, 5, 1000);
check("a loop is the file's loop", near(plan.loop.start, 0.5 + 4 * 0.6) && near(plan.loop.end, 0.5 + 8 * 0.6), plan);
check("and its place goes round it", plan.from >= plan.loop.start && plan.from < plan.loop.end, plan);
check("no file, or not playing, is no plan", Sound.filePlan({phase: [0, 0, 120]}, 0, 0) === null && Sound.filePlan({audio: {bpm: 120, offset: 0}, phase: null}, 0, 0) === null);

// every voice runs on a stub of the audio graph, for each beat of the bar, and they are not one voice
const nodes = [];
const param = () => ({value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {}});
const node = (kind) => { const n = {kind, connect() {}, start() {}, stop() {}, frequency: param(), gain: param(), pan: param()}; nodes.push(n); return n; };
const ctx = {sampleRate: 8000, createOscillator: () => node("osc"), createGain: () => node("gain"), createBiquadFilter: () => node("filter"),
  createBufferSource: () => node("noise"), createBuffer: (c, length) => ({getChannelData: () => new Float32Array(length)})};
check("four voices", Sound.voices.length === 4);
const made = Sound.voices.map((voice) => {
  nodes.length = 0;
  for (let beat = 1; beat <= 4; beat++) voice(ctx, node("out"), beat, 0, 0.25);
  return nodes.map((n) => n.kind).join();
});
check("the voices are not the same", new Set(made).size === 4, made.map((m) => m.length));

// a deck's file: a nudge back onto the beat (a synced deck) and a new tempo keep the sound playing, a jump fades over to the new place
{
  const started = [];
  const prm = () => ({value: 1, sets: [], setValueAtTime(v, t) { this.sets.push(["set", v, t]); },
                      linearRampToValueAtTime(v, t) { this.sets.push(["ramp", v, t]); }, cancelScheduledValues() {}});
  const fake = {state: "running", currentTime: 10, destination: {},
    createBufferSource: () => { const n = {playbackRate: prm(), connect() {}, disconnect() {}, start(at, from) { started.push({at, from, n}); }, stop(t) { n.stopped = t; }}; return n; },
    createGain: () => ({gain: prm(), connect() {}, disconnect() {}}), createStereoPanner: () => ({pan: prm(), connect() {}, disconnect() {}})};
  Sound.ctx = fake; Sound.master = {};
  Sound.buffers["2/x.wav/30"] = {duration: 30};
  const fd = {on: true, play: true, phase: [1000, 4.0, 100], loop: 0, loop_from: 0, on_air: true, audio: {file: "x.wav", bpm: 100, offset: 0.5, seconds: 30}};
  sandbox.S = {state: {decks: {2: fd}, protocols: {}}, offset: 1005 - Date.now() / 1000};     // the bench's time is 1005
  Sound.tick();
  check("the file starts", started.length === 1 && near(started[0].from, 0.5 + (4 + 5 * 100 / 60) * 0.6, 0.01), started.map((x) => x.from));
  fd.phase = [1000, 4.0 + 0.02 * 100 / 60, 100];                       // put back 20 ms
  Sound.tick();
  check("a nudge of 20 ms does not start it again", started.length === 1);
  fd.phase = [1005, 4 + 5 * 100 / 60 + 0.02 * 100 / 60, 110];          // the pitch fader: the same place, faster
  Sound.tick();
  check("a new tempo is a new speed for the same sound", started.length === 1 &&
        started[0].n.playbackRate.sets.some(([kind, v]) => kind === "set" && near(v, 1.1)), started[0].n.playbackRate.sets);
  fd.phase = [1005, 20, 110];                                            // a jump in the track
  Sound.tick();
  check("a jump starts it at the new place, fading over", started.length === 2 && near(started[1].from, 0.5 + 20 * 0.6, 0.01) &&
        near(started[0].n.stopped, 10 + 0.017, 1e-9), started.map((x) => [x.from, x.n.stopped]));
  Sound.files = {}; Sound.ctx = null; Sound.master = null; delete sandbox.S;
}

// a browser with no Web Audio says so
Sound.toggle().then(() => check("no Web Audio", false), (e) => check("no Web Audio says why", /Web Audio/.test(e.message), e.message)).then(async () => {
  sandbox.window.AudioContext = class {
    constructor() { this.state = "suspended"; this.destination = {}; }
    createGain() { return {gain: {value: 0}, connect() {}}; }
    resume() { return Promise.resolve(); }
  };
  try {
    await Sound.toggle();
    check("suspended context must not appear to be listening", false);
  } catch (e) {
    check("suspended context gives a useful error", /suspended/.test(e.message) && !Sound.on);
  }
  Sound.ctx.state = "running";
  check("a later gesture can enable audio", await Sound.toggle());
  check("audio can be stopped again", !(await Sound.toggle()));
  console.log(failures ? failures + " failed" : "ok");
  process.exit(failures ? 1 : 0);
});
