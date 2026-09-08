// ---------------------------------------------------------------------------
// THE SCORE
//
// This is the authored document. Everything about how the piece sounds lives
// here; audio.js only reads it. Edit numbers, reload, listen.
//
// THE ONE IDEA: every layer computes a single value, `p` — its proximity to
// wherever you're looking, from 0 (out of range) to 1 (you're on top of it).
// Every other property of that layer is a curve over p. Volume, how muffled it
// is, how drowned in reverb, how granular and smeared. That's the whole model.
// Nothing switches on or off; everything is a position on a curve.
//
// p is computed from where the map is centred AND how far out you're zoomed.
// Zooming out literally raises you away from the ground, so every anchored
// layer recedes and the global bed is all that's left. Zooming into a
// neighbourhood brings that neighbourhood's material up and pushes the bed
// down. There is no separate "zoom" feature — it's the same distance maths.
// ---------------------------------------------------------------------------

// Curves are breakpoint lists: [[p, value], ...] read left to right,
// p = 0 is far away, p = 1 is right on the anchor. Values interpolate between
// breakpoints, so two points give you a ramp and four give you a shape.

const KINDS = {

  // Always present, everywhere, at low priority. The thing that never fully
  // goes away and never leads. Derived from the movement data as a whole.
  bed: {
    priority: 0.22,
    reach: null,              // null = global, p is always 1
    curves: {
      gain:    [[0, 0.55], [1, 0.55]],
      lowpass: [[0, 2600], [1, 2600]],
      reverb:  [[0, 0.55], [1, 0.55]],
      grain:   [[0, 0.30], [1, 0.30]],
      detune:  [[0, 0],    [1, 0]],
    },
  },

  // Field recording of a neighbourhood. Wide reach, middling priority. Always
  // somewhat smeared — it's meant to read as the texture of a place, not as a
  // recording you're auditing.
  place: {
    priority: 0.50,
    reach: 1400,
    curves: {
      gain:    [[0, 0],    [0.2, 0.10], [0.65, 0.55], [1, 0.80]],
      lowpass: [[0, 420],  [0.45, 1600], [1, 7000]],
      reverb:  [[0, 0.85], [0.5, 0.55],  [1, 0.30]],
      grain:   [[0, 1.0],  [0.5, 0.72],  [1, 0.45]],
      detune:  [[0, -260], [0.6, -70],   [1, -15]],
    },
  },

  // Oral history — someone else's account of this place. Narrower than the
  // field layer and louder than it, so it takes the lead where it exists, but
  // it still arrives already degraded: this is inherited memory, not yours.
  oral: {
    priority: 0.78,
    reach: 800,
    curves: {
      gain:    [[0, 0],    [0.25, 0.12], [0.7, 0.7],  [1, 0.95]],
      lowpass: [[0, 300],  [0.4, 1200],  [0.85, 5200], [1, 9000]],
      reverb:  [[0, 0.9],  [0.55, 0.42], [1, 0.18]],
      grain:   [[0, 1.0],  [0.5, 0.55],  [1, 0.18]],
      detune:  [[0, -340], [0.55, -90],  [1, 0]],
    },
  },

  // Your own voice. Tightest reach, highest priority, and the only layer that
  // resolves to genuinely undistorted at p = 1. Everything else stays a
  // texture; this is the one thing that can come fully into focus.
  voice: {
    priority: 1.00,
    reach: 380,
    curves: {
      gain:    [[0, 0],    [0.3, 0.15], [0.75, 0.8], [1, 1.0]],
      lowpass: [[0, 480],  [0.5, 2400], [1, 18000]],
      reverb:  [[0, 0.8],  [0.6, 0.3],  [1, 0.06]],
      grain:   [[0, 0.9],  [0.6, 0.35], [1, 0.0]],
      detune:  [[0, -220], [0.7, -30],  [1, 0]],
    },
  },
};


// ---------------------------------------------------------------------------
// The layers themselves.
//
// `src` points at a file in audio/. Leave it null and audio.js substitutes a
// synthesised placeholder so the layer is still audible and still responds to
// every control — useful for tuning the geography before the real recordings
// exist. Drop a file onto a layer in the panel to audition it without editing
// this file; the panel's "copy score" button then gives you back JSON to paste
// here once you're happy.
//
// Per-layer `priority`, `reach` and `curves` override the kind's defaults.
// ---------------------------------------------------------------------------

const LAYERS = [
  { id: 'bed',            kind: 'bed',   src: null, label: 'movement bed' },

  { id: 'bedstuy-field',  kind: 'place', src: null, label: 'bed-stuy — street',
    anchor: [-73.9442, 40.6872] },
  { id: 'crown-field',    kind: 'place', src: null, label: 'crown heights — street',
    anchor: [-73.9442, 40.6694] },
  { id: 'wburg-field',    kind: 'place', src: null, label: 'williamsburg — street',
    anchor: [-73.9571, 40.7143] },
  { id: 'prospect-field', kind: 'place', src: null, label: 'prospect park — open',
    anchor: [-73.9690, 40.6602], reach: 1900 },

  { id: 'bedstuy-oral',   kind: 'oral',  src: null, label: 'bed-stuy — oral history',
    anchor: [-73.9448, 40.6884] },
  { id: 'crown-oral',     kind: 'oral',  src: null, label: 'crown heights — oral history',
    anchor: [-73.9430, 40.6702] },

  { id: 'voice-01',       kind: 'voice', src: null, label: 'voice — memory 01',
    anchor: [-73.9440, 40.6876] },
  { id: 'voice-02',       kind: 'voice', src: null, label: 'voice — memory 02',
    anchor: [-73.9700, 40.6612] },
];


const SCORE = {

  // How zoom becomes altitude. At zoomNear you're standing on the ground and
  // only real horizontal distance matters. At zoomFar you're maxAltitude above
  // it, which is far enough that nothing anchored can reach you.
  listener: { zoomNear: 15.5, zoomFar: 11.0, maxAltitude: 3400 },

  // How hard the loudest layer pushes everything quieter than it out of the
  // way. 0 = no hierarchy, all layers just sum. 1 = the leader flattens
  // everything below it. Sidechain logic, one number.
  duck: 0.8,

  master: 0.85,

  // Synthesised stand-ins for layers with no recording yet. Useful while
  // tuning geography against nothing; switch on only when you want to hear
  // where an empty layer WOULD sit.
  placeholders: false,

  KINDS,
  LAYERS,
};

window.SCORE = SCORE;
