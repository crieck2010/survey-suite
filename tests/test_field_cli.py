"""Tests for the field CLI."""

import json
import os

from field.cli import main

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples",
                       "demo_emlid_flow.csv")


def test_import_writes_job_and_reports_errors(tmp_path, capsys):
    out = str(tmp_path / "job.sfield.json")
    # duplicate point name "105" -> validation error -> exit 1, job still written
    rc = main(["import", EXAMPLE, "-o", out, "--name", "demo"])
    assert rc == 1
    assert os.path.exists(out)
    captured = capsys.readouterr()
    assert "duplicate-name" in captured.out or "duplicate-name" in captured.err
    with open(out, encoding="utf-8") as fh:
        env = json.load(fh)
    assert env["format"] == "survey-field/job"
    assert env["project"]["name"] == "demo"


def test_import_clean_file_exits_zero(tmp_path, capsys):
    # single clean FIX point
    csv_path = str(tmp_path / "clean.csv")
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("Name,Easting,Northing,Elevation,Solution status,"
                 "Base easting,Base northing,Base elevation\n")
        fh.write("1,500001.0,4500001.0,100.5,FIX,500000.0,4500000.0,100.0\n")
    out = str(tmp_path / "clean.sfield.json")
    rc = main(["import", csv_path, "-o", out])
    assert rc == 0
    assert "validation: 0 error(s)" in capsys.readouterr().out


def test_inspect(tmp_path, capsys):
    out = str(tmp_path / "job.sfield.json")
    main(["import", EXAMPLE, "-o", out])
    capsys.readouterr()
    rc = main(["inspect", out, "--issues"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "demo_emlid_flow" in text
    assert "BASE-1" in text
    assert "FIX=9" in text


def test_export_csv(tmp_path, capsys):
    job = str(tmp_path / "job.sfield.json")
    main(["import", EXAMPLE, "-o", job])
    capsys.readouterr()
    out = str(tmp_path / "points.csv")
    rc = main(["export", job, "-o", out, "--format", "csv"])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        lines = fh.read().strip().splitlines()
    assert lines[0].startswith("session,name,code")
    assert len(lines) == 12  # header + 11 points


def test_inspect_missing_file_fails(capsys):
    assert main(["inspect", "/nonexistent/job.json"]) == 1
