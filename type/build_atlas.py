#!/usr/bin/env python3
"""
Turn the segmented glyphs into a sprite sheet the map can draw from.

    python3 build_atlas.py

Three jobs.

CLEANING. Each glyph is upsampled, blurred and re-thresholded, which puts its
contour at a sub-pixel position and turns the camera's ragged stair-stepping
back into a drawn edge. potrace then writes a real vector of each glyph into
type/svg/ — those are the archival copies, and they are what "vectorised"
means here. The sprite sheet itself is rasterised from the same cleaned mask,
because its only consumer is a texture a few dozen pixels across.

REFLECTION. Three glyphs were placeholders on the sheet, and are built from
the ones they are reflections of:

    d = b mirrored        q = p mirrored        x = uppercase X, reduced

x is reduced by the ratio the specimen itself sets — its own x-height over its
own cap height — so it matches the lowercase it sits among rather than an
assumed proportion.

NORMALISATION. Every glyph in a set is placed at one scale on one baseline.
The scale comes from the set's own reference height — cap height for capitals,
x-height for lowercase — measured as the median across the set, so a single
letter drawn slightly large cannot pull the rest out of true. Ascenders and
descenders keep the length they were drawn with; only the common measure is
standardised.

Output is type/hand.png (a sprite sheet) and type/hand.json (metrics), both
read by inscribe.js.
"""

import json, subprocess
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
GLYPHS = HERE / "glyphs"
SVG = HERE / "svg"

CELL = 220          # px per sprite cell
BASELINE = 168      # px from the cell top
REF = 100           # px the set's reference height is scaled to
UP = 3              # upsample factor while smoothing

# letters that neither rise above the x-height nor fall below the baseline;
# these define the lowercase measure
XHEIGHT = set("acemnorsuvwz")
DESCEND = set("gjpqy")


def boxblur(a, r):
    pad = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = a.shape
    k = 2 * r + 1
    return (c[k:k + h, k:k + w] - c[0:h, k:k + w]
            - c[k:k + h, 0:w] + c[0:h, 0:w]) / (k * k)


def clean(mask):
    """Upsample, blur, re-threshold: a drawn edge instead of a pixel staircase."""
    big = np.repeat(np.repeat(mask.astype(np.float32), UP, axis=0), UP, axis=1)
    for _ in range(2):
        big = (boxblur(big, 4) > 0.5).astype(np.float32)
    return big > 0.5


def trace(mask, path):
    """Archival vector of one glyph."""
    pbm = path.with_suffix(".pbm")
    Image.fromarray((~mask).astype(np.uint8) * 255).convert("1").save(pbm)
    subprocess.run(["potrace", str(pbm), "-s", "-o", str(path),
                    "--turdsize", "8", "--alphamax", "1.334",
                    "--opttolerance", "0.6", "--turnpolicy", "black"],
                   check=True)
    pbm.unlink()


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    SVG.mkdir(exist_ok=True)

    # --- load and clean ----------------------------------------------------
    glyphs = {}
    for m in manifest:
        raw = np.asarray(Image.open(GLYPHS / m["file"]).convert("L")) < 128
        glyphs[m["char"]] = {"mask": clean(raw), "m": m}
    print(f"{len(glyphs)} glyphs loaded and cleaned")

    # --- baselines, per row ------------------------------------------------
    # A set spans three physical rows on the sheet, each written on its own
    # line. Taking one baseline per SET puts the first and last rows a
    # hundred pixels off their true line, which throws them clean out of
    # their sprite cells. Each row is measured separately.
    rows = {}
    for m in manifest:
        rows.setdefault(m["row"], []).append(m)

    base_of_row = {}
    for ri, ms in rows.items():
        sitting = [m for m in ms if m["char"] not in DESCEND]
        base_of_row[ri] = float(np.median([m["bottom"] for m in (sitting or ms)]))

    for ch, g in glyphs.items():
        g["base"] = base_of_row[g["m"]["row"]]

    # reference heights, measured from each glyph's own line
    upper = [c for c in glyphs if glyphs[c]["m"]["set"] == "upper"]
    lower = [c for c in glyphs if glyphs[c]["m"]["set"] == "lower"]
    cap_h = float(np.median([glyphs[c]["base"] - glyphs[c]["m"]["top"] for c in upper]))
    x_h = float(np.median([glyphs[c]["base"] - glyphs[c]["m"]["top"]
                           for c in lower if c in XHEIGHT]))

    print(f"cap height {cap_h:.0f} px, x-height {x_h:.0f} px "
          f"({x_h / cap_h:.3f} of cap)")
    print("row baselines: " + ", ".join(f"{r}:{b:.0f}" for r, b in sorted(base_of_row.items())))

    REF_OF = {"upper": cap_h, "lower": x_h, "punct": x_h}

    # --- reflections -------------------------------------------------------
    made = {}
    for target, source, flip in (("d", "b", True), ("q", "p", True)):
        g = glyphs[source]
        made[target] = {"mask": g["mask"][:, ::-1],
                        "m": dict(g["m"], char=target), "base": g["base"]}
        print(f"{target} built from {source}, mirrored")

    # x: the uppercase X, reduced to the lowercase measure. Scaling happens in
    # placement, so all that is recorded here is the mask and a synthetic box
    # sitting on the lowercase baseline.
    gx = glyphs["X"]
    x_base = base_of_row[4]                     # the middle lowercase row
    h_scaled = (gx["base"] - gx["m"]["top"]) * (x_h / cap_h)
    made["x"] = {
        "mask": gx["mask"], "base": x_base,
        "m": {"char": "x", "set": "lower", "row": 4,
              "top": x_base - h_scaled, "bottom": x_base,
              "w": gx["m"]["w"], "h": h_scaled},
    }
    print(f"x built from uppercase X at {x_h / cap_h:.3f} scale")
    glyphs.update(made)

    # --- sprite sheet ------------------------------------------------------
    chars = sorted(glyphs, key=lambda c: (glyphs[c]["m"]["set"], c))
    cols = 8
    rows = (len(chars) + cols - 1) // cols
    # RGBA, not greyscale. IconLayer is told to treat the atlas as a mask, so
    # it reads the ALPHA channel — a greyscale sheet composites its black
    # background as fully opaque and every glyph renders as a solid square.
    sheet = Image.new("LA", (cols * CELL, rows * CELL), (255, 0))

    entries = {}
    for i, ch in enumerate(chars):
        g = glyphs[ch]
        m = g["m"]
        base, ref = g["base"], REF_OF[m["set"]]
        scale = REF / ref

        mask = g["mask"]
        h_px = (m["bottom"] - m["top"]) * scale        # target height in cell px
        w_px = h_px * mask.shape[1] / mask.shape[0]
        alpha = Image.fromarray((mask * 255).astype(np.uint8)).resize(
            (max(1, round(w_px)), max(1, round(h_px))), Image.LANCZOS)
        img = Image.merge("LA", (Image.new("L", alpha.size, 255), alpha))

        # baseline alignment: the glyph's own bottom relative to its set's
        # baseline, so descenders hang and ascenders rise as drawn
        dy = (m["bottom"] - base) * scale
        cx = (i % cols) * CELL + (CELL - img.width) // 2
        cy = (i // cols) * CELL + round(BASELINE + dy) - img.height
        sheet.paste(img, (cx, cy), alpha)

        entries[ch] = {
            "x": (i % cols) * CELL, "y": (i // cols) * CELL,
            "w": CELL, "h": CELL,
            "set": m["set"],
        }
        trace(g["mask"], SVG / f"{ord(ch):03d}.svg")

    sheet.convert("RGBA").save(HERE / "hand.png")
    (HERE / "hand.json").write_text(json.dumps({
        "cell": CELL, "baseline": BASELINE, "ref": REF,
        "capOverX": round(cap_h / x_h, 4),
        "glyphs": entries,
    }, indent=1))

    px = (HERE / "hand.png").stat().st_size / 1000
    print(f"\nsheet {cols}x{rows} cells, {len(chars)} glyphs, {px:.0f} KB")
    print("".join(sorted(glyphs)))


if __name__ == "__main__":
    main()
