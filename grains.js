// ---------------------------------------------------------------------------
// Generative playback of supplied recordings.
//
// A recording is never played as a loop. It is played as a stream of grains —
// fragments cut from the buffer and triggered continuously — and one
// parameter, `order`, controls how those fragments relate to each other:
//
//   order = 0   grains are drawn from all over the recording, pitch-scattered,
//               wide. You hear that a recording exists without hearing what it
//               is. A cloud made of it.
//
//   order = 1   grains advance sequentially, long, centred, unscattered.
//               Effectively the recording playing intact.
//
// Everything between is a continuous morph, so material ASSEMBLES as you
// approach and dissolves as you leave. Nothing triggers; it coheres.
//
// SMOOTHNESS IS THE WHOLE GAME HERE, and it comes from three rules that are
// easy to get wrong:
//
//   1. Overlap-add. Each grain has a triangular envelope (fade in and out each
//      take half its length) and the next one starts exactly halfway through
//      the last. Overlapping triangles sum to a constant, so the output has no
//      amplitude ripple at all. Break the relationship between fade length and
//      hop and you get audible pulsing; leave gaps and you get stuttering.
//
//   2. Regular hop. Randomising the time between grains destroys the constant
//      sum above. Variety comes from WHERE grains are read and how they are
//      pitched — never from when they fire.
//
//   3. One panner per voice, drifting slowly. Panning each grain independently
//      makes the stereo image leap around several times a second, which reads
//      as broken rather than as spacious. Instead the whole voice occupies a
//      position that wanders over ten seconds or more.
// ---------------------------------------------------------------------------

class GenerativeVoice {

  constructor(buffer, out, seed) {
    this.buffer = buffer;
    this.dur = buffer.duration;
    this.order = 0;
    this.rate = 1;
    this.running = false;
    this.live = new Set();

    let s = (seed || 1) >>> 0;
    this.rnd = () => {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };

    this.playhead = this.rnd() * this.dur;

    // one position for the whole voice, moved slowly and never jumped
    this.panner = new Tone.Panner((this.rnd() * 2 - 1) * 0.4);
    this.panner.connect(out);
    this.panUntil = 0;
  }

  get params() {
    const o = Math.max(0, Math.min(1, this.order));
    return {
      // long grains: short ones read as granular effect, long ones read as
      // the place the recording was made
      grain: 0.55 + 1.15 * o,
      scatter: (1 - o) * this.dur * 0.35,
      jitter: (1 - o) * 0.045,          // gentle: ±4% is colour, ±22% is chaos
      width: 0.15 + (1 - o) * 0.45,
    };
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.next = Tone.now() + 0.05;
    this.tick();
  }

  stop() {
    this.running = false;
    for (const g of this.live) { try { g.stop(); g.dispose(); } catch (e) {} }
    this.live.clear();
  }

  dispose() {
    this.stop();
    // let anything still ringing finish into the panner before removing it
    setTimeout(() => { try { this.panner.dispose(); } catch (e) {} }, 3000);
  }

  // Lookahead scheduler. Grains are placed on the Web Audio clock, so their
  // timing does not depend on how busy the main thread is with map rendering.
  tick() {
    if (!this.running) return;
    const now = Tone.now();
    const horizon = now + 0.6;
    let guard = 0;

    while (this.next < horizon && guard++ < 32) {
      const p = this.params;
      this.emit(Math.max(this.next, now + 0.02), p);
      this.next += p.grain * 0.5;         // exact half-overlap: no ripple
    }
    if (this.next < now) this.next = now + 0.02;

    // slow stereo drift, retargeted every 9-20s and taking 7-15s to get there
    if (now > this.panUntil) {
      const w = this.params.width;
      this.panner.pan.rampTo((this.rnd() * 2 - 1) * w, 7 + this.rnd() * 8);
      this.panUntil = now + 9 + this.rnd() * 11;
    }

    setTimeout(() => this.tick(), 150);
  }

  emit(when, p) {
    let offset = this.playhead + (this.rnd() - 0.5) * 2 * p.scatter;
    offset = ((offset % this.dur) + this.dur) % this.dur;
    if (offset + p.grain > this.dur) offset = Math.max(0, this.dur - p.grain);

    const grain = Math.min(p.grain, this.dur - offset);
    if (grain < 0.05) { this.playhead = 0; return; }

    // the playhead advances by real elapsed time, so at order = 1 successive
    // grains line up into the actual recording
    this.playhead = (this.playhead + p.grain * 0.5 * this.rate) % this.dur;

    const src = new Tone.ToneBufferSource({
      url: this.buffer,
      playbackRate: this.rate * (1 + (this.rnd() - 0.5) * 2 * p.jitter),
      // triangular envelope — the half-length fades are what make overlapping
      // grains sum flat instead of pulsing
      fadeIn: grain * 0.5,
      fadeOut: grain * 0.5,
      curve: 'linear',
    });

    src.connect(this.panner);
    src.onended = () => {
      this.live.delete(src);
      try { src.dispose(); } catch (e) {}
    };
    this.live.add(src);
    src.start(when, offset, grain);
  }

  set(order, rate) {
    this.order = order;
    this.rate = rate === undefined ? this.rate : rate;
  }
}

window.GenerativeVoice = GenerativeVoice;
