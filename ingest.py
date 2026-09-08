#!/usr/bin/env python3
"""
Turn a real location export into the trace this piece is built from.

    python3 ingest.py ~/Downloads/Timeline.json
    python3 ingest.py ~/Downloads/Takeout            # a whole folder works too

Google has changed this format repeatedly and the export you get depends on
your phone, your account age and when you asked for it. Rather than make you
work out which one you have, this sniffs all of the shapes I know about:

  * on-device Timeline export, Android  (semanticSegments / timelinePath)
  * on-device Timeline export, iOS      (a bare list of segments)
  * Takeout Records.json                (locations[] with latitudeE7)
  * Takeout Semantic Location History   (timelineObjects[] per month)
  * GPX from anything else              (Strava, a handheld, a watch)

It writes data/trace.json, which trace.py picks up automatically. Nothing else
in the pipeline changes — run build.py afterwards and the city relights around
your real movement.

Three things happen on the way in, each of which changes what the piece says:

  ACCURACY   points with a poor fix are thrown away. A reading with a 500 m
             radius will smear light across blocks you never entered.

  DWELL      a night's sleep is not a thousand separate visits. Consecutive
             points that stay put are collapsed into one, carrying a weight
             for how long you were there — and that weight is capped, so your
             own bed doesn't outshine the entire rest of the city.

  REDACTION  anything inside a circle listed in data/exclude.json is dropped
             before it ever reaches the output. This piece lights up real
             addresses, so other people's homes are worth thinking about.
"""

import argparse, json, math, re, sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).parent
DATA = HERE / "data"

# --- tunables --------------------------------------------------------------

MAX_ACCURACY = 120.0   # metres. drop fixes vaguer than this, when known.
STILL_RADIUS = 45.0    # metres. inside this you count as not having moved.
STILL_GAP = 7200.0     # seconds. a longer silence starts a new cluster.
DWELL_CAP = 90.0       # minutes. the most any single place can bank per visit.
DWELL_UNIT = 6.0       # minutes per unit of weight. 6 min of standing still
                       # counts for about as much as one passing GPS ping.

# ---------------------------------------------------------------------------


def parse_latlng(s):
    """Google writes coordinates about five different ways. Take them all."""
    if not isinstance(s, str):
        return None
    s = s.strip().replace("geo:", "").replace("°", "")
    nums = re.findall(r"-?\d+\.?\d*", s)
    if len(nums) < 2:
        return None
    lat, lng = float(nums[0]), float(nums[1])
    if abs(lat) > 90 or abs(lng) > 180:
        return None
    return lat, lng


def parse_time(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000.0 if v > 1e11 else 1.0)
    s = str(v)
    if s.isdigit():
        n = float(s)
        return n / (1000.0 if n > 1e11 else 1.0)
    try:
        s = s.replace("Z", "+00:00")
        # some exports carry more than six fractional digits
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


# --- format handlers -------------------------------------------------------
# Each yields (lng, lat, epoch_seconds, accuracy_or_None, known_dwell_seconds).
# A "visit" record already states how long you stayed, so it says so rather
# than emitting two points and hoping the clusterer works it back out.


def from_records(obj):
    for r in obj.get("locations", []):
        if "latitudeE7" in r:
            lat, lng = r["latitudeE7"] / 1e7, r["longitudeE7"] / 1e7
        elif "latitude" in r:
            lat, lng = r["latitude"], r["longitude"]
        else:
            continue
        t = parse_time(r.get("timestamp") or r.get("timestampMs"))
        yield lng, lat, t, r.get("accuracy"), 0.0


def from_segments(segments):
    """The on-device export, both platforms. Segments hold either a path you
    walked or a place you stopped; both are useful and they carry duration."""
    for seg in segments:
        t0 = parse_time(seg.get("startTime"))
        t1 = parse_time(seg.get("endTime"))

        path = seg.get("timelinePath") or []
        for p in path:
            ll = parse_latlng(p.get("point"))
            if not ll:
                continue
            off = p.get("durationMinutesOffsetFromStartTime")
            t = t0 + float(off) * 60 if (t0 and off is not None) else t0
            yield ll[1], ll[0], t, None, 0.0

        visit = seg.get("visit") or {}
        cand = visit.get("topCandidate") or {}
        ll = parse_latlng((cand.get("placeLocation") or {}).get("latLng")
                          if isinstance(cand.get("placeLocation"), dict)
                          else cand.get("placeLocation"))
        if ll:
            yield ll[1], ll[0], t0, None, (t1 - t0) if (t0 and t1) else 0.0

        act = seg.get("activity") or {}
        for end in ("start", "end"):
            e = act.get(end)
            ll = parse_latlng(e.get("latLng") if isinstance(e, dict) else e)
            if ll:
                yield ll[1], ll[0], t0 if end == "start" else t1, None, 0.0


def from_timeline_objects(obj):
    """Takeout Semantic Location History, one file per month."""
    for o in obj.get("timelineObjects", []):
        visit = o.get("placeVisit")
        if visit:
            loc = visit.get("location", {})
            if "latitudeE7" in loc:
                d = visit.get("duration", {})
                t0 = parse_time(d.get("startTimestampMs") or d.get("startTimestamp"))
                t1 = parse_time(d.get("endTimestampMs") or d.get("endTimestamp"))
                lat, lng = loc["latitudeE7"] / 1e7, loc["longitudeE7"] / 1e7
                yield lng, lat, t0, None, (t1 - t0) if (t0 and t1) else 0.0
        seg = o.get("activitySegment")
        if seg:
            d = seg.get("duration", {})
            t0 = parse_time(d.get("startTimestampMs") or d.get("startTimestamp"))
            for pt in (seg.get("waypointPath") or {}).get("waypoints", []):
                if "latE7" in pt:
                    yield pt["lngE7"] / 1e7, pt["latE7"] / 1e7, t0, None, 0.0
            for pt in (seg.get("simplifiedRawPath") or {}).get("points", []):
                yield (pt["lngE7"] / 1e7, pt["latE7"] / 1e7,
                       parse_time(pt.get("timestampMs")), pt.get("accuracyMetres"), 0.0)


def from_gpx(path):
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    root = ElementTree.parse(path).getroot()
    pts = root.findall(".//g:trkpt", ns) or root.findall(".//trkpt")
    for pt in pts:
        try:
            lat, lng = float(pt.get("lat")), float(pt.get("lon"))
        except (TypeError, ValueError):
            continue
        te = pt.find("g:time", ns)
        if te is None:
            te = pt.find("time")
        yield lng, lat, parse_time(te.text if te is not None else None), None, 0.0


def read_file(path):
    if path.suffix.lower() == ".gpx":
        yield from from_gpx(path)
        return
    try:
        obj = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    if isinstance(obj, list):
        yield from from_segments(obj)                  # iOS on-device export
    elif "locations" in obj:
        yield from from_records(obj)                   # Records.json
    elif "semanticSegments" in obj:
        yield from from_segments(obj["semanticSegments"])
    elif "timelineObjects" in obj:
        yield from from_timeline_objects(obj)
    elif "timelinePath" in obj or "visit" in obj:
        yield from from_segments([obj])


# --- cleaning --------------------------------------------------------------


def load_boundary(path):
    """Polygons defining where the piece is allowed to look.

    A bounding box would be the easy version and the wrong one: a box around
    New York takes in half of New Jersey and a good deal of Nassau County. The
    borough outlines are already on disk, so the test is the real city limit,
    accurate to the simplification tolerance they were written at.
    """
    obj = json.loads(Path(path).read_text())
    polys = []
    for f in obj.get("features", []):
        g = f.get("geometry", {})
        groups = (g.get("coordinates", []) if g.get("type") == "MultiPolygon"
                  else [g.get("coordinates", [])])
        for rings in groups:
            if not rings:
                continue
            xs = [pt[0] for r in rings for pt in r]
            ys = [pt[1] for r in rings for pt in r]
            polys.append(((min(xs), min(ys), max(xs), max(ys)), rings))
    xs0 = min(b[0] for b, _ in polys); ys0 = min(b[1] for b, _ in polys)
    xs1 = max(b[2] for b, _ in polys); ys1 = max(b[3] for b, _ in polys)
    print(f"boundary: {len(polys)} polygons, "
          f"{xs0:.3f},{ys0:.3f} to {xs1:.3f},{ys1:.3f}")
    return polys, (xs0, ys0, xs1, ys1)


def inside(lng, lat, polys, bbox):
    """Even-odd ray cast. Holes are just more rings, so they work for free."""
    if not (bbox[0] <= lng <= bbox[2] and bbox[1] <= lat <= bbox[3]):
        return False
    for (bx0, by0, bx1, by1), rings in polys:
        if not (bx0 <= lng <= bx1 and by0 <= lat <= by1):
            continue
        crossings = 0
        for ring in rings:
            for i in range(len(ring) - 1):
                x0, y0 = ring[i]
                x1, y1 = ring[i + 1]
                if (y0 > lat) != (y1 > lat):
                    xh = x0 + (lat - y0) * (x1 - x0) / (y1 - y0)
                    if xh > lng:
                        crossings += 1
        if crossings % 2:
            return True
    return False


def load_exclusions():
    path = DATA / "exclude.json"
    if not path.exists():
        return []
    zones = json.loads(path.read_text())
    print(f"redacting {len(zones)} zone(s) from data/exclude.json")
    return zones


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="export file, or a folder to search")
    ap.add_argument("--from", dest="since", help="earliest date, YYYY-MM-DD")
    ap.add_argument("--to", dest="until", help="latest date, YYYY-MM-DD")
    ap.add_argument("--within", default=str(DATA / "boroughs.geojson"),
                    help="only keep points inside these polygons "
                         "(default: the NYC borough outlines). 'none' to disable.")
    args = ap.parse_args()

    src = Path(args.source).expanduser()
    files = ([src] if src.is_file()
             else sorted(p for p in src.rglob("*")
                         if p.suffix.lower() in (".json", ".gpx")))
    if not files:
        sys.exit(f"nothing readable in {src}")

    lo = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc).timestamp() if args.since else None
    hi = datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc).timestamp() if args.until else None

    bounds = None
    if args.within and args.within.lower() != "none" and Path(args.within).exists():
        bounds = load_boundary(args.within)
    elif args.within and args.within.lower() != "none":
        print(f"no boundary file at {args.within} — keeping everything", file=sys.stderr)

    raw, vague, undated, outside, elsewhere = [], 0, 0, 0, 0
    for f in files:
        n0 = len(raw)
        for lng, lat, t, acc, dwell in read_file(f):
            if acc is not None and acc > MAX_ACCURACY:
                vague += 1
                continue
            if t is None:
                undated += 1
                continue
            if (lo and t < lo) or (hi and t > hi):
                outside += 1
                continue
            # cheap bbox reject here; the exact polygon test runs after
            # clustering, when there are far fewer things to test
            if bounds and not (bounds[1][0] <= lng <= bounds[1][2]
                               and bounds[1][1] <= lat <= bounds[1][3]):
                elsewhere += 1
                continue
            raw.append((t, lng, lat, dwell or 0.0))
        got = len(raw) - n0
        if got:
            print(f"  {got:>8,}  {f.name}")

    if not raw:
        sys.exit("no usable points found — is this the right export?")

    raw.sort()
    span = (datetime.fromtimestamp(raw[0][0]).date(),
            datetime.fromtimestamp(raw[-1][0]).date())
    print(f"\n{len(raw):,} points, {span[0]} to {span[1]}")
    if vague:
        print(f"  dropped {vague:,} with accuracy worse than {MAX_ACCURACY:.0f} m")
    if undated:
        print(f"  dropped {undated:,} with no usable timestamp")
    if outside:
        print(f"  dropped {outside:,} outside the requested dates")
    if elsewhere:
        print(f"  dropped {elsewhere:,} far outside the boundary")

    # --- collapse the times you were standing still ------------------------

    lat0 = sum(p[2] for p in raw) / len(raw)
    mx = 111320 * math.cos(math.radians(lat0))
    my = 110540

    clusters = []
    cur = None
    for t, lng, lat, dwell in raw:
        if cur:
            dx = (lng - cur["lng"]) * mx
            dy = (lat - cur["lat"]) * my
            if math.hypot(dx, dy) <= STILL_RADIUS and t - cur["last"] <= STILL_GAP:
                n = cur["n"] + 1
                cur["lng"] += (lng - cur["lng"]) / n
                cur["lat"] += (lat - cur["lat"]) / n
                cur["n"] = n
                cur["last"] = t
                cur["dwell"] += dwell
                continue
            clusters.append(cur)
        cur = {"lng": lng, "lat": lat, "n": 1, "first": t, "last": t, "dwell": dwell}
    if cur:
        clusters.append(cur)

    out = []
    for c in clusters:
        # elapsed inside the cluster, plus any duration a visit record stated
        dwell_min = (c["last"] - c["first"] + c["dwell"]) / 60.0
        w = max(1.0, min(dwell_min, DWELL_CAP) / DWELL_UNIT)
        out.append((round(c["lng"], 6), round(c["lat"], 6), round(w, 3)))

    print(f"{len(clusters):,} places after collapsing stationary runs "
          f"(from {len(raw):,} points)")

    # --- confine to the boundary -------------------------------------------

    if bounds:
        polys, bbox = bounds
        kept = [(lng, lat, w) for lng, lat, w in out if inside(lng, lat, polys, bbox)]
        print(f"  {len(out) - len(kept):,} places fell outside the city limits")
        out = kept
        if not out:
            sys.exit("nothing left inside the boundary")

    # --- redact ------------------------------------------------------------

    zones = load_exclusions()
    if zones:
        kept = []
        cut = 0
        for lng, lat, w in out:
            hit = False
            for z in zones:
                dx = (lng - z["lng"]) * mx
                dy = (lat - z["lat"]) * my
                if math.hypot(dx, dy) <= z.get("radius_m", 150):
                    hit = True
                    break
            if hit:
                cut += 1
            else:
                kept.append((lng, lat, w))
        print(f"  removed {cut:,} inside redacted zones")
        out = kept

    heaviest = sorted(out, key=lambda p: -p[2])[:3]
    print(f"\ntotal weight {sum(p[2] for p in out):,.0f} across {len(out):,} places")
    print("heaviest: " + ", ".join(f"{p[1]:.4f},{p[0]:.4f} (x{p[2]:.0f})" for p in heaviest))

    (DATA / "trace.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"\nwrote data/trace.json — now run:  python3 fetch.py && python3 build.py")


if __name__ == "__main__":
    main()
