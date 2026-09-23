# Changelog

All notable changes to this project will be documented in this file.

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
