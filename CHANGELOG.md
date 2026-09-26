# Changelog

All notable changes to this project will be documented in this file.

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
