"""Tests for the survey-opus CLI (``survey_opus.cli``).

All commands run through ``cli.main(argv)`` with stdout captured. The real
RINEX fixture exercises the true ``validate`` path end to end; submit/parse
internals are monkeypatched so these tests never touch the network and never
depend on sibling parser behavior beyond the public contract in
``/tmp/opus_findings.md``.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import survey_opus.cli as cli
from survey_opus.client import OpusError
from survey_opus.rinex import RinexError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RINEX_FIX = FIXTURES / "rinex" / "minimal_2.11.obs"
REPORT_FIX = FIXTURES / "reports" / "synthetic_success.txt"


def _receipt(**overrides):
    fields = dict(
        submitted_at="2026-10-08T21:00:00",
        email="you@example.com",
        rinex_filename="TESTRV0010.26o",
        antenna_type="TRM59900.00",
        antenna_height=1.842,
        mode="static",
        endpoint_url="https://www.ngs.noaa.gov/OPUS-cgi/OPUS/Upload/Opusup.prl",
        seqnum="OP20261008210000",
        response_status=200,
        response_excerpt="uploadPending.jsp?opusProcess=OPUS",
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _solution(**overrides):
    fields = dict(
        file="synthetic_success.txt",
        email="surveyor@example.com",
        processing_date="October 08, 2026",
        nad83=SimpleNamespace(
            frame="NAD83(2011)", epoch="2010.0000",
            lat_deg=44.90370770, lon_deg=-68.66336760, ell_ht_m=60.512,
        ),
        itrf=None,
        utm=None,
        spc=None,
        overall_rms_m=0.012,
        pct_obs_used=97.0,
        pct_ambiguities_fixed=94.0,
        peak_to_peak_m={"lat": 0.020, "lon": 0.018, "ht": 0.035},
        base_stations=["P039", "P040", "P041"],
        software="page5 2008.1917",
        ephemeris="igs22345.eph [precise]",
        raw_text="...",
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def test_fixture_files_exist():
    assert RINEX_FIX.is_file(), f"missing RINEX fixture: {RINEX_FIX}"
    assert REPORT_FIX.is_file(), f"missing report fixture: {REPORT_FIX}"


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_fixture_ok(capsys):
    """Real fixture, real parser: 4 h session, good antenna -> exit 0."""
    rc = cli.main(["validate", str(RINEX_FIX)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TESTRV" in out            # marker name from the header
    assert "TRM59900.00" in out       # antenna type from the header
    assert "1.842 m" in out           # antenna height from the header
    assert "OK" in out


def test_validate_lists_problems(capsys, monkeypatch):
    """Problems from validate_for_opus are printed and exit code is 1."""
    monkeypatch.setattr(cli, "validate_for_opus",
                        lambda header: ["synthetic problem A", "synthetic problem B"])
    rc = cli.main(["validate", str(RINEX_FIX)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "synthetic problem A" in out
    assert "synthetic problem B" in out


def test_validate_missing_file(capsys):
    rc = cli.main(["validate", str(FIXTURES / "rinex" / "nope.obs")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err


def test_validate_unparseable(capsys, monkeypatch):
    def boom(path):
        raise RinexError("bad header")
    monkeypatch.setattr(cli, "parse_header", boom)
    rc = cli.main(["validate", str(RINEX_FIX)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "bad header" in err


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

def test_submit_prints_receipt(capsys, monkeypatch):
    seen = {}

    def fake_submit(rinex_path, email, antenna_type, antenna_height,
                    mode="static", timeout=60, session=None):
        seen.update(mode=mode, email=email)
        return _receipt(email=email, mode=mode)

    monkeypatch.setattr(cli, "submit", fake_submit)
    rc = cli.main(["submit", str(RINEX_FIX),
                   "--email", "you@example.com",
                   "--antenna-type", "TRM59900.00",
                   "--antenna-height", "1.842",
                   "--mode", "static"])
    out = capsys.readouterr().out
    assert rc == 0
    assert seen == {"mode": "static", "email": "you@example.com"}
    assert "you@example.com" in out
    assert "TRM59900.00" in out
    assert "OP20261008210000" in out     # seqnum from the receipt
    assert "static" in out


def test_submit_rapid_static_mode(capsys, monkeypatch):
    monkeypatch.setattr(cli, "submit",
                        lambda *a, **k: _receipt(mode=k.get("mode", "static")))
    rc = cli.main(["submit", str(RINEX_FIX),
                   "--email", "you@example.com",
                   "--antenna-type", "TRM59900.00",
                   "--antenna-height", "1.842",
                   "--mode", "rapid-static"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "rapid-static" in out


def test_submit_failure(capsys, monkeypatch):
    def boom(*a, **k):
        raise OpusError("connection refused")
    monkeypatch.setattr(cli, "submit", boom)
    rc = cli.main(["submit", str(RINEX_FIX),
                   "--email", "you@example.com",
                   "--antenna-type", "TRM59900.00",
                   "--antenna-height", "1.842"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "connection refused" in err


def test_submit_missing_file(capsys):
    rc = cli.main(["submit", str(FIXTURES / "rinex" / "nope.obs"),
                   "--email", "you@example.com",
                   "--antenna-type", "TRM59900.00",
                   "--antenna-height", "1.842"])
    assert rc == 2


def test_submit_help_shows_etiquette(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["submit", "--help"])
    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "be a good citizen" in out.lower()
    assert "one job at a time" in out.lower()
    assert "no polling api" in out.lower()


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def test_parse_human_summary(capsys, monkeypatch):
    monkeypatch.setattr(cli, "parse_solution", lambda text: _solution())
    rc = cli.main(["parse", str(REPORT_FIX)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NAD83(2011)" in out
    assert "44.90370770" in out
    assert "68.66336760" in out
    assert "12.0 mm" in out            # overall RMS printed in mm
    assert "P039" in out               # base stations listed


def test_parse_json(capsys, monkeypatch):
    monkeypatch.setattr(cli, "parse_solution", lambda text: _solution())
    monkeypatch.setattr(cli, "solution_to_json",
                        lambda sol: json.dumps({"file": sol.file,
                                                "email": sol.email}))
    rc = cli.main(["parse", str(REPORT_FIX), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload == {"file": "synthetic_success.txt",
                       "email": "surveyor@example.com"}


def test_parse_fixture_with_real_parser(capsys):
    """Synthetic report fixture parses end-to-end with the real parser."""
    rc = cli.main(["parse", str(REPORT_FIX)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NAD83(2011)" in out
    assert "surveyor@example.com" in out
    assert "October 08, 2026" in out
    assert "44.90342935" in out          # DMS -> decimal degrees
    assert "68.66336763" in out and "W" in out
    assert "19N" in out                  # UTM zone with hemisphere
    assert "12.0 mm" in out              # overall RMS
    assert "XA0390" in out               # base stations


def test_parse_not_a_report(capsys, monkeypatch):
    def boom(text):
        raise OpusError("unrecognized report")
    monkeypatch.setattr(cli, "parse_solution", boom)
    rc = cli.main(["parse", str(REPORT_FIX)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unrecognized report" in err


def test_parse_missing_file(capsys):
    rc = cli.main(["parse", str(FIXTURES / "reports" / "nope.txt")])
    assert rc == 2
