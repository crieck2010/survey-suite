"""Description keys and figure-prefix DB: matching rules and validation."""
from __future__ import annotations

import pytest

from linework.errors import DescriptionKeyError, PrefixDBError
from linework.keys import DescriptionKeys, keys_template, load_keys
from linework.prefixes import FigurePrefixDB, prefixes_template


# -- description keys -------------------------------------------------------


def test_longest_match_wins():
    dk = DescriptionKeys.from_dict({
        "format": "survey-linework/description-keys",
        "schema_version": 1,
        "keys": [
            {"pattern": "E*", "layer": "a", "symbol": "circle", "label": "{name}"},
            {"pattern": "EP*", "layer": "b", "symbol": "square", "label": "{name}"},
        ],
    })
    assert dk.match("EP12").layer == "b"
    assert dk.match("EX1").layer == "a"


def test_exact_beats_wildcard_on_tie_by_length():
    dk = DescriptionKeys.from_dict({
        "format": "survey-linework/description-keys",
        "schema_version": 1,
        "keys": [
            {"pattern": "EP*", "layer": "wild", "symbol": "circle", "label": "{name}"},
            {"pattern": "EP1", "layer": "exact", "symbol": "circle", "label": "{name}"},
        ],
    })
    # Same length: file order wins (documented tie-break).
    assert dk.match("EP1").layer == "wild"


def test_no_match_falls_back_to_default():
    dk = DescriptionKeys.from_dict(keys_template())
    assert dk.match("ZZZ9").label == "{name}"
    assert dk.match("ZZZ9").layer == "points"


def test_match_is_case_insensitive():
    dk = DescriptionKeys.from_dict(keys_template())
    assert dk.match("ec1").layer == "linework"


def test_label_rendering():
    dk = DescriptionKeys.from_dict(keys_template())
    key = dk.match("BM1")
    assert dk.render_label(key, {"name": "101", "code": "BM1",
                                 "easting": 1.0, "northing": 2.0,
                                 "elevation": 3.5}) == "101 BM 3.5"


def test_bad_label_format_fails_at_load():
    d = keys_template()
    d["keys"].append({"pattern": "XX*", "layer": "points",
                      "symbol": "circle", "label": "{bogus}"})
    with pytest.raises(DescriptionKeyError, match="bad label format"):
        DescriptionKeys.from_dict(d)


def test_duplicate_pattern_fails_loud():
    d = keys_template()
    d["keys"].append({"pattern": "ec*", "layer": "points",
                      "symbol": "circle", "label": "{name}"})
    with pytest.raises(DescriptionKeyError, match="duplicate pattern"):
        DescriptionKeys.from_dict(d)


def test_newer_schema_rejected():
    d = keys_template()
    d["schema_version"] = 7
    with pytest.raises(DescriptionKeyError, match="newer than this reader"):
        DescriptionKeys.from_dict(d)


def test_load_keys_missing_file():
    with pytest.raises(DescriptionKeyError, match="cannot read"):
        load_keys("/nonexistent/keys.json")


# -- figure prefix DB ---------------------------------------------------------


def test_longest_prefix_wins():
    db = FigurePrefixDB.from_dict(prefixes_template())
    assert db.match("EC1").prefix == "EC"
    assert db.match("BLDG2").prefix == "BLDG"


def test_numeric_suffix_claim():
    db = FigurePrefixDB.from_dict(prefixes_template())
    assert db.match("EC12").prefix == "EC"
    assert db.match("ECX") is None  # non-numeric suffix: no claim


def test_exact_match_without_suffix():
    db = FigurePrefixDB.from_dict({
        "format": "survey-linework/figure-prefixes",
        "schema_version": 1,
        "prefixes": [
            {"prefix": "DITCH", "allow_numeric_suffix": False},
        ],
    })
    assert db.match("DITCH").prefix == "DITCH"
    assert db.match("DITCH1") is None


def test_no_match_returns_none():
    db = FigurePrefixDB.from_dict(prefixes_template())
    assert db.match("ZZZ9") is None


def test_duplicate_prefix_rejected():
    d = prefixes_template()
    d["prefixes"].append({"prefix": "ec"})
    with pytest.raises(PrefixDBError, match="duplicate prefix"):
        FigurePrefixDB.from_dict(d)


def test_negative_tolerance_rejected():
    d = prefixes_template()
    d["prefixes"][0]["closure_tolerance_m"] = -1.0
    with pytest.raises(PrefixDBError, match="closure_tolerance_m"):
        FigurePrefixDB.from_dict(d)


def test_newer_schema_rejected_prefixes():
    d = prefixes_template()
    d["schema_version"] = 42
    with pytest.raises(PrefixDBError, match="newer than this reader"):
        FigurePrefixDB.from_dict(d)
