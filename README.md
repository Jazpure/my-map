# my map

A non-representational self-portrait: a year of my own movement through New
York, rendered as text.

The essay that accompanies the piece is set as ordinary prose across the whole
city, line by line, clipped to the borough outlines. Where I actually spent
time, that text is pulled out of shape — dragged toward the mass, skewed out of
its line, inked from pink into red, yellow and blue, and finally broken apart
into particles. Where nothing happened to me it lies flat and legible.

The argument is in the contrast. A place you crossed once keeps its sentence.
A corner you lived on is unreadable.

Sound works the same way: a pool of city recordings, granulated so nothing ever
repeats, with the balance between them following how dense the ground under the
camera is. Quiet ground pulls in distant rumble; dense ground pulls in crowds.

## Running it

Any static server will do:

```bash
python3 -m http.server 5173
```

Then open <http://localhost:5173>. Sound starts on the first click — browsers
will not open an audio context without one.

## Moving around

The piece is a zoom instrument, and the whole range does something:

| zoom | what happens |
|---|---|
| ~10.5 | the city entire; the prose is a fine pink field, movement is coloured mass |
| ~13 | prose resolves into letters, the warp around the nodes becomes visible |
| ~15–16 | the prose is readable; the node letters are at their most legible |
| ~17+ | letters atomise into particles and the text comes apart |

## The pipeline

Each step writes into `data/` and the next one reads it. Only the first needs
re-running when the movement data changes.

```
ingest.py        location export (Google Timeline / Takeout / GPX) -> trace.json
fetch.py         asks Overpass only for the ground the trace touches
build.py         bakes a `lit` value onto every footprint and street segment
subway.py        keeps the subway lines that join the places actually visited
prepare_audio.py measures and converts field recordings into the sound pool
title/trace_title.py  cleans and vectorises the hand-lettered title
```

`trace.py` is the single source of movement data; everything imports `points()`
from it. With no export present it falls back to a synthetic stand-in, so the
whole pipeline runs end to end with nothing plugged in.

## Not in this repository

`data/trace.json` — the raw movement data. The site renders from the baked
geojson and never reads it, so it stays local.

`data/osm/` — 29 MB of raw Overpass responses. `fetch.py` regenerates them.

## Built with

MapLibre GL JS, deck.gl and Tone.js, all from CDN. Geometry from
OpenStreetMap via Overpass; borough boundaries from NYC Open Data. City
ambience from Epidemic Sound. Typeface is Courier.
