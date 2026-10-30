/* A strip for each deck that scrolls past a fixed playhead: a tick for every beat, a heavier line for every bar, the beat of the track
 * written on it, and a loop tinted and marked where it goes back. A grid, on one time scale for all the decks, so that decks that are
 * synced line up and one that is not drifts. A deck with a sound file of its own has its waveform behind the grid, laid out beat by beat
 * (`options.wave`), so that the beats can be seen to fall where they should in it. A bench deck's loop is known exactly. For a device on the link the page remembers
 * the beats it was told of (the bench hears one at each beat) and draws what came, the jumps back of a loop included, and goes on from the
 * last one at its tempo. */
"use strict";

const Strip = (() => {
  const BEHIND = 2.0, AHEAD = 6.0;              /* seconds before and after the playhead: it stands a quarter of the way in */
  const v = {BEHIND, AHEAD, history: {}, deviceLoops: {}};

  v.beatOf = (deck, now, offset) => {
    const phase = deck.bar_phase || deck.phase;
    if (!phase) return 0;
    const [t, pos, bpm] = phase;
    let at = pos + (now + offset - t) * bpm / 60;
    if (!deck.bar_phase && deck.loop && at >= deck.loop_from + deck.loop) {
      at = deck.loop_from + (at - deck.loop_from) % deck.loop;
    }
    return ((Math.floor(at) % 4) + 4) % 4 + 1;
  };

  v.master = (state) => {
    for (const [number, deck] of Object.entries(state.decks || {})) {
      if (deck.on && deck.master && deck.phase) return {...deck, number};
    }
    const link = state.protocols && state.protocols.prolink;
    return ((link && link.devices) || []).find((d) => d.online && d.status && d.status.master && d.phase) || null;
  };

  /* The ticks of a deck to draw, as {dt (seconds from now), at (the beat of the track), beat (1 to 4), inLoop, wrap}, and what is known
   * of it: {ticks, stopped, loop (its length in beats, or 0), looping (a device says it loops)}. `deck` is a bench deck of the state,
   * or {phase, status...} of a device with its `observed` beats. now and offset are as Sound.beats takes them. */
  v.layout = (deck, now, offset) => {
    const lo = now - BEHIND - 1, hi = now + AHEAD + 1;
    if (deck.phase) {
      const end = deck.loop_from + deck.loop, going = !!deck.loop && deck.phase[1] < end;      /* moved past its loop: it is behind, as a mark */
      const ticks = Sound.beats(deck, lo, hi, offset).map((b) => ({
        dt: b.time - now, at: b.at, beat: b.beat,
        inLoop: !!deck.loop && b.k >= deck.loop_from && (going || b.k < end),
        wrap: going && b.k >= end && (b.k - deck.loop_from) % deck.loop === 0}));
      const [t, pos, bpm] = deck.phase, here = pos + (now + offset - t) * bpm / 60;
      return {ticks, stopped: false, loop: deck.loop || 0, loopAhead: deck.loop && deck.loop_from > here ? deck.loop_from - here : 0};
    }
    const at = deck.at, rate = (deck.bpm || 120) / 60;
    if (at == null) return {ticks: [], stopped: true, loop: 0};
    const ticks = [], loop = deck.loop || 0, from = deck.loop_from || 0;       /* a loop that is set is seen when stopped too, and ahead of the playhead */
    const going = !!loop && at < from + loop;                                  /* a deck that is past its loop has left it behind */
    for (let k = Math.ceil(at - (BEHIND + 1) * rate); k <= Math.floor(at + (AHEAD + 1) * rate); k++) {
      const shown = going && k >= from + loop ? from + ((k - from) % loop) : k;
      ticks.push({dt: (k - at) / rate, at: shown, beat: ((shown % 4) + 4) % 4 + 1, inLoop: !!loop && k >= from && (going || k < from + loop),
                  wrap: going && k >= from + loop && (k - from) % loop === 0});
    }
    return {ticks, stopped: true, loop, loopAhead: loop && from > at ? from - at : 0};
  };

  /* remember the beats a device is told of: each change of its phase is a beat, [bench time, place, tempo] */
  v.observe = (key, phase, offset, barPhase = null) => {
    const list = v.history[key] = v.history[key] || [];
    if (!phase) return;
    const last = list[list.length - 1];
    if (last && last.sig === phase.join(",")) return;
    if (last && last.stamp === phase[0]) {
      // A later status can correct the track count of the same beat.
      list.pop();
      if (v.deviceLoops[key]) v.deviceLoops[key].checked = list.length ? list[list.length - 1].t : -Infinity;
    }
    list.push({t: phase[0] - offset, stamp: phase[0], pos: phase[1], bpm: phase[2], sig: phase.join(","),
               bar: barPhase ? barPhase[1] + 1 : ((Math.round(phase[1]) % 4) + 4) % 4 + 1});
    while (list.length > 60) list.shift();
  };

  /* A device's ticks: the beats it was told of, then its beats at its tempo from the last. A jump back in the place is a loop. If it
   * loops, and has gone back before, the future goes back the same way. `bars` is for one that gives no beat of the track: it is
   * labelled with its beat of the bar. */
  v.layoutDevice = (key, device, now) => {
    const history = v.history[key] || [], status = device.status;
    const list = history.filter((e) => e.t > now - BEHIND - 1.5 && e.t <= now + 0.5);
    const looping = !!(status && status.loop && device.online !== false);
    const track = status ? [status.source, status.slot, status.rbid].join(":") : "";
    let bounds = v.deviceLoops[key];
    if (!bounds || bounds.looping !== looping || bounds.track !== track) {
      // A new loop or track must not inherit the previous loop's bounds.
      const since = bounds && history.length ? history[history.length - 1].t : -Infinity;
      bounds = v.deviceLoops[key] = {looping, track, since, checked: -Infinity, from: null, length: 0};
    }
    if (looping) {
      for (let i = 1; i < history.length; i++) {
        const e = history[i], prev = history[i - 1];
        if (e.t <= bounds.checked || prev.t <= bounds.since) continue;
        // Repeated positions are not wraps. Missing samples can span beats.
        if (e.pos < prev.pos - 0.5) {
          const elapsed = Math.max(1, Math.round((e.t - prev.t) * prev.bpm / 60));
          bounds.from = e.pos;
          bounds.length = Math.round(prev.pos + elapsed - e.pos);
        }
      }
      if (history.length) bounds.checked = history[history.length - 1].t;
    }
    if (!list.length) return {ticks: [], stopped: true, loop: 0, looping};
    const ticks = [];
    const {from, length} = bounds;
    const loopPlace = (pos) => looping && from != null && length > 0 && pos >= from + length
      ? from + ((pos - from) % length) : pos;
    list.forEach((e) => {
      const prev = history[history.indexOf(e) - 1];
      const at = loopPlace(e.pos);
      const inLoop = looping && from != null && at >= from && at < from + length;
      const wrap = inLoop && !!prev && at === from && at < loopPlace(prev.pos) - 0.5;
      ticks.push({dt: e.t - now, at, beat: e.bar, inLoop, wrap});
    });
    const last = list[list.length - 1], rate = last.bpm / 60;
    for (let n = 1; last.t + n / rate < now + AHEAD + 1; n++) {
      let at = last.pos + n, wrap = false;
      if (looping && from != null && length > 0 && at >= from + length) {
        const wrapped = from + ((at - from) % length);
        wrap = (at - from) % length === 0;
        at = wrapped;
      }
      ticks.push({dt: last.t + n / rate - now, at, beat: (last.bar - 1 + n) % 4 + 1, inLoop: looping && from != null, wrap});
    }
    return {ticks, stopped: false, loop: looping ? length : 0, looping};
  };

  /* -- drawing -- */
  const color = (name, fallback) => (getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback);

  /* The peaks a little smoothed ([1, 2, 1] / 4 with the neighbours), so that what a column of the strip shows does not jump as the strip
   * scrolls and the column falls on other values. */
  v.smooth = (peaks) => peaks.map((p, i) => (peaks[Math.max(0, i - 1)] + 2 * p + peaks[Math.min(peaks.length - 1, i + 1)]) / 4);

  /* The waveform: for each run of beats that follow each other in the file, the file's loudness over them (the file's second of beat b
   * is offset + b * 60 / bpm, bpm being the tempo it was made at) spread over their width on the strip, so that a loop's jump back
   * shows in it. wave is {peaks (0 to 100, see smooth), rate (a second of them), offset, bpm}. It is one shape, mirrored round the
   * middle, with the loudness between two values taken in proportion, so that it moves smoothly as the strip does. */
  v.waveform = (g, wave, ticks, x, gap, w, h, colour) => {
    const {peaks, rate, offset, bpm} = wave;
    if (!peaks || !peaks.length || !(bpm > 0)) return;
    const perBeat = 60 / bpm, mid = h / 2, scale = h * 0.42 / 100, last = peaks.length - 1;
    const level = (i) => {                                          /* at a place of the file, in values: 0 outside it */
      if (i < 0 || i > last) return 0;
      const k = Math.floor(i);
      return peaks[k] + (peaks[Math.min(k + 1, last)] - peaks[k]) * (i - k);
    };
    g.fillStyle = colour;
    g.globalAlpha = 0.28;
    for (let from = 0; from < ticks.length;) {
      let to = from;
      while (to + 1 < ticks.length && ticks[to + 1].at === ticks[to].at + 1) to++;           /* a loop's jump back ends the run */
      const x0 = x(ticks[from].dt), x1 = x(ticks[to].dt) + gap, start = offset + ticks[from].at * perBeat, span = (to - from + 1) * perBeat;
      if (x1 >= 0 && x0 <= w && x1 > x0) {
        const tops = [];
        for (let px = Math.max(0, Math.floor(x0)); px <= Math.min(w, Math.ceil(x1)); px++) {
          tops.push([px, Math.max(0.4, level((start + (px - x0) / (x1 - x0) * span) * rate) * scale)]);
        }
        g.beginPath();
        g.moveTo(tops[0][0], mid - tops[0][1]);
        for (const [px, a] of tops) g.lineTo(px, mid - a);
        for (let i = tops.length - 1; i >= 0; i--) g.lineTo(tops[i][0], mid + tops[i][1]);
        g.closePath();
        g.fill();
      }
      from = to + 1;
    }
    g.globalAlpha = 1;
  };

  /* The offset of the bench's clock from the page's, followed over the states that come. A state says the bench's time when it was
   * made and the page reads its own clock when it arrives, so each sample is late by the delay of that message, which is not the same
   * from one to the next (a few milliseconds, more through WSL's forwarding of localhost): used as it came, it moved every strip a few
   * pixels at each state. The least delay is the truest. A sample that says the bench is further ahead (a message that came quicker)
   * is followed, but by 5 ms at most for each state: the answer to a click comes by another road than the stream and can be 100 ms quicker,
   * and followed at once it moved the strip, and the sound, forward by that much, as if the deck caught up. One that says less (a slow
   * one) counts for little, and a clock that drifts is still followed. A change of over half a second is another clock (the bench
   * started again): taken as it is. */
  v.followClock = (previous, sample) => {
    if (previous == null || Math.abs(sample - previous) > 0.5) return sample;
    return previous + (sample > previous ? Math.min((sample - previous) * 0.5, 0.005) : (sample - previous) * 0.02);
  };

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

    if (options.wave) v.waveform(g, options.wave, ticks, x, gap, w, h, text);

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

    const coming = plan.loop && plan.loopAhead > 0.05 ? "LOOP " + plan.loop + " in " + (Math.round(plan.loopAhead * 10) / 10) + " beats" : "";
    const label = options.label || coming || (plan.stopped ? (plan.loop ? "stopped, LOOP " + plan.loop : "stopped") : plan.loop ? "LOOP " + plan.loop : plan.looping ? "LOOP" : "");
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
