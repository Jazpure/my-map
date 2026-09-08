"""The movement data itself.

Everything else in the pipeline imports `points()` from here, so swapping the
placeholder for the real Takeout / EXIF export is a single-file change.
"""

import json, math, random
from pathlib import Path

# --- tunables shared across the pipeline -----------------------------------

SIGMA = 34.0      # metres. how far a GPS point's light spreads.
CUTOFF = 3.0      # in sigmas. beyond this, contribution is ignored.
REACH = SIGMA * CUTOFF


def points():
    """The trace, as (lng, lat, weight) triples.

    Weight is how much of your life a point represents: a passing GPS ping is
    1, somewhere you sat for an hour is worth more. ingest.py works it out
    from dwell time and caps it, so home is heavy but not blinding.

    If data/trace.json exists it wins. Otherwise you get the synthetic stand-in
    so the pipeline still runs end to end with nothing plugged in.
    """
    real = Path(__file__).parent / "data" / "trace.json"
    if real.exists():
        return [tuple(p) for p in json.loads(real.read_text())]
    return _synthetic()


def _synthetic():
    """Placeholder movement data, used only until a real export lands."""
    rnd = random.Random(20260812)
    gauss = lambda: sum(rnd.random() for _ in range(4)) / 2 - 1

    haunts = [
        (-73.9442, 40.6872, 3200), (-73.9442, 40.6694, 1400),
        (-73.9571, 40.7143, 1100), (-73.9212, 40.6944, 800),
        (-73.9690, 40.6602, 900),  (-73.9750, 40.6892, 600),
        (-73.9903, 40.7033, 400),  (-73.9876, 40.7185, 500),
    ]
    routes = [(0,1),(0,2),(0,5),(1,4),(2,7),(5,6),(0,3),(5,4)]

    pts = []
    for lng, lat, n in haunts:
        for _ in range(n):
            pts.append((lng + gauss() * 0.0045, lat + gauss() * 0.0034, 1.0))
    for a, b in routes:
        for _ in range(rnd.randint(6, 28)):
            ox, oy = gauss() * 0.004, gauss() * 0.003
            for s in range(91):
                f = s / 90
                bend = math.sin(f * math.pi)
                pts.append((
                    haunts[a][0] + (haunts[b][0] - haunts[a][0]) * f + ox * bend + gauss() * 0.0006,
                    haunts[a][1] + (haunts[b][1] - haunts[a][1]) * f + oy * bend + gauss() * 0.0005,
                    1.0,
                ))
    return pts


class Frame:
    """Flat local metric projection. Accurate to well under a metre at city scale."""

    def __init__(self, lat0, lng0):
        self.lat0, self.lng0 = lat0, lng0
        self.mx = 111320.0 * math.cos(math.radians(lat0))
        self.my = 110540.0

    def to_m(self, lng, lat):
        return ((lng - self.lng0) * self.mx, (lat - self.lat0) * self.my)

    def to_deg(self, x, y):
        return (self.lng0 + x / self.mx, self.lat0 + y / self.my)
