"""CLI smoke tests: list / search / info / convert."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from crs.cli import main


def test_list_group(capsys):
    assert main(["list", "--group", "geographic"]) == 0
    out = capsys.readouterr().out
    assert "EPSG:6318" in out and "EPSG:4326" in out


def test_list_state(capsys):
    assert main(["list", "--state", "NY"]) == 0
    out = capsys.readouterr().out
    assert "EPSG:6538" in out


def test_search(capsys):
    assert main(["search", "long island"]) == 0
    assert "6539" in capsys.readouterr().out


def test_info(capsys):
    assert main(["info", "6538"]) == 0
    out = capsys.readouterr().out
    assert "Lambert" in out or "lcc" in out
    assert "https://epsg.io/6538" in out


def test_convert_geo_to_projected(capsys):
    # NB2147 -> NY Central m
    lat = 42 + 25 / 60 + 58.52091 / 3600
    lon = -(76 + 51 / 60 + 46.55757 / 3600)
    assert main(["convert", "--from-epsg", "6318", "--to-epsg", "6534",
                 "--lat", str(lat), "--lon", str(lon)]) == 0
    out = capsys.readouterr().out
    assert "easting=226994.09" in out
    assert "northing=270216.77" in out


def test_convert_projected_to_geo(capsys):
    assert main(["convert", "--from-epsg", "6538", "--to-epsg", "4326",
                 "--easting", "367742.490", "--northing", "66266.506"]) == 0
    out = capsys.readouterr().out
    assert "lat=40.760" in out


def test_convert_missing_args_returns_2(capsys):
    assert main(["convert", "--from-epsg", "6538", "--to-epsg", "4326"]) == 2


def test_convert_unknown_epsg_returns_1(capsys):
    assert main(["convert", "--from-epsg", "6318", "--to-epsg", "999999",
                 "--lat", "40.0", "--lon", "-74.0"]) == 1
