// ---------------------------------------------------------------------------
// The text, scattered as a free-form field over the city, alive.
//
// PLACEMENT. Letters are no longer set along building outlines. They are
// scattered freely, and the only thing the city decides is HOW MANY land in a
// given place: a building you crossed once seeds a couple of letters, a corner
// you lived on seeds dozens. Neighbouring clouds merge, so what you see is a
// continuous field of text whose thickness is your own movement, rather than
// an architectural drawing that happens to be made of type.
//
// COLOUR. Each letter is fixed at build time to red, yellow or blue — the
// painter's primaries rather than the screen's. They are drawn additively, so
// where the field thickens the letters pile onto each other and climb toward
// white. Brightening and obscuring are the same act, not two effects.
//
// DISTANCE. Legibility is a band, not a ramp. Far out the letters are faint
// and small, a texture you can tell is writing without reading it. At middle
// distance they resolve — this is where the piece is meant to be read. Closer
// still they atomise: each letter breaks into the particles it was made of and
// those drift apart, so arriving at a place destroys the ability to read it.
// You can be near enough to see, or near enough to read, but not both.
//
// MOVEMENT. One coherent wave crosses the whole field rather than per-letter
// jitter, so neighbours lean together. Amplitude rises with density: quiet
// ground breathes, crowded ground agitates.
// ---------------------------------------------------------------------------

const Inscription = (() => {

  const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,\'!?-;:';
  const BOX = 64;

  // Red, yellow, blue as INKS. These are multiplied onto the paper rather
  // than added to black, so overlap darkens: red x yellow is a deep orange,
  // red x blue is nearly black, all three together are black. The page fills
  // in where you went most, which is the same accumulation the density image
  // uses and the same one a print does.
  const PRIMARIES = [[214, 46, 38], [240, 196, 32], [28, 62, 168]];

  const CFG = {
    // Share of letters set in the drawn type rather than Courier. Chosen per
    // letter at build time, so a given letter keeps its face for the session
    // and nothing shimmers between the two.
    handShare: 0.40,

    seedMin: 1,        // letters seeded by a barely-visited building
    seedMax: 34,       // extra letters at full density
    spread: 21,        // metres a building scatters its letters across
    // Sized so a letter is roughly 18-20 px through the reading band. At 4 m
    // the type was technically present but only ever read as coloured specks —
    // the band has to land where the glyphs are genuinely resolvable.
    size: 8.0,         // glyph height in metres
    swell: 4.0,        // extra height where the field is thick
    sway: 0.5,
    swayLit: 2.4,
    speed: 0.55,

    // TYPOGRAPHIC CASCADE.
    // Letters are sized in screen pixels, not metres, and every letter is
    // assigned a level at build time. Only the coarsest level exists when you
    // are far out — few letters, set large — and each finer level fades in as
    // you approach while the whole field shrinks. So the text does not fade
    // up out of nothing; it REFINES. Big sparse type resolves into smaller,
    // denser type, the way a poster read across a room becomes body copy in
    // the hand.
    //
    // Sizing in pixels is what makes this possible. In metres the letters
    // shrank with the map and the far view emptied out no matter how the
    // opacity was tuned.
    // Five levels rather than four. The extra one at the bottom is what lets
    // you pull back to the whole city and still have something on the page —
    // without it the coarsest type began at z11.4 and anything wider was a
    // blank sheet. The reading band and the atomiser are untouched; this only
    // extends the range downwards.
    levelAt: [9.8, 11.6, 13.1, 14.6, 15.9],   // zoom each level fades in at
    levelSpan: 1.0,                            // how long that fade takes
    levelScale: [1.3, 1.2, 1.1, 1.0, 0.92],    // relative size, coarsest first
    // cumulative share of letters at or above each level. Steep on purpose:
    // the city-wide view is a scattering of a few hundred letters, and each
    // step closer roughly triples what is on the page.
    levelCut: [0.007, 0.035, 0.13, 0.37],
    // Two things to satisfy at once: the far view must not be clunky, and the
    // middle must stay readable. Dropping the base size fixed the first and
    // broke the second — at 0.80 per level the type was down to 6-9 px right
    // where it is meant to be read. A gentler shrink keeps the whole range
    // usable, and the depth variation below is what removes the clunkiness
    // rather than sheer smallness.
    sizeFar: 21,       // pixel height at sizeZoom
    sizeZoom: 10.5,
    shrink: 0.86,      // size multiplier per zoom level closer
    sizeMin: 5,
    sizeMax: 34,

    // DEPTH.
    // Each letter carries how far out of the mass it sits, and that drives
    // its size: letters near the core are set large, letters thrown to the
    // outskirts are small. Size reading as distance is what gives the
    // scattered field volume instead of flatness — and near letters are drawn
    // over far ones so the overlaps agree with it.
    depthNear: 1.45,   // size multiplier at the core
    depthFar: 0.34,    // size multiplier at the outer edge
    // Depth alone is radial, so it reads as a gradient rather than as
    // variety. A fixed per-letter jitter on top breaks that up and stops the
    // wide view looking like uniform type sprayed evenly over the page.
    jitterLo: 0.62,
    jitterHi: 1.45,
    depthFade: 0.72,   // how much the outermost letters lighten
    depthFlat: 0.45,   // how much variation survives once fully gathered

    // CONSTRICTION.
    // Far out, every letter is displaced from where it belongs by up to
    // scatterFar metres, so the trace reads as a loose mass that only alludes
    // to its shape. Coming closer pulls each letter back onto its true
    // position and the mass tightens into the actual form. Past that, the
    // atomiser takes over and throws it apart again — so the arc across the
    // whole zoom range is diffuse, then coherent, then destroyed.
    // Wider too, since at city scale 700 m is a rounding error. The curve is
    // unchanged, so the gathering still resolves at the same zooms.
    scatterFar: 1900,  // metres of displacement at the widest view
    scatterFrom: 9.8,  // fully scattered at or below this zoom
    scatterTo: 15.8,   // fully gathered at or above this zoom

    goneZoom: 18.4,    // letters entirely dispersed

    atomStart: 16.3,   // letters begin breaking apart
    atomFull: 18.4,
    atomsPer: 3,
    atomSpread: 7.0,   // metres the particles drift apart by

    // Threads along the subway, joining the places you actually went. They
    // are faint, small, and barely scattered — the nodes are allowed to
    // disperse into a mass, but a connection has to stay legible as a line or
    // it stops connecting anything.
    linkStep: 105,     // metres between letters along a line
    linkFade: 0.52,
    linkScale: 0.62,
    linkScatter: 0.16, // fraction of the normal displacement

    budget: 42000,
  };

  let L = null;
  let index = new Map();
  let atlas = null, mapping = null;
  let hand = null;                 // { sheet, meta } once loaded
  const HAND = '\u0001';           // suffix marking a hand-drawn variant
  const CELL = 0.0022;
  const key = (a, b) => a + ',' + b;
  const clamp01 = x => Math.max(0, Math.min(1, x));

  // Measure where Courier actually puts its ink inside a cell, so the drawn
  // glyphs can be set on the same baseline at the same cap and x heights.
  // Guessing these from font size alone does not work — canvas 'middle'
  // baseline is the middle of the em, not of the letter.
  function metricsOf(ctx, ch) {
    ctx.clearRect(0, 0, BOX, BOX);
    ctx.fillText(ch, BOX / 2, BOX / 2 + 1);
    const d = ctx.getImageData(0, 0, BOX, BOX).data;
    let top = BOX, bottom = 0;
    for (let y = 0; y < BOX; y++) {
      for (let x = 0; x < BOX; x++) {
        if (d[(y * BOX + x) * 4 + 3] > 40) { if (y < top) top = y; if (y > bottom) bottom = y; }
      }
    }
    return { top, bottom };
  }

  function buildAtlas() {
    const c = document.createElement('canvas');
    c.width = BOX * GLYPHS.length;
    c.height = BOX * 2;            // row 0 Courier, row 1 the drawn type
    const g = c.getContext('2d');
    g.fillStyle = '#fff';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.font = `600 ${Math.round(BOX * 0.74)}px "Courier New", Courier, ui-monospace, monospace`;
    mapping = {};
    for (let i = 0; i < GLYPHS.length; i++) {
      g.fillText(GLYPHS[i], i * BOX + BOX / 2, BOX / 2 + 1);
      mapping[GLYPHS[i]] = {
        x: i * BOX, y: 0, width: BOX, height: BOX,
        anchorX: BOX / 2, anchorY: BOX / 2, mask: true,
      };
    }

    if (hand) {
      // one scratch cell, same font settings, to read Courier's own metrics
      const s = document.createElement('canvas');
      s.width = s.height = BOX;
      const sg = s.getContext('2d', { willReadFrequently: true });
      sg.fillStyle = '#fff';
      sg.textAlign = 'center';
      sg.textBaseline = 'middle';
      sg.font = g.font;
      const H = metricsOf(sg, 'H');
      const X = metricsOf(sg, 'x');
      const base = H.bottom + 1;
      const REF = { upper: base - H.top, lower: base - X.top };
      REF.punct = REF.lower;

      const M = hand.meta;
      for (let i = 0; i < GLYPHS.length; i++) {
        const ch = GLYPHS[i];
        const e = M.glyphs[ch];
        if (!e) continue;                       // no drawn form; keeps Courier
        const k = (REF[e.set] || REF.lower) / M.ref;
        // the sprite's own baseline lands on Courier's baseline, and the cell
        // is centred, so a swapped letter occupies the same ink box
        g.drawImage(hand.sheet, e.x, e.y, e.w, e.h,
                    i * BOX + BOX / 2 - (e.w * k) / 2,
                    BOX + base - M.baseline * k,
                    e.w * k, e.h * k);
        mapping[ch + HAND] = {
          x: i * BOX, y: BOX, width: BOX, height: BOX,
          anchorX: BOX / 2, anchorY: BOX / 2, mask: true,
        };
      }
    }
    atlas = c;
  }

  // Must run before build(); the atlas is assembled once and the drawn cells
  // have to be in it by then.
  async function loadHand(sheetUrl, metaUrl) {
    const [sheet, meta] = await Promise.all([
      new Promise((res, rej) => {
        const im = new Image();
        im.onload = () => res(im);
        im.onerror = rej;
        im.src = sheetUrl;
      }),
      fetch(metaUrl, { cache: 'no-cache' }).then(r => r.json()),
    ]);
    hand = { sheet, meta };
    atlas = null;                  // force a rebuild that includes the type
    return Object.keys(meta.glyphs).length;
  }

  // --- placement ----------------------------------------------------------

  function build(geojson, text, links) {
    viewSig = null;   // any cached letter list belongs to the old field
    if (!atlas) buildAtlas();
    const feats = geojson.features;
    if (!feats.length) return null;

    const chars = [...text.replace(/\s+/g, ' ')].filter(ch => mapping[ch]);
    let ci = 0;

    // a letter is set in the drawn type if one was drawn for it — the
    // specimen has no apostrophe or hyphen, so those always stay Courier
    const drawn = c => Math.random() < CFG.handShare && !!mapping[c + HAND];

    let lat0 = 0;
    for (const f of feats) lat0 += f.geometry.coordinates[0][0][1];
    lat0 /= feats.length;
    const mx = 111320 * Math.cos(lat0 * Math.PI / 180);
    const my = 110540;

    const lng = [], lat = [], ch = [], col = [], ang = [], lit = [], ph = [], lvl = [], ox = [], oy = [], dep = [], jit = [], link = [], hnd = [];

    for (const f of feats) {
      const ring = f.geometry.coordinates[0];
      const v = clamp01(f.properties.lit || 0);

      // seed point: the building's centre, but the letters do not stay there
      let cx = 0, cy = 0;
      for (let i = 0; i < ring.length - 1; i++) { cx += ring[i][0]; cy += ring[i][1]; }
      cx /= ring.length - 1; cy /= ring.length - 1;

      const n = Math.round(CFG.seedMin + CFG.seedMax * Math.pow(v, 0.8));
      for (let i = 0; i < n; i++) {
        // uniform inside a disc — sqrt keeps them from bunching at the centre
        const a = Math.random() * Math.PI * 2;
        const r = Math.sqrt(Math.random()) * CFG.spread;
        lng.push(cx + (Math.cos(a) * r) / mx);
        lat.push(cy + (Math.sin(a) * r) / my);
        ch.push(chars[ci++ % chars.length]);
        col.push((Math.random() * 3) | 0);
        // power-law: the coarse levels are rare, so the far view is sparse
        // and every step closer roughly triples what is on the page
        const tier = Math.random();
        let L4 = CFG.levelCut.length;
        for (let k = 0; k < CFG.levelCut.length; k++) {
          if (tier < CFG.levelCut[k]) { L4 = k; break; }
        }
        lvl.push(L4);
        // where this letter drifts to when the field is scattered — a fixed
        // direction per letter, so gathering and dispersing are the same
        // motion run forwards and backwards rather than a reshuffle
        const oa = Math.random() * Math.PI * 2;
        const orr = Math.sqrt(Math.random());
        ox.push(Math.cos(oa) * orr);
        oy.push(Math.sin(oa) * orr);
        dep.push(orr);          // 0 at the core, 1 at the outskirts
        jit.push(CFG.jitterLo + Math.random() * (CFG.jitterHi - CFG.jitterLo));
        link.push(0);
        hnd.push(drawn(ch[ch.length - 1]) ? 1 : 0);
        ang.push((Math.random() - 0.5) * 44);   // loose, still readable
        lit.push(v);
        ph.push(Math.random() * Math.PI * 2);
      }
    }

    // --- the connective threads -----------------------------------------
    // Same text, same inks, continuing the same sentence — these are not a
    // separate annotation layer, they are the writing carrying on between the
    // places it was densest.
    if (links && links.features) {
      for (const f of links.features) {
        const line = f.geometry.coordinates;
        // Distance carries across segment boundaries. The subway runs are
        // resampled at 25 m and the letter spacing is four times that, so a
        // per-segment counter never reaches the threshold and you get exactly
        // one letter per run — which is what happened the first time.
        let since = CFG.linkStep;
        for (let i = 0; i < line.length - 1; i++) {
          const [ax, ay] = line[i], [bx, by] = line[i + 1];
          const len = Math.hypot((bx - ax) * mx, (by - ay) * my);
          if (len < 1e-6) continue;
          let pos = 0;
          while (since + (len - pos) >= CFG.linkStep) {
            pos += CFG.linkStep - since;
            since = 0;
            const t = pos / len;
            const oa = Math.random() * Math.PI * 2;
            const orr = Math.sqrt(Math.random());
            lng.push(ax + (bx - ax) * t);
            lat.push(ay + (by - ay) * t);
            ch.push(chars[ci++ % chars.length]);
            col.push((Math.random() * 3) | 0);
            ang.push((Math.random() - 0.5) * 30);
            lit.push(0.05);
            ph.push(Math.random() * Math.PI * 2);
            // Biased hard toward the coarse levels, unlike the nodes. A
            // connection is only doing its job in the wide view — by the time
            // you are close enough to read individual letters you are inside
            // one place and no longer need to be shown how it joins another.
            // Left on the node distribution these appeared at 0.7% strength
            // and the threads were invisible exactly where they mattered.
            const tier = Math.random();
            lvl.push(tier < 0.30 ? 0 : tier < 0.75 ? 1 : 2);
            ox.push(Math.cos(oa) * orr);
            oy.push(Math.sin(oa) * orr);
            dep.push(orr);
            jit.push(CFG.jitterLo + Math.random() * (CFG.jitterHi - CFG.jitterLo));
            link.push(1);
            hnd.push(drawn(ch[ch.length - 1]) ? 1 : 0);
          }
          since += len - pos;
        }
      }
    }

    L = {
      n: ch.length,
      lng: new Float64Array(lng), lat: new Float64Array(lat),
      ch, col: new Uint8Array(col),
      ang: new Float32Array(ang), lit: new Float32Array(lit),
      ph: new Float32Array(ph),
      lvl: new Uint8Array(lvl),
      ox: new Float32Array(ox), oy: new Float32Array(oy),
      dep: new Float32Array(dep),
      jit: new Float32Array(jit), link: new Uint8Array(link),
      hnd: new Uint8Array(hnd),
      mx, my,
    };

    index = new Map();
    for (let i = 0; i < L.n; i++) {
      const k = key(Math.floor(L.lng[i] / CELL), Math.floor(L.lat[i] / CELL));
      let b = index.get(k);
      if (!b) index.set(k, b = []);
      b.push(i);
    }
    // painter's order, once, per bucket: deepest first so the letters nearest
    // the core draw over the ones thrown furthest out. Sorting locally is
    // enough because overlaps only ever happen between neighbours, and doing
    // it here costs nothing per frame.
    for (const b of index.values()) b.sort((p, q) => L.dep[q] - L.dep[p]);
    return L;
  }

  // --- zoom response ------------------------------------------------------

  // Distance is now carried by the cascade, so this only reports the overall
  // ink strength and how far the letters have come apart.
  function bands(zoom) {
    const C = CFG;
    const atom = clamp01((zoom - C.atomStart) / (C.atomFull - C.atomStart));
    // ink stays fully opaque until the letters start dispersing
    const legible = 1 - 0.9 * atom;
    return { legible, atom };
  }

  // how present a given level is at this zoom: 0 before it appears, 1 after
  function levelAlpha(l, zoom) {
    const a = CFG.levelAt[l];
    return clamp01((zoom - a) / CFG.levelSpan);
  }

  // metres of displacement at this zoom: full at scatterFrom, nothing at
  // scatterTo, eased so the gathering happens mostly as you close in
  function scatterAt(zoom) {
    const t = clamp01((CFG.scatterTo - zoom) / (CFG.scatterTo - CFG.scatterFrom));
    return CFG.scatterFar * Math.pow(t, 1.5);
  }

  // screen height of a letter, before its level's relative scale
  function baseSize(zoom) {
    const px = CFG.sizeFar * Math.pow(CFG.shrink, zoom - CFG.sizeZoom);
    return Math.max(CFG.sizeMin, Math.min(CFG.sizeMax, px));
  }

  // deterministic per-particle offsets, so a letter always comes apart the
  // same way rather than boiling
  function hash(i) {
    let x = (i * 2246822519 + 374761393) >>> 0;
    x = (x ^ (x >>> 13)) >>> 0;
    x = (x * 3266489917) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
  }

  // --- per-frame ----------------------------------------------------------

  let lastCount = 0;
  // the visible letter list, kept across frames — see `sig` in layer()
  let viewSig = null, viewData = [];

  function layer(map, timeSec) {
    if (!L) return [];
    const zoom = map.getZoom();
    const { legible, atom } = bands(zoom);
    if (legible <= 0 && atom <= 0) return [];

    const alphaFor = CFG.levelAt.map((_, l) => levelAlpha(l, zoom));
    if (alphaFor.every(a => a <= 0)) return [];
    const base = baseSize(zoom);
    const scatter = scatterAt(zoom);
    // depth reads hardest while the field is thrown apart; once it has
    // gathered, the type evens out into a coherent block
    const spread = CFG.scatterFar > 0 ? scatter / CFG.scatterFar : 0;
    const depthMix = CFG.depthFlat + (1 - CFG.depthFlat) * spread;
    const sizeAt = i => {
      const d = L.dep[i];
      const m = CFG.depthNear + (CFG.depthFar - CFG.depthNear) * Math.pow(d, 0.8);
      return 1 + (m - 1) * depthMix;
    };

    const b = map.getBounds();
    // a letter whose home is off-screen can scatter into view, so the cull
    // has to be widened by however far the field is currently thrown
    const pad = CELL + scatter / 110540;
    const x0 = Math.floor((b.getWest() - pad) / CELL);
    const x1 = Math.floor((b.getEast() + pad) / CELL);
    const y0 = Math.floor((b.getSouth() - pad) / CELL);
    const y1 = Math.floor((b.getNorth() + pad) / CELL);

    // Held across frames. A fresh array is a fresh data reference, and deck
    // treats that as everything having changed — every attribute of every
    // letter rebuilt, rather than only the ones whose triggers moved. The
    // list itself changes only when the visible cells do, or when a level of
    // type comes in or goes out.
    const live = alphaFor.map(a => (a > 0.01 ? 1 : 0)).join('');
    const sig = x0 + ',' + x1 + ',' + y0 + ',' + y1 + ',' + live;
    if (sig !== viewSig) {
      viewSig = sig;
      const d = [];
      outer:
      for (let gx = x0; gx <= x1; gx++) {
        for (let gy = y0; gy <= y1; gy++) {
          const bucket = index.get(key(gx, gy));
          if (!bucket) continue;
          for (const i of bucket) {
            // a level that has not appeared yet costs nothing to skip here
            if (alphaFor[L.lvl[i]] <= 0.01) continue;
            if (d.length >= CFG.budget) break outer;
            d.push(i);
          }
        }
      }
      viewData = d;
    }
    const data = viewData;
    lastCount = data.length;

    const t = timeSec * CFG.speed;
    const mx = L.mx, my = L.my;

    // the coherent wave, shared by letters and by their particles
    const drift = i => {
      const amp = CFG.sway + CFG.swayLit * L.lit[i];
      const px = L.lng[i] * mx, py = L.lat[i] * my;
      const sc = L.link[i] ? scatter * CFG.linkScatter : scatter;
      return [amp * Math.sin(t + px * 0.012 + L.ph[i] * 0.25) + L.ox[i] * sc,
              amp * Math.cos(t * 0.78 + py * 0.010 + L.ph[i] * 0.25) * 0.7 + L.oy[i] * sc];
    };

    const tint = (i, mul) => {
      const p = PRIMARIES[L.col[i]];
      // On paper, "fainter" means closer to the page rather than closer to
      // black, so sparse ground gets a washed-out ink and dense ground gets
      // it at full strength.
      const k = INK_MIN + (1 - INK_MIN) * L.lit[i];
      return [255 - (255 - p[0]) * k,
              255 - (255 - p[1]) * k,
              255 - (255 - p[2]) * k,
              255 * mul];
    };

    const layers = [];

    if (legible > 0.004) {
      layers.push(new deck.IconLayer({
        id: 'inscription',
        data,
        iconAtlas: atlas,
        iconMapping: mapping,
        billboard: false,
        sizeUnits: 'pixels',
        getIcon: i => (L.hnd[i] ? L.ch[i] + HAND : L.ch[i]),
        // the field shrinks as a whole, and each level sits at its own
        // relative weight within it
        getSize: i => base * CFG.levelScale[L.lvl[i]] * sizeAt(i) * L.jit[i]
          * (L.link[i] ? CFG.linkScale : 1) * (1 + 0.22 * L.lit[i]),
        getColor: i => tint(i, legible * alphaFor[L.lvl[i]]
          * (1 - (1 - CFG.depthFade) * L.dep[i] * depthMix)
          * (L.link[i] ? CFG.linkFade : 1)),
        getPosition: i => {
          const d = drift(i);
          return [L.lng[i] + d[0] / mx, L.lat[i] + d[1] / my];
        },
        getAngle: i => L.ang[i] + 7 * Math.sin(t * 0.9 + L.ph[i]),
        parameters: ADDITIVE,
        updateTriggers: { getPosition: [t, scatter], getAngle: t, getColor: [legible, zoom, depthMix], getSize: [zoom, depthMix] },
      }));
    }

    if (atom > 0.004) {
      // each letter breaks into a few particles that push outward as you
      // close in — arriving somewhere is what destroys its legibility
      const parts = [];
      const cap = Math.min(data.length, Math.floor(CFG.budget / CFG.atomsPer));
      for (let k = 0; k < cap; k++) {
        for (let a = 0; a < CFG.atomsPer; a++) parts.push(data[k] * 4 + a);
      }
      layers.push(new deck.ScatterplotLayer({
        id: 'inscription-atoms',
        data: parts,
        radiusUnits: 'pixels',
        antialiasing: true,
        getPosition: p => {
          const i = Math.floor(p / 4), a = p % 4;
          const d = drift(i);
          const ang = hash(p) * Math.PI * 2;
          const rad = (0.35 + hash(p + 7) * 1.0) * CFG.atomSpread * Math.pow(atom, 1.3);
          return [L.lng[i] + (d[0] + Math.cos(ang) * rad) / mx,
                  L.lat[i] + (d[1] + Math.sin(ang) * rad) / my];
        },
        getRadius: p => {
          const i = Math.floor(p / 4);
          return base * CFG.levelScale[L.lvl[i]] * sizeAt(i) * L.jit[i] * 0.16 * (0.6 + 0.8 * atom);
        },
        getFillColor: p => tint(Math.floor(p / 4), atom * alphaFor[L.lvl[Math.floor(p / 4)]]),
        parameters: ADDITIVE,
        updateTriggers: { getPosition: [t, atom, scatter], getFillColor: [atom, zoom], getRadius: [atom, zoom, depthMix] },
      }));
    }

    return layers;
  }

  // Full-strength ink everywhere. Nothing is watered down per letter and
  // nothing mixes: density is legible purely as how many letters land in one
  // place, never as a colour shift.
  const INK_MIN = 0.92;

  // Plain source-over. Overlapping letters cover each other and each stays
  // red, yellow or blue — no multiplying to black, no adding to white. A
  // crowded block is illegible because it is crowded, not because it has
  // turned into a blot.
  const ADDITIVE = {
    depthCompare: 'always',
    depthWriteEnabled: false,
    blendColorSrcFactor: 'src-alpha', blendColorDstFactor: 'one-minus-src-alpha',
    blendAlphaSrcFactor: 'one', blendAlphaDstFactor: 'one-minus-src-alpha',
    blendColorOperation: 'add', blendAlphaOperation: 'add',
  };

  // Prose draws from the same glyph sheet — one texture upload, one typeface,
  // and the background text is unmistakably the same writing as the letters
  // caught in the nodes.
  function glyphs() {
    if (!atlas) buildAtlas();
    return { atlas, mapping, GLYPHS, PRIMARIES, HAND, hasHand: c => !!(hand && hand.meta.glyphs[c]) };
  }

  return { build, layer, bands, levelAlpha, baseSize, scatterAt, glyphs, loadHand, CFG, stats: () => L, drawn: () => lastCount };
})();
