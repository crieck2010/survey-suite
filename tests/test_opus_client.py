"""Tests for survey_opus.client: submit(), parse_solution(), solution_to_json().

ZERO live NGS contact: submit() is tested against a mock session and a
local http.server; the autouse socket guard in conftest.py blocks any
non-localhost connection, so no test can ever POST to noaa.gov.
"""

from __future__ import annotations

import datetime
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from survey_opus import client
from survey_opus.client import (
    OPUS_RS_UPLOAD_URL,
    OPUS_UPLOAD_URL,
    OpusError,
    parse_solution,
    solution_to_json,
    submit,
)

REPORTS = Path(__file__).parent / "fixtures" / "reports"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _lab(body: str, label: str) -> str:
    return body.ljust(60) + label


def _write_rinex(
    path: Path,
    *,
    marker: str = "TEST01",
    antenna: str = "TRM57971.00",
    height: float = 2.0,
    start=(2026, 10, 8, 12, 0, 0.0),
    end=(2026, 10, 8, 16, 30, 0.0),
    obs=("C1", "P1", "P2", "L1", "L2"),
) -> Path:
    """Write a minimal RINEX 2.11 header the real rinex engine accepts."""

    def epoch_line(dt, label):
        y, mo, d, h, mi, s = dt
        body = f"  {y:4d}    {mo:2d}     {d:2d}    {h:2d}     {mi:2d}    {s:8.4f}     GPS"
        return _lab(body, label)

    codes = "".join(f"    {c}" for c in obs)
    lines = [
        _lab("     2.11           O", "RINEX VERSION / TYPE"),
        _lab("survey-opus test generator", "PGM / RUN BY / DATE"),
        _lab(marker, "MARKER NAME"),
        _lab(" " * 20 + antenna, "ANT # / TYPE"),
        _lab(f"{height:14.4f}", "ANTENNA: DELTA H/E/N"),
        _lab(f"{len(obs):6d}{codes}", "# / TYPES OF OBSERV"),
        epoch_line(start, "TIME OF FIRST OBS"),
        epoch_line(end, "TIME OF LAST OBS"),
        _lab("", "END OF HEADER"),
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "mock OPUS upload ack"):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    """requests-like mock: records the single POST call."""

    def __init__(self, response: _FakeResponse | None = None):
        self.response = response or _FakeResponse()
        self.calls: list[dict] = []

    def post(self, url, files=None, data=None, timeout=None):
        self.calls.append(
            {"url": url, "files": files, "data": data, "timeout": timeout}
        )
        return self.response


class _CaptureHandler(BaseHTTPRequestHandler):
    received: dict | None = None
    response_body: bytes = b"mock NGS upload ack"

    def do_POST(self):  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        _CaptureHandler.received = {
            "path": self.path,
            "content_type": self.headers.get("Content-Type", ""),
            "body": raw,
        }
        payload = _CaptureHandler.response_body
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args, **kwargs):  # silence test output
        pass


@pytest.fixture()
def full_report_text() -> str:
    return (REPORTS / "opus_static_full.txt").read_text()


@pytest.fixture()
def minimal_report_text() -> str:
    return (REPORTS / "opus_rapidstatic_minimal.txt").read_text()


# ---------------------------------------------------------------------------
# parse_solution(): full static fixture
# ---------------------------------------------------------------------------


def test_parse_full_static_report(full_report_text):
    sol = parse_solution(full_report_text)

    # echo lines
    assert sol.file == "syra274a.26o OP20261008120000"
    assert sol.email == "surveyor@example.com"
    assert sol.processing_date == "October 08, 2026"

    # NAD83(2011) realization
    assert sol.nad83 is not None
    assert sol.nad83.frame == "NAD83(2011)"
    assert sol.nad83.epoch == "2010.0000"
    assert abs(sol.nad83.lat_deg - 43.03753429166667) < 1e-6
    assert abs(sol.nad83.lon_deg - (-76.14527434722223)) < 1e-6
    assert sol.nad83.ell_ht_m == pytest.approx(175.432)

    # ITRF2014 realization
    assert sol.itrf is not None
    assert sol.itrf.frame == "ITRF2014"
    assert sol.itrf.epoch == "2026.7498"
    assert abs(sol.itrf.lat_deg - 43.03753916111111) < 1e-6
    assert abs(sol.itrf.lon_deg - (-76.14527812222222)) < 1e-6
    assert sol.itrf.ell_ht_m == pytest.approx(174.718)

    # grids
    assert sol.utm is not None
    assert sol.utm.system == "UTM"
    assert sol.utm.zone == "18N"
    assert sol.utm.northing_m == pytest.approx(4768432.105)
    assert sol.utm.easting_m == pytest.approx(402118.765)
    assert sol.spc is not None
    assert sol.spc.system == "SPC"
    assert sol.spc.zone == "3101 NY W"
    assert sol.spc.northing_m == pytest.approx(98765.432)
    assert sol.spc.easting_m == pytest.approx(654321.098)

    # quality metrics
    assert sol.overall_rms_m == pytest.approx(0.012)
    assert sol.pct_obs_used == pytest.approx(96.0)
    assert sol.pct_ambiguities_fixed == pytest.approx(93.0)
    assert sol.peak_to_peak_m["lat"] == pytest.approx(0.005)
    assert sol.peak_to_peak_m["lon"] == pytest.approx(0.003)
    assert sol.peak_to_peak_m["ht"] == pytest.approx(0.009)

    # base stations + provenance
    assert sol.base_stations == ["AB1234", "CD5678", "EF9012"]
    assert sol.software == "page5 2008.25 master312.pl 160321"
    assert sol.ephemeris == "igs23344.eph [precise]"

    assert sol.raw_text == full_report_text


def test_parse_minimal_rapidstatic_report(minimal_report_text):
    """Missing SPC / base-station sections degrade to None/[], never invented."""
    sol = parse_solution(minimal_report_text)

    assert sol.file == "frco280b.26o OP20261007143022"
    assert sol.email == "field@example.com"
    assert sol.processing_date == "October 07, 2026"

    assert sol.nad83 is not None
    assert sol.nad83.frame == "NAD83(2011)"
    assert abs(sol.nad83.lat_deg - 39.736821327777776) < 1e-6
    assert abs(sol.nad83.lon_deg - (-105.008367625)) < 1e-6
    assert sol.nad83.ell_ht_m == pytest.approx(1650.750)

    assert sol.itrf is not None
    assert sol.itrf.frame == "IGS14"  # kept as reported
    assert sol.itrf.epoch == "2026.7612"
    assert abs(sol.itrf.lat_deg - 39.73682619722222) < 1e-6
    assert abs(sol.itrf.lon_deg - (-105.00837774444445)) < 1e-6

    assert sol.utm is not None
    assert sol.utm.zone == "13N"
    assert sol.utm.northing_m == pytest.approx(4401234.567)
    assert sol.utm.easting_m == pytest.approx(500123.456)

    assert sol.spc is None
    assert sol.base_stations == []
    assert sol.overall_rms_m == pytest.approx(0.018)
    assert sol.pct_obs_used == pytest.approx(90.0)
    assert sol.pct_ambiguities_fixed == pytest.approx(75.0)
    assert sol.software == "page5 2008.25 master318.pl 160321"
    assert sol.ephemeris == "igr23340.eph [rapid]"


def test_parse_e_lon_fallback_to_signed():
    """When only E LON (0..360) is present, longitude converts to -180..180."""
    text = (
        "NGS OPUS SOLUTION REPORT\n"
        "REF FRAME: NAD_83(2011)(EPOCH:2010.0000)  ITRF2014 (EPOCH:2026.7000)\n"
        "LAT: 39 47 35.82240  0.012(m)  39 47 35.84065  0.012(m)\n"
        "E LON: 255 7 10.09106  0.014(m)  255 7 10.03933  0.014(m)\n"
        "EL HGT: 1585.203(m)  0.090(m)  1584.324(m)  0.090(m)\n"
    )
    sol = parse_solution(text)
    assert sol.nad83 is not None
    assert abs(sol.nad83.lon_deg - (-104.88053026111109)) < 1e-6
    assert sol.itrf is not None
    assert abs(sol.itrf.lon_deg - (-104.88054463055557)) < 1e-6


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello, this is not a report",
        "NGS OPUS SOLUTION",  # marker substring, incomplete
        "FILE: x.26o\nUSER: a@b.com",  # echo lines but no marker
    ],
)
def test_parse_rejects_non_reports(text):
    with pytest.raises(OpusError):
        parse_solution(text)


def test_solution_to_json_round_trip(full_report_text):
    sol = parse_solution(full_report_text)
    data = json.loads(solution_to_json(sol))
    assert data["file"] == "syra274a.26o OP20261008120000"
    assert data["email"] == "surveyor@example.com"
    assert data["processing_date"] == "October 08, 2026"
    assert data["nad83"]["frame"] == "NAD83(2011)"
    assert abs(data["nad83"]["lat_deg"] - 43.03753429166667) < 1e-6
    assert data["itrf"]["frame"] == "ITRF2014"
    assert data["utm"]["zone"] == "18N"
    assert data["spc"]["zone"] == "3101 NY W"
    assert data["overall_rms_m"] == pytest.approx(0.012)
    assert data["base_stations"] == ["AB1234", "CD5678", "EF9012"]
    assert data["software"] == "page5 2008.25 master312.pl 160321"
    assert data["ephemeris"] == "igs23344.eph [precise]"
    assert data["raw_text"] == full_report_text


# ---------------------------------------------------------------------------
# submit(): mock-session tests (no network at all)
# ---------------------------------------------------------------------------

EXPECTED_FIELD_DEFAULTS = {
    "theHost1": "www.ngs.noaa.gov",
    "submit_database": "2",
    "extend_code": "0",
    "share": "2",
    "xml_code": "0",
    "set_profile": "0",
    "delete_profile": "0",
    "selectList1": "",
    "geoid_model": "",
    "SolutionFormat": "",
    "state_plane": "",
    "project_name": "",
    "MyProfile": "",
    "sharedOption": "2",
}


def test_submit_static_posts_all_multipart_fields(tmp_path):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    sess = _FakeSession()

    receipt = submit(
        rinex_file, "User@Example.COM", "TRM57971.00", 2.0, session=sess
    )

    # exactly one attempt, no retry loop
    assert len(sess.calls) == 1
    call = sess.calls[0]
    assert call["url"] == OPUS_UPLOAD_URL
    assert call["timeout"] == 60

    fname, payload = call["files"]["uploadfile"]
    assert fname == "good.26o"
    assert payload == rinex_file.read_bytes()

    data = call["data"]
    assert data["email_address"] == "user@example.com"  # lowercased
    assert data["height"] == "2.000"  # 3 decimals
    assert data["ant_type"] == "TRM57971.00"
    assert data["opusOption"] == "1"
    assert re.fullmatch(r"OP\d{14}", data["seqnum"])
    for key, value in EXPECTED_FIELD_DEFAULTS.items():
        assert data[key] == value, key
    assert set(data) == {
        "email_address",
        "height",
        "ant_type",
        "opusOption",
        "seqnum",
        *EXPECTED_FIELD_DEFAULTS,
    }

    # receipt echoes the submission
    assert receipt.seqnum == data["seqnum"]
    assert receipt.email == "user@example.com"
    assert receipt.rinex_filename == "good.26o"
    assert receipt.antenna_type == "TRM57971.00"
    assert receipt.antenna_height == pytest.approx(2.0)
    assert receipt.mode == "static"
    assert receipt.endpoint_url == OPUS_UPLOAD_URL
    assert receipt.response_status == 200
    assert receipt.response_excerpt == "mock OPUS upload ack"
    assert receipt.warnings == []


def test_submit_rapid_static_uses_rs_endpoint(tmp_path):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    sess = _FakeSession()

    receipt = submit(
        rinex_file, "user@example.com", "TRM57971.00", 1.5,
        mode="rapid-static", session=sess,
    )

    call = sess.calls[0]
    assert call["url"] == OPUS_RS_UPLOAD_URL
    assert call["data"]["opusOption"] == "2"
    assert receipt.mode == "rapid-static"
    assert receipt.endpoint_url == OPUS_RS_UPLOAD_URL


def test_submit_seqnum_is_current_utc_timestamp(tmp_path):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    sess = _FakeSession()
    receipt = submit(rinex_file, "u@e.com", "TRM57971.00", 2.0, session=sess)
    parsed = datetime.datetime.strptime(
        receipt.seqnum, "OP%Y%m%d%H%M%S"
    ).replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    assert abs((now - parsed).total_seconds()) < 120


def test_submit_height_formatting(tmp_path):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    sess = _FakeSession()
    submit(rinex_file, "u@e.com", "TRM57971.00", 1.23456, session=sess)
    assert sess.calls[0]["data"]["height"] == "1.235"


def test_submit_warn_advisories_pass_through_on_receipt(tmp_path):
    rinex_file = _write_rinex(
        tmp_path / "warn.26o",
        end=(2026, 10, 8, 12, 45, 0.0),  # 45 min: WARN, not a hard problem
    )
    sess = _FakeSession()
    receipt = submit(rinex_file, "u@e.com", "TRM57971.00", 2.0, session=sess)
    assert len(receipt.warnings) == 1
    assert receipt.warnings[0].startswith("WARN:")
    assert receipt.response_status == 200


def test_submit_hard_rinex_problems_raise(tmp_path):
    short = _write_rinex(
        tmp_path / "short.26o", end=(2026, 10, 8, 12, 5, 0.0)  # 5 min < 15 min
    )
    with pytest.raises(OpusError, match="15 min"):
        submit(short, "u@e.com", "TRM57971.00", 2.0, session=_FakeSession())

    zero_ht = _write_rinex(tmp_path / "zeroht.26o", height=0.0)
    with pytest.raises(OpusError, match="antenna height"):
        submit(zero_ht, "u@e.com", "TRM57971.00", 2.0, session=_FakeSession())


def test_submit_unparseable_rinex_raises(tmp_path):
    bad = tmp_path / "not_rinex.txt"
    bad.write_text("this is definitely not a RINEX file\n")
    with pytest.raises(OpusError, match="RINEX header parse failed"):
        submit(bad, "u@e.com", "TRM57971.00", 2.0, session=_FakeSession())


def test_submit_missing_file_raises(tmp_path):
    with pytest.raises(OpusError, match="not found"):
        submit(tmp_path / "nope.26o", "u@e.com", "T", 2.0, session=_FakeSession())


@pytest.mark.parametrize(
    "email", ["not-an-email", "a@b", "@example.com", "user@", "", None]
)
def test_submit_rejects_bad_email(tmp_path, email):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    with pytest.raises(OpusError, match="invalid email"):
        submit(rinex_file, email, "T", 2.0, session=_FakeSession())


def test_submit_rejects_bad_mode(tmp_path):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    with pytest.raises(OpusError, match="mode"):
        submit(rinex_file, "u@e.com", "T", 2.0, mode="STATIC", session=_FakeSession())


@pytest.mark.parametrize("name", ["bad!name.26o", "has space.26o", "semi;colon.26o"])
def test_submit_rejects_illegal_filename_chars(tmp_path, name):
    rinex_file = _write_rinex(tmp_path / name)
    with pytest.raises(OpusError, match="rejects"):
        submit(rinex_file, "u@e.com", "T", 2.0, session=_FakeSession())


def test_submit_rejects_filename_over_44_chars(tmp_path):
    rinex_file = _write_rinex(tmp_path / ("x" * 41 + ".26o"))  # 45 chars
    with pytest.raises(OpusError, match="44"):
        submit(rinex_file, "u@e.com", "T", 2.0, session=_FakeSession())


def test_submit_accepts_44_char_filename(tmp_path):
    rinex_file = _write_rinex(tmp_path / ("v" * 40 + ".26o"))  # exactly 44
    receipt = submit(rinex_file, "u@e.com", "T", 2.0, session=_FakeSession())
    assert receipt.rinex_filename == "v" * 40 + ".26o"


def test_submit_response_excerpt_truncated_to_500(tmp_path):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    sess = _FakeSession(_FakeResponse(text="x" * 1200))
    receipt = submit(rinex_file, "u@e.com", "T", 2.0, session=sess)
    assert len(receipt.response_excerpt) == 500


def test_submit_custom_timeout_forwarded(tmp_path):
    rinex_file = _write_rinex(tmp_path / "good.26o")
    sess = _FakeSession()
    submit(rinex_file, "u@e.com", "T", 2.0, timeout=15, session=sess)
    assert sess.calls[0]["timeout"] == 15


# ---------------------------------------------------------------------------
# submit(): real POST path against a local http.server (never noaa.gov)
# ---------------------------------------------------------------------------


def _run_local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.mark.parametrize("force_urllib", [False, True])
def test_submit_real_post_against_local_server(monkeypatch, tmp_path, force_urllib):
    """Exercises the genuine POST code path (requests, then stdlib urllib)
    against a localhost mock -- the NGS endpoint constant is monkeypatched,
    and conftest blocks any non-localhost connection regardless."""
    _CaptureHandler.received = None
    _CaptureHandler.response_body = b"local mock upload ack"
    server, thread = _run_local_server()
    try:
        monkeypatch.setattr(
            client,
            "OPUS_UPLOAD_URL",
            f"http://127.0.0.1:{server.server_address[1]}/upload",
        )
        if force_urllib:
            monkeypatch.setattr(client, "_requests", None)
        rinex_file = _write_rinex(tmp_path / "good.26o")
        receipt = submit(
            rinex_file, "User@Example.COM", "TRM57971.00", 1.5, session=None
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    rec = _CaptureHandler.received
    assert rec is not None, "local server never received the POST"
    assert rec["path"] == "/upload"
    assert "multipart/form-data" in rec["content_type"]
    body = rec["body"]
    assert b'filename="good.26o"' in body
    assert rinex_file.read_bytes() in body  # the actual file bytes went out
    assert b'name="email_address"\r\n\r\nuser@example.com' in body
    assert b'name="opusOption"\r\n\r\n1' in body
    assert b'name="height"\r\n\r\n1.500' in body
    assert b'name="theHost1"\r\n\r\nwww.ngs.noaa.gov' in body

    assert receipt.response_status == 200
    assert receipt.response_excerpt == "local mock upload ack"
    assert receipt.endpoint_url.startswith("http://127.0.0.1")
    assert "noaa.gov" not in receipt.endpoint_url


def test_package_root_exports_contract_names():
    import survey_opus

    for name in (
        "submit",
        "parse_solution",
        "solution_to_json",
        "OpusError",
        "SubmissionReceipt",
        "OpusSolution",
        "Coordinate",
        "GridCoordinate",
        "OPUS_UPLOAD_URL",
        "OPUS_RS_UPLOAD_URL",
    ):
        assert hasattr(survey_opus, name), name
    assert survey_opus.OPUS_UPLOAD_URL == (
        "https://www.ngs.noaa.gov/OPUS-cgi/OPUS/Upload/Opusup.prl"
    )
    assert survey_opus.OPUS_RS_UPLOAD_URL == (
        "https://www.ngs.noaa.gov/OPUS-cgi/OPUS/Upload/Opus-rsup.prl"
    )
