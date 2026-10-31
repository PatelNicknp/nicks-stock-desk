"""Chart Viewer: its page, its switches, its help rows, and its list and swipe rules (fixed rows, no clock)."""
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
sys.path.insert(0, os.path.join(ROOT, "site"))

import tables  # noqa: E402
import build_pages  # noqa: E402

SITE = os.path.join(ROOT, "site")


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_switch_and_config_block():
    cfg = _cfg()
    assert cfg["features"]["chart_viewer"] is True
    cv = cfg["chart_viewer"]
    assert cv["swipe_right_is_next"] is True
    assert cv["chart_touch_pan"] is False
    assert (cv["ma_10"], cv["ma_20"], cv["ma_50"], cv["ma_150"], cv["ma_200"]) == (False, False, True, True, True)
    assert cv["volume"] is True and cv["reason_box"] is True and cv["reason_box_toggle"] is True
    for key in ("list_picker", "fullscreen", "swipe", "flip_toggle", "arrows", "keyboard", "counter", "preload_next",
                "ma_chips", "volume_toggle", "company_line", "day_change", "scanner_links"):
        assert isinstance(cv[key], bool), key


def test_settings_rows_carry_every_option():
    cfg = _cfg()
    got = dict(zip(tables.settings_rows(cfg)["setting"], tables.settings_rows(cfg)["value"]))
    assert got["feature.chart_viewer"] is True
    for key, value in cfg["chart_viewer"].items():
        if key.startswith("_"):
            assert "chart_viewer." + key not in got
            continue
        assert got["chart_viewer." + key] == value, key


def test_published_settings_and_help_match_the_code():
    cfg = _cfg()
    settings = _read("data", "settings.csv")
    assert "feature.chart_viewer,True" in settings
    for key in cfg["chart_viewer"]:
        if not key.startswith("_"):
            assert "\nchart_viewer." + key + "," in settings, key
    topics = [t for t, _ in tables.help_rows()]
    for topic in ("Chart Viewer", "Chart Viewer swipes", "Chart Viewer lines and reason box", "Chart Viewer settings"):
        assert topic in topics
        assert "\n" + topic + "," in _read("data", "help.csv"), topic


def test_page_menu_and_scripts():
    assert ("chart-viewer.html", "chartviewer", "Chart Viewer") in build_pages.PAGES
    html = _read("site", "chart-viewer.html")
    assert html.index("js/desk.js") < html.index("js/viewer.js") < html.index("js/pages.js")
    desk = _read("site", "js", "desk.js")
    assert '["Chart Viewer", [\n      ["Chart Viewer", "chart-viewer.html", "chartviewer"],' in desk
    assert 'chartviewer: "feature.chart_viewer"' in desk
    pages = _read("site", "js", "pages.js")
    assert "chartviewer:" in pages and "Open in Chart Viewer" in pages
    # Only the viewer page loads the viewer script.
    for name in os.listdir(SITE):
        if name.endswith(".html") and name != "chart-viewer.html":
            assert "viewer.js" not in _read("site", name), name


def test_plain_words_no_alerts_no_tradingview_buttons():
    js = _read("site", "js", "viewer.js")
    assert "\u2014" not in js
    assert "\u2014" not in _read("tables.py")
    assert "alert(" not in js and "Notification" not in js
    # The only TradingView mention is the library credit line, not a button or a link out per stock.
    assert len(re.findall(r"tradingview\.com", js)) == 1
    assert "tradingview.com/chart" not in js.lower() and "symbol=" not in js
    assert "Full screen" in js


def test_no_new_market_requests():
    js = _read("site", "js", "viewer.js")
    assert "fetch(" not in js and "XMLHttpRequest" not in js
    assert "yahoo" not in js.lower()
    assert re.findall(r'loadCsv\("([^"+]+)', js) == ["ohlc/", "ohlc/"]


def _node(*args):
    try:
        return subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        _skip("node is not installed: " + str(exc))


def test_scripts_parse():
    for name in ("viewer.js", "desk.js", "pages.js"):
        proc = _node("--check", os.path.join("site", "js", name))
        assert proc.returncode == 0, name + ": " + proc.stderr


def test_list_and_swipe_rules():
    proc = _node(os.path.join("tests", "chart_viewer_logic.js"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "chart viewer logic ok" in proc.stdout


if __name__ == "__main__":
    test_switch_and_config_block()
    test_settings_rows_carry_every_option()
    test_published_settings_and_help_match_the_code()
    test_page_menu_and_scripts()
    test_plain_words_no_alerts_no_tradingview_buttons()
    test_no_new_market_requests()
    try:
        test_scripts_parse()
        test_list_and_swipe_rules()
    except _Skip:
        print("node checks skipped")
    print("chart viewer ok")
