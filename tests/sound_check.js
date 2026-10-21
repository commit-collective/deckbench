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

// a browser with no Web Audio says so
Sound.toggle().then(() => check("no Web Audio", false), (e) => check("no Web Audio says why", /Web Audio/.test(e.message), e.message)).then(() => {
  console.log(failures ? failures + " failed" : "ok");
  process.exit(failures ? 1 : 0);
});
