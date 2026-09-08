#!/usr/bin/env python3
"""
Fetch only the city that lights up.

Rather than downloading a bounding box around everything and throwing 90% of it
away, this works out which ground the trace actually touches, merges that into
a small set of boxes, and asks Overpass only for those. Brooklyn-wide the
trace is mostly thin route corridors, so this is a fraction of the full extent.

Run once. Output lands in data/osm/ and build.py takes it from there.
"""

import json, sys, time, urllib.request
from pathlib import Path

from trace import points, REACH, Frame

HERE = Path(__file__).parent
OSM = HERE / "data" / "osm"

CELL = 150.0          # metres. coverage resolution. keep near REACH — coarser
                      # cells mean fewer, larger boxes but much more wasted area
MIN_PTS = 2           # a cell needs this many points before it's worth fetching
BOXES_PER_QUERY = 25  # keep individual Overpass requests modest
ENDPOINT = "https://overpass-api.de/api/interpreter"

STREET_CLASSES = ("motorway|motorway_link|trunk|trunk_link|primary|primary_link|"
                  "secondary|secondary_link|tertiary|tertiary_link|residential|"
                  "unclassified|living_street|pedestrian")


def coverage_boxes():
    """Cells the trace touches, padded by the light's reach and merged into rows."""
    pts = points()
    lat0 = sum(p[1] for p in pts) / len(pts)
    lng0 = sum(p[0] for p in pts) / len(pts)
    frame = Frame(lat0, lng0)

    counts = {}
    for lng, lat, w in pts:
        x, y = frame.to_m(lng, lat)
        key = (int(x // CELL), int(y // CELL))
        counts[key] = counts.get(key, 0) + 1
    live = {k for k, n in counts.items() if n >= MIN_PTS}

    # a lit building can sit up to REACH outside a cell holding points, so grow
    # the footprint before merging or we'd clip the edges of every cluster
    pad = int(REACH // CELL) + 1
    grown = set()
    for gx, gy in live:
        for dx in range(-pad, pad + 1):
            for dy in range(-pad, pad + 1):
                grown.add((gx + dx, gy + dy))

    # merge horizontally-contiguous cells into runs — far fewer, larger boxes
    boxes = []
    for gy in sorted({y for _, y in grown}):
        row = sorted(x for x, y in grown if y == gy)
        start = prev = row[0]
        for x in row[1:] + [None]:
            if x is not None and x == prev + 1:
                prev = x
                continue
            w, s = frame.to_deg(start * CELL, gy * CELL)
            e, n = frame.to_deg((prev + 1) * CELL, (gy + 1) * CELL)
            boxes.append((s, w, n, e))
            if x is not None:
                start = prev = x
        # note: rows are not merged vertically; runs are already large enough
        # that the extra query weight isn't worth the bookkeeping

    area = sum((n - s) * (e - w) for s, w, n, e in boxes)
    print(f"{len(live)} live cells -> {len(grown)} padded -> {len(boxes)} boxes")
    print(f"covering {area * 111.32 * 84.5:.1f} km2")
    return boxes


def query(boxes):
    parts = []
    for s, w, n, e in boxes:
        bb = f"{s:.5f},{w:.5f},{n:.5f},{e:.5f}"
        parts.append(f'way["building"]({bb});')
        parts.append(f'way["highway"~"^({STREET_CLASSES})$"]({bb});')
    return "[out:json][timeout:300];(" + "".join(parts) + ");out geom;"


def main():
    OSM.mkdir(parents=True, exist_ok=True)
    boxes = coverage_boxes()

    batches = [boxes[i:i + BOXES_PER_QUERY] for i in range(0, len(boxes), BOXES_PER_QUERY)]
    print(f"{len(batches)} Overpass requests\n")

    total = 0
    for i, batch in enumerate(batches):
        out = OSM / f"{i:03d}.json"
        if out.exists():
            print(f"  {i+1}/{len(batches)}  cached")
            total += out.stat().st_size
            continue
        body = query(batch).encode()
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    ENDPOINT, data=body,
                    headers={"User-Agent": "spime-selfportrait/0.1 (personal art project)"})
                with urllib.request.urlopen(req, timeout=320) as r:
                    data = r.read()
                out.write_bytes(data)
                total += len(data)
                print(f"  {i+1}/{len(batches)}  {len(data)/1e6:.1f} MB")
                break
            except Exception as exc:
                wait = 20 * (attempt + 1)
                print(f"  {i+1}/{len(batches)}  {type(exc).__name__}, retrying in {wait}s")
                time.sleep(wait)
        else:
            print(f"  {i+1}/{len(batches)}  FAILED, skipping", file=sys.stderr)
        time.sleep(4)   # be a decent citizen on a free shared endpoint

    print(f"\n{total/1e6:.1f} MB in data/osm/")


if __name__ == "__main__":
    main()
