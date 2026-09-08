#!/usr/bin/env python3
"""
The subway lines that join up the places you actually went.

The piece is otherwise a set of islands: dense knots with blank paper between
them, which is true to where you stood but false to how the city is used. You
did not teleport between Brooklyn and midtown. These are the threads.

Deliberately NOT the whole subway map. A segment is kept only if it runs near
ground the trace already lit, so what gets drawn is the part of the network you
personally use — the rest of the system stays off the page.

Run after build.py (it reads buildings.geojson to know what's lit):

    python3 subway.py
"""

import json, math, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

NEAR = 700.0       # metres. how close a segment must run to lit ground.
STEP = 25.0        # metres. resampling interval along each line.
MIN_RUN = 200.0    # metres. drop stubs shorter than this — they read as specks
                   # rather than as connections.
ENDPOINT = "https://overpass-api.de/api/interpreter"


def main():
    lit = json.loads((DATA / "buildings.geojson").read_text())["features"]
    if not lit:
        raise SystemExit("no buildings.geojson — run build.py first")

    pts = []
    for f in lit:
        ring = f["geometry"]["coordinates"][0]
        pts.append((ring[0][0], ring[0][1]))

    lat0 = sum(p[1] for p in pts) / len(pts)
    mx = 111320 * math.cos(math.radians(lat0))
    my = 110540

    w = min(p[0] for p in pts); e = max(p[0] for p in pts)
    s = min(p[1] for p in pts); n = max(p[1] for p in pts)
    pad = 0.02
    bbox = f"{s-pad:.4f},{w-pad:.4f},{n+pad:.4f},{e+pad:.4f}"
    print(f"trace bbox {bbox}")

    # --- fetch ------------------------------------------------------------

    cache = DATA / "osm" / "subway.json"
    if cache.exists():
        print("using cached subway.json")
        raw = json.loads(cache.read_text())
    else:
        q = (f'[out:json][timeout:180];way["railway"="subway"]'
             f'["service"!~"yard|siding|spur"]({bbox});out geom;')
        print("querying Overpass…")
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    ENDPOINT, data=q.encode(),
                    headers={"User-Agent": "spime-selfportrait/0.1 (personal art project)"})
                with urllib.request.urlopen(req, timeout=200) as r:
                    body = r.read()
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(body)
                raw = json.loads(body)
                break
            except Exception as exc:
                print(f"  {type(exc).__name__}, retrying in {20*(attempt+1)}s")
                time.sleep(20 * (attempt + 1))
        else:
            raise SystemExit("could not reach Overpass")

    ways = [e for e in raw["elements"] if e.get("geometry")]
    print(f"{len(ways)} subway ways in the box")

    # --- index the lit ground ---------------------------------------------

    cell = NEAR
    grid = {}
    for lng, lat in pts:
        x, y = (lng - w) * mx, (lat - s) * my
        grid.setdefault((int(x // cell), int(y // cell)), True)

    def near_lit(lng, lat):
        x, y = (lng - w) * mx, (lat - s) * my
        gx, gy = int(x // cell), int(y // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (gx + dx, gy + dy) in grid:
                    return True
        return False

    # --- resample, keep only the used parts -------------------------------

    features = []
    kept_m = total_m = 0.0

    for way in ways:
        line = [(p["lon"], p["lat"]) for p in way["geometry"]]
        run = []
        for a, b in zip(line, line[1:]):
            ax, ay = (a[0] - w) * mx, (a[1] - s) * my
            bx, by = (b[0] - w) * mx, (b[1] - s) * my
            length = math.hypot(bx - ax, by - ay)
            total_m += length
            steps = max(1, int(length // STEP))
            for i in range(steps):
                t = i / steps
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if near_lit(*p):
                    run.append(p)
                elif run:
                    if len(run) * STEP >= MIN_RUN:
                        features.append(run)
                        kept_m += len(run) * STEP
                    run = []
        if run and len(run) * STEP >= MIN_RUN:
            features.append(run)
            kept_m += len(run) * STEP

    out = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {},
         "geometry": {"type": "LineString",
                      "coordinates": [[round(x, 6), round(y, 6)] for x, y in run]}}
        for run in features]}

    path = DATA / "subway.geojson"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(features)} runs, {kept_m/1000:.1f} km kept "
          f"of {total_m/1000:.1f} km in the box")
    print(f"wrote {path.name}  {path.stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
