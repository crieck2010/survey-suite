# SurveySuite — field-to-finish land surveying software

> **Project scope:** this repo is the **terrestrial surveying** half of the
> geospatial suite — field import, least-squares adjustment, drafting,
> drone basemaps, and the desktop app. Remote-sensing work (satellite
> imagery, change detection, site monitoring) lives in its own project:
> **[crieck2010/earthwatch-suite](https://github.com/crieck2010/earthwatch-suite)**.

SurveySuite is a standalone desktop application that takes you from the
field to a finished plat: import Emlid RTK CSVs, run a user-weighted
least-squares adjustment with a written justification, draft plats/plans/maps
to PDF over a toggleable drone-orthomosaic basemap — all offline, on your
own machine.

**v0.2.0 "field-to-finish"** is the first product release: the five-build
program (field import → adjustment workflow → drafting/deliverables →
drone basemap → desktop app) wired into one GUI.

## The 5-minute field-to-finish tour

1. **Project tab** — New project, name it, set the CRS (e.g.
   `NAD83(2011) / UTM zone 18N`), fill in your surveyor profile once.
2. **Import tab** — pick your Emlid Flow CSVs → Run import. Errors and
   warnings are shown separately; the job saves as `.sfield.json`.
3. **Adjust tab** — the weights editor shows your stochastic model
   (RTK RMS × scale, mm/√km for levels, arcseconds, mm + ppm). Tune it,
   Validate, then Run adjustment. A green **VALID** banner plus the
   written justification report tells you *why* the adjustment is valid.
   Red **NOT VALID**? Read the report — it names the failed criterion.
4. **Map tab** — zoom/pan your points (colored by FIX/FLOAT/SINGLE),
   toggle the drone basemap on/off, slide the opacity.
5. **Basemap tab** — load your DJI Terra / ODM GeoTIFF, check the
   GSD-vs-scale verdict, build overviews once, attach to the project.
6. **Draft tab** — order your boundary points, pick sheet + scale,
   Compose PDF. The plat carries the title block with seal/signature
   block, line/curve tables, and your adjustment report as an appendix.
   If the adjustment isn't VALID, there is no plat — no override, on purpose.

## Install (from source)

```bash
pip install -r requirements.txt   # twelve engines, from public GitHub repos
pip install -e .
survey-suite                      # launch the desktop app
```

Requires Python ≥ 3.9 (3.11/3.12 recommended). Pure Python + tkinter —
no compiled dependencies, works fully offline after install.

## Build the Windows .exe (on your ASUS)

PyInstaller builds for the OS it runs on, so the distributable `.exe`
must be produced on a Windows PC. On the ASUS:

1. Install **Python 3.11 or 3.12** from python.org (check "Add python.exe
   to PATH").
2. Double-click **`build_exe.bat`** — installs everything, builds
   `dist\SurveySuite\SurveySuite.exe`.
3. (Optional installer) Open **`installer.iss`** in Inno Setup and hit
   Compile → `SurveySuite-0.2.0-setup.exe`.

That's it — three steps, no command line needed after step 1.

## The engines

| Package | What it does |
|---|---|
| `survey-cogo` | COGO: inverses, forwards, intersections, traverses, areas |
| `survey-levels` | Differential leveling: HI reduction, page checks, misclosure |
| `survey-adjust` | Least-squares: level nets, angle adjustment, chi-square testing |
| `survey-geodesy` | Ellipsoids, ECEF, Helmert, Transverse Mercator, UTM, Vincenty |
| `survey-raster` | Rasters: indices (NDVI/EVI/...), stats, resampling, tiling |
| `survey-pointcloud` | Point clouds: thinning, ground classification, DEMs, volumes |
| `survey-gnss` | GNSS: NMEA parsing, WGS84, DOP, session statistics |
| `survey-field` | Field import: Emlid Flow/ReachView CSV -> canonical job, validation |
| `survey-adjust-workflow` | Adjustment: user-weighted LS (RTK means, level nets, traverse), Baarda snooping, justification reports |
| `survey-drafting` | Drafting: plats/plans/maps to PDF, validity gate, metes-and-bounds |
| `survey-basemap` | Drone basemap: GeoTIFF reader, overviews, CRS gate, drafting adapter |
| `survey-crs` | CRS registry + transforms: 345 EPSG-researched entries (NAD83(2011) SPCS, WGS 84 UTM, geographic), stdlib TM/LCC/Hotine/UTM engine, datum accuracy metadata, picker API, CLI |

Each engine is pure Python, dependency-free, independently tested, and
usable on its own. This repo adds the product layer:

- **`suite.project`** — the `.sproj` project manifest (portable, relative paths)
- **`suite.runners`** — field-to-finish orchestration, Tk-free and tested
- **`suite.app`** — the tkinter desktop app (thin UI over the runners)
- **`suite.workflows`** — cross-engine integration workflows
- **`suite.licensing` / `suite.updates`** — monetization hooks (stubbed, fail-open)
- **`build.py`, `build_exe.bat`, `installer.iss`** — Windows packaging

## FAQ

**Where does the .exe come from?**
From *your* machine. `build_exe.bat` runs PyInstaller locally and bundles
the Python interpreter plus all twelve engines into one file. Nothing is
downloaded at runtime; the app works fully offline.

**Do I need internet?**
Only for the initial `pip install` (engines come from GitHub). After that,
field -> plat runs offline.

**Why won't it draft my plat?**
The validity gate: drafting requires a VALID adjustment verdict. Open the
justification report on the Adjust tab — it names the failed criterion
(datum, redundancy, stochastic model, or unresolved blunders). Fix the
cause, re-run, then draft. There is deliberately no override.

**Can I use it for licensed plats?**
The plat title block carries a seal/signature block from day one. In NY
(and most states) a plat needs a licensed PLS seal to be recorded — the
software prepares everything up to the seal; the license is yours to earn.

**Is my data sent anywhere?**
No. Everything runs locally. The update check fetches one tiny version
file and never sends anything.

**Does it process raw GNSS baselines?**
No — Emlid Flow/Studio does your baseline processing; SurveySuite imports
the processed solutions. Raw carrier-phase processing is out of scope.

## Docs

- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) — every tab, and the weights
  editor explained (doubles as FS-exam study material)
- [`docs/INTEROP.md`](docs/INTEROP.md) — the contracts between this repo
  and the engine repos
- [`CHANGELOG.md`](CHANGELOG.md) — version history
