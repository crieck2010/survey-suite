# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-09-27 -- "coordinates"

Final build of the current three-build sequence: the toolbox registry,
the native Coordinates toolbox, and reproject-on-import.

### Added
- Registry-driven toolbox architecture (`suite.toolboxes`): the
  `Toolbox` spec (id, title, tab_factory, engine_deps, description,
  order), `register_toolbox` / `all_toolboxes` / `toolbox_by_id` /
  `missing_engine_deps`, duplicate-id rejection, and auto-discovery of
  every `suite.toolbox_*` module. `suite.app` iterates the registry --
  no hardcoded tab list. A future toolbox is one new module with one
  `register_toolbox(...)` call; `app.py` is never touched.
- Missing engine dependencies degrade per-tab: a toolbox whose
  `engine_deps` aren't importable builds a "not installed" notice frame
  with a `pip install` hint instead of raising. The app always launches.
- **Coordinates toolbox** (native, order 70): CRS picker over the
  survey-crs v0.1.0 registry (345 entries) -- text search, EPSG lookup
  ("6539" / "EPSG:6539"), SPCS/UTM/Geographic type filter, state filter
  (defaults to NY), position suggestions via `crs.suggest(lat, lon)`,
  honest UI-level "did you mean …?" fallback for no-hit queries,
  selection details (name, EPSG, datum, kind, unit, area of use,
  state/zone, source, notes), "Set as project CRS", editable datum-note
  field with "Copy to Draft tab", and the reproject-on-import toggle.
- **Reproject on import**: `runners.run_import(..., target_crs=...)`
  threads the project CRS into Import when the Coordinates toggle is
  on. Geographic Emlid exports are transformed via
  `field.reproject.reproject_project` (survey-field v0.2.0, survey-crs
  backend); the job file keeps the `crs_provenance` block and the
  Import tab's report gains a CRS REPROJECTION section with datum-shift
  warnings. Projected-in-a-different-CRS input is refused loudly and
  no half-written job file survives.
- Project tab: the free-text CRS field is gone -- read-only display +
  "Choose…" jumping to the Coordinates picker. New projects capture the
  picker's pending selection; opened projects sync their stored CRS.
- Tests: `tests/test_toolboxes.py` (registry contract, ordering,
  duplicate/invalid ids, missing-dep notice wiring, picker helpers
  against the real survey-crs registry) and GUI flow tests in
  `tests/test_app_smoke.py` (seven tabs from the registry; full
  Coordinates picker flow: search → select → pending CRS → new project
  → reproject toggle → Import target). 48 tests pass (xvfb).
- Docs: new `docs/TOOLBOXES.md` (registry contract + minimal toolbox
  module example), USER_GUIDE gains the Coordinates tab and the NY
  Emlid-geographic → EPSG:6539 workflow, INTEROP gains the survey-crs
  section and the reproject handoff.

### Changed
- Pinned `survey-field@v0.2.0` (reproject API) and added
  `survey-crs@v0.1.0` (picker + transform backend).
- Pinned `survey-adjust-workflow@v0.1.2` (packaging: survey-field pin
  v0.1.0 → v0.2.0; adjustment behavior, weights editor, and
  justification report untouched).
- `installer.iss` and package version bumped to 0.3.0.

### Fixed (interop, landed in the engine repos)
- `survey-adjust-workflow v0.1.2`: dependency metadata now accepts
  `survey-field v0.2.0`, resolving the pip `ResolutionImpossible`
  between the suite's field pin and the workflow's field pin. Verified:
  all 52 engine tests pass unchanged against survey-field v0.2.0.

### Limitations (stated, not fixed)
- survey-crs v0.1.0 has no geoid/NAVD88 model: heights are ellipsoidal.
- Datum transforms between distinct datums may be null approximations;
  accuracy warnings are surfaced in the import report -- never treat the
  output as survey control without reading them.
- survey-field v0.2.0 does not reproject base stations, and refuses
  projected-to-different-projected CRS transformations.
- The CRS registry is intentionally limited to its 345 entries;
  `suggest()` is bbox-based and coarse near zone boundaries.
- The Windows `.exe` must be built on the user's ASUS; the Linux
  PyInstaller run only proves the spec still works.

## [0.2.0] - 2026-09-26 -- "field-to-finish"

### Added
- Six-tab product GUI (`suite.app`, tkinter only): Project, Import,
  Adjust, Map, Draft, Basemap.
- `.sproj` project manifest (`suite.project`): portable relative
  artifact paths, surveyor profile, recent-project tracking.
- Tk-free orchestration (`suite.runners`): import/adjust/draft/basemap
  chain with zero surveying math in the UI layer.
- Adjust tab: full weights editor for the user-dictated stochastic
  model (RTK RMS scale, mm/sqrt(km), arcseconds, mm+ppm, float policy,
  datum hold, JSON overrides with reasons), validation, and the
  written justification report with a VALID / NOT VALID verdict banner.
- Map tab: tkinter Canvas with zoom/pan/fit, solution-status colors,
  boundary polyline, north arrow, scale bar, GeoTIFF basemap toggle +
  opacity.
- Draft tab: parcel point ordering, style JSON editor, sheet/scale/kind
  page setup, seal/signature title block, layer toggles, PDF manifest
  with SHA-256 of every input. The validity gate is absolute: no VALID
  verdict, no plat, no override.
- Basemap tab: GeoTIFF info (CRS/GSD/dims/overviews), plat-scale GSD
  quality verdict, overview builder, attach to project.
- Licensing/update hooks wired into the app as fail-open stubs.
- Docs: product README, `docs/USER_GUIDE.md`, `docs/INTEROP.md`.
- 14 product-layer tests (project model, weights validation,
  end-to-end synthetic Emlid CSV -> import -> VALID adjustment ->
  plat PDF, NOT VALID -> DraftRefused) plus GUI smoke tests that skip
  cleanly headless.

### Changed
- Pinned `survey-adjust-workflow@v0.1.1` and `survey-drafting@v0.1.2`
  (interop fixes found during app integration -- see below).
- `installer.iss` bumped to 0.2.0.

### Fixed (interop, landed in the engine repos)
- `survey-adjust-workflow v0.1.1`: `.sadj.json` points merged by name
  across the rtk/level-net/traverse paths (first non-null coordinate
  wins, sources joined). Previously one entry per (path, station) was
  emitted and survey-drafting's last-wins lookup lost planimetric
  coordinates -- valid adjustments refused to compose.
- `survey-drafting v0.1.2`: point/text entities with no planimetric
  coordinates (elevation-only stations such as held bases) are skipped
  in drawing and extent calculation instead of crashing composition.
- `survey-drafting v0.1.1` (from build #3): `compose_deliverable` also
  accepts a `RasterSource` as the basemap option.

## [0.1.0] - 2026-09-23

### Added
- Meta-package over the seven survey-suite engines (pip-installable via
  git+https dependencies; `survey-suite` console entry point)
- `suite.workflows`: cross-engine integration workflows --
  `dem_volume_workflow` (pointcloud -> raster DTM -> cut/fill),
  `level_to_adjustment_workflow` (levels reduction/page check -> adjust
  least-squares), `gnss_cogo_control_workflow` (NMEA log -> session mean
  -> UTM -> COGO control point)
- `suite.app`: tkinter desktop application, one tab per engine, thin UI
  (all math in the engines; import side-effect free)
- `suite.licensing`: license-key hook, stubbed and non-blocking
  (`REQUIRE_LICENSE = False`)
- `suite.updates`: update-check hook, stubbed, never raises or blocks
- `build.py` + `build_exe.bat`: one-command PyInstaller builds
  (Windows .exe must be built on a Windows PC)
- `installer.iss`: Inno Setup installer script
- 10 unit tests covering the workflows, stubs, and app import, all passing
