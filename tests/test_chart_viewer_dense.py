"""Chart Viewer opening candles: one width everywhere, with a floor and a cap (fixed numbers, no clock)."""
import json
import os
import subprocess
import sys

try:
    import pytest
    _skip = pytest.skip
    _Skip = pytest.skip.Exception
except ImportError:
    class _Skip(Exception):
        pass

    def _skip(msg):
        raise _Skip(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tables  # noqa: E402


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _node(*args):
    try:
        return subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        _skip("node is not installed: " + str(exc))


def test_dense_settings():
    cv = _cfg()["chart_viewer"]
    assert cv["dense_default"] is True
    assert cv["target_bar_spacing"] == 5.8
    assert cv["min_bar_spacing_px"] == 3
    assert cv["max_bar_spacing_px"] == 8
    # The old month spans stay in config for when dense_default is off.
    assert (cv["range_months"], cv["range_months_phone"]) == (6, 3)
    assert (cv["range_months_weekly"], cv["range_months_weekly_phone"]) == (24, 12)
    assert "target_bar_spacing 5.8" in cv["_note"] and "dense_default" in cv["_note"]
    got = dict(zip(tables.settings_rows(_cfg())["setting"], tables.settings_rows(_cfg())["value"]))
    settings = _read("data", "settings.csv")
    assert got["chart_viewer.dense_default"] is True
    assert got["chart_viewer.target_bar_spacing"] == 5.8
    assert got["chart_viewer.min_bar_spacing_px"] == 3
    assert got["chart_viewer.max_bar_spacing_px"] == 8
    assert "\nchart_viewer.dense_default,True\n" in settings
    assert "\nchart_viewer.target_bar_spacing,5.8\n" in settings
    assert "\nchart_viewer.min_bar_spacing_px,3\n" in settings
    assert "\nchart_viewer.max_bar_spacing_px,8\n" in settings
    topics = dict(tables.help_rows())
    assert "Chart Viewer default candles" in topics
    assert "\nChart Viewer default candles," in _read("data", "help.csv")
    text = topics["Chart Viewer default candles"]
    assert "5.8" in text and "dense_default" in text
    assert "3 pixels" in text and "8 pixels" in text
    assert "weekly" in text and "Drag and pinch" in text
    assert "dense_default" in topics["Chart Viewer settings"]
    assert "target_bar_spacing" in topics["Chart Viewer history and range"]
    assert "\u2014" not in text


def test_viewer_uses_the_spacing_switch():
    js = _read("site", "js", "viewer.js")
    assert 'on("dense_default") && !pick' in js
    assert 'cfgNum("target_bar_spacing", 5.8)' in js
    assert 'cfgNum("min_bar_spacing_px", 3)' in js
    assert 'cfgNum("max_bar_spacing_px", 8)' in js
    # Month spans remain the path when the switch is off, or when a range chip is tapped.
    assert 'cfgNum("range_months_phone", 3)' in js and 'cfgNum("range_months", 6)' in js
    assert "horzTouchDrag: state.pan" in js and "pinch: state.pan" in js
    # Row charts in desk.js are not part of this open-view rule.
    assert "denseRange" not in _read("site", "js", "desk.js")


def test_dense_range_rules():
    proc = _node(os.path.join("tests", "chart_viewer_logic.js"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "chart viewer logic ok" in proc.stdout


if __name__ == "__main__":
    test_dense_settings()
    test_viewer_uses_the_spacing_switch()
    try:
        test_dense_range_rules()
    except _Skip as exc:
        print("dense range check skipped: " + str(exc))
    print("chart viewer dense ok")
