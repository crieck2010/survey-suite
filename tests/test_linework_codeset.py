"""Code-set config: validation, presets, and raw-code parsing."""
from __future__ import annotations

import pytest

from linework.codeset import (
    BUILTIN_PRESETS,
    CodeSetError,
    LineworkCodeSet,
    builtin_codeset,
    codeset_template,
)


def test_builtin_presets_exist():
    assert set(BUILTIN_PRESETS) == {"emlid", "civil3d"}


def test_emlid_default_tokens_are_the_field_convention():
    cs = builtin_codeset("emlid")
    assert cs.separator == " "
    assert cs.tokens["begin"] == "*bl"   # field-verified Emlid crew convention
    assert cs.tokens["end"] == "*el"     # field-verified Emlid crew convention
    assert cs.auto_begin is True
    assert cs.case_sensitive is False


def test_civil3d_preset_tokens():
    cs = builtin_codeset("civil3d")
    assert cs.tokens["begin"] == "BEG"
    assert cs.tokens["end"] == "END"
    assert cs.tokens["begin_curve_3pt"] == "BCV"
    assert cs.tokens["end_curve_3pt"] == "ECV"
    assert cs.tokens["close"] == "CLS"


def test_unknown_preset_fails_loud():
    with pytest.raises(CodeSetError, match="unknown codeset preset"):
        codeset_template("carlson")


def test_parse_simple_begin_end():
    cs = builtin_codeset("emlid")
    parsed = cs.parse_code("EC1 *bl")
    assert parsed.base == "EC1"
    assert [c.kind for c in parsed.controls] == ["begin"]
    parsed = cs.parse_code("EC1")
    assert parsed.base == "EC1"
    assert parsed.controls == ()


def test_parse_is_case_insensitive_by_default():
    cs = builtin_codeset("emlid")
    parsed = cs.parse_code("ec1 *BL")
    assert parsed.base == "EC1"
    assert parsed.controls[0].kind == "begin"


def test_parse_radius_param_styles():
    cs = builtin_codeset("emlid")
    for raw in ("EP1 *bcr R=50", "EP1 *bcr:R=50", "EP1 *bcr 50"):
        parsed = cs.parse_code(raw)
        assert parsed.controls[0].kind == "begin_curve_radius"
        assert cs.radius_param(parsed.controls[0].param, raw) == 50.0


def test_parse_offset_param_styles():
    cs = builtin_codeset("emlid")
    cases = {
        "CL1 *off +0.6": 0.6,
        "CL1 *off:+0.6": 0.6,
        "CL1 *off -0.6": -0.6,
        "CL1 *off R2.0": 2.0,
        "CL1 *off L2.0": -2.0,
        "CL1 *off 2.0": 2.0,
    }
    for raw, want in cases.items():
        parsed = cs.parse_code(raw)
        assert parsed.controls[0].kind == "offset", raw
        assert cs.offset_param(parsed.controls[0].param, raw) == want, raw


def test_bad_radius_param_fails_loud():
    cs = builtin_codeset("emlid")
    with pytest.raises(CodeSetError, match="bad radius parameter"):
        cs.radius_param("banana", "EP1 *bcr")


def test_bad_offset_param_fails_loud():
    cs = builtin_codeset("emlid")
    with pytest.raises(CodeSetError, match="bad offset parameter"):
        cs.offset_param("banana", "CL1 *off")


def test_unknown_control_field_fails_loud():
    cs = builtin_codeset("emlid")
    with pytest.raises(CodeSetError, match="unrecognised control field"):
        cs.parse_code("EC1 *zzz")


def test_duplicate_tokens_rejected():
    d = codeset_template("emlid")
    d["tokens"]["end"] = "*bl"
    with pytest.raises(CodeSetError, match="must be distinct"):
        LineworkCodeSet.from_dict(d)


def test_missing_token_rejected():
    d = codeset_template("emlid")
    del d["tokens"]["close"]
    with pytest.raises(CodeSetError, match="missing control token"):
        LineworkCodeSet.from_dict(d)


def test_empty_separator_rejected():
    d = codeset_template("emlid")
    d["separator"] = ""
    with pytest.raises(CodeSetError, match="separator"):
        LineworkCodeSet.from_dict(d)


def test_newer_schema_rejected_loudly():
    d = codeset_template("emlid")
    d["schema_version"] = 99
    with pytest.raises(CodeSetError, match="newer than this reader"):
        LineworkCodeSet.from_dict(d)


def test_wrong_format_rejected():
    d = codeset_template("emlid")
    d["format"] = "something/else"
    with pytest.raises(CodeSetError, match="not a linework code set"):
        LineworkCodeSet.from_dict(d)


def test_round_trip():
    cs = builtin_codeset("civil3d")
    assert LineworkCodeSet.from_dict(cs.to_dict()).tokens == cs.tokens
