#!/usr/bin/env python3
"""
Cut the hand-drawn Courier specimen into individual glyphs.

    python3 segment.py <photo.png>

The sheet is three labelled sections — uppercase, lowercase, punctuation —
drawn in marker on graph paper. Three glyphs are ringed placeholders rather
than drawings, because they are reflections of glyphs already present:

    d = b mirrored        q = p mirrored        x = uppercase X, reduced

Those are dropped here; build_atlas.py constructs them.

Four properties of this sheet defeat the obvious approach, each handled below:

  Rows cannot be found by horizontal projection. The gaps between lines fall
  to a single pixel, because ascenders and descenders interlock.

  Glyphs cannot be found by vertical gaps either. The specimen is drawn
  tightly and neighbouring letters sit a few pixels apart, so any gap wide
  enough to catch an i's dot also welds A to B. Connected components already
  separate the letters; the only work needed is attaching the loose marks.

  Rows must be clustered from every mark, not from the letters alone. The
  bodies of ? and ! rise well above the line their dots sit on, so clustering
  letters first puts them in the row above.

  The ringed placeholders survive any size filter, a ring being as large as a
  letter. They are identified by containment instead: a ring is the only mark
  on the sheet whose bounding box wholly encloses another mark's.
"""

import json, sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "glyphs"

WIDTH = 2600       # px to work at
BLUR = 81          # px. background estimate window.
BIAS = 0.74        # ink is below this fraction of local paper value.
SPECK = 150        # px. low enough for a full stop, high enough to
                   # reject a stray speck on the paper.
LEFT_EDGE = 430    # px. the section labels are written left of this.

ROWS = [
    list("ABCDEFGHIJK"),
    list("LMNOPQRSTUV"),
    list("WXYZ"),
    # the ringed placeholders are removed before grouping, so d, q and x are
    # simply absent from the rows they were drawn in
    list("abcefghijk"),
    list("lmnoprstuv"),
    list("wyz"),
    [".", ",", "?", "!", ":", ";"],
]
SETS = ["upper"] * 3 + ["lower"] * 3 + ["punct"]


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


def main():
    src = Path(sys.argv[1]).expanduser()
    img = Image.open(src).convert("L")
    img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
    a = np.asarray(img, dtype=np.float32) / 255.0
    H = a.shape[0]

    mask = a < boxblur(a, BLUR) * BIAS
    comps = components(mask, SPECK)
    print(f"{src.name} at {a.shape[1]}x{H} — {len(comps)} components")

    live = []
    for c in comps:
        y0, x0, y1, x1 = c["box"]
        if x0 < LEFT_EDGE:                        # section label
            continue
        if (x1 - x0) > 250 and (y1 - y0) < 45:    # table edge in the photograph
            continue
        if y0 > H * 0.80:
            continue
        live.append(c)

    rings = set()
    for i, c in enumerate(live):
        ay0, ax0, ay1, ax1 = c["box"]
        for j, d in enumerate(live):
            if i == j:
                continue
            by0, bx0, by1, bx1 = d["box"]
            if ax0 <= bx0 and ay0 <= by0 and ax1 >= bx1 and ay1 >= by1:
                rings.add(i)
                rings.add(j)
    live = [c for i, c in enumerate(live) if i not in rings]
    print(f"{len(live)} marks in the specimen, {len(rings)} dropped as placeholders")

    med_h = float(np.median([c["box"][2] - c["box"][0] for c in live]))
    med_w = float(np.median([c["box"][3] - c["box"][1] for c in live]))

    def is_letter(c):
        y0, x0, y1, x1 = c["box"]
        return (y1 - y0) > med_h * 0.55 and (x1 - x0) > med_w * 0.30

    cy = sorted((0.5 * (c["box"][0] + c["box"][2]), i) for i, c in enumerate(live))
    gaps = sorted(((cy[i + 1][0] - cy[i][0], i) for i in range(len(cy) - 1)),
                  reverse=True)
    cuts = sorted(g[1] for g in gaps[:len(ROWS) - 1])
    bands, start = [], 0
    for cut in cuts + [len(cy) - 1]:
        bands.append([live[i] for _, i in cy[start:cut + 1]])
        start = cut + 1
    print("rows: " + ", ".join(str(len(b)) for b in bands))

    OUT.mkdir(exist_ok=True)
    for f in OUT.glob("*.pbm"):
        f.unlink()

    manifest = []
    for ri, row in enumerate(bands):
        row.sort(key=lambda c: c["box"][1])

        if ri < 6:
            groups = [[c] for c in row if is_letter(c)]
            for m in row:
                if is_letter(m):
                    continue
                mx = 0.5 * (m["box"][1] + m["box"][3])
                best, bi = 1e9, 0
                for i, g in enumerate(groups):
                    x0, x1 = g[0]["box"][1], g[0]["box"][3]
                    d = 0 if x0 <= mx <= x1 else min(abs(mx - x0), abs(mx - x1))
                    if d < best:
                        best, bi = d, i
                # a dot sits over its own stem; a mark out in open space is
                # left over from a placeholder and is discarded
                if best < med_w * 0.45:
                    groups[bi].append(m)
        else:
            groups = [[row[0]]]
            for c in row[1:]:
                if c["box"][1] - max(g["box"][3] for g in groups[-1]) < 70:
                    groups[-1].append(c)
                else:
                    groups.append([c])

        expect = ROWS[ri]
        ok = "ok" if len(groups) == len(expect) else "MISMATCH"
        print(f"row {ri}: {len(groups)} glyphs, expect {len(expect)}  {ok}")
        if len(groups) != len(expect):
            for g in groups:
                print("    ", [x["box"] for x in g], file=sys.stderr)
            return

        for ci, grp in enumerate(groups):
            ch = expect[ci]
            y0 = min(g["box"][0] for g in grp); y1 = max(g["box"][2] for g in grp)
            x0 = min(g["box"][1] for g in grp); x1 = max(g["box"][3] for g in grp)
            glyph = np.zeros((y1 - y0, x1 - x0), dtype=bool)
            for g in grp:
                for y, x in g["cells"]:
                    glyph[y - y0, x - x0] = True

            name = f"{SETS[ri]}_{ord(ch):03d}.pbm"
            Image.fromarray((~glyph).astype(np.uint8) * 255).convert("1").save(OUT / name)
            manifest.append({
                "char": ch, "set": SETS[ri], "file": name, "row": ri,
                "top": int(y0), "bottom": int(y1),
                "w": int(x1 - x0), "h": int(y1 - y0),
            })

    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"\n{len(manifest)} glyphs -> {OUT.name}/")
    for s in ("upper", "lower", "punct"):
        got = "".join(m["char"] for m in manifest if m["set"] == s)
        print(f"  {s:6} {len(got):2}  {got}")


if __name__ == "__main__":
    main()
