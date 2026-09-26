"""Product-layer tests: project model + runners, Tk-free.

Covers the field-to-finish chain end to end through the app's own
orchestration functions: synthetic Emlid CSV -> import -> adjust ->
draft PDF. GUI tests live in test_app_smoke.py.
"""
import json
import os

import pytest

from suite import project as project_mod
from suite.project import SurveyProject
from suite import runners


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

EMLID_HEADER = ("Name,Code,Easting,Northing,Elevation,Description,Longitude,"
                "Latitude,Ellipsoidal height,Origin,Tilt angle,Easting RMS,"
                "Northing RMS,Elevation RMS,Lateral RMS,Antenna height,"
                "Antenna height units,Solution status,Correction type,"
                "Averaging start,Averaging end,Samples,PDOP,Base easting,"
                "Base northing,Base elevation,Base longitude,Base latitude,"
                "Base ellipsoidal height,Baseline,CS name")


def emlid_row(name, e, n, h, day, de=0.0, dn=0.0, dh=0.0):
    return (f"{name},EP,{e + de:.3f},{n + dn:.3f},{h + dh:.3f},desc,"
            f"-77.60972,43.16112,136.021,Global,0.8,0.011,0.010,0.018,0.015,"
            f"2.000,m,FIX,RTK,{day} 14:02:11.2 UTC+00:00,"
            f"{day} 14:02:16.2 UTC+00:00,25,1.8,284000.000,4780000.000,"
            f"172.500,-77.61000,43.16100,138.214,17.832,"
            f"NAD83(2011) / UTM zone 18N")


def write_csv(path, day, perturbs):
    base = {"101": (284012.512, 4780012.884, 170.214),
            "102": (284042.512, 4780012.884, 170.201),
            "103": (284042.512, 4780042.884, 170.195),
            "104": (284012.512, 4780042.884, 170.208)}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(EMLID_HEADER + "\n")
        for name, (e, n, h) in base.items():
            de, dn, dh = perturbs.get(name, (0.0, 0.0, 0.0))
            fh.write(emlid_row(name, e, n, h, day, de, dn, dh) + "\n")


@pytest.fixture()
def workdir(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


# ---------------------------------------------------------------------------
# project model
# ---------------------------------------------------------------------------

def test_project_roundtrip(workdir, tmp_path, monkeypatch):
    monkeypatch.setattr(project_mod, "RECENT_FILE",
                        str(tmp_path / "recent.json"))
    p = SurveyProject.new("job1", workdir, crs="NAD83(2011) / UTM zone 18N")
    p.surveyor_name = "Test Surveyor"
    csv = os.path.join(workdir, "day1.csv")
    open(csv, "w").write("x")
    p.csv_files.append(p.relpath(csv))
    p.set_artifact("job_path", os.path.join(workdir, "job.sfield.json"))
    sproj = p.save()
    assert os.path.isfile(sproj)

    q = SurveyProject.load(sproj)
    assert q.name == "job1"
    assert q.crs == "NAD83(2011) / UTM zone 18N"
    assert q.surveyor_name == "Test Surveyor"
    # stored relative, resolves absolute
    assert q.job_path == "job.sfield.json"
    assert q.resolve(q.job_path) == os.path.join(workdir, "job.sfield.json")
    assert project_mod.recent_projects()[0] == sproj


def test_project_rejects_newer_schema(workdir):
    p = SurveyProject.new("job1", workdir)
    sproj = p.save()
    with open(sproj, encoding="utf-8") as fh:
        d = json.load(fh)
    d["schema_version"] = 999
    with open(sproj, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    with pytest.raises(ValueError, match="newer"):
        SurveyProject.load(sproj)


# ---------------------------------------------------------------------------
# weights
# ---------------------------------------------------------------------------

def test_default_weights_valid():
    cfg = runners.default_weights()
    assert runners.validate_weights(cfg) == []
    summary = runners.weights_summary(cfg)
    assert "RTK" in summary and "Levels" in summary


def test_invalid_weights_explained():
    cfg = runners.default_weights()
    cfg["rtk"]["rms_scale"] = -1.0
    problems = runners.validate_weights(cfg)
    assert problems and "rms_scale" in problems[0]

    cfg = runners.default_weights()
    cfg["rtk"]["float_policy"] = "sometimes"
    assert runners.validate_weights(cfg)

    cfg = runners.default_weights()
    cfg["overrides"] = [{"scope": "bogus", "class": "rtk",
                         "params": {"rms_scale": 2.0}}]
    assert runners.validate_weights(cfg)


def test_style_template_valid():
    assert runners.validate_style(runners.style_template()) == []
    bad = runners.style_template()
    bad["layers"]["boundary"]["color"] = [999, 0, 0]
    assert runners.validate_style(bad)


def test_parcel_template_closes():
    parcel = runners.parcel_template(["101", "102", "103"], units="ft")
    assert parcel["units"] == "ft"
    assert parcel["segments"][-1]["to"] == "101"


# ---------------------------------------------------------------------------
# end to end: CSV -> import -> adjust -> draft
# ---------------------------------------------------------------------------

def test_field_to_finish_end_to_end(workdir):
    day1 = os.path.join(workdir, "day1.csv")
    day2 = os.path.join(workdir, "day2.csv")
    write_csv(day1, "2026-09-25", {})
    write_csv(day2, "2026-09-26",
              {"101": (0.003, -0.002, 0.004), "102": (-0.002, 0.003, -0.003),
               "103": (0.002, 0.002, 0.002), "104": (-0.003, -0.003, -0.004)})

    # 1. import
    job_path = os.path.join(workdir, "job.sfield.json")
    imp = runners.run_import([day1, day2], job_path, project_name="e2e")
    assert imp.ok, imp.issues
    assert imp.n_errors == 0
    assert imp.summary["n_points"] == 8  # 4 points x 2 occupations

    # 2. adjust
    cfg = runners.default_weights()
    adj = runners.run_adjust(job_path, cfg, workdir, name="e2e")
    assert adj.valid, adj.checks
    assert adj.verdict == "VALID"
    assert os.path.isfile(adj.report_path)
    assert os.path.isfile(adj.sadj_path)
    assert adj.n_points >= 4
    import json as _json
    with open(adj.sadj_path, encoding="utf-8") as fh:
        sadj = _json.load(fh)
    rtk_pts = [p for p in sadj["points"]
               if "rtk-weighted-mean" in p["source"]]
    assert len(rtk_pts) == 4
    # merged points keep planimetric coordinates (the v0.1.1 interop fix)
    assert all(p["easting"] is not None and p["northing"] is not None
               for p in rtk_pts)
    report_text = runners.read_report(adj.report_path)
    assert "VALID" in report_text

    # 3. map data prefers adjusted coordinates
    pts = runners.map_points(job_path=job_path, sadj_path=adj.sadj_path)
    by_name = {p["name"]: p for p in pts}
    assert "rtk-weighted-mean" in by_name["101"]["source"]
    assert by_name["101"]["sigma_e"] is not None
    assert runners.map_extent(pts) is not None

    # 4. draft
    names = ["101", "102", "103", "104"]
    parcel = runners.parcel_template(names, units="ft")
    out_pdf = os.path.join(workdir, "plat.pdf")
    manifest = runners.run_draft(
        adj.sadj_path, parcel, None, out_pdf,
        options={"kind": "plat", "sheet": "ARCH_D", "scale": "fit",
                 "title": "E2E Test Plat",
                 "surveyor": {"name": "Test", "license_no": "123",
                              "state": "NY"}})
    assert os.path.isfile(out_pdf)
    assert os.path.getsize(out_pdf) > 1000
    assert manifest["validity"] is True
    assert manifest["kind"] == "plat"


def test_not_valid_adjustment_refuses_plat(workdir):
    # single occupations -> no redundancy -> NOT VALID -> DraftRefused
    day1 = os.path.join(workdir, "day1.csv")
    write_csv(day1, "2026-09-25", {})
    job_path = os.path.join(workdir, "job.sfield.json")
    imp = runners.run_import([day1], job_path, project_name="single")
    assert imp.ok
    adj = runners.run_adjust(job_path, runners.default_weights(),
                             workdir, name="single")
    assert not adj.valid
    assert adj.verdict == "NOT VALID"

    from drafting.sadj import DraftRefused
    parcel = runners.parcel_template(["101", "102", "103", "104"])
    with pytest.raises(DraftRefused):
        runners.run_draft(adj.sadj_path, parcel, None,
                          os.path.join(workdir, "nope.pdf"),
                          options={"kind": "plat"})
