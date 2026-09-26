# SurveySuite User Guide — v0.2.0

The desktop app walks the field-to-finish chain in order. Each tab below
feeds the next; the Project tab's checklist shows where you stand.

## Project tab

A project is a folder plus a `<name>.sproj` manifest. All artifact paths
are stored *relative* to the folder, so the whole folder is portable —
zip it, move it to the ASUS, open it there.

- **New**: name + directory + CRS (e.g. `NAD83(2011) / UTM zone 18N`).
- **Open / Recent**: reopen any `.sproj`.
- **Surveyor profile**: name, license #, state, firm, client — filled once,
  stamped on every plat's seal block.
- **Checklist**: job → weights → adjustment → report → parcel → basemap →
  deliverables, each ✓/✗.

## Import tab

1. Pick one or more Emlid Flow / ReachView 3 CSV exports (multi-day jobs
   merge into one project).
2. Set acceptance thresholds (lateral/elev RMS, PDOP, max baseline).
3. **Run import** → the validation report appears with **errors** (block
   the chain: duplicate names, missing positions, missing base) and
   **warnings** (FLOAT solutions, high RMS, long baselines) in separate
   sections.
4. The canonical `.sfield.json` job is written into the project.

Errors must be fixed in the field data (or the CSV) — the app never
edits your observations for you.

## Adjust tab — the weights editor

This is the heart of the product. Least squares is only as honest as its
stochastic model, and the model is *yours to dictate*.

**Per-class sigma models** (each editable, each validated):

| Class | Meaning | Default |
|---|---|---|
| RTK | σ = receiver RMS × `rms_scale`, floored at `min_sigma_m` | scale 1.0, floor 5 mm |
| Levels | σ = `mm_per_sqrt_km` / √km | 3.0 mm/√km |
| Angles | σ = `arcseconds` | 5″ |
| Distances | σ = `mm` + `ppm` × D | 2 mm + 2 ppm |

- **`float_policy`** (RTK): `exclude` (default), `downweight`
  (σ × `downweight_factor`), or `include` FLOAT/SINGLE points.
- **`datum_hold`**: which base stations to hold (empty = all).
- **Overrides**: JSON list for class/session/observation-level tweaks,
  each with a `reason` — the justification report quotes your reasons.

**Validate** checks the config and explains every problem in plain
language. **Run adjustment** executes the RTK weighted-mean, level-net,
and (optional) traverse paths, then shows the **justification report**:
datum held and why, your weighting choices with rationale, redundancy,
chi-square test in plain English, blunder analysis (Baarda snooping —
every rejection listed with its residual), adjusted coordinates with
one-sigma uncertainties, and the four-criterion validity verdict.

*FS-exam note: this report is a worked example of everything the exam
asks about least squares — weight matrices, degrees of freedom,
a-posteriori variance factor, and blunder detection. Read it alongside
`docs/WEIGHTING.md` in survey-adjust-workflow.*

## Map tab

- Points colored by solution: **FIX** green, **FLOAT** orange,
  **SINGLE** red, **BASE** blue square.
- Mousewheel zoom, drag pan, Fit button; north arrow and a live scale
  readout.
- **Basemap toggle + opacity slider** — your drone orthomosaic under
  the linework, on/off at will (the same toggle the plat uses at print
  time).
- Boundary polyline draws once a parcel is defined on the Draft tab.

## Basemap tab

1. Load a finished orthomosaic GeoTIFF (DJI Terra 2D export or ODM
   orthophoto).
2. The info panel shows CRS, GSD, dimensions, bands, overviews.
3. The **GSD-vs-scale verdict** tells you whether the imagery is fine
   enough for your plat scale (e.g. 1″=50′ wants ≈15 cm GSD) — a WARN
   here means the basemap will look soft, not that anything is wrong
   with your survey.
4. **Build overviews** once per TIFF (cached in a `.ovr` sidecar) for
   fast rendering.
5. **Attach to project** — the Draft tab and Map tab pick it up.

A CRS mismatch between basemap and project is refused loudly — the
basemap never renders under linework in the wrong coordinate system.

## Draft tab

1. Order boundary points (from the adjusted set) → parcel preview.
2. Style sheet: JSON editor with Load template + Validate.
3. Sheet (ANSI A–E, ARCH C/D), scale (fit or standard), kind
   (plat / plan / map).
4. Title block fields; the surveyor block comes from your profile.
5. Layer toggles: basemap, easements, boundary, linework, points,
   control, annotations — exactly what prints.
6. **Compose PDF** → the manifest (with SHA-256 of every input and the
   PDF) is shown and stored in the project.

The **validity gate is absolute**: without a VALID adjustment verdict
there is no plat, and there is no override switch. This is deliberate —
a plat that drafts from a failed adjustment is worse than no plat.

The plat set includes your adjustment justification report as an
appendix, so the *why* behind the numbers travels with the deliverable.
