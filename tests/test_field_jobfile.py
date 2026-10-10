"""Tests for the canonical JSON job file."""

import pytest

from field.emlid import import_emlid_csv
from field.jobfile import dump_job, load_job, read_job, write_job
from field.models import JOB_FORMAT, SCHEMA_VERSION, Project

import os
EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples",
                       "demo_emlid_flow.csv")


def test_round_trip(tmp_path):
    project = import_emlid_csv(EXAMPLE)
    path = str(tmp_path / "job.sfield.json")
    write_job(project, path)
    clone = read_job(path)
    assert clone.to_dict() == project.to_dict()
    assert clone.n_points() == 11


def test_envelope_fields():
    project = import_emlid_csv(EXAMPLE)
    env = dump_job(project)
    assert env["format"] == JOB_FORMAT
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["generator"].startswith("survey-field ")


def test_rejects_wrong_format():
    with pytest.raises(ValueError, match="not a survey-field job file"):
        load_job({"format": "something-else", "project": {}})


def test_rejects_newer_schema():
    project = Project(name="t")
    env = dump_job(project)
    env["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="newer than this reader"):
        load_job(env)
