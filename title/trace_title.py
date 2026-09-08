#!/usr/bin/env python3
"""
Turn the photographed hand-lettering into a clean vector title.

    python3 trace_title.py <photo.png>

The source is brush lettering on graph paper, shot with a phone. Four things
have to happen before it can be traced:

  1. The grid has to go. It is a light blue-grey and the ink is nearly black,
     so a straight luminance threshold separates them — but the photo is lit
     unevenly, so the threshold is computed against a heavily blurred copy of
     the page rather than against a fixed number. That way a dim corner does
     not turn into ink.

  2. The dust has to go. There are paper fibres and specks around the letters.
     Connected components below a size floor are dropped, which removes them
     without touching the strokes.

  3. The edges have to be smoothed. Phone-camera noise leaves the stroke
     boundary ragged, and potrace faithfully reproduces every wobble. A close
     followed by an open rounds the contour and fills pinholes while leaving
     the letterform alone.

  4. Then potrace, tuned for a brush script: aggressive corner smoothing, so
     the curves read as drawn strokes rather than as polygons.
"""

import subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent

SPECK = 400        # px. connected components smaller than this are dust.
BLUR = 61          # px. background estimate window; must exceed stroke width.
BIAS = 0.72        # ink is anything below this fraction of local paper value.
WORD_GAP = 0.68    # the single word space is closed to this much of its width.


def boxblur(a, r):
    """Separable box blur via summed-area table — fast enough at this size."""
    pad = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = a.shape
    k = 2 * r + 1
    return (c[k:k + h, k:k + w] - c[0:h, k:k + w]
            - c[k:k + h, 0:w] + c[0:h, 0:w]) / (k * k)


def neighbours(m, op):
    """3x3 dilate (max) or erode (min) with numpy shifts."""
    out = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            s = np.roll(np.roll(m, dy, axis=0), dx, axis=1)
            out = np.maximum(out, s) if op == "max" else np.minimum(out, s)
    return out


def components(mask, floor):
    """Iterative flood fill; drops anything smaller than `floor` pixels."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    keep = np.zeros_like(mask, dtype=bool)
    ys, xs = np.nonzero(mask)
    kept = dropped = 0
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        cells = []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(cells) >= floor:
            kept += 1
            for y, x in cells:
                keep[y, x] = True
        else:
            dropped += 1
    print(f"  {kept} strokes kept, {dropped} specks removed")
    return keep


def main():
    src = Path(sys.argv[1]).expanduser()
    img = Image.open(src).convert("L")

    # work at a manageable size; 1600 px wide is far more than the trace needs
    scale = 1600 / img.width
    img = img.resize((1600, round(img.height * scale)), Image.LANCZOS)
    a = np.asarray(img, dtype=np.float32) / 255.0
    print(f"{src.name} -> {a.shape[1]}x{a.shape[0]}")

    # 1. local threshold against the paper, not against a constant
    paper = boxblur(a, BLUR)
    mask = a < paper * BIAS
    print(f"  {mask.sum():,} ink pixels before cleaning")

    # 2. drop dust
    mask = components(mask, SPECK)

    # 3. close then open: fill pinholes, shave ragged edges
    m = mask.astype(np.uint8)
    for _ in range(2):
        m = neighbours(m, "max")
    for _ in range(4):
        m = neighbours(m, "min")
    for _ in range(2):
        m = neighbours(m, "max")
    mask = m.astype(bool)

    # Round the contour properly. Morphology alone leaves stair-stepping on
    # diagonals, and potrace reproduces every step of it. Upsampling, blurring
    # and re-thresholding puts the boundary at a sub-pixel position, which is
    # what turns a faceted outline into a drawn curve.
    big = np.repeat(np.repeat(mask.astype(np.float32), 2, axis=0), 2, axis=1)
    for _ in range(2):
        big = (boxblur(big, 5) > 0.5).astype(np.float32)
    mask = big > 0.5

    # Tighten the word space. There is exactly one real gap in this line —
    # between "my" and "map" — and at 141 px against a 2150 px line it sits a
    # little wide for a brush script, which lets the two words read as
    # separate drawings rather than one title. Closed to about two thirds.
    # Nothing else moves: the letters within each word keep the spacing they
    # were drawn with.
    cols = mask.any(axis=0)
    runs, start = [], None
    for x, v in enumerate(cols):
        if not v and start is None:
            start = x
        elif v and start is not None:
            runs.append((start, x - start)); start = None
    inner = [r for r in runs if r[0] > 0]
    if inner:
        gx, gw = max(inner, key=lambda r: r[1])
        shift = int(gw * (1 - WORD_GAP))
        if shift > 0:
            out = np.zeros_like(mask)
            out[:, :gx] = mask[:, :gx]
            right = mask[:, gx + gw:]
            x0 = gx + gw - shift
            out[:, x0:x0 + right.shape[1]] = right
            mask = out
            print(f"  word gap {gw} -> {gw - shift} px")

    # crop to the lettering with a small margin
    ys, xs = np.nonzero(mask)
    pad = 12
    y0, y1 = max(0, ys.min() - pad), min(mask.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(mask.shape[1], xs.max() + pad + 1)
    mask = mask[y0:y1, x0:x1]
    print(f"  cropped to {mask.shape[1]}x{mask.shape[0]}")

    pbm = HERE / "mymap.pbm"
    Image.fromarray((~mask).astype(np.uint8) * 255).convert("1").save(pbm)

    # 4. trace. alphamax high = corners rounded into curves, which is what a
    # brush stroke actually is; opttolerance a little loose so the output is
    # a handful of long curves rather than hundreds of tiny ones.
    out = HERE / "mymap.svg"
    subprocess.run([
        "potrace", str(pbm), "-s", "-o", str(out),
        "--turdsize", "16", "--alphamax", "1.334", "--opttolerance", "0.9",
        "--turnpolicy", "black",
    ], check=True)
    print(f"wrote {out.name}  {out.stat().st_size/1000:.0f} KB")


if __name__ == "__main__":
    main()
