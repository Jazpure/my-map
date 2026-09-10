// ---------------------------------------------------------------------------
// Birds.
//
// Drawn birds crossing the page on wide arcs. They are screen-space, not
// geographic: a flock does not pan with the map, it flies its arc and goes.
//
// ALTITUDE. Every flock is born at a zoom — its altitude — and is only visible
// while the camera is within a band of it. Coming down through the zooms you
// pass them: they fade up as you reach their level and fade out below it, and
// they carry on flying whether or not you are there to see them. Nothing about
// a flock is recomputed when you zoom; you simply arrive at its height or
// leave it.
//
//   top view      seen from above, so they belong to the far and middle
//                 views — you are above them
//   three-quarter seen from the side, so they belong to the middle and close
//                 views — you are among them. Rarer, and they take a wider
//                 arc nearer the edge of the frame.
//
// ARCS. A flock travels an elliptical arc at a fixed radius from the centre of
// the screen, entering at one bearing and leaving at another. Because the
// radius never shrinks, the path cannot cross the middle of the page — the
// centre is where the map is being read, and nothing should fly through it.
// ---------------------------------------------------------------------------

const Birds = (() => {

  const CFG = {
    // zoom bands. `spread` is the half-width of the band a flock is visible in
    size: [34, 78],

    // Which way each drawing already faces, in degrees, 0 pointing right and
    // increasing clockwise. A bird is rotated by its heading MINUS this, so
    // the beak leads. Read off the drawings by eye — on the star-shaped top
    // views the head and a wingtip are hard to tell apart, so if one flies
    // backwards this is the number to change.
    faces: {
      q1: 12, q2: 172, q3: 164,
      t1: -90, t2: -112, t3: -108, t4: -110,
      t5: -38, t6: -140, t7: -57, t8: -43,
    },

    // How much a bird grows per zoom level as you come down onto it. Full
    // perspective would be 1.0 and is far too violent across eight levels.
    grow: 0.5,
    growClamp: [0.30, 3.4],

    top:     { zoom: [9.6, 15.2], spread: 1.6, clear: [0.46, 0.72],
               speed: [0.200, 0.410], flock: [1, 3] },
    quarter: { zoom: [14.6, 17.9], spread: 1.3, clear: [0.74, 1.02],
               speed: [0.145, 0.290], flock: [1, 2] },

    maxTop: 3,          // top-view flocks alive at once
    maxQuarter: 1,      // three-quarter flocks alive at once
    quarterOdds: 0.35,  // chance a freed quarter slot is refilled at all
    gapTop: [0.8, 5.5], // seconds before a finished flock is replaced
    gapQuarter: [14, 46],
    idle: 0.35,         // seconds of empty sky before one is launched anyway
    entry: 1.7,         // …and how long it then has to fly in before asking again
    sweep: [1.15, 2.45], // radians between entry and exit bearings
    alpha: 0.94,
  };

  let sheet = null, meta = null, canvas = null, ctx = null;
  // A flock is drawn into this at full strength and then composited once, so
  // birds inside a group occlude each other instead of showing through.
  let buf = null, bctx = null;
  const flocks = [];
  let last = 0, running = false;
  let zoomNow = 12;          // where the camera is, so a flock is born in sight
  let idle = 0;              // seconds since anything was last drawn
  let lastFlew = 0;          // flocks drawn on the most recent frame

  let dpr = 1;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = arr => arr[(Math.random() * arr.length) | 0];

  // --- setup --------------------------------------------------------------

  async function init(container, map) {
    const [img, m] = await Promise.all([
      new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => res(i);
        i.onerror = rej;
        i.src = 'birds/birds.png';
      }),
      fetch('birds/birds.json', { cache: 'no-cache' }).then(r => r.json()),
    ]);
    sheet = img;
    meta = m;

    // The sheet already carries the drawing: a white body with the drawn pen
    // line as its edge, and the filled silhouette in alpha. It is drawn as-is,
    // so a bird is opaque and covers the text it passes over.
    canvas = document.createElement('canvas');
    canvas.id = 'birds';
    container.appendChild(canvas);
    ctx = canvas.getContext('2d');
    buf = document.createElement('canvas');
    bctx = buf.getContext('2d');
    resize();
    new ResizeObserver(resize).observe(container);

    zoomNow = map.getZoom();
    // the first flock is already on its way in when the page opens
    for (let i = 0; i < CFG.maxTop; i++) flocks.push(spawn('top', i * rnd(0.8, 2.6)));
    flocks.push(spawn('quarter', rnd(0, 20)));

    running = true;
    last = performance.now();
    requestAnimationFrame(frame.bind(null, map));
    return meta.birds.length;
  }

  function resize() {
    if (!canvas) return;
    const r = canvas.parentElement.getBoundingClientRect();
    const d = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(r.width * d);
    canvas.height = Math.round(r.height * d);
    canvas.style.width = r.width + 'px';
    canvas.style.height = r.height + 'px';
    ctx.setTransform(d, 0, 0, d, 0, 0);
    buf.width = canvas.width;
    buf.height = canvas.height;
    bctx.setTransform(d, 0, 0, d, 0, 0);
    dpr = d;
  }

  // --- flocks -------------------------------------------------------------

  function spawn(view, delay) {
    const c = CFG[view];
    const pool = meta.birds.filter(b => b.view === view);
    const n = Math.round(rnd(c.flock[0], c.flock[1]));

    // Entry and exit bearings, both well outside the frame. The curve between
    // them bows away from the middle of the screen, so a flock enters from
    // off-page, passes across, and leaves off-page — nothing pops into being
    // mid-air, and the centre stays clear.
    const from = Math.random() * Math.PI * 2;
    const dir = Math.random() < 0.5 ? 1 : -1;
    const sweep = rnd(CFG.sweep[0], CFG.sweep[1]) * dir;
    const size = rnd(CFG.size[0], CFG.size[1]);

    const birds = [];
    for (let i = 0; i < n; i++) {
      birds.push({
        sprite: pick(pool),
        // trailing offsets, so a group reads as a skein rather than a rank
        lead: i === 0 ? 0 : rnd(0.035, 0.10) * i,
        side: i === 0 ? 0 : rnd(-0.55, 0.55),
        scale: rnd(0.82, 1.18),
        flap: Math.random() * Math.PI * 2,
      });
    }

    // Altitude is drawn around where the camera is NOW rather than from the
    // whole band, so a flock is born at a height this view can see. Taken from
    // the band at large, two flights in three were born above or below the
    // frame and flew their arc unseen: the opening view sat empty three
    // fifths of the time, in stretches of up to thirteen seconds. A flock is
    // still fixed at its altitude once born — you can climb away from it or
    // come down onto it, and it is never recomputed to follow you. The clamp
    // is what keeps the top views out of the close zooms.
    const band = c.spread;
    const altitude = Math.max(c.zoom[0], Math.min(c.zoom[1],
                              zoomNow + rnd(-band * 0.9, band * 0.55)));

    return {
      view, birds, from, sweep, size,
      clear: rnd(c.clear[0], c.clear[1]),   // closest approach to the centre
      altitude,
      speed: rnd(c.speed[0], c.speed[1]),
      t: 0,
      // Seconds, counted down in real time. Holding the delay as negative `t`
      // and letting the arc speed consume it made every gap about thirty
      // times longer than intended.
      wait: Math.max(0, delay || 0),
    };
  }

  // The path: a quadratic curve from off-screen to off-screen.
  //
  // Both ends sit at OUT times the half-diagonal, so they are comfortably
  // outside the frame whatever its shape. The control point is placed so the
  // curve's own midpoint — which by symmetry is its closest approach — lands
  // exactly at the requested clearance from the centre. That is what keeps
  // the middle of the page clear without having to test the curve.
  const OUT = 1.35;

  function path(f, w, h) {
    const half = Math.min(w, h) / 2;
    const diag = Math.hypot(w, h) / 2;
    const Rout = OUT * diag;
    const D = f.clear * half;
    const mid = f.from + f.sweep / 2;
    const Rmid = 2 * D - Rout * Math.cos(f.sweep / 2);
    return [
      [w / 2 + Math.cos(f.from) * Rout, h / 2 + Math.sin(f.from) * Rout],
      [w / 2 + Math.cos(mid) * Rmid, h / 2 + Math.sin(mid) * Rmid],
      [w / 2 + Math.cos(f.from + f.sweep) * Rout,
       h / 2 + Math.sin(f.from + f.sweep) * Rout],
    ];
  }

  function at(f, t, w, h) {
    const [p0, p1, p2] = path(f, w, h);
    const u = 1 - t;
    return [u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]];
  }

  // --- frame --------------------------------------------------------------

  function frame(map, now) {
    if (!running) return;
    requestAnimationFrame(frame.bind(null, map));

    // A cap, not a frame budget. At 0.05 anything drawing slower than twenty
    // frames a second flew in slow motion — the map itself runs at about six
    // on integrated graphics with the whole inscription up, so the birds were
    // crossing at a third of the speed they are set to. This still swallows
    // the jump after a tab has been in the background without holding the
    // flight to the frame rate.
    const dt = Math.min(0.2, (now - last) / 1000);
    last = now;
    const w = canvas.width / (ctx.getTransform().a || 1);
    const h = canvas.height / (ctx.getTransform().d || 1);
    ctx.clearRect(0, 0, w, h);

    const zoom = zoomNow = map.getZoom();
    let flew = 0;

    // Draw the higher birds last so they sit over the lower ones. Altitude is
    // held as the zoom a flock lives at, and coming down through the zooms is
    // descending — so the SMALLER altitude is the bird higher in the air, and
    // it takes precedence.
    const order = flocks.map((f, i) => i).sort(
      (a, b) => flocks[b].altitude - flocks[a].altitude);

    for (const i of order) {
      const f = flocks[i];
      if (f.wait > 0) { f.wait -= dt; continue; }
      f.t += dt * f.speed;

      if (f.t > 1.15) {
        const gap = f.view === 'top' ? CFG.gapTop : CFG.gapQuarter;
        flocks[i] = (f.view === 'quarter' && Math.random() > CFG.quarterOdds)
          ? spawn('quarter', rnd(gap[0], gap[1]) * 2)
          : spawn(f.view, rnd(gap[0], gap[1]));
        continue;
      }

      // Altitude only sets a floor. Above it a bird does not fade out — it
      // grows, the way anything does as you come down onto it.
      const band = CFG[f.view].spread;
      const below = (zoom - (f.altitude - band)) / band;
      if (below <= 0) continue;
      const near = Math.min(1, below);

      const grown = Math.min(CFG.growClamp[1],
                    Math.max(CFG.growClamp[0],
                             Math.pow(2, (zoom - f.altitude) * CFG.grow)));

      const edge = Math.min(1, f.t / 0.05, (1.15 - f.t) / 0.08);
      const alpha = CFG.alpha * near * Math.max(0, edge);
      if (alpha <= 0.01) continue;

      // work out where every bird in the flock sits, and the box they cover
      const px = f.size * grown;
      const draw = [];
      let bx0 = 1e9, by0 = 1e9, bx1 = -1e9, by1 = -1e9;
      for (const b of f.birds) {
        const t = f.t - b.lead;
        if (t < 0 || t > 1) continue;
        const [x, y] = at(f, t, w, h);
        const [x2, y2] = at(f, t + 0.004, w, h);
        const heading = Math.atan2(y2 - y, x2 - x);
        const ox = Math.cos(heading + Math.PI / 2) * b.side * px * 1.6;
        const oy = Math.sin(heading + Math.PI / 2) * b.side * px * 1.6;
        const s = px * b.scale;
        const sp = b.sprite;
        const dw = s, dh = s * (sp.ch / sp.cw);
        const cx = x + ox, cy = y + oy;
        const r = Math.max(dw, dh);
        if (cx + r < -40 || cx - r > w + 40 || cy + r < -40 || cy - r > h + 40) continue;
        draw.push({ cx, cy, heading, dw, dh, sp, b });
        bx0 = Math.min(bx0, cx - r); by0 = Math.min(by0, cy - r);
        bx1 = Math.max(bx1, cx + r); by1 = Math.max(by1, cy + r);
      }
      if (!draw.length) continue;

      bx0 = Math.max(0, bx0 - 2); by0 = Math.max(0, by0 - 2);
      bx1 = Math.min(w, bx1 + 2); by1 = Math.min(h, by1 + 2);
      if (bx1 <= bx0 || by1 <= by0) continue;

      bctx.clearRect(bx0, by0, bx1 - bx0, by1 - by0);
      bctx.globalAlpha = 1;
      for (const o of draw) {
        const beat = 1 + Math.sin(now / 1000 * 1.7 + o.b.flap) * 0.045;
        const faces = (CFG.faces[o.sp.name] || 0) * Math.PI / 180;
        bctx.save();
        bctx.translate(o.cx, o.cy);
        bctx.rotate(o.heading - faces);
        bctx.drawImage(sheet, o.sp.x, o.sp.y, meta.cell, meta.cell,
                       -o.dw / 2, -o.dh / 2 * beat, o.dw, o.dh * beat);
        bctx.restore();
      }

      // one composite for the whole flock: the group carries the transparency,
      // never the birds within it
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = alpha;
      const dx = bx0 * dpr, dy = by0 * dpr;
      const dw2 = (bx1 - bx0) * dpr, dh2 = (by1 - by0) * dpr;
      ctx.drawImage(buf, dx, dy, dw2, dh2, dx, dy, dw2, dh2);
      ctx.restore();
      flew++;
    }
    ctx.globalAlpha = 1;

    // Something is always in the air. The gaps between flights are random and
    // the arcs are long, so left alone the page goes quiet for a while at a
    // time; if it has been empty for a moment, whichever flock is nearest to
    // ready is put up now. Only the top views are used for this — the
    // three-quarter birds are meant to be rare and are left rare.
    lastFlew = flew;
    if (flew) {
      idle = 0;
    } else if ((idle += dt) > CFG.idle) {
      let best = -1, soonest = Infinity;
      for (let i = 0; i < flocks.length; i++) {
        if (flocks[i].view !== 'top') continue;
        // one that is counting down beats one already flying somewhere unseen
        const ready = flocks[i].wait > 0 ? flocks[i].wait : 1e6;
        if (ready < soonest) { soonest = ready; best = i; }
      }
      // a launched flock is still outside the frame for a second or so;
      // without this grace the next few would be scrambled after it and all
      // arrive together, leaving the same empty page just after
      if (best >= 0) { flocks[best] = spawn('top', 0); idle = -CFG.entry; }
    }
  }

  const state = () => ({
    onScreen: lastFlew,
    flocks: flocks.map(f => ({ view: f.view, n: f.birds.length,
                               altitude: +f.altitude.toFixed(2),
                               t: +f.t.toFixed(2), wait: +f.wait.toFixed(1),
                               size: Math.round(f.size), clear: +f.clear.toFixed(2) })),
  });

  return { init, state, CFG };
})();
