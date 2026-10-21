/* A strip for each deck that scrolls past a fixed playhead: a tick for every beat, a heavier line for every bar, the beat of the track
 * written on it, and a loop tinted and marked where it goes back. No waveform: a grid, on one time scale for all the decks, so that decks
 * that are synced line up and one that is not drifts. A bench deck's loop is known exactly. For a device on the link the page remembers
 * the beats it was told of (the bench hears one at each beat) and draws what came, the jumps back of a loop included, and goes on from the
 * last one at its tempo. */
"use strict";

const Strip = (() => {
  const BEHIND = 2.0, AHEAD = 6.0;              /* seconds before and after the playhead: it stands a quarter of the way in */
  const v = {BEHIND, AHEAD, history: {}};

  /* The ticks of a deck to draw, as {dt (seconds from now), at (the beat of the track), beat (1 to 4), inLoop, wrap}, and what is known
   * of it: {ticks, stopped, loop (its length in beats, or 0), looping (a device says it loops)}. `deck` is a bench deck of the state,
   * or {phase, status...} of a device with its `observed` beats. now and offset are as Sound.beats takes them. */
  v.layout = (deck, now, offset) => {
    const lo = now - BEHIND - 1, hi = now + AHEAD + 1;
    if (deck.phase) {
      const ticks = Sound.beats(deck, lo, hi, offset).map((b) => ({
        dt: b.time - now, at: b.at, beat: b.beat,
        inLoop: !!deck.loop && b.k >= deck.loop_from,
        wrap: !!deck.loop && b.k >= deck.loop_from + deck.loop && (b.k - deck.loop_from) % deck.loop === 0}));
      return {ticks, stopped: false, loop: deck.loop || 0};
    }
    const at = deck.at, rate = (deck.bpm || 120) / 60;
    if (at == null) return {ticks: [], stopped: true, loop: 0};
    const ticks = [];
    for (let k = Math.ceil(at - (BEHIND + 1) * rate); k <= Math.floor(at + (AHEAD + 1) * rate); k++) {
      ticks.push({dt: (k - at) / rate, at: k, beat: ((k % 4) + 4) % 4 + 1, inLoop: false, wrap: false});
    }
    return {ticks, stopped: true, loop: 0};
  };

  /* remember the beats a device is told of: each change of its phase is a beat, [bench time, place, tempo] */
  v.observe = (key, phase, offset) => {
    const list = v.history[key] = v.history[key] || [];
    if (!phase) return;
    const last = list[list.length - 1];
    if (last && last.sig === phase.join(",")) return;
    list.push({t: phase[0] - offset, pos: phase[1], bpm: phase[2], sig: phase.join(",")});
    while (list.length > 60) list.shift();
  };

  /* A device's ticks: the beats it was told of, then its beats at its tempo from the last. A jump back in the place is a loop. If it
   * loops, and has gone back before, the future goes back the same way. `bars` is for one that gives no beat of the track: it is
   * labelled with its beat of the bar. */
  v.layoutDevice = (key, device, now) => {
    const list = (v.history[key] || []).filter((e) => e.t > now - BEHIND - 1.5 && e.t <= now + 0.5);
    const looping = !!(device.status && device.status.loop);
    if (!list.length) return {ticks: [], stopped: true, loop: 0, looping};
    const ticks = [];
    let from = null, length = 0, inLoop = false;
    list.forEach((e, i) => {
      const prev = list[i - 1];
      const wrap = !!prev && e.pos < prev.pos + 0.5 && looping;
      if (wrap) { from = e.pos; length = Math.round(prev.pos + 1 - e.pos); inLoop = true; }
      ticks.push({dt: e.t - now, at: e.pos, beat: ((Math.round(e.pos) % 4) + 4) % 4 + 1, inLoop: inLoop && looping, wrap});
    });
    const last = list[list.length - 1], rate = last.bpm / 60;
    for (let n = 1; last.t + n / rate < now + AHEAD + 1; n++) {
      let at = last.pos + n, wrap = false;
      if (looping && from != null && length > 0 && at >= from + length) {
        const wrapped = from + ((at - from) % length);
        wrap = (at - from) % length === 0;
        at = wrapped;
      }
      ticks.push({dt: last.t + n / rate - now, at, beat: ((Math.round(at) % 4) + 4) % 4 + 1, inLoop: looping && from != null, wrap});
    }
    return {ticks, stopped: false, loop: looping ? length : 0, looping};
  };

  /* -- drawing -- */
  const color = (name, fallback) => (getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback);

  v.draw = (canvas, plan, options = {}) => {
    const ratio = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
      canvas.width = Math.round(w * ratio);
      canvas.height = Math.round(h * ratio);
    }
    const g = canvas.getContext("2d");
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    g.clearRect(0, 0, w, h);
    const head = w * BEHIND / (BEHIND + AHEAD), pps = w / (BEHIND + AHEAD);
    const first = color("--first", "#ef4444"), muted = color("--muted", "#8f95a1"), loopColor = color("--loop", "#b98af0"), text = color("--text", "#e6e8ec");
    const x = (dt) => head + dt * pps;
    const ticks = plan.ticks;
    const gap = ticks.length > 1 ? Math.abs(x(ticks[1].dt) - x(ticks[0].dt)) : 30;

    g.fillStyle = "rgba(128,128,128,0.07)";                         /* every other bar a little lighter */
    ticks.forEach((t, i) => {
      if (t.beat !== 1 || Math.floor(t.at / 4) % 2) return;
      g.fillRect(x(t.dt), 0, gap * 4, h);
    });

    g.fillStyle = loopColor;
    g.globalAlpha = 0.2;                                            /* the loop */
    ticks.forEach((t, i) => { if (t.inLoop) g.fillRect(x(t.dt), 0, gap, h); });
    g.globalAlpha = 1;

    g.font = "10px ui-monospace, Menlo, Consolas, monospace";
    g.textBaseline = "top";
    ticks.forEach((t) => {
      const px = x(t.dt), past = t.dt < 0;
      if (px < -2 || px > w + 2) return;
      g.globalAlpha = past ? 0.45 : 1;
      g.strokeStyle = t.beat === 1 ? first : muted;
      g.lineWidth = t.beat === 1 ? 2 : 1;
      g.beginPath();
      g.moveTo(px + 0.5, t.beat === 1 ? 3 : h * 0.5);
      g.lineTo(px + 0.5, h - 3);
      g.stroke();
      if (gap >= 15) {
        g.fillStyle = t.beat === 1 ? text : muted;
        g.fillText(String(options.bars ? t.beat : Math.round(t.at) + 1), px + 3, t.beat === 1 ? 4 : h * 0.5 - 10);
      }
      if (t.wrap) {                                                 /* the loop goes back here */
        g.globalAlpha = 1;
        g.strokeStyle = loopColor;
        g.lineWidth = 2;
        g.setLineDash([3, 3]);
        g.beginPath();
        g.moveTo(px + 0.5, 0);
        g.lineTo(px + 0.5, h);
        g.stroke();
        g.setLineDash([]);
        g.fillStyle = loopColor;
        g.fillText("↻", px + 3, h - 12);
      }
    });
    g.globalAlpha = 1;

    g.fillStyle = text;                                             /* the playhead */
    g.fillRect(head - 1, 0, 2, h);
    g.beginPath();
    g.moveTo(head - 5, 0);
    g.lineTo(head + 5, 0);
    g.lineTo(head, 6);
    g.fill();

    const label = options.label || (plan.stopped ? "stopped" : plan.loop ? "LOOP " + plan.loop : plan.looping ? "LOOP" : "");
    if (label) {                                                    /* on a chip, so that it does not run into the numbers */
      g.font = "bold 10px ui-monospace, Menlo, Consolas, monospace";
      const width = g.measureText(label).width + 10;
      g.fillStyle = color("--lcd-bg", "#0a0c0e");
      g.globalAlpha = 0.92;
      g.fillRect(w - width - 4, h - 17, width, 14);
      g.globalAlpha = 1;
      g.fillStyle = plan.loop || plan.looping ? loopColor : muted;
      g.fillText(label, w - width + 1, h - 15);
    }
  };

  return v;
})();
