# survey-suite

> **Project scope:** this repo is the **terrestrial surveying** half of the
> geospatial suite — COGO, leveling, least-squares adjustment, geodesy,
> GNSS, point clouds, and the desktop app. Remote-sensing work (satellite
> imagery, change detection, site monitoring) has moved to its own project:
> **[crieck2010/earthwatch-suite](https://github.com/crieck2010/earthwatch-suite)**.
> The two projects stay compatible through the
> [cross-suite contracts](https://github.com/crieck2010/earthwatch-suite/blob/main/docs/CONTRACTS.md)
> (site-config schema, alert-event schema, GeoJSON interchange).
> `survey-qgis` stays here as the shared cartography bridge.

Meta-package and desktop application over the eight survey-suite
computation engines. The engines do the math; this repo wires them
together into documented workflows and a double-clickable Windows app.

## The engines

| Package | Repo | What it does |
|---|---|---|
| `survey-cogo` | [crieck2010/survey-cogo](https://github.com/crieck2010/survey-cogo) | COGO: inverses, forwards, intersections, traverses, areas |
| `survey-levels` | [crieck2010/survey-levels](https://github.com/crieck2010/survey-levels) | Differential leveling: HI reduction, page checks, misclosure |
| `survey-adjust` | [crieck2010/survey-adjust](https://github.com/crieck2010/survey-adjust) | Least-squares: level nets, angle adjustment, chi-square testing |
| `survey-geodesy` | [crieck2010/survey-geodesy](https://github.com/crieck2010/survey-geodesy) | Ellipsoids, ECEF, Helmert, Transverse Mercator, UTM, Vincenty |
| `survey-raster` | [crieck2010/survey-raster](https://github.com/crieck2010/survey-raster) | Rasters: indices (NDVI/EVI/...), stats, resampling, tiling |
| `survey-pointcloud` | [crieck2010/survey-pointcloud](https://github.com/crieck2010/survey-pointcloud) | Point clouds: thinning, ground classification, DEMs, volumes |
| `survey-gnss` | [crieck2010/survey-gnss](https://github.com/crieck2010/survey-gnss) | GNSS: NMEA parsing, WGS84, DOP, session statistics |
| `survey-field` | [crieck2010/survey-field](https://github.com/crieck2010/survey-field) | Field import: Emlid Flow/ReachView CSV, job model, validation, handoffs to cogo/adjust |

Each engine is pure Python, dependency-free, independently tested, and
usable on its own. This repo adds:

- **`suite.workflows`** — cross-engine integration workflows (below)
- **`suite.app`** — tkinter desktop app, one tab per engine
- **`suite.licensing` / `suite.updates`** — monetization hooks, stubbed
- **`build.py`, `build_exe.bat`, `installer.iss`** — Windows packaging

## Installation

```bash
pip install -e .
```

This pulls the seven engines from their public GitHub repos. Requires
Python ≥ 3.9. Launch the desktop app with:

```bash
survey-suite
# or
python -m suite.app
```

## Integration workflows

`suite.workflows` composes engines into tasks crews actually perform.
Thin orchestration only — no duplicated math.

```python
from suite.workflows import (
    dem_volume_workflow,          # pointcloud -> raster -> volumes
    level_to_adjustment_workflow, # levels -> least-squares
    gnss_cogo_control_workflow,   # gnss -> geodesy -> cogo
)

# 1. Stockpile volume: classify ground, grid a DTM raster, cut/fill.
r = dem_volume_workflow(points, 0, 0, 1.0, 200, 200, base_elevation=100.0)
print(r["cut"], r["fill"], r["net"])   # r["dtm"] is a survey-raster Raster

# 2. Level loop: reduce notes, page-check, then rigorously adjust.
r = level_to_adjustment_workflow("BM-A", 100.0, setups)
print(r["page_check"].ok, r["adjustment"].points)

# 3. NMEA log: session mean -> UTM -> COGO control point.
r = gnss_cogo_control_workflow(open("rover.log"), "CTRL-1")
print(r["control_point"], f"{r['accuracy_m']:.3f} m @95%")
```

## Desktop app

Seven tabs, one per engine; each tab is a form over engine functions:

- **COGO** — inverse (azimuth/distance) and forward computation
- **Levels** — paste setup lines, get HI reduction + page check
- **Adjust** — closed-horizon angle adjustment
- **Geodesy** — lat/lon to UTM
- **Raster** — NDVI from red/NIR grids
- **Point Cloud** — paste XYZ, get ground classification + DTM + volume
  (runs `dem_volume_workflow`)
- **GNSS** — paste an NMEA log, get session mean + UTM control point
  (runs `gnss_cogo_control_workflow`)

The UI is deliberately thin: adding a feature means adding an engine
function, then a tab that calls it.

## Building the Windows .exe

PyInstaller targets the OS it runs on, so the distributable `.exe` must
be built on a Windows PC:

```bat
build_exe.bat
```

This installs dependencies and produces
`dist\SurveySuite\SurveySuite.exe`. Then compile `installer.iss` with
[Inno Setup](https://jrsoftware.org/isinfo.php) for a real installer
with Start Menu and desktop shortcuts.

## Monetization hooks (stubbed)

- **Licensing** (`suite/licensing.py`): `check_license()` looks for a key
  in `SURVEY_SUITE_LICENSE` or `~/.survey-suite/license.key`. Enforcement
  is **off** (`REQUIRE_LICENSE = False`); the stub accepts any key as a
  beta license. Swap in real verification (signed key, or Gumroad / Lemon
  Squeezy license API) before selling.
- **Updates** (`suite/updates.py`): `check_for_updates()` fetches a
  version file with a 3 s timeout. Point `UPDATE_URL` at the real feed at
  release time. Both hooks never raise and never block the UI.

Payments go through a merchant of record (Gumroad / Lemon Squeezy) —
never custom billing code.

## Interoperability

The suite's interop contracts, enforced by the workflows and their tests:

- **NMEA in, control out.** Receiver logs from any hardware parse through
  `survey-gnss` and land as a `survey-cogo` control point via UTM —
  the field-to-office path in one call.
- **Points to rasters.** `survey-pointcloud` DEM grids are already the
  row-major structure `survey-raster` wraps; `dem_volume_workflow`
  returns a first-class `Raster` for hillshading, contours, or export.
- **Notes to adjustment.** `survey-levels` reductions become weighted
  `survey-adjust` observations with the benchmark as held datum — the
  page check guards the adjustment's input.
- **Shared vocabularies.** ASPRS classification codes, GGA fix-quality
  flags, GDAL-style geotransforms, and WGS84 throughout mean data
  round-trips with laspy/PDAL/GDAL-style tooling at the boundaries.

## Scaling

- **Stream at the edges.** NMEA logs and point clouds stream through
  generators and O(1)-memory accumulators; the app tabs that paste data
  are demos — production jobs point the same workflows at files.
- **Rasterize early.** The point-cloud workflow grids once, then every
  downstream step (volumes, indices) runs on the grid, which is orders
  of magnitude smaller than the source cloud.
- **Engines stay dependency-free and import-light** so the PyInstaller
  bundle stays small and cold startup stays fast; heavy future
  dependencies (numpy, laspy, rasterio) belong in optional engine
  upgrades, not in the suite core.
- **Desktop now, services later.** The workflows are UI-agnostic pure
  functions — the same code serves a future web API or batch runner
  without modification.

## Testing

```bash
python -m unittest discover -s tests
```

10 tests covering the three cross-engine workflows (hand-computed
volumes, a closed level loop, a synthetic NMEA log), the licensing and
update stubs (never raise, degrade gracefully), and side-effect-free app
import. All pass. Engine test suites live in their own repos.

## Project structure

```
survey-suite/
├── src/suite/
│   ├── __init__.py      # version
│   ├── workflows.py     # cross-engine integration workflows
│   ├── app.py           # tkinter desktop app (thin UI, 7 tabs)
│   ├── licensing.py     # license-key hook (stubbed, non-blocking)
│   └── updates.py       # update-check hook (stubbed, never raises)
├── tests/test_suite.py
├── pyproject.toml       # engines as git+https dependencies
├── requirements.txt
├── build.py             # one-command PyInstaller build
├── build_exe.bat        # Windows one-command build wrapper
├── installer.iss        # Inno Setup installer script
├── CHANGELOG.md
└── LICENSE
```

## Roadmap

- Engine upgrades: numpy-backed raster/pointcloud paths, RINEX support,
  weighted DOP, progressive morphological ground filters
- App: file dialogs + project save/load, map preview, batch processing
- Distribution: signed installer, auto-updater wired to `suite.updates`,
  license enforcement via merchant-of-record

## License

MIT — see [LICENSE](LICENSE).
