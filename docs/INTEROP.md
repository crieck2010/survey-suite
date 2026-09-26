# INTEROP — how the SurveySuite app talks to the engines

The app (`suite.runners`, `suite.project`) orchestrates; the engines do
the math. Call shapes below are pinned to the engine versions in
`requirements.txt` / `pyproject.toml` — bump a pin deliberately, rerun
the suite, note it in the CHANGELOG.

## Dependency pins (why these exact refs)

pip rejects two different URLs for the same package, so this repo's
pins match the engines' own `pyproject.toml` pins exactly:

| Package | Pin | Pinned by |
|---|---|---|
| survey-adjust | `@bc14483` | survey-adjust-workflow |
| survey-field | `@v0.1.0` | survey-adjust-workflow |
| survey-cogo | `@f59b04d` | survey-drafting |
| survey-drafting | `@v0.1.2` | this repo (RasterSource basemap option; skip elevation-only stations in draw/extent) |
| survey-adjust-workflow | `@v0.1.1` | this repo (merge duplicate stations across paths) |
| survey-basemap | `@v0.1.0` | — |
| survey-levels/geodesy/raster/pointcloud/gnss | `@main` | — |

## survey-field (Import tab)

- `field.emlid.parse_emlid_csv(fh)` → `EmlidParseResult`
  (`.points`, `.base_info`, `.dialect`); multi-CSV merge = concatenate
  points + base_info, then `build_project(...)`.
- `field.validate.validate_project(project, rms_lateral_warn=…,
  rms_elev_warn=…, pdop_warn=…, baseline_warn_m=…)` →
  `[ValidationIssue(severity, code, message, session_id, point_name)]`;
  `has_errors(issues)` gates the chain.
- `field.jobfile.write_job(project, path)` / `read_job(path)`;
  `field.adapters.job_summary(project)`.

## survey-adjust-workflow (Adjust tab)

- `adjustflow.stochastic.default_weights()` → editable dict;
  `validate_weights(cfg)` raises `ValueError` naming the problem.
- The runner mirrors `adjustflow run`: `rtk.adjust_rtk_points`,
  `levelnet.adjust_level_network`, `traverse.adjust_traverse`,
  `report.build_report(ReportData(...))`,
  `jobio.write_sadj(...)` / `write_adjusted_job_revision(...)`.
- Validity via `adjustflow.cli._validity_checks` (documented private
  handoff per the engine's INTEROP; replace if the engine promotes it).
- Outputs: `<name>.report.md`, `<name>.sadj.json`
  (`survey-adjust-workflow/adjusted` schema v1), `<name>.adjusted.sfield.json`.

## survey-drafting (Draft tab)

- `compose_deliverable(sadj_path, parcel_path, style, out_pdf, options)`
  with `options["basemap"]` = image path **or** a `RasterSource`
  instance (v0.1.1 addition — this is why the pin is v0.1.1).
- `DraftRefused` → the validity gate; the app surfaces
  `e.failed` criteria and offers no override.
- `load_style` / `style_template` / `drafting.layout.SHEETS` /
  `parse_scale` drive the page-setup UI.

## survey-basemap (Basemap + Map tabs)

- `GeoTIFFRasterSource(path, project_crs=…, opacity=…, max_render_px=…)`
  (context manager); `.info()`, `.extent_world()`, `.image()`.
- `basemap.overview.build_overviews(path)`; `basemap.quality.check_scale`.
- `CRSMismatch` on CRS disagreement — surfaced to the user, never
  coerced.

## Project manifest (`.sproj`)

Format `survey-suite/project`, schema v1 — see `suite/project.py`.
All artifact paths relative to the project root (portable).
