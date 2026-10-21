/* Sound in the page: a drum pattern for each deck that plays, on its beat, made with Web Audio. It is only what the page shows turned
 * into sound (the decks' tempo and place in the bar): nothing is sent to the device under test. With a mixer on, only the decks that
 * are on the air are heard, as on a real mixer. For the sound the bench itself serves, see docs/audio.md (--audio-port). */
"use strict";

const Sound = (() => {
  const LOOKAHEAD = 0.18;                     /* seconds of beats scheduled ahead of the clock */
  const s = {ctx: null, on: false, timer: null, last: {}, played: 0};   /* played: how many beats were sounded (for a check) */

  /* The beats of a deck between two moments (seconds, the page's clock), as {k, time, beat}: k counts the beats of the deck's
   * timeline, beat is its place in the bar (1 to 4, as in a loop). `offset` is what to add to the page's clock to get the bench's.
   * phase is [the bench's time, the beat position at that time, the tempo], as the state has it. */
  s.beats = (deck, from, to, offset) => {
    if (!deck.phase) return [];
    const [t, pos, bpm] = deck.phase, rate = bpm / 60;
    if (!(rate > 0)) return [];
    const posAt = (w) => pos + (w + offset - t) * rate;
    const out = [];
    for (let k = Math.ceil(posAt(from) - 1e-9); k <= Math.floor(posAt(to)); k++) {
      let at = k;
      if (deck.loop && at >= deck.loop_from + deck.loop) at = deck.loop_from + ((at - deck.loop_from) % deck.loop);
      out.push({k, time: t + (k - pos) / rate - offset, beat: ((at % 4) + 4) % 4 + 1, half: 0.5 / rate});
    }
    return out;
  };

  /* is a deck heard: it plays, and with a mixer on it is on the air */
  s.audible = (deck, mixerOn) => !!deck.on && !!deck.play && !deck.unplugged && (!mixerOn || !!deck.on_air);

  /* -- the voices -- */
  function noise(ctx) {
    if (!s.noiseBuffer) {
      const length = Math.floor(ctx.sampleRate * 0.3), buffer = ctx.createBuffer(1, length, ctx.sampleRate), data = buffer.getChannelData(0);
      for (let i = 0; i < length; i++) data[i] = Math.random() * 2 - 1;
      s.noiseBuffer = buffer;
    }
    const source = ctx.createBufferSource();
    source.buffer = s.noiseBuffer;
    return source;
  }

  function envelope(ctx, out, at, peak, length) {
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(peak, at + 0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, at + length);
    g.connect(out);
    return g;
  }

  function kick(ctx, out, at) {
    const o = ctx.createOscillator();
    o.frequency.setValueAtTime(150, at);
    o.frequency.exponentialRampToValueAtTime(45, at + 0.12);
    o.connect(envelope(ctx, out, at, 0.9, 0.22));
    o.start(at);
    o.stop(at + 0.25);
  }

  function snare(ctx, out, at) {
    const n = noise(ctx), f = ctx.createBiquadFilter();
    f.type = "bandpass";
    f.frequency.value = 1800;
    n.connect(f);
    f.connect(envelope(ctx, out, at, 0.45, 0.14));
    n.start(at);
    n.stop(at + 0.16);
  }

  function hat(ctx, out, at) {
    const n = noise(ctx), f = ctx.createBiquadFilter();
    f.type = "highpass";
    f.frequency.value = 7000;
    n.connect(f);
    f.connect(envelope(ctx, out, at, 0.16, 0.04));
    n.start(at);
    n.stop(at + 0.06);
  }

  function tone(ctx, out, at, type, freq, peak, length, filter) {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.value = freq;
    let node = o;
    if (filter) {
      const f = ctx.createBiquadFilter();
      f.type = "lowpass";
      f.frequency.value = filter;
      o.connect(f);
      node = f;
    }
    node.connect(envelope(ctx, out, at, peak, length));
    o.start(at);
    o.stop(at + length + 0.03);
  }

  /* A voice for each deck, so that they can be told apart, and a note for each beat of the bar so that the bar can be heard:
   *   1 a bass: a sine that walks A1 A1 E2 D2
   *   2 drums: a kick on 1 and 3, a snare on 2 and 4, a hat between
   *   3 keys: a triangle that climbs A3 C4 E4 G4, and an octave above between
   *   4 percussion: a wood block, higher on the 1, and a shaker between
   * Decks 5 and 6 take the voices of 1 and 2. */
  s.voices = [
    (ctx, out, beat, at) => tone(ctx, out, at, "sine", [55, 55, 82.4, 73.4][beat - 1], 0.95, 0.3, 400),
    (ctx, out, beat, at, half) => {
      if (beat === 1 || beat === 3) kick(ctx, out, at); else snare(ctx, out, at);
      hat(ctx, out, at + half);
    },
    (ctx, out, beat, at, half) => {
      const f = [220, 261.6, 329.6, 392][beat - 1];
      tone(ctx, out, at, "triangle", f, 0.32, 0.22, 2400);
      tone(ctx, out, at + half, "triangle", f * 2, 0.1, 0.1, 3000);
    },
    (ctx, out, beat, at, half) => {
      tone(ctx, out, at, "square", beat === 1 ? 1320 : 880, 0.16, 0.05, 3500);
      const n = noise(ctx), f = ctx.createBiquadFilter();
      f.type = "highpass";
      f.frequency.value = 9000;
      n.connect(f);
      f.connect(envelope(ctx, out, at + half, 0.14, 0.05));
      n.start(at + half);
      n.stop(at + half + 0.07);
    },
  ];

  /* A beat of a deck, in its voice. Each deck has its own place in the stereo field. */
  function play(deck, number, beat, at, half) {
    const ctx = s.ctx, pan = ctx.createStereoPanner ? ctx.createStereoPanner() : null;
    const out = pan || s.master;
    if (pan) { pan.pan.value = Math.max(-0.8, Math.min(0.8, (number - 2.5) * 0.4)); pan.connect(s.master); }
    s.voices[(Math.max(1, number) - 1) % s.voices.length](ctx, out, beat, at, half);
    s.played++;
  }

  function tick() {
    const state = typeof S !== "undefined" ? S.state : null;
    if (!state || !s.ctx || s.ctx.state !== "running") return;
    const mixer = state.protocols && state.protocols.prolink && state.protocols.prolink.mixer;
    const mixerOn = !!(mixer && mixer.on), now = Date.now() / 1000, offset = S.offset;
    const clock = s.ctx.currentTime - now;      /* the page's clock to the audio clock */
    for (const [n, d] of Object.entries(state.decks)) {
      if (!s.audible(d, mixerOn)) { delete s.last[n]; continue; }
      const sig = d.phase.join(","), last = s.last[n];
      const beats = s.beats(d, now, now + LOOKAHEAD, offset);
      if (!last || last.sig !== sig) {          /* a new phase: from here on, not the beats that were */
        s.last[n] = {sig, k: Math.floor(d.phase[1] + (now + offset - d.phase[0]) * d.phase[2] / 60)};
      }
      const seen = s.last[n];
      for (const b of beats) {
        if (b.k <= seen.k) continue;
        seen.k = b.k;
        play(d, Number(n), b.beat, Math.max(s.ctx.currentTime, b.time + clock), b.half);
      }
    }
  }

  s.tick = tick;

  /* Switches the sound on or off. It must be called from a click: a browser starts audio only then. Resolves to whether it is on. */
  s.toggle = async () => {
    if (s.on) {
      s.on = false;
      clearInterval(s.timer);
      s.last = {};
      return false;
    }
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) throw new Error("this browser has no Web Audio");
    if (!s.ctx) {
      s.ctx = new Context();
      s.master = s.ctx.createGain();
      s.master.gain.value = 0.4;
      s.master.connect(s.ctx.destination);
    }
    await s.ctx.resume();
    s.on = true;
    s.last = {};
    s.timer = setInterval(tick, 25);
    return true;
  };

  return s;
})();
