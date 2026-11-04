"""Chart Viewer weekly bars, bar style, reason-box spot, and the switches that turn them on (fixed dates, no clock)."""
import json
import os
import re
import subprocess
import sys

try:
    import pytest
    _skip = pytest.skip
    _Skip = pytest.skip.Exception
except ImportError:  # the data workflow runs this file with plain python and no pytest
    class _Skip(Exception):
        pass

    def _skip(msg):
        raise _Skip(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tables  # noqa: E402

BAR_UP = "#60a5fa"
BAR_DOWN = "#d946ef"
BAR_UP_LIGHT = "#1d4ed8"
BAR_DOWN_LIGHT = "#a21caf"


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


def test_new_switches_default_on():
    cv = _cfg()["chart_viewer"]
    assert cv["why_box_top_left"] is True
    assert cv["weekly_toggle"] is True
    assert cv["hide_range_chips"] is True
    assert cv["bars_toggle"] is True
    assert (cv["range_months"], cv["range_months_phone"]) == (6, 3)
    assert (cv["range_months_weekly"], cv["range_months_weekly_phone"]) == (24, 12)
    assert (cv["bar_up"], cv["bar_down"], cv["bar_up_light"], cv["bar_down_light"]) == (
        BAR_UP, BAR_DOWN, BAR_UP_LIGHT, BAR_DOWN_LIGHT)
    # The moving-average colors are not part of this change.
    colors = _cfg()["chart_colors"]
    assert colors["ma_colors"]["10"] == "#22c55e" and colors["ma_colors"]["200"] == "#ef4444"
    note = cv["_note"]
    for phrase in ("why_box_top_left", "weekly_toggle", "hide_range_chips", "bars_toggle",
                   "header row (ticker, price, counter) always does", "scrolls the chips",
                   "kept when the screen turns"):
        assert phrase in note, phrase


def test_settings_and_help_rows():
    cfg = _cfg()
    got = dict(zip(tables.settings_rows(cfg)["setting"], tables.settings_rows(cfg)["value"]))
    settings = _read("data", "settings.csv")
    for key in ("why_box_top_left", "weekly_toggle", "hide_range_chips", "bars_toggle"):
        assert got["chart_viewer." + key] is True, key
        assert "\nchart_viewer." + key + ",True\n" in settings, key
    assert got["chart_viewer.range_months_weekly"] == 24
    assert got["chart_viewer.range_months_weekly_phone"] == 12
    assert "\nchart_viewer.range_months_weekly,24\n" in settings
    assert "\nchart_viewer.range_months_weekly_phone,12\n" in settings
    for key, color in (("bar_up", BAR_UP), ("bar_down", BAR_DOWN), ("bar_up_light", BAR_UP_LIGHT), ("bar_down_light", BAR_DOWN_LIGHT)):
        assert got["chart_viewer." + key] == color
        assert "\nchart_viewer." + key + "," + color + "\n" in settings
    topics = dict(tables.help_rows())
    help_csv = _read("data", "help.csv")
    for topic in ("Chart Viewer reason box spot", "Chart Viewer weekly candles", "Chart Viewer bars",
                  "Chart Viewer history and range", "Chart Viewer settings"):
        assert topic in topics
        assert "\n" + topic + "," in help_csv, topic
    assert "top left" in topics["Chart Viewer reason box spot"]
    assert "why_box_top_left" in topics["Chart Viewer reason box spot"]
    assert "Monday to Friday" in topics["Chart Viewer weekly candles"]
    assert "10 weeks" in topics["Chart Viewer weekly candles"]
    assert "weekly_toggle" in topics["Chart Viewer weekly candles"]
    assert "tick to the left for the open" in topics["Chart Viewer bars"]
    assert BAR_UP in topics["Chart Viewer bars"] and BAR_DOWN in topics["Chart Viewer bars"]
    assert BAR_UP_LIGHT in topics["Chart Viewer bars"] and BAR_DOWN_LIGHT in topics["Chart Viewer bars"]
    assert "bars_toggle" in topics["Chart Viewer bars"]
    assert "hide_range_chips" in topics["Chart Viewer history and range"]
    assert "2 years" in topics["Chart Viewer history and range"]
    assert "fit_wide_ranges" in topics["Chart Viewer settings"]
    assert "why_box_top_left" in topics["Chart Viewer settings"]
    assert "\u2014" not in "".join(topics.values())


def test_viewer_wires_the_switches():
    js = _read("site", "js", "viewer.js")
    assert 'on("why_box_top_left")' in js
    assert 'on("weekly_toggle")' in js and 'on("bars_toggle")' in js
    assert 'on("range_chips") && !on("hide_range_chips")' in js
    assert 'storedStr("desk-cv-tf", ["daily", "weekly"], "daily")' in js
    assert 'storedStr("desk-cv-style", ["candles", "bars"], "candles")' in js
    assert 'storeStr("desk-cv-tf", tf)' in js and 'storeStr("desk-cv-style", style)' in js
    assert 'cfgNum("range_months_weekly", 24)' in js and 'cfgNum("range_months_weekly_phone", 12)' in js
    assert 'cfgNum("range_months_phone", 3)' in js and 'cfgNum("range_months", 6)' in js
    # Weekly bars replace the daily bars before the averages are worked out, so MA 10 is 10 weeks.
    draw = js.split("const daily = D.barsFromRows", 1)[1].split("header(t, daily)", 1)[0]
    assert 'state.tf === "weekly" ? aggregateWeekly(daily) : daily' in draw
    assert "const closes = bars.map((b) => b.c);" in js
    assert "LC.BarSeries" in js and "openVisible: true" in js and "thinBars: true" in js
    assert "LC.CandlestickSeries" in js
    assert "edgePad(visible, plot, RIGHT_MARGIN_PX)" in js
    assert "padBars(visible, plot, state.open ? Math.min(boxPad(), 260) : boxPad())" in js
    # No new market requests, and the saved file is still what the chart reads.
    assert "fetch(" not in js and "yahoo" not in js.lower()
    assert re.findall(r'loadCsv\("([^"+]+)', js) == ["ohlc/", "ohlc/"]
    css = _read("site", "css", "desk.css")
    assert ".cv-why.tl{" in css and ".cvseg{" in css


def test_weekly_aggregation_rules():
    proc = _node(os.path.join("tests", "chart_viewer_logic.js"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "chart viewer logic ok" in proc.stdout


if __name__ == "__main__":
    test_new_switches_default_on()
    test_settings_and_help_rows()
    test_viewer_wires_the_switches()
    try:
        test_weekly_aggregation_rules()
    except _Skip as exc:
        print("weekly aggregation check skipped: " + str(exc))
    print("chart viewer weekly ok")
