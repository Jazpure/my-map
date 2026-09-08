// ---------------------------------------------------------------------------
// The city-noise pool.
//
// Not one clip per place, and not a set of tracks that switch. A handful of
// recordings all sounding at once, all the time, granulated into texture — and
// what moving around changes is the BALANCE between them, never whether they
// are on.
//
//   WHICH clips lead      each slot's level comes from how closely its
//                         measured intensity matches the built density under
//                         the camera. Sparse ground raises distant rumble and
//                         quiet night; dense ground raises crowds and traffic.
//                         Nothing is switched off — it recedes.
//
//   HOW PRESENT it all is zooming out lowpasses and drowns the whole bus until
//                         it is a thin distant wash. Never silence.
//
// Two rules keep it from sounding like components:
//
//   Constant power. Slot levels are normalised so the sum of squares stays
//   fixed. As the balance shifts, the total never swells or dips — one clip
//   rising is exactly another receding.
//
//   Rotation only under cover. A slot's clip is replaced only once that slot
//   has already faded down to near-inaudible AND its time is up. You never
//   hear a swap, because nothing swaps while you can hear it.
// ---------------------------------------------------------------------------

const Pool = (() => {

  let out, bus, filter, reverbSend;
  let clips = [];
  let slots = [];
  let target = 0.5, presence = 1, order = 0.3;
  const cache = new Map();
  const MAX_CACHE = 8;

  const CFG = {
    slots: 4,
    fade: 6.0,          // seconds. rotation cover, and every balance move.
    life: [45, 90],     // how long a clip may hold a slot, once quiet
    match: 0.28,        // how sharply intensity has to match the ground
    quiet: 0.22,        // a slot below this is inaudible enough to swap
    curve: 0.6,         // raises rowhouse density off the floor of the range
    zoomNear: 15.5,
    zoomFar: 11.0,
  };

  const lerp = (a, b, t) => a + (b - a) * t;
  const clamp01 = x => Math.max(0, Math.min(1, x));
  const weigh = intensity => {
    const d = (intensity - target) / CFG.match;
    return Math.exp(-0.5 * d * d) + 0.02;
  };

  // --- setup --------------------------------------------------------------

  async function init(destination, reverb) {
    out = destination;
    clips = await fetch('data/pool.json', { cache: 'no-cache' }).then(r => r.json());

    bus = new Tone.Gain(0);
    filter = new Tone.Filter({ type: 'lowpass', frequency: 18000, rolloff: -24 });
    reverbSend = new Tone.Gain(0);

    filter.connect(bus);
    bus.connect(out);
    bus.connect(reverbSend);
    if (reverb) reverbSend.connect(reverb);

    for (let i = 0; i < CFG.slots; i++) {
      // two gains per slot: `level` carries the continuous balance, `swap`
      // is only ever used to cover a rotation. Keeping them separate means a
      // rotation can never fight the balance for control of the same node.
      const level = new Tone.Gain(0);
      const swap = new Tone.Gain(1);
      level.connect(swap);
      swap.connect(filter);
      slots.push({ level, swap, voice: null, clip: null, until: 0, w: 0 });
    }

    await Promise.all(slots.map((s, i) => fill(s, i * 400)));
    bus.gain.rampTo(1, 3);
    rotate();
    return clips.length;
  }

  // --- buffers ------------------------------------------------------------

  async function buffer(src) {
    if (cache.has(src)) return cache.get(src);
    const buf = await Tone.ToneAudioBuffer.fromUrl(src);
    cache.set(src, buf);
    if (cache.size > MAX_CACHE) {
      const busy = new Set(slots.map(s => s.clip && s.clip.src));
      for (const key of cache.keys()) {
        if (!busy.has(key) && key !== src) {
          try { cache.get(key).dispose(); } catch (e) {}
          cache.delete(key);
          break;
        }
      }
    }
    return buf;
  }

  // --- choosing -----------------------------------------------------------

  function pick() {
    // `reserved` as well as `clip`: fill() awaits before it assigns, so two
    // slots rotating together would otherwise both pick the same clip
    const busy = new Set();
    for (const s of slots) {
      if (s.clip) busy.add(s.clip.id);
      if (s.reserved) busy.add(s.reserved);
    }
    const options = clips.filter(c => !busy.has(c.id));
    if (!options.length) return null;

    // weighted by fit, but nothing is excluded — an occasional far-off rumble
    // over a busy block is what keeps this sounding like a city rather than
    // like a lookup table
    const weights = options.map(c => weigh(c.intensity));
    const total = weights.reduce((a, b) => a + b, 0);
    let r = Math.random() * total;
    for (let i = 0; i < options.length; i++) {
      r -= weights[i];
      if (r <= 0) return options[i];
    }
    return options[options.length - 1];
  }

  async function fill(slot, delay = 0) {
    const clip = pick();
    if (!clip) return;
    slot.reserved = clip.id;
    if (delay) await new Promise(r => setTimeout(r, delay));

    const old = slot.voice;
    if (old) {
      // duck this slot out, swap underneath, bring it back. The slot is
      // already near-silent when we get here, so this is cover, not a fade.
      slot.swap.gain.rampTo(0, CFG.fade * 0.5);
      await new Promise(r => setTimeout(r, CFG.fade * 500 + 150));
      try { old.dispose(); } catch (e) {}
    }

    let buf;
    try { buf = await buffer(clip.src); }
    catch (e) {
      console.warn('pool: could not load', clip.src, e);
      slot.reserved = null;
      slot.swap.gain.rampTo(1, CFG.fade * 0.5);
      return;
    }

    const voice = new GenerativeVoice(buf, slot.level, Math.floor(Math.random() * 1e9));
    voice.set(order, 1);
    voice.start();

    slot.voice = voice;
    slot.clip = clip;
    slot.reserved = null;
    slot.started = performance.now();
    slot.until = slot.started + lerp(CFG.life[0], CFG.life[1], Math.random()) * 1000;
    slot.swap.gain.rampTo(1, CFG.fade * 0.5);
  }

  function rotate() {
    const now = performance.now();
    for (const slot of slots) {
      // only swap what cannot currently be heard
      const inaudible = slot.w < CFG.quiet;
      if (!slot.busy && (!slot.voice || (now > slot.until && inaudible))) {
        slot.busy = true;
        fill(slot).finally(() => { slot.busy = false; });
      }
    }
    setTimeout(rotate, 2000);
  }

  // --- per-frame ----------------------------------------------------------

  function update({ zoom, density }) {
    if (!bus) return;
    target = Math.pow(clamp01(density), CFG.curve);

    // one zoom level is a doubling of ground scale, so presence falls off
    // logarithmically like the anchored layers do
    const z = Math.max(CFG.zoomFar, Math.min(CFG.zoomNear, zoom));
    const near = Math.pow((z - CFG.zoomFar) / (CFG.zoomNear - CFG.zoomFar), 0.65);

    presence = lerp(0.16, 1.0, near);
    order = lerp(0.04, 0.42, near);

    const now = Tone.now();
    bus.gain.rampTo(presence * lerp(0.78, 1.0, target), 0.6, now);
    filter.frequency.rampTo(lerp(430, 17000, Math.pow(near, 1.4)), 0.8, now);
    reverbSend.gain.rampTo(lerp(0.8, 0.12, near) * presence, 0.8, now);

    // constant power: the balance can shift all it likes, the total cannot
    const raw = slots.map(s => (s.clip ? weigh(s.clip.intensity) : 0));
    const norm = Math.sqrt(raw.reduce((a, b) => a + b * b, 0)) || 1;

    slots.forEach((slot, i) => {
      slot.w = raw[i] / norm;
      // long ramps on every balance move — this is the difference between
      // a mix that breathes and one that jumps
      slot.level.gain.rampTo(slot.w, CFG.fade * 0.5, now);
      if (slot.voice) slot.voice.set(order);
    });
  }

  const playing = () => slots
    .filter(s => s.clip)
    .map(s => ({ label: s.clip.label, intensity: s.clip.intensity, level: s.w }))
    .sort((a, b) => b.level - a.level);

  return { init, update, playing, state: () => ({ target, presence, order }) };
})();


// ---------------------------------------------------------------------------
// Built density, computed in the browser from the footprints already loaded
// for the render. Floor area rather than footprint: a tower and a rowhouse
// cover the same ground but are not the same amount of city.
// ---------------------------------------------------------------------------

const Density = (() => {
  const CELL = 150;
  let grid = new Map(), origin = null, mx = 1, my = 110540, ref = 1;

  const key = (cx, cy) => cx + ',' + cy;

  function build(geojson) {
    const feats = geojson.features;
    if (!feats.length) return;

    let lat0 = 0;
    for (const f of feats) lat0 += f.geometry.coordinates[0][0][1];
    lat0 /= feats.length;
    mx = 111320 * Math.cos(lat0 * Math.PI / 180);

    let w = Infinity, s = Infinity;
    const cells = [];
    for (const f of feats) {
      const ring = f.geometry.coordinates[0];
      let a = 0, cx = 0, cy = 0;
      for (let i = 0; i < ring.length - 1; i++) {
        const [x0, y0] = ring[i], [x1, y1] = ring[i + 1];
        a += x0 * y1 - x1 * y0;
        cx += x0; cy += y0;
      }
      const n = ring.length - 1;
      cx /= n; cy /= n;
      const area = Math.abs(a) / 2 * mx * my;
      const floors = Math.max(1, (f.properties.h || 9) / 3.2);
      cells.push([cx, cy, area * floors]);
      w = Math.min(w, cx); s = Math.min(s, cy);
    }
    origin = [w, s];

    for (const [cx, cy, mass] of cells) {
      const gx = Math.floor((cx - w) * mx / CELL);
      const gy = Math.floor((cy - s) * my / CELL);
      const k = key(gx, gy);
      grid.set(k, (grid.get(k) || 0) + mass);
    }

    const vals = [...grid.values()].sort((a, b) => a - b);
    ref = vals[Math.floor(vals.length * 0.96)] || 1;
  }

  // 3x3 average so crossing a block eases rather than steps
  function at(lng, lat) {
    if (!origin) return 0.5;
    const gx = Math.floor((lng - origin[0]) * mx / CELL);
    const gy = Math.floor((lat - origin[1]) * my / CELL);
    let sum = 0;
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++)
        sum += grid.get(key(gx + dx, gy + dy)) || 0;
    return clamp01Local(sum / 9 / ref);
  }
  const clamp01Local = x => Math.max(0, Math.min(1, x));

  return { build, at };
})();
