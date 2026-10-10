"""Picker API behavior: search, by_epsg, zones_for_state, group_by_type, suggest."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import crs


def test_by_epsg_ok_and_unknown():
    e = crs.by_epsg(6538)
    assert e.name == "NAD83(2011) / New York Long Island"
    with pytest.raises(crs.UnknownEpsg):
        crs.by_epsg(999999)


def test_search_long_island():
    hits = crs.search("long island")
    codes = {e.epsg for e in hits}
    assert {6538, 6539} <= codes


def test_search_epsg_number():
    hits = crs.search("32618")
    assert [e.epsg for e in hits] == [32618]


def test_search_case_insensitive_and_empty():
    assert crs.search("UTM ZONE 18N")
    assert crs.search("") == []
    assert crs.search("zzzz-no-such-crs") == []


def test_search_multiword_tokens():
    hits = crs.search("utm 18n")
    assert [e.epsg for e in hits] == [32618]
    assert [e.epsg for e in crs.search("utm 18s")] == [32718]


def test_zones_for_state_abbr_and_name():
    abbr = crs.zones_for_state("NY")
    name = crs.zones_for_state("New York")
    lower = crs.zones_for_state("ny")
    assert [e.epsg for e in abbr] == [e.epsg for e in name] == \
        [e.epsg for e in lower]
    assert len(abbr) == 8
    with pytest.raises(crs.UnknownState):
        crs.zones_for_state("XX")


def test_zones_for_state_texas_has_five_zones():
    zones = {e.zone for e in crs.zones_for_state("TX")}
    assert zones == {"Central", "North", "North Central", "South",
                     "South Central"}


def test_group_by_type_keys_sorted():
    g = crs.group_by_type()
    assert set(g) == {"spcs", "utm", "geographic"}
    for entries in g.values():
        codes = [e.epsg for e in entries]
        assert codes == sorted(codes)


def test_suggest_finds_ny_central_and_utm18():
    picks = crs.suggest(42.43, -76.86)
    codes = [e.epsg for e in picks]
    assert 6534 in codes and 6535 in codes  # NY Central m + ftUS
    assert 32618 in codes  # UTM 18N


def test_suggest_long_island():
    picks = crs.suggest(40.76, -73.20)
    codes = [e.epsg for e in picks]
    assert 6538 in codes and 6539 in codes


def test_suggest_southern_hemisphere_utm():
    picks = crs.suggest(-33.9, 151.2)  # Sydney
    codes = [e.epsg for e in picks]
    assert 32756 in codes  # UTM 56S


def test_suggest_empty_ocean_point():
    # mid-Pacific: no SPCS zone contains it, but a UTM zone always applies
    picks = crs.suggest(0.0, -150.0)
    assert [e.epsg for e in picks] == [32606]
