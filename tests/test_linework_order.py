"""End-to-end order preservation: CSV -> survey-field job -> figures.

survey-field's ``parse_emlid_csv`` iterates CSV rows in order and appends
points to per-(base, day) RoverSessions in row order; JSON lists round-trip
in order. This test asserts the whole chain: the figure vertex order must
equal the CSV row order.
"""
from __future__ import annotations

import io

import pytest

field_emlid = pytest.importorskip("field.emlid")
field_jobfile = pytest.importorskip("field.jobfile")

from linework.codeset import builtin_codeset  # noqa: E402
from linework.figures import FigureBuilder  # noqa: E402
from linework.keys import DescriptionKeys, keys_template  # noqa: E402
from linework.prefixes import FigurePrefixDB, prefixes_template  # noqa: E402

CSV = """Name,Code,Easting,Northing,Elevation
103,EC1 *bl,30.0,100.0,5.0
101,EC1,10.0,100.0,5.1
105,EC1,50.0,100.0,5.2
102,EC1,20.0,100.0,5.3
104,EC1 *el,40.0,100.0,5.4
"""


def test_order_preserved_csv_to_figures(tmp_path):
    csv_path = tmp_path / "coded.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    project = field_emlid.import_emlid_csv(str(csv_path))

    # CSV row order survives the parse...
    assert [p.name for p in project.sessions[0].points] == \
        ["103", "101", "105", "102", "104"]

    # ...the job-file round trip...
    job_path = str(tmp_path / "job.sfield.json")
    field_jobfile.write_job(project, job_path)
    project2 = field_jobfile.read_job(job_path)
    assert [p.name for p in project2.sessions[0].points] == \
        ["103", "101", "105", "102", "104"]

    # ...and the figure build.
    builder = FigureBuilder(
        builtin_codeset("emlid"),
        DescriptionKeys.from_dict(keys_template()),
        FigurePrefixDB.from_dict(prefixes_template()))
    result = builder.build(project2)
    assert len(result.figures) == 1
    fig = result.figures[0]
    assert [v.name for v in fig.vertices] == ["103", "101", "105", "102", "104"]
    assert [round(v.easting, 1) for v in fig.vertices] == \
        [30.0, 10.0, 50.0, 20.0, 40.0]


def test_csv_rows_out_of_numeric_order_still_follow_row_order(tmp_path):
    # Point names are deliberately *not* the collection order; the figure
    # must follow rows, not names.
    rows = ["Name,Code,Easting,Northing,Elevation"]
    for i, name in enumerate(["Z9", "A1", "M5", "B2"]):
        code = "EC1 *bl" if i == 0 else ("EC1 *el" if i == 3 else "EC1")
        rows.append(f"{name},{code},{i * 10.0},0.0,0.0")
    csv_path = tmp_path / "coded2.csv"
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    project = field_emlid.import_emlid_csv(str(csv_path))
    builder = FigureBuilder(
        builtin_codeset("emlid"),
        DescriptionKeys.from_dict(keys_template()),
        FigurePrefixDB.from_dict(prefixes_template()))
    fig = builder.build(project).figures[0]
    assert [v.name for v in fig.vertices] == ["Z9", "A1", "M5", "B2"]
