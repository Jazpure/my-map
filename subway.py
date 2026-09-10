#!/usr/bin/env python3
"""
The subway lines that join up the places you actually went.

The piece is otherwise a set of islands: dense knots with blank paper between
them, which is true to where you stood but false to how the city is used. You
did not teleport between Brooklyn and midtown. These are the threads.

Deliberately NOT the whole subway map. A segment is kept only if it runs near
ground the trace already lit, so what gets drawn is the part of the network you
personally use — the rest of the system stays off the page.

That rule alone leaves the uptown days stranded. Inwood and East Harlem are lit
but small, and the track between them and downtown crosses miles of ground the
trace never touched, so the near-lit test drops exactly the part that does the
connecting. The second stage repairs that: the network is walked as a graph and
the shortest run of real track between two places is kept whole, whether or not
the ground under it was ever visited. Only the gaps are emitted — where the
route passes ground already lit, the first stage has drawn it — so the two
stages meet rather than overprint.

Run after build.py (it reads buildings.geojson to know what's lit):

    python3 subway.py
"""

import heapq, json, math, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

NEAR = 700.0       # metres. how close a segment must run to lit ground.
STEP = 25.0        # metres. resampling interval along each line.
MIN_RUN = 200.0    # metres. drop stubs shorter than this — they read as specks
                   # rather than as connections.
ENDPOINT = "https://overpass-api.de/api/interpreter"

# The journeys to draw. Each place is a point in the trace, not a point on the
# map: it is snapped to the lit ground nearest it and the route is run from
# there, so a link starts where you actually stood.
PLACES = {
    "lower manhattan": (-74.006, 40.720),
    "east harlem":     (-73.938, 40.803),
    "inwood":          (-73.922, 40.867),
}
LINKS = [("lower manhattan", "east harlem"),
         ("lower manhattan", "inwood")]
JOIN = 150.0       # metres of overlap where a link meets the lit runs, so the
                   # two stages join instead of leaving a seam.
WALK = 900.0       # metres. how far from the trace a journey may board.


# --- the network as a graph ------------------------------------------------
# Overpass returns each way's node ids alongside its geometry, and tracks share
# node ids where they meet. That is the whole graph: no geometric snapping is
# needed, and none is done — two rails that cross without a junction in OSM do
# not join here either, which is correct. A route can only run where a train can.

def graph(ways, mx, my):
    pos, adj = {}, {}
    for way in ways:
        ids, geo = way.get("nodes") or [], way["geometry"]
        if len(ids) != len(geo):
            continue
        for nid, p in zip(ids, geo):
            pos[nid] = (p["lon"], p["lat"])
        for a, b in zip(ids, ids[1:]):
            (ax, ay), (bx, by) = pos[a], pos[b]
            d = math.hypot((bx - ax) * mx, (by - ay) * my)
            adj.setdefault(a, []).append((b, d))
            adj.setdefault(b, []).append((a, d))
    return pos, adj


def near_nodes(pos, adj, target, mx, my, radius):
    """Every node you could reasonably board at, with the walk to it."""
    tx, ty = target
    out = {}
    for nid, (x, y) in pos.items():
        if nid not in adj:
            continue
        d = math.hypot((x - tx) * mx, (y - ty) * my)
        if d <= radius:
            out[nid] = d
    return out


def route(adj, srcs, dsts):
    """
    Shortest run of track between two neighbourhoods, as a list of node ids.

    Both ends are sets of nodes rather than single ones, and that is not a
    refinement — it is the difference between working and not. The IRT and the
    IND are separate networks in OSM, joined only at a handful of junctions, so
    fixing each place to its single closest rail decides which system the
    journey uses before the search runs, and the wrong guess leaves two places
    that are four stops apart with no route between them at all. Seeded from
    every platform within walking distance of each end, the search picks the
    line that actually serves both.
    """
    dist = dict(srcs)
    prev = {}
    seen = set()
    q = [(d, n) for n, d in srcs.items()]
    heapq.heapify(q)
    end = None
    while q:
        d, n = heapq.heappop(q)
        if n in seen:
            continue
        seen.add(n)
        if n in dsts:
            end = n
            break
        for m, w in adj.get(n, ()):
            nd = d + w
            if nd < dist.get(m, 1e18):
                dist[m] = nd
                prev[m] = n
                heapq.heappush(q, (nd, m))
    if end is None:
        return None
    path, n = [end], end
    while n in prev:
        n = prev[n]
        path.append(n)
    return path[::-1]


def resample(line, mx, my, step):
    out = []
    for a, b in zip(line, line[1:]):
        length = math.hypot((b[0] - a[0]) * mx, (b[1] - a[1]) * my)
        n = max(1, int(length // step))
        for i in range(n):
            t = i / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(line[-1])
    return out


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

    # --- the journeys ------------------------------------------------------

    pos, adj = graph(ways, mx, my)
    named = {}
    for way in ways:
        for a, b in zip(way.get("nodes") or [], (way.get("nodes") or [])[1:]):
            named[(min(a, b), max(a, b))] = (way.get("tags") or {}).get("name", "")
    print(f"\nnetwork: {len(pos)} nodes, {sum(len(v) for v in adj.values())//2} edges")

    anchors = {}
    for name, target in PLACES.items():
        # the nearest ground the trace actually lit, then every platform within
        # walking distance of it — so a journey starts from where you stood
        ground = min(pts, key=lambda p: math.hypot((p[0] - target[0]) * mx,
                                                   (p[1] - target[1]) * my))
        anchors[name] = near_nodes(pos, adj, ground, mx, my, WALK)
        print(f"  {name:16} {len(anchors[name])} track nodes within {WALK:.0f} m "
              f"of the trace")

    used = set()
    link_m = 0.0
    for a, b in LINKS:
        nodes = route(adj, anchors[a], anchors[b])
        if not nodes:
            print(f"  no track from {a} to {b}")
            continue

        lines = " → ".join(dict.fromkeys(
            n for n in (named.get((min(x, y), max(x, y)), "") for x, y in
                        zip(nodes, nodes[1:])) if n))
        total = sum(math.hypot((pos[y][0] - pos[x][0]) * mx,
                               (pos[y][1] - pos[x][1]) * my)
                    for x, y in zip(nodes, nodes[1:]))
        print(f"  {a} – {b}: {total/1000:.1f} km  [{lines}]")

        # A stretch of track already carried by the other journey is not drawn
        # twice; the second link picks up where the shared trunk ends.
        pieces, cur = [], []
        for x, y in zip(nodes, nodes[1:]):
            e = (min(x, y), max(x, y))
            if e in used:
                if len(cur) > 1:
                    pieces.append(cur)
                cur = []
            else:
                used.add(e)
                cur = (cur or [x]) + [y]
        if len(cur) > 1:
            pieces.append(cur)

        for piece in pieces:
            line = resample([pos[n] for n in piece], mx, my, STEP)
            # Emit only what the near-lit stage dropped, plus JOIN metres of
            # overlap at each end, so the connection reaches into the knot it
            # is connecting instead of stopping short of it.
            flag = [near_lit(*p) for p in line]
            pad = int(JOIN / STEP)
            i = 0
            while i < len(line):
                if flag[i]:
                    i += 1
                    continue
                j = i
                while j < len(line) and not flag[j]:
                    j += 1
                run = line[max(0, i - pad):min(len(line), j + pad)]
                if len(run) * STEP >= MIN_RUN:
                    out["features"].append({
                        "type": "Feature", "properties": {"link": f"{a} – {b}"},
                        "geometry": {"type": "LineString", "coordinates":
                                     [[round(x, 6), round(y, 6)] for x, y in run]}})
                    link_m += len(run) * STEP
                i = j + 1

    path = DATA / "subway.geojson"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"\n{len(features)} runs, {kept_m/1000:.1f} km kept "
          f"of {total_m/1000:.1f} km in the box")
    print(f"{len(out['features']) - len(features)} link runs, "
          f"{link_m/1000:.1f} km of connecting track")
    print(f"wrote {path.name}  {path.stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
