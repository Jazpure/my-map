#!/usr/bin/env python3
"""
Bake illumination into real city geometry.

Reads the Overpass dumps from fetch.py, works out how much light each building
footprint and each ~20 m street segment receives from the trace, and writes
GeoJSON carrying a `lit` value in 0..1.

Only lit geometry is written. Untouched city never enters the output, so file
size scales with where you've been rather than with the size of the city.

Also writes a coarse level-of-detail layer for zoomed-out views, and simplified
borough outlines for geographic context.
"""

import json, math, sys
from collections import defaultdict
from pathlib import Path

sys.setrecursionlimit(50000)   # simplify() recurses once per retained vertex

from trace import points, Frame, SIGMA, CUTOFF, REACH

HERE = Path(__file__).parent
DATA = HERE / "data"

# --- tunables --------------------------------------------------------------

SEG_LEN = 20.0    # metres. street centrelines are split this finely.
PCTL = 0.985      # brightness normalises to this percentile, not the max, so
                  # one pathological hotspot can't crush everything else dark.
FLOOR = 0.02      # below this a thing counts as untouched and is not written.
                  # this is an editorial knob: raise it and the piece is only
                  # your entrenched habits, lower it and every passing-through
                  # shows up.
LOD_CELL = 110.0  # metres. resolution of the zoomed-out aggregate.
SIMPLIFY = 40.0   # metres. borough outline tolerance.
DENS_CELL = 150.0 # metres. resolution of the built-density field the city
                  # noise pool reads from. Independent of `lit` — this is how
                  # dense the city is, not how much of it you visited.

# ---------------------------------------------------------------------------


def height_of(tags):
    for key in ("height", "building:height"):
        if key in tags:
            try:
                return float(str(tags[key]).split()[0])
            except ValueError:
                pass
    for key in ("building:levels", "levels"):
        if key in tags:
            try:
                return float(str(tags[key]).split()[0]) * 3.2
            except ValueError:
                pass
    return 9.0   # nominal 3-storey rowhouse


def ring_area_m2(ring_m):
    """Shoelace, on metric coordinates."""
    a = 0.0
    for (x0, y0), (x1, y1) in zip(ring_m, ring_m[1:]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


def simplify(pts, tol):
    """Douglas-Peucker. Keeps outlines readable at a fraction of the weight."""
    if len(pts) < 3:
        return pts
    ax, ay = pts[0]
    bx, by = pts[-1]
    dx, dy = bx - ax, by - ay
    span = math.hypot(dx, dy)

    worst, idx = -1.0, 0
    for i, (px, py) in enumerate(pts[1:-1], 1):
        if span == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            d = abs(dy * px - dx * py + bx * ay - by * ax) / span
        if d > worst:
            worst, idx = d, i

    if worst <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:idx + 1], tol)[:-1] + simplify(pts[idx:], tol)


def density_field(buildings, frame):
    """How built-up the ground is, everywhere — not just where the trace went.

    Uses footprint area times storeys rather than footprint alone: a tower and
    a rowhouse cover the same ground but do not hold the same number of people,
    and the city noise pool is trying to track people.

    Note this only has data where fetch.py actually pulled geometry, which is
    the corridors the trace touches. Outside those, cells read 0 and the
    runtime treats that as "quiet" rather than "unknown" — fine here, since
    there's nothing to look at out there either.
    """
    if not buildings:
        return None

    xs = [b["c"][0] for b in buildings]
    ys = [b["c"][1] for b in buildings]
    x0, y0 = min(xs) - DENS_CELL, min(ys) - DENS_CELL
    cols = int((max(xs) + DENS_CELL - x0) // DENS_CELL) + 1
    rows = int((max(ys) + DENS_CELL - y0) // DENS_CELL) + 1

    acc = [0.0] * (cols * rows)
    for b in buildings:
        floors = max(1.0, b["h"] / 3.2)
        cx = int((b["c"][0] - x0) // DENS_CELL)
        cy = int((b["c"][1] - y0) // DENS_CELL)
        if 0 <= cx < cols and 0 <= cy < rows:
            acc[cy * cols + cx] += b["a"] * floors

    live = sorted(v for v in acc if v > 0)
    ref = live[min(len(live) - 1, int(len(live) * 0.97))] if live else 1.0
    values = [round(min(1.0, v / ref), 3) for v in acc]

    lng0, lat0 = frame.to_deg(x0, y0)
    filled = sum(1 for v in values if v > 0)
    print(f"density field {cols}x{rows} cells at {DENS_CELL:.0f} m, "
          f"{filled} occupied ({100*filled/len(values):.0f}%)")

    return {"cell": DENS_CELL, "cols": cols, "rows": rows,
            "origin": [round(lng0, 6), round(lat0, 6)],
            "mx": round(frame.mx, 3), "my": round(frame.my, 3),
            "values": values}


def load_osm():
    """Merge every dump, deduping ways that fall in overlapping fetch boxes."""
    seen = {}
    for path in sorted((DATA / "osm").glob("*.json")):
        for e in json.loads(path.read_text())["elements"]:
            if e.get("geometry") and e["id"] not in seen:
                seen[e["id"]] = e
    return list(seen.values())


def main():
    elements = load_osm()
    pts = points()

    lat0 = sum(p[1] for p in pts) / len(pts)
    lng0 = sum(p[0] for p in pts) / len(pts)
    frame = Frame(lat0, lng0)
    print(f"{len(elements)} unique OSM ways, {len(pts)} trace points")

    # --- collect candidates ------------------------------------------------
    # Each is reduced to a representative point for the light calculation.
    # Rowhouses are ~10 m across and segments are 20 m, both small against
    # SIGMA, so a centroid is a fair stand-in and keeps this linear.

    buildings, streets = [], []

    for e in elements:
        geom, tags = e["geometry"], e.get("tags", {})
        if len(geom) < 2:
            continue

        if "building" in tags:
            ring = [(n["lon"], n["lat"]) for n in geom]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            if len(ring) < 4:
                continue
            ring_m = [frame.to_m(*p) for p in ring]
            cx = sum(x for x, _ in ring_m[:-1]) / (len(ring_m) - 1)
            cy = sum(y for _, y in ring_m[:-1]) / (len(ring_m) - 1)
            buildings.append({"ring": ring, "c": (cx, cy),
                              "h": height_of(tags), "a": ring_area_m2(ring_m)})

        elif "highway" in tags:
            line = [(n["lon"], n["lat"]) for n in geom]
            for a, b in zip(line, line[1:]):
                ax, ay = frame.to_m(*a)
                bx, by = frame.to_m(*b)
                steps = max(1, int(math.hypot(bx - ax, by - ay) // SEG_LEN))
                for i in range(steps):
                    t0, t1 = i / steps, (i + 1) / steps
                    p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
                    p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
                    mid = frame.to_m((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                    streets.append({"line": [p0, p1], "c": mid})

    print(f"{len(buildings)} buildings, {len(streets)} street segments in range")

    # --- deposit light ------------------------------------------------------
    # Walk the trace and add energy to nearby geometry, rather than walking the
    # city and searching for points. Scales with the trace, not with the city.

    targets = buildings + streets
    for t in targets:
        t["lit"] = 0.0

    grid = defaultdict(list)
    for t in targets:
        grid[(int(t["c"][0] // REACH), int(t["c"][1] // REACH))].append(t)

    reach2, denom = REACH ** 2, 2 * SIGMA * SIGMA
    for lng, lat, w in pts:
        px, py = frame.to_m(lng, lat)
        gx, gy = int(px // REACH), int(py // REACH)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for t in grid.get((gx + dx, gy + dy), ()):
                    d2 = (t["c"][0] - px) ** 2 + (t["c"][1] - py) ** 2
                    if d2 < reach2:
                        t["lit"] += w * math.exp(-d2 / denom)

    # --- normalise ----------------------------------------------------------
    # Separately per kind: streets collect more light simply because you walk
    # down them, and a shared scale would blow them out.

    def normalise(items):
        vals = sorted(t["lit"] for t in items if t["lit"] > 0)
        if not vals:
            return
        ref = vals[min(len(vals) - 1, int(len(vals) * PCTL))] or 1.0
        for t in items:
            t["lit"] = round(min(1.0, t["lit"] / ref), 4)

    normalise(buildings)
    normalise(streets)

    lit_b = [b for b in buildings if b["lit"] > FLOOR]
    lit_s = [s for s in streets if s["lit"] > FLOOR]
    print(f"{len(lit_b)}/{len(buildings)} buildings and "
          f"{len(lit_s)}/{len(streets)} segments survive the floor")

    # --- zoomed-out aggregate ----------------------------------------------
    # Rather than drawing thousands of individual footprints at a zoom where
    # each is sub-pixel, collapse them per cell into one block that preserves
    # what actually reads at that distance: total built area, mean height,
    # area-weighted brightness. The block's side is sized so its footprint
    # equals the real footprint it stands in for, so density stays honest.

    cells = defaultdict(list)
    for b in lit_b:
        cells[(int(b["c"][0] // LOD_CELL), int(b["c"][1] // LOD_CELL))].append(b)

    coarse = []
    for (gx, gy), members in cells.items():
        area = sum(m["a"] for m in members)
        if area <= 0:
            continue
        lit = sum(m["lit"] * m["a"] for m in members) / area
        h = sum(m["h"] * m["a"] for m in members) / area
        side = min(LOD_CELL, math.sqrt(area))
        cx, cy = (gx + 0.5) * LOD_CELL, (gy + 0.5) * LOD_CELL
        corners = [(cx - side/2, cy - side/2), (cx + side/2, cy - side/2),
                   (cx + side/2, cy + side/2), (cx - side/2, cy + side/2)]
        ring = [frame.to_deg(x, y) for x, y in corners]
        coarse.append({"ring": ring + [ring[0]], "lit": round(lit, 4), "h": round(h, 1)})

    print(f"{len(coarse)} aggregate cells for low zoom "
          f"({len(lit_b) / max(1, len(coarse)):.1f}x fewer shapes)")

    # --- boroughs -----------------------------------------------------------

    boroughs = []
    raw = DATA / "boroughs_raw.geojson"
    if raw.exists():
        before = after = 0
        for f in json.loads(raw.read_text())["features"]:
            polys = []
            for poly in f["geometry"]["coordinates"]:
                rings = []
                for ring in poly:
                    before += len(ring)
                    s = simplify([tuple(p) for p in ring], SIMPLIFY / 111320.0)
                    if len(s) >= 4:
                        if s[0] != s[-1]:
                            s.append(s[0])
                        rings.append([[round(x, 5), round(y, 5)] for x, y in s])
                        after += len(s)
                if rings:
                    polys.append(rings)
            if polys:
                boroughs.append({
                    "type": "Feature",
                    "properties": {"name": f["properties"].get("boroname", "")},
                    "geometry": {"type": "MultiPolygon", "coordinates": polys},
                })
        print(f"{len(boroughs)} borough outlines, {before} -> {after} vertices")
    else:
        print("no boroughs_raw.geojson, skipping outlines")

    # --- write --------------------------------------------------------------

    def write(name, features):
        path = DATA / name
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                   separators=(",", ":")))
        print(f"  {name}  {path.stat().st_size / 1e6:.2f} MB")

    print("\nwrote:")
    write("buildings.geojson", [{
        "type": "Feature",
        "properties": {"lit": b["lit"], "h": round(b["h"], 1)},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[round(x, 6), round(y, 6)] for x, y in b["ring"]]]},
    } for b in lit_b])

    write("streets.geojson", [{
        "type": "Feature",
        "properties": {"lit": s["lit"]},
        "geometry": {"type": "LineString",
                     "coordinates": [[round(x, 6), round(y, 6)] for x, y in s["line"]]},
    } for s in lit_s])

    write("coarse.geojson", [{
        "type": "Feature",
        "properties": {"lit": c["lit"], "h": c["h"]},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[round(x, 6), round(y, 6)] for x, y in c["ring"]]]},
    } for c in coarse])

    # only rewrite the outlines if we actually have a source for them —
    # without this a re-run without boroughs_raw.geojson silently replaces a
    # good file with an empty collection
    if boroughs:
        write("boroughs.geojson", boroughs)
    else:
        print("  boroughs.geojson  left as-is (no raw source present)")

    # the raw trace itself is no longer served — the page draws the baked
    # geometry and the letters, never the points

    field = density_field(buildings, frame)
    if field:
        path = DATA / "density.json"
        path.write_text(json.dumps(field, separators=(",", ":")))
        print(f"  density.json  {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
