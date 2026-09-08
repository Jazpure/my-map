// ---------------------------------------------------------------------------
// The sound engine + authoring panel.
//
// Reads score.js and does exactly what it says. No mixing decisions are made
// here — this file is the mechanism, score.js is the authorship.
//
// Signal path per layer:
//
//   source ──▶ lowpass filter ──▶ layer gain ──┬──▶ master ──▶ out
//                                              └──▶ reverb send ──▶ shared
//                                                                   reverb
//
// `grain` and `detune` act on the source itself: on a GrainPlayer they are
// real granular smear and pitch, on a synthesised placeholder they drive a
// wobble of equivalent depth so the control still reads while you tune.
// ---------------------------------------------------------------------------

const Audio = (() => {

  const S = window.SCORE;
  let started = false;
  let master, reverb;
  const layers = [];

  // --- curve reading ------------------------------------------------------

  function at(curve, p) {
    if (p <= curve[0][0]) return curve[0][1];
    for (let i = 1; i < curve.length; i++) {
      if (p <= curve[i][0]) {
        const [p0, v0] = curve[i - 1], [p1, v1] = curve[i];
        const t = p1 === p0 ? 0 : (p - p0) / (p1 - p0);
        return v0 + (v1 - v0) * t;
      }
    }
    return curve[curve.length - 1][1];
  }

  const smoothstep = x => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));

  // --- layer config resolution -------------------------------------------
  // A layer is its kind's defaults with its own overrides on top. Reading
  // this back out is what the panel displays, so what you see is what runs.

  function resolve(def) {
    const kind = S.KINDS[def.kind];
    return {
      ...def,
      priority: def.priority ?? kind.priority,
      reach: def.reach !== undefined ? def.reach : kind.reach,
      curves: { ...kind.curves, ...(def.curves || {}) },
    };
  }

  // --- placeholder voices -------------------------------------------------
  // Stand-ins so the geography can be tuned before any recording exists.
  // Each kind gets a distinguishable texture; none of them are the point.

  function placeholder(kind) {
    if (kind === 'bed') {
      const a = new Tone.Oscillator({ frequency: 55, type: 'sawtooth', volume: -20 });
      const b = new Tone.Oscillator({ frequency: 55.7, type: 'sawtooth', volume: -22 });
      const c = new Tone.Oscillator({ frequency: 82.5, type: 'sine', volume: -24 });
      const sum = new Tone.Gain(1);
      [a, b, c].forEach(o => { o.connect(sum); o.start(); });
      return { node: sum, parts: [a, b, c], type: 'synth' };
    }
    if (kind === 'oral') {
      // resonant band wandering through the speech range — babble, not words
      const n = new Tone.Noise({ type: 'pink', volume: -8 });
      const f = new Tone.Filter({ type: 'bandpass', frequency: 900, Q: 7 });
      const lfo = new Tone.LFO({ frequency: 2.6, min: 380, max: 2300, type: 'triangle' });
      const amp = new Tone.LFO({ frequency: 1.4, min: 0.05, max: 1, type: 'sawtooth' });
      const g = new Tone.Gain(0.5);
      n.connect(f); f.connect(g);
      lfo.connect(f.frequency); amp.connect(g.gain);
      n.start(); lfo.start(); amp.start();
      return { node: g, parts: [n, lfo, amp], type: 'synth' };
    }
    if (kind === 'voice') {
      const o = new Tone.Oscillator({ frequency: 196, type: 'triangle', volume: -16 });
      const v = new Tone.LFO({ frequency: 5.2, min: -12, max: 12, type: 'sine' });
      const g = new Tone.Gain(1);
      o.connect(g); v.connect(o.detune);
      o.start(); v.start();
      return { node: g, parts: [o, v], type: 'synth' };
    }
    // place — broadband ambience
    const n = new Tone.Noise({ type: 'brown', volume: -6 });
    const f = new Tone.Filter({ type: 'bandpass', frequency: 500, Q: 1.1 });
    const lfo = new Tone.LFO({ frequency: 0.08, min: 260, max: 1500, type: 'sine' });
    const g = new Tone.Gain(0.8);
    n.connect(f); f.connect(g); lfo.connect(f.frequency);
    n.start(); lfo.start();
    return { node: g, parts: [n, lfo], type: 'synth' };
  }

  // --- construction -------------------------------------------------------

  async function start() {
    if (started) return;
    await Tone.start();
    started = true;

    master = new Tone.Gain(S.master).toDestination();
    reverb = new Tone.Reverb({ decay: 7.5, preDelay: 0.03, wet: 1 });
    reverb.connect(master);
    await reverb.generate();

    for (const def of S.LAYERS) {
      const cfg = resolve(def);
      // Placeholder synths were scaffolding for tuning the geography before
      // any recordings existed. Now that real material is in the pool they
      // are just a drone of wind over the top of it, so a layer with no file
      // stays silent rather than inventing something to play.
      if (!cfg.src && !S.placeholders) continue;
      const filter = new Tone.Filter({ type: 'lowpass', frequency: 800, rolloff: -24 });
      const gain = new Tone.Gain(0);
      const send = new Tone.Gain(0);

      filter.connect(gain);
      gain.connect(master);
      gain.connect(send);
      send.connect(reverb);

      const L = { cfg, filter, gain, send, source: null, p: 0, out: 0 };
      layers.push(L);
      await attach(L, cfg.src);
    }

    const n = await Pool.init(master, reverb);
    buildPanel();
    return n;
  }

  // Swap a layer's source. `url` may be a path or an object-URL from a
  // dropped file; null falls back to the synthesised placeholder.
  async function attach(L, url) {
    if (L.source) {
      try { L.source.parts ? L.source.parts.forEach(p => p.dispose()) : null; } catch (e) {}
      try { L.source.node.dispose(); } catch (e) {}
      L.source = null;
    }
    if (url) {
      try {
        const player = new Tone.GrainPlayer({
          url, loop: true, grainSize: 0.2, overlap: 0.1, playbackRate: 1,
        });
        await Tone.loaded();
        player.connect(L.filter);
        player.start();
        L.source = { node: player, type: 'grain' };
        L.cfg.src = url;
        return;
      } catch (e) {
        console.warn(`layer ${L.cfg.id}: could not load ${url}`, e);
      }
    }
    const ph = placeholder(L.cfg.kind);
    ph.node.connect(L.filter);
    L.source = ph;
  }

  // --- the per-frame calculation -----------------------------------------

  function update(listener) {
    if (!started) return;

    // Zoom is logarithmic — one level is a doubling of ground scale — so
    // altitude has to be too. A linear ramp spends almost its whole range up
    // in the stratosphere and everything anchored dies within a level of the
    // ground. This keeps the near zooms roomy and collapses fast further out.
    const { zoomNear, zoomFar, maxAltitude } = S.listener;
    const z = Math.max(zoomFar, Math.min(zoomNear, listener.zoom));
    const span = Math.pow(2, zoomNear - zoomFar) - 1;
    const altitude = maxAltitude * (Math.pow(2, zoomNear - z) - 1) / span;

    // metres per degree at this latitude
    const mLng = 111320 * Math.cos(listener.lat * Math.PI / 180);
    const mLat = 110540;

    // pass one: proximity and raw activity
    for (const L of layers) {
      const c = L.cfg;
      if (!c.reach || !c.anchor) {
        L.p = 1;                       // global bed: always fully present
      } else {
        const dx = (c.anchor[0] - listener.lng) * mLng;
        const dy = (c.anchor[1] - listener.lat) * mLat;
        const d = Math.hypot(Math.hypot(dx, dy), altitude);
        L.p = smoothstep(1 - d / c.reach);
      }
      L.activity = L.p * c.priority;
    }

    // pass two: the loudest thing present flattens everything quieter
    const lead = layers.reduce((m, L) => Math.max(m, L.activity), 0);

    const now = Tone.now();
    for (const L of layers) {
      const c = L.cfg;
      const duck = 1 - S.duck * Math.max(0, lead - L.activity);
      const g = at(c.curves.gain, L.p) * c.priority * duck;
      L.out = g;

      // ramp everything — nothing is allowed to jump-cut
      L.gain.gain.rampTo(g, 0.25, now);
      L.filter.frequency.rampTo(at(c.curves.lowpass, L.p), 0.3, now);
      L.send.gain.rampTo(at(c.curves.reverb, L.p) * g, 0.3, now);

      const grain = at(c.curves.grain, L.p);
      const detune = at(c.curves.detune, L.p);
      L.grain = grain;
      L.detune = detune;

      if (L.source && L.source.type === 'grain') {
        const p = L.source.node;
        // more grain = shorter fragments, heavier overlap: the recording
        // stops being a recording and becomes a texture of one
        p.grainSize = 0.34 - 0.30 * grain;
        p.overlap = 0.05 + 0.45 * grain;
        p.detune = detune;
      } else if (L.source && L.source.parts) {
        // placeholders have no buffer to granulate, so grain drives an
        // equivalent-depth wobble to keep the control meaningful while tuning
        for (const part of L.source.parts) {
          if (part instanceof Tone.LFO) {
            part.amplitude && part.amplitude.rampTo(0.25 + 0.75 * grain, 0.4, now);
          }
        }
      }
    }
  }

  // --- authoring panel ----------------------------------------------------

  const FIELDS = ['gain', 'lowpass', 'reverb', 'grain', 'detune'];

  function buildPanel() {
    // The per-layer mixer belongs to the anchored voice/oral-history system,
    // which has no recordings yet and so builds no layers. Nothing to show
    // until there are; the pool has its own readout.
    const host = document.getElementById('mixer');
    if (!host) return;
    host.innerHTML = '';

    for (const L of layers) {
      const row = document.createElement('div');
      row.className = 'lay';
      row.innerHTML = `
        <div class="lh">
          <span class="nm">${L.cfg.label}</span>
          <span class="kd">${L.cfg.kind}</span>
        </div>
        <div class="bars">
          <div class="bar"><i data-m="p"></i></div>
          <div class="bar out"><i data-m="out"></i></div>
        </div>
        <div class="nums">
          <label>reach <input type="number" step="20" min="0" data-f="reach"
                 value="${L.cfg.reach ?? ''}" ${L.cfg.reach ? '' : 'disabled'}></label>
          <label>prio <input type="number" step="0.02" min="0" max="1" data-f="priority"
                 value="${L.cfg.priority}"></label>
        </div>
        <div class="live"></div>
        <label class="file">audio<input type="file" accept="audio/*"></label>
      `;
      host.appendChild(row);

      row.querySelector('[data-f="reach"]').oninput = e =>
        L.cfg.reach = e.target.value === '' ? null : +e.target.value;
      row.querySelector('[data-f="priority"]').oninput = e =>
        L.cfg.priority = +e.target.value;

      row.querySelector('input[type=file]').onchange = async e => {
        const f = e.target.files[0];
        if (!f) return;
        row.querySelector('.nm').textContent = L.cfg.label + ' · ' + f.name;
        await attach(L, URL.createObjectURL(f));
      };

      L.ui = {
        p: row.querySelector('[data-m="p"]'),
        out: row.querySelector('[data-m="out"]'),
        live: row.querySelector('.live'),
      };
    }
  }

  function paint() {
    for (const L of layers) {
      if (!L.ui) continue;
      L.ui.p.style.width = (L.p * 100).toFixed(1) + '%';
      L.ui.out.style.width = (Math.min(1, L.out) * 100).toFixed(1) + '%';
      L.ui.live.textContent =
        `${Math.round(at(L.cfg.curves.lowpass, L.p))}hz · ` +
        `rev ${at(L.cfg.curves.reverb, L.p).toFixed(2)} · ` +
        `grain ${L.grain !== undefined ? L.grain.toFixed(2) : '—'}`;
    }
  }

  // What you'd paste back into score.js once the tuning is right.
  function exportScore() {
    return JSON.stringify(layers.map(L => ({
      id: L.cfg.id, kind: L.cfg.kind, label: L.cfg.label,
      anchor: L.cfg.anchor, reach: L.cfg.reach, priority: L.cfg.priority,
      src: typeof L.cfg.src === 'string' && L.cfg.src.startsWith('blob:') ? null : L.cfg.src,
    })), null, 2);
  }

  // Reach circles, so the geography of the mix is visible and not just audible.
  function reachGeoJSON() {
    const features = [];
    for (const def of S.LAYERS) {
      const c = resolve(def);
      if (!c.reach || !c.anchor) continue;
      const ring = [];
      const mLng = 111320 * Math.cos(c.anchor[1] * Math.PI / 180);
      for (let i = 0; i <= 72; i++) {
        const a = (i / 72) * Math.PI * 2;
        ring.push([c.anchor[0] + Math.cos(a) * c.reach / mLng,
                   c.anchor[1] + Math.sin(a) * c.reach / 110540]);
      }
      features.push({
        type: 'Feature',
        properties: { kind: c.kind, priority: c.priority, label: c.label },
        geometry: { type: 'Polygon', coordinates: [ring] },
      });
    }
    return { type: 'FeatureCollection', features };
  }

  return { start, update, paint, exportScore, reachGeoJSON, isStarted: () => started };
})();
