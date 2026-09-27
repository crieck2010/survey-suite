# SurveySuite User Guide — v0.3.0

The desktop app walks the field-to-finish chain in order. Each tab below
feeds the next; the Project tab's checklist shows where you stand.

## Project tab

A project is a folder plus a `<name>.sproj` manifest. All artifact paths
are stored *relative* to the folder, so the whole folder is portable —
zip it, move it to the ASUS, open it there.

- **New**: name + directory + CRS — picked in the **Coordinates**
  toolbox, never typed freehand (see below). The CRS field on this tab
  is read-only; the **Choose…** button jumps you to the picker.
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

**Reproject on import** (new in v0.3.0): if your Emlid export is in a
*geographic* coordinate system (lon/lat, e.g. WGS 84) but your project
CRS is a projected zone, tick **Reproject geographic imports to the
project CRS** on the Coordinates tab. Import then transforms every
point into the project CRS via `survey-field --target-crs`
(survey-crs backend) and records a `crs_provenance` block in the job.
The Import tab shows the live target ("Reproject on import: ON →
…") and the report gains a **CRS REPROJECTION** section with any
**datum warnings** — read them before treating the result as control.

Rules the toggle follows (loud, never silent):

- Geographic in, target set → transformed. Projected-in-the-*same*-CRS
  in, target set → no-op, noted in provenance.
- Projected in a *different* CRS than the target → **refused**: the
  import aborts and no half-written job file is left behind. Mixing
  coordinate systems silently is how plats end up in the wrong county.
- Base-station coordinates are *not* reprojected (survey-field v0.2.0
  limitation) — they keep their export values.
- Heights stay **ellipsoidal**: survey-crs v0.1.0 has no geoid/NAVD88
  model. Orthometric heights are not computed.

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

## Coordinates tab (new in v0.3.0)

The CRS picker over the survey-crs registry (345 EPSG-researched
entries: NAD83(2011) SPCS zones, WGS 84 UTM zones, geographic systems).

- **Search**: type a name fragment ("york long island") or an EPSG
  code ("6539" / "EPSG:6539"). Unknown text gets a "did you mean …?"
  list — that's a UI-level token fallback, not fuzzy matching from
  the engine.
- **Filters**: Type (SPCS / UTM / Geographic) and State — the State
  list defaults to **NY** and shows that state's SPCS zones first.
- **Suggest for position**: enter lat/lon and the registry returns the
  SPCS zones whose area contains the point, then UTM — coarse near
  zone boundaries, so confirm against your project location.
- **Selection**: full details — name, EPSG (with epsg.io link), datum,
  kind, unit, area of use, state/zone, source, notes.
- **Set as project CRS**: with a project open it writes `project.crs`
  and saves the `.sproj` immediately; with none open it stages the
  choice as pending text that the next New project captures.
- **Datum note**: editable field pre-filled from the registry entry;
  **Copy to Draft tab** drops it into the plat's datum-note field.

### The NY workflow (Emlid geographic export → NY Long Island ftUS)

The canonical v0.3.0 flow, end to end:

1. **Coordinates tab** — search `york long island`, select
   **NAD83(2011) / New York Long Island (ftUS)** (EPSG:6539),
   **Set as project CRS**. Read the datum note: heights are
   ellipsoidal, and any WGS 84 → NAD83(2011) shift is a null
   approximation.
2. Tick **Reproject geographic imports to the project CRS**.
3. **Project tab** — New project (the CRS arrives from the picker).
4. **Import tab** — pick your Emlid geographic CSVs (lon/lat +
   ellipsoidal height), Run import. The report's **CRS REPROJECTION**
   section shows source → target, point count, and datum warnings.
5. Continue the chain: Adjust → Map → Draft, exactly as before —
   now in NY SPCS feet.

If the survey-crs engine isn't installed, this tab shows an install
notice instead of the picker; the other six toolboxes work normally.
