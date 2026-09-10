#!/usr/bin/env python3
"""
Cut the bird drawings out of the sheet, clean them and vectorise them.

    python3 extract.py

The sheet is pen on graph paper. Some birds are enclosed in hand-drawn squares
and are the top-view drawings; the rest are three-quarter views. Two shapes are
scribbled out and are not birds.

Automatic segmentation does not work here and is not worth forcing: the squares
overlap each other, several birds cross their own square's edge, and closing
the broken pen strokes enough to make a bird one component also welds every
square on the sheet into a single blob. The regions are therefore listed by
hand below, read off the sheet. Within each region the work is automatic —
threshold, drop any leftover straight edge of a square, clean, trace.
"""

import json, subprocess
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "svg"
SHEET = HERE / "sheet.png"

BLUR = 41          # px. background window; the pen is faint on this paper.
# 0.78, not the 0.90 an eye would pick. The graph rule is only a little
# lighter than the pen once a shadow crosses the sheet, and above about 0.80
# whole patches of grid come through and end up welded to a bird. Ink counts
# flatten below 0.80, which is the pen on its own.
BIAS = 0.78
SPECK = 700        # px. drops grid patches and paper texture.
# A square's edge is straight; every part of a bird curves. Straightness is
# measured as the spread perpendicular to a component's own long axis, divided
# by the spread along it — so it works for the diagonal edges too, which a
# bounding-box ratio misses entirely. A pen line a few pixels wide and a few
# hundred long lands near 0.03; the thinnest wing fragment here is above 0.15.
STRAIGHT = 0.085
UP = 2

# (name, view, x0, y0, x1, y1[, erase]) in sheet.png coordinates.
# `erase` is an optional list of rectangles blanked before thresholding, for
# the one case where a square's edge runs into a bird's wing and the two
# become a single component that no shape filter can separate.
REGIONS = [
    ("q1", "quarter", 335,   40,  715,  415),
    ("q2", "quarter", 1345,  20, 1790,  355),
    ("q3", "quarter", 1025,  250, 1520,  730),

    ("t1", "top",     280,  435,  655,  770),
    ("t2", "top",     685,  705,  935,  890),
    ("t3", "top",    1585,  480, 1860,  740),
    ("t4", "top",    1125,  795, 1385, 1050),
    ("t5", "top",    1470,  855, 1650, 1050),
    ("t6", "top",    1595,  950, 1870, 1155, [(1588, 940, 1642, 1030)]),
    # The square's top edge runs only about 7 px above this bird's wing apex, so
    # the erase has to be a thin band; a deeper one takes the wing with it and
    # the outline is left open, which the fill then leaks straight through.
    ("t7", "top",      55,  935,  480, 1385, [(45, 914, 480, 938), (430, 914, 480, 1010)]),
    ("t8", "top",     772, 1005,  995, 1210),
]


# Corrections applied to individual drawings, in the FINAL mask space — the
# 2x-upsampled, trimmed image saved as <name>.npy — because that is the space
# the reference renders are read from.
#
#   flipv   mirror the drawing top to bottom
#   merase  blank a rectangle (x0, y0, x1, y1)
#   mjoin   close an unfinished outline: a quadratic arc from p0 through a
#           control point to p1, painted at the width of the pen
FIXES = {
    "q2": {"flipv": True},
    "q3": {"flipv": True},
    # a line projecting out of the left wing, not part of the drawing
    "t6": {"merase": [(95, 0, 158, 172)]},
    # the left wing was left open; its two edges are closed with an arc
    # the interior line of the right wing stops in mid air; arc it back to
    # the wing's own edge so the wing reads as closed
    "t7": {"mjoin": [((568, 458), (592, 474), (613, 486), 12)]},
}


def apply_fixes(name, mask):
    fx = FIXES.get(name)
    if not fx:
        return mask
    for x0, y0, x1, y1 in fx.get("merase", []):
        mask[max(0, y0):y1, max(0, x0):x1] = False
    for p0, pc, p1, width in fx.get("mjoin", []):
        r = width / 2
        h, w = mask.shape
        for i in range(241):
            t = i / 240
            u = 1 - t
            cx = u * u * p0[0] + 2 * u * t * pc[0] + t * t * p1[0]
            cy = u * u * p0[1] + 2 * u * t * pc[1] + t * t * p1[1]
            y0 = max(0, int(cy - r)); y1 = min(h, int(cy + r) + 1)
            x0 = max(0, int(cx - r)); x1 = min(w, int(cx + r) + 1)
            ys = np.arange(y0, y1)[:, None]
            xs = np.arange(x0, x1)[None, :]
            mask[y0:y1, x0:x1] |= ((xs - cx) ** 2 + (ys - cy) ** 2) <= r * r
    if fx.get("flipv"):
        mask = mask[::-1]
    return mask


def boxblur(a, r):
    pad = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = a.shape
    k = 2 * r + 1
    return (c[k:k + h, k:k + w] - c[0:h, k:k + w]
            - c[k:k + h, 0:w] + c[0:h, 0:w]) / (k * k)


def components(mask, floor):
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack, cells = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(cells) < floor:
            continue
        cy = [c[0] for c in cells]
        cx = [c[1] for c in cells]
        out.append({"box": (min(cy), min(cx), max(cy) + 1, max(cx) + 1),
                    "cells": cells})
    return out


def solidify(mask, k=20):
    """Close the outline, fill the body, shrink back.

    The pen line has gaps in it, so flooding straight from outside leaks
    through and fills nothing. Dilating first seals the gaps, and eroding by
    the same amount afterwards puts the silhouette back on the drawn edge.

    k has to clear the widest gap on the sheet. At 8 every bird filled except
    the large lower-left one, whose outline is open by more than that, and it
    came back as a bare outline.
    """
    m = mask.astype(np.uint8)
    for _ in range(k):
        m = nb(m, "max")

    # flood the outside, then everything unreached is body
    pad = np.pad(m.astype(bool), 1)
    out = np.zeros_like(pad)
    stack = [(0, 0)]
    out[0, 0] = True
    while stack:
        y, x = stack.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if (0 <= ny < pad.shape[0] and 0 <= nx < pad.shape[1]
                    and not out[ny, nx] and not pad[ny, nx]):
                out[ny, nx] = True
                stack.append((ny, nx))
    solid = (~out[1:-1, 1:-1]).astype(np.uint8)

    for _ in range(k):
        solid = nb(solid, "min")
    return solid.astype(bool) | mask


def nb(m, op):
    o = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            s = np.roll(np.roll(m, dy, 0), dx, 1)
            o = np.maximum(o, s) if op == "max" else np.minimum(o, s)
    return o


def main():
    sheet = np.asarray(Image.open(SHEET).convert("L"), dtype=np.float32) / 255.0
    OUT.mkdir(exist_ok=True)
    meta = []

    for region in REGIONS:
        name, view, x0, y0, x1, y1 = region[:6]
        a = sheet[y0:y1, x0:x1].copy()
        for ex0, ey0, ex1, ey1 in (region[6] if len(region) > 6 else []):
            a[max(0, ey0 - y0):ey1 - y0, max(0, ex0 - x0):ex1 - x0] = 1.0
        mask = a < boxblur(a, BLUR) * BIAS

        # close the pen line so a bird is one component rather than a dashed
        # outline; one pass only, since two welds the squares together
        m = nb(mask.astype(np.uint8), "max")
        mask = m.astype(bool)

        comps = components(mask, SPECK)
        keep = np.zeros_like(mask)
        dropped = 0
        for c in comps:
            pts = np.asarray(c["cells"], dtype=np.float64)
            pts -= pts.mean(axis=0)
            ev = np.linalg.eigvalsh(np.cov(pts, rowvar=False))
            ratio = (ev[0] / ev[1]) ** 0.5 if ev[1] > 0 else 1.0
            if ratio < STRAIGHT:
                dropped += 1
                continue
            for y, x in c["cells"]:
                keep[y, x] = True
        mask = keep

        if not mask.any():
            print(f"  {name}: EMPTY")
            continue

        # trim to the drawing, then round the contour off the pixel grid
        ys, xs = np.nonzero(mask)
        mask = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        big = np.repeat(np.repeat(mask.astype(np.float32), UP, 0), UP, 1)
        for _ in range(2):
            big = (boxblur(big, 3) > 0.5).astype(np.float32)
        mask = apply_fixes(name, big > 0.5)

        # a fix can leave the drawing off-centre in its box
        ys, xs = np.nonzero(mask)
        mask = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

        pbm = OUT / f"{name}.pbm"
        svg = OUT / f"{name}.svg"
        Image.fromarray((~mask).astype(np.uint8) * 255).convert("1").save(pbm)
        subprocess.run(["potrace", str(pbm), "-s", "-o", str(svg),
                        "--turdsize", "12", "--alphamax", "1.334",
                        "--opttolerance", "0.7", "--turnpolicy", "black"],
                       check=True)
        pbm.unlink()

        np.save(OUT / f"{name}.npy", mask)
        meta.append({"name": name, "view": view,
                     "w": int(mask.shape[1]), "h": int(mask.shape[0])})
        print(f"  {name:3} {view:8} {mask.shape[1]:4}x{mask.shape[0]:<4} "
              f"ink {mask.sum():6,}  ({dropped} edge{'s' if dropped != 1 else ''} dropped)")

    # --- sprite sheet ------------------------------------------------------
    # RGBA with the drawing in the alpha channel, so the renderer can tint the
    # birds to the page's ink rather than being stuck with black.
    CELL = 256
    cols = 4
    rows = (len(meta) + cols - 1) // cols
    sheet = Image.new("LA", (cols * CELL, rows * CELL), (255, 0))
    for i, m in enumerate(meta):
        mask = np.load(OUT / f"{m['name']}.npy")
        solid = solidify(mask)
        m["fill"] = round(float(solid.mean()), 3)
        k = (CELL - 12) / max(mask.shape)
        size = (max(1, round(mask.shape[1] * k)), max(1, round(mask.shape[0] * k)))
        a = Image.fromarray((solid * 255).astype(np.uint8)).resize(size, Image.LANCZOS)
        # luminance carries the drawing: body white, drawn line dark. Alpha is
        # the filled silhouette, so a bird is opaque and covers the text it
        # passes over instead of letting it read through.
        lum = Image.fromarray(((~mask) * 255).astype(np.uint8)).resize(size, Image.LANCZOS)
        cx = (i % cols) * CELL + (CELL - a.width) // 2
        cy = (i // cols) * CELL + (CELL - a.height) // 2
        sheet.paste(Image.merge("LA", (lum, a)), (cx, cy), a)
        m["x"] = (i % cols) * CELL
        m["y"] = (i // cols) * CELL
        m["cw"] = a.width
        m["ch"] = a.height
    sheet.convert("RGBA").save(HERE / "birds.png")
    print(f"sheet {cols}x{rows} cells -> birds.png "
          f"({(HERE / 'birds.png').stat().st_size / 1000:.0f} KB)")

    (HERE / "birds.json").write_text(json.dumps({"cell": CELL, "birds": meta}, indent=1))
    q = sum(1 for m in meta if m["view"] == "quarter")
    print(f"\n{len(meta)} birds: {q} three-quarter, {len(meta) - q} top view")


if __name__ == "__main__":
    main()
