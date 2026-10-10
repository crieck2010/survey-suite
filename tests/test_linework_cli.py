"""CLI: templates print valid JSON; build runs end to end."""
from __future__ import annotations

import json

import pytest

from linework.cli import EXIT_ERROR, EXIT_OK, EXIT_STRICT, main

field = pytest.importorskip("field")


def _write_configs(tmp_path):
    from linework.codeset import codeset_template
    from linework.keys import keys_template
    from linework.prefixes import prefixes_template
    paths = {}
    for name, doc in (("codeset.json", codeset_template("emlid")),
                      ("keys.json", keys_template()),
                      ("prefixes.json", prefixes_template())):
        p = tmp_path / name
        p.write_text(json.dumps(doc), encoding="utf-8")
        paths[name] = str(p)
    return paths


def _write_job(tmp_path):
    from field.jobfile import write_job
    from field.models import Project, RoverSession, SurveyPoint
    pts = [
        SurveyPoint(name="101", code="EC1 *bl",
                    easting=100.0, northing=200.0, elevation=5.0),
        SurveyPoint(name="102", code="EC1",
                    easting=110.0, northing=200.0, elevation=5.1),
        SurveyPoint(name="103", code="EC1 *el",
                    easting=120.0, northing=200.0, elevation=5.2),
        SurveyPoint(name="104", code="",
                    easting=0.0, northing=0.0, elevation=0.0),
    ]
    project = Project(name="cli-test", crs="",
                      sessions=[RoverSession(id="s1", base_station_id=None,
                                             date="2026-10-10", points=pts)])
    job = tmp_path / "job.sfield.json"
    write_job(project, str(job))
    return str(job)


def test_keys_template_is_valid_json(capsys):
    assert main(["keys-template"]) == EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["format"] == "survey-linework/description-keys"


def test_codeset_template_presets(capsys):
    assert main(["codeset-template", "--preset", "civil3d"]) == EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["tokens"]["begin"] == "BEG"
    assert main(["codeset-template"]) == EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["tokens"]["begin"] == "*bl"


def test_prefixes_template_is_valid_json(capsys):
    assert main(["prefixes-template"]) == EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["format"] == "survey-linework/figure-prefixes"


def test_build_smoke(tmp_path, capsys):
    cfg = _write_configs(tmp_path)
    job = _write_job(tmp_path)
    out = str(tmp_path / "figures.json")
    rc = main(["build", "--job", job, "--codeset", cfg["codeset.json"],
               "--keys", cfg["keys.json"], "--prefixes", cfg["prefixes.json"],
               "--out", out])
    assert rc == EXIT_OK
    data = json.loads(open(out, encoding="utf-8").read())
    assert data["format"] == "survey-linework/figures"
    assert len(data["figures"]) == 1
    assert data["figures"][0]["id"] == "EC1"
    assert data["report"]["counts"]["n_uncoded_points"] == 1
    assert "figures: 1" in capsys.readouterr().out


def test_build_preset_flag(tmp_path):
    cfg = _write_configs(tmp_path)
    job = _write_job(tmp_path)
    out = str(tmp_path / "figures.json")
    rc = main(["build", "--job", job, "--preset", "emlid",
               "--keys", cfg["keys.json"], "--prefixes", cfg["prefixes.json"],
               "--out", out])
    assert rc == EXIT_OK


def test_build_failure_exit_code(tmp_path, capsys):
    cfg = _write_configs(tmp_path)
    from field.jobfile import write_job
    from field.models import Project, RoverSession, SurveyPoint
    pts = [SurveyPoint(name="101", code="EC1 *el",
                       easting=100.0, northing=200.0)]
    project = Project(name="bad", crs="",
                      sessions=[RoverSession(id="s1", base_station_id=None,
                                             date="2026-10-10", points=pts)])
    job = tmp_path / "bad.sfield.json"
    write_job(project, str(job))
    rc = main(["build", "--job", str(job), "--codeset", cfg["codeset.json"],
               "--keys", cfg["keys.json"], "--prefixes", cfg["prefixes.json"],
               "--out", str(tmp_path / "o.json")])
    assert rc == EXIT_ERROR
    assert "end-without-begin" in capsys.readouterr().err


def test_build_strict_flag_exit_code(tmp_path):
    cfg = _write_configs(tmp_path)
    from field.jobfile import write_job
    from field.models import Project, RoverSession, SurveyPoint
    # Auto-begin, never ended -> figure_never_ended flag.
    pts = [SurveyPoint(name="101", code="EC1",
                       easting=100.0, northing=200.0),
           SurveyPoint(name="102", code="EC1",
                       easting=110.0, northing=200.0)]
    project = Project(name="flaggy", crs="",
                      sessions=[RoverSession(id="s1", base_station_id=None,
                                             date="2026-10-10", points=pts)])
    job = tmp_path / "flaggy.sfield.json"
    write_job(project, str(job))
    out = str(tmp_path / "o.json")
    base = ["build", "--job", str(job), "--codeset", cfg["codeset.json"],
            "--keys", cfg["keys.json"], "--prefixes", cfg["prefixes.json"],
            "--out", out]
    assert main(base) == EXIT_OK
    assert main(base + ["--strict"]) == EXIT_STRICT
