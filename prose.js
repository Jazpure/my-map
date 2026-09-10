// ---------------------------------------------------------------------------
// The essay, set as ordinary prose across the whole city — and then bent.
//
// TYPESETTING. The text is laid out line by line, left to right, on a fixed
// grid measured in metres, and clipped to the borough outlines by scanline:
// for each line of type, the horizontal is intersected with every boundary
// edge, the crossings are sorted, and characters are only set inside the
// resulting spans. So the writing genuinely fills New York and stops at the
// water. It reads normally wherever it is left alone.
//
// Sized in METRES, unlike the node letters. This text is printed on the city
// at a fixed physical size, so it is a fine dust at the widest view and
// resolves into readable prose as you come down. Nothing about it is
// screen-relative.
//
// GRAVITY. The places you actually went are mass. Each one deforms the text
// around it, and the closer the prose gets the more it gives way:
//
//   pulled    letters slide toward the node, along the gradient of the
//             density field, with a slight rotation so they spiral rather
//             than fall straight in
//   skewed    they turn out of the line of type, progressively, until the
//             notion of a line has gone
//   scattered they jitter off the grid entirely
//   inked     they take on the red / yellow / blue of the node letters and
//             brighten from background grey
//   varied    their uniform size gives way to the same size variation the
//             node letters have
//
// At full influence a prose letter is indistinguishable from a node letter —
// which is the point. There is one text. Where nothing happened to you it lies
// flat and legible; where your life piled up it has been dragged out of shape
// and is no longer readable as language at all.
// ---------------------------------------------------------------------------

const Prose = (() => {

  const CFG = {
    charStep: 55,      // metres between characters along a line
    lineStep: 88,      // metres between lines of type
    // At 30 m the prose was 4 px through the middle zooms — present as a
    // stipple but not identifiable as letters, which is the one thing it has
    // to be. Raised so it resolves as type from about z13 rather than z15.
    // Still well inside the line spacing, so it reads as set text.
    size: 50,          // glyph height in metres
    // The floor, not the size — this is what the far view actually shows,
    // since 30 m is sub-pixel until about z14. Raised so the field is legible
    // as writing at city scale while staying well under the node letters,
    // which are 20-26 px there.
    sizeMinPx: 3.6,
    // Metres-based type grows without limit as you descend — by z17 it was
    // 66 px against 10 px node letters, which inverts the hierarchy exactly
    // where the nodes are supposed to take over. Capped at body-copy size, so
    // the prose reaches a comfortable reading weight, stays there, and then
    // simply fades as the atomiser starts.
    // Lower than before, deliberately. Metres-based type outgrows the node
    // letters once you are close — the cap is what keeps the prose reading as
    // the ground the nodes sit in rather than competing with them.
    sizeMaxPx: 15,

    // background ink: a light pink, well under the node letters. It has to
    // carry at a 2 px mark on cream paper, so it is a touch more saturated
    // than "pale" suggests — anything lighter reads as nothing once the
    // letters are small.
    ink: [230, 152, 164],
    alphaFar: 0.66,    // opacity out in empty country
    alphaNear: 0.95,   // opacity once fully captured

    // PRESENCE ACROSS ZOOM.
    // The wide view keeps the level it has — a secondary ground under the
    // nodes — and the text firms up as you descend, so approaching the page
    // is what makes it readable rather than just larger. It holds through the
    // reading band and then hands over to the atomiser.
    readFrom: 11.0,    // at or below: the far level, unchanged
    readTo: 15.4,      // fully present
    nearBoost: 1.5,    // how much stronger the ink gets by then

    // gravity
    pull: 190,         // metres a letter is dragged toward the mass
    swirl: 0.55,       // radians the pull is rotated by — spiral, not free-fall
    jitter: 90,        // metres of disorder at full influence
    skew: 115,         // degrees a letter may turn out of its line
    // <1 on purpose: it widens the influence so the far field is already
    // leaning slightly. Above 1 the transition collapses into the node and
    // everything outside it lies perfectly flat.
    grip: 0.55,

    sway: 2.0,         // metres of drift, shared with the node letters' wave
    speed: 0.55,
    tick: 0.22,        // seconds between prose repositions

    handShare: 0.40,   // share set in the drawn type rather than Courier

    budget: 140000,
  };

  // --- the gravity field --------------------------------------------------
  // Built from the lit footprints rather than from the raw trace: it is
  // already smoothed by the bake, already normalised, and already the thing
  // the rest of the piece is drawing.

  const Field = (() => {
    // Coarse and heavily blurred on purpose. The first attempt used 170 m
    // with five passes, which spread the influence about 850 m — so 97% of the
    // page sat below 0.1 and the warp only existed inside the nodes
    // themselves. Gravity needs a long reach to read as gravity; the text has
    // to start leaning well before it arrives.
    const CELL = 320;
    let g = null, cols = 0, rows = 0, w0 = 0, s0 = 0, mx = 1, my = 110540;

    function build(buildings) {
      const f = buildings.features;
      if (!f.length) return;
      const pts = f.map(x => {
        const r = x.geometry.coordinates[0];
        let cx = 0, cy = 0;
        for (let i = 0; i < r.length - 1; i++) { cx += r[i][0]; cy += r[i][1]; }
        return [cx / (r.length - 1), cy / (r.length - 1), x.properties.lit || 0];
      });

      const lat0 = pts.reduce((a, p) => a + p[1], 0) / pts.length;
      mx = 111320 * Math.cos(lat0 * Math.PI / 180);

      // pad generously: the field has to keep falling off well outside the
      // built area or the pull stops dead at the edge of the data
      const pad = 2500;
      let w = Infinity, e = -Infinity, s = Infinity, n = -Infinity;
      for (const p of pts) {
        w = Math.min(w, p[0]); e = Math.max(e, p[0]);
        s = Math.min(s, p[1]); n = Math.max(n, p[1]);
      }
      w0 = w - pad / mx; s0 = s - pad / my;
      cols = Math.ceil(((e - w) * mx + 2 * pad) / CELL) + 1;
      rows = Math.ceil(((n - s) * my + 2 * pad) / CELL) + 1;
      g = new Float32Array(cols * rows);

      for (const [lng, lat, lit] of pts) {
        const cx = Math.floor((lng - w0) * mx / CELL);
        const cy = Math.floor((lat - s0) * my / CELL);
        if (cx >= 0 && cx < cols && cy >= 0 && cy < rows) g[cy * cols + cx] += lit;
      }

      // blur hard. The gradient is what letters follow, so a blocky field
      // makes them march in grid-aligned lines instead of curving inward.
      for (let pass = 0; pass < 7; pass++) {
        const t = new Float32Array(g.length);
        for (let y = 0; y < rows; y++) {
          for (let x = 0; x < cols; x++) {
            let sum = 0, k = 0;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                const nx = x + dx, ny = y + dy;
                if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
                sum += g[ny * cols + nx]; k++;
              }
            }
            t[y * cols + x] = sum / k;
          }
        }
        g.set(t);
      }

      const vals = Array.from(g).filter(v => v > 0).sort((a, b) => a - b);
      const ref = vals.length ? vals[Math.floor(vals.length * 0.94)] : 1;
      for (let i = 0; i < g.length; i++) g[i] = Math.min(1, g[i] / (ref || 1));
    }

    const sample = (x, y) =>
      (x < 0 || y < 0 || x >= cols || y >= rows) ? 0 : g[y * cols + x];

    // value plus gradient, bilinear enough for the purpose
    function at(lng, lat) {
      if (!g) return [0, 0, 0];
      const fx = (lng - w0) * mx / CELL, fy = (lat - s0) * my / CELL;
      const x = Math.floor(fx), y = Math.floor(fy);
      const tx = fx - x, ty = fy - y;
      const a = sample(x, y), b = sample(x + 1, y);
      const c = sample(x, y + 1), d = sample(x + 1, y + 1);
      const v = a * (1 - tx) * (1 - ty) + b * tx * (1 - ty)
              + c * (1 - tx) * ty + d * tx * ty;
      const gx = (sample(x + 1, y) - sample(x - 1, y)) * 0.5;
      const gy = (sample(x, y + 1) - sample(x, y - 1)) * 0.5;
      return [v, gx, gy];
    }

    return { build, at };
  })();

  // --- typesetting --------------------------------------------------------

  let P = null;
  let index = new Map();
  const CELL = 0.0022;
  const key = (a, b) => a + ',' + b;
  const clamp01 = x => Math.max(0, Math.min(1, x));

  function hash(i) {
    let x = (i * 1597334677 + 2246822519) >>> 0;
    x = (x ^ (x >>> 15)) >>> 0;
    x = (x * 2654435761) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
  }

  function build(boroughs, text, buildings) {
    viewSig = null;   // any cached glyph list belongs to the old field
    const { mapping, HAND } = Inscription.glyphs();
    const drawn = c => Math.random() < CFG.handShare && !!mapping[c + HAND];
    Field.build(buildings);

    const chars = [...text.replace(/\s+/g, ' ')].filter(c => mapping[c] || c === ' ');

    // every boundary edge, flattened once
    const edges = [];
    let w = Infinity, e = -Infinity, s = Infinity, n = -Infinity;
    for (const f of boroughs.features) {
      const groups = f.geometry.type === 'MultiPolygon'
        ? f.geometry.coordinates : [f.geometry.coordinates];
      for (const rings of groups) {
        for (const ring of rings) {
          for (let i = 0; i < ring.length - 1; i++) {
            edges.push([ring[i][0], ring[i][1], ring[i + 1][0], ring[i + 1][1]]);
          }
          for (const p of ring) {
            w = Math.min(w, p[0]); e = Math.max(e, p[0]);
            s = Math.min(s, p[1]); n = Math.max(n, p[1]);
          }
        }
      }
    }
    if (!edges.length) return null;

    const mx = 111320 * Math.cos(((s + n) / 2) * Math.PI / 180);
    const my = 110540;
    const dLng = CFG.charStep / mx;
    const dLat = CFG.lineStep / my;

    const lng = [], lat = [], ch = [], jit = [], hnd = [];
    let ci = 0;

    // Scanline fill, top to bottom so the text reads down the page the way it
    // would on paper.
    for (let y = n; y >= s; y -= dLat) {
      const xs = [];
      for (const [ax, ay, bx, by] of edges) {
        if ((ay > y) !== (by > y)) {
          xs.push(ax + ((y - ay) / (by - ay)) * (bx - ax));
        }
      }
      if (xs.length < 2) continue;
      xs.sort((a, b) => a - b);

      for (let i = 0; i + 1 < xs.length; i += 2) {
        for (let x = xs[i]; x < xs[i + 1]; x += dLng) {
          const c = chars[ci++ % chars.length];
          if (c === ' ') continue;
          lng.push(x);
          lat.push(y);
          ch.push(c);
          jit.push(0.62 + hash(lng.length * 7) * 0.85);
          hnd.push(drawn(c) ? 1 : 0);
        }
      }
    }

    // The field never changes, so every letter's influence and pull direction
    // is resolved once here rather than re-sampled every frame. That was the
    // whole per-frame cost, and removing it is what allows the page to be
    // filled rather than thinned down to dust.
    const gv = new Float32Array(ch.length);
    const gdx = new Float32Array(ch.length);
    const gdy = new Float32Array(ch.length);
    for (let i = 0; i < ch.length; i++) {
      const [v, dx, dy] = Field.at(lng[i], lat[i]);
      gv[i] = Math.pow(clamp01(v), CFG.grip);
      const len = Math.hypot(dx, dy) || 1;
      // rotated here too: the spiral is a property of the field, not of the
      // frame, so it can be baked with everything else
      const a = Math.atan2(dy / len, dx / len) + CFG.swirl * gv[i];
      gdx[i] = Math.cos(a);
      gdy[i] = Math.sin(a);
    }

    P = {
      n: ch.length,
      lng: new Float64Array(lng), lat: new Float64Array(lat),
      ch, jit: new Float32Array(jit), hnd: new Uint8Array(hnd),
      g: gv, gx: gdx, gy: gdy,
      mx, my,
    };

    index = new Map();
    for (let i = 0; i < P.n; i++) {
      const k = key(Math.floor(P.lng[i] / CELL), Math.floor(P.lat[i] / CELL));
      let b = index.get(k);
      if (!b) index.set(k, b = []);
      b.push(i);
    }
    return P;
  }

  // --- per-frame ----------------------------------------------------------

  let lastCount = 0;
  // the visible glyph list, kept across frames — see `sig` in layer()
  let viewSig = null, viewData = [];

  function layer(map, timeSec) {
    if (!P) return null;
    const zoom = map.getZoom();

    // Prose recedes as the node letters start coming apart: past that point
    // the piece is about one place, not about the field between places.
    const atom = Inscription.bands(zoom).atom;
    const near = clamp01((zoom - CFG.readFrom) / (CFG.readTo - CFG.readFrom));
    // rises, holds through the reading band, then goes with the atomiser
    const show = (1 + (CFG.nearBoost - 1) * near) * (1 - atom);
    if (show <= 0.01) return null;

    // No thinning. The whole point of this layer is that the page is FULL —
    // thinned to a sixth it read as scattered dust rather than as a field of
    // text, which is the one thing it has to be. Drawing all of it is only
    // affordable because the gravity is precomputed and the motion below is
    // quantised.
    const stride = 1;

    const b = map.getBounds();
    const pad = CELL + CFG.pull / 110540;
    const x0 = Math.floor((b.getWest() - pad) / CELL);
    const x1 = Math.floor((b.getEast() + pad) / CELL);
    const y0 = Math.floor((b.getSouth() - pad) / CELL);
    const y1 = Math.floor((b.getNorth() + pad) / CELL);

    // THE LIST OF GLYPHS ON SCREEN, AND WHY IT IS CACHED.
    //
    // deck.gl recalculates every attribute of every instance whenever the
    // `data` reference changes. This array was rebuilt on each frame, so a
    // new reference arrived sixty times a second and all 132k glyphs had
    // their position, size, angle and colour recomputed and re-uploaded even
    // while the map sat perfectly still. It cost about nine tenths of the
    // frame rate: with this layer removed the page ran at 58 fps and with it
    // at 10.
    //
    // The list only actually changes when the visible range of cells does, so
    // it is rebuilt then and the same array handed back otherwise. Movement
    // is unaffected — the drift still arrives through updateTriggers, on its
    // own quantised clock below.
    const sig = x0 + ',' + x1 + ',' + y0 + ',' + y1 + ',' + stride;
    if (sig !== viewSig) {
      viewSig = sig;
      const d = [];
      outer:
      for (let gx = x0; gx <= x1; gx++) {
        for (let gy = y0; gy <= y1; gy++) {
          const bucket = index.get(key(gx, gy));
          if (!bucket) continue;
          for (const i of bucket) {
            if (i % stride) continue;
            if (d.length >= CFG.budget) break outer;
            d.push(i);
          }
        }
      }
      viewData = d;
    }
    const data = viewData;
    lastCount = data.length;

    // Quantised to CFG.tick. Every accessor below is re-evaluated whenever
    // this changes, and there are 130k of them — at 60 Hz that is the entire
    // frame budget spent on background text. A few updates a second is plenty
    // for a drift this slow, and the node letters carry the real movement.
    //
    // And the clock stops entirely while the drift is smaller than a pixel.
    // The sway is measured in metres, so at the opening view a whole one of
    // them is a twentieth of a pixel: the recomputation was moving nothing at
    // all, and moving nothing across the most glyphs the page ever shows.
    const c = map.getCenter();
    const dLng = 0.002;
    const mPerPx = (dLng * 111320 * Math.cos(c.lat * Math.PI / 180))
                 / Math.max(1e-6, Math.abs(map.project([c.lng + dLng, c.lat]).x
                                         - map.project([c.lng, c.lat]).x));
    const moves = CFG.sway * 1.4 / mPerPx > 0.3;
    const t = moves ? Math.round(timeSec * CFG.speed / CFG.tick) * CFG.tick : 0;
    const mx = P.mx, my = P.my;
    const { atlas, mapping, PRIMARIES } = Inscription.glyphs();

    const place = i => {
      const g = P.g[i];
      const d = CFG.pull * g;
      const j = CFG.jitter * Math.pow(g, 1.6);
      const px = P.lng[i] * mx, py = P.lat[i] * my;
      const sway = CFG.sway * (0.4 + g);
      return [
        P.lng[i] + (P.gx[i] * d + (hash(i * 3) - 0.5) * 2 * j
                    + sway * Math.sin(t + px * 0.012)) / mx,
        P.lat[i] + (P.gy[i] * d + (hash(i * 3 + 1) - 0.5) * 2 * j
                    + sway * Math.cos(t * 0.78 + py * 0.010) * 0.7) / my,
      ];
    };

    return new deck.IconLayer({
      id: 'prose',
      data,
      iconAtlas: atlas,
      iconMapping: mapping,
      billboard: false,
      sizeUnits: 'meters',
      sizeMinPixels: CFG.sizeMinPx,
      sizeMaxPixels: CFG.sizeMaxPx,
      getIcon: i => (P.hnd[i] ? P.ch[i] + Inscription.glyphs().HAND : P.ch[i]),
      getPosition: place,
      getSize: i => {
        const g = P.g[i];
        // uniform where it is undisturbed, as varied as the node letters once
        // it has been taken
        return CFG.size * (1 + (P.jit[i] - 1) * g);
      },
      // set flat as a line of type, turned progressively out of it
      getAngle: i => (hash(i * 5) - 0.5) * 2 * CFG.skew * Math.pow(P.g[i], 1.25),
      getColor: i => {
        const g = P.g[i];
        const ink = PRIMARIES[Math.floor(hash(i * 11) * 3)];
        // Ink arrives late. At 0.75 the whole field picked up colour and the
        // background stopped being background — the contrast between quiet
        // prose and captured prose is the entire effect, so the far country
        // has to stay grey.
        const mix = Math.pow(g, 1.7);
        return [
          CFG.ink[0] + (ink[0] - CFG.ink[0]) * mix,
          CFG.ink[1] + (ink[1] - CFG.ink[1]) * mix,
          CFG.ink[2] + (ink[2] - CFG.ink[2]) * mix,
          Math.min(255, 255 * show * (CFG.alphaFar + (CFG.alphaNear - CFG.alphaFar) * mix)),
        ];
      },
      parameters: {
        depthCompare: 'always',
        depthWriteEnabled: false,
        blendColorSrcFactor: 'src-alpha', blendColorDstFactor: 'one-minus-src-alpha',
        blendAlphaSrcFactor: 'one', blendAlphaDstFactor: 'one-minus-src-alpha',
        blendColorOperation: 'add', blendAlphaOperation: 'add',
      },
      updateTriggers: {
        getPosition: [t, stride], getSize: stride,
        getAngle: stride, getColor: [show, stride],
      },
    });
  }

  return { build, layer, CFG, field: Field, stats: () => P, drawn: () => lastCount };
})();
