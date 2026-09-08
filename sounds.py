#!/usr/bin/env python3
"""
Turn the audio/ folder into a manifest the page can read.

The whole convention is the filename:

    <kind>_<name>.wav        e.g.  voice_grandmothers-stoop.wav
                                   oral_crown-heights-1977.wav
                                   place_nostrand-morning.wav
                                   bed_underlayer.wav

kind is one of the kinds defined in score.js (bed / place / oral / voice) and
sets that clip's default reach, priority and curves. Everything after the
underscore is just a label.

Drop files in, run this, reload the page. Placement is done by dragging the
clip onto the map, which writes anchors into placements.json — this script
never overwrites those.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
AUDIO = HERE / "audio"
OUT = HERE / "data" / "sounds.json"
PLACEMENTS = HERE / "data" / "placements.json"

KINDS = ("bed", "place", "oral", "voice")
EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus")


def main():
    AUDIO.mkdir(exist_ok=True)
    OUT.parent.mkdir(exist_ok=True)

    placements = {}
    if PLACEMENTS.exists():
        placements = json.loads(PLACEMENTS.read_text())

    clips, skipped = [], []
    for f in sorted(AUDIO.iterdir()):
        if f.name.startswith(".") or f.suffix.lower() not in EXTS:
            continue
        kind, _, rest = f.stem.partition("_")
        if kind not in KINDS or not rest:
            skipped.append(f.name)
            continue
        clip = {
            "id": f.stem,
            "kind": kind,
            "label": rest.replace("-", " "),
            "src": f"audio/{f.name}",
        }
        # a placement made in the browser wins over anything here
        if f.stem in placements:
            clip["anchor"] = placements[f.stem].get("anchor")
            if placements[f.stem].get("reach") is not None:
                clip["reach"] = placements[f.stem]["reach"]
            if placements[f.stem].get("priority") is not None:
                clip["priority"] = placements[f.stem]["priority"]
        clips.append(clip)

    OUT.write_text(json.dumps(clips, indent=2))

    placed = sum(1 for c in clips if c.get("anchor"))
    print(f"{len(clips)} clips -> {OUT.relative_to(HERE)}")
    for c in clips:
        where = "placed" if c.get("anchor") else "UNPLACED — drag it onto the map"
        print(f"  {c['kind']:<6} {c['label']:<28} {where}")
    if skipped:
        print(f"\nskipped {len(skipped)} (need a {'/'.join(KINDS)} prefix):")
        for s in skipped:
            print(f"  {s}")
    print(f"\n{placed}/{len(clips)} placed")


if __name__ == "__main__":
    main()
