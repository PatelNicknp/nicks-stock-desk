"""Technical | Fundamental split: the scanner_groups mapping, its switches, settings and help rows, the menu,
the Chart Viewer switch and list filtering, the remembered pick, and features.split_tech_fund off (fixed rows, no clock)."""
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

TECHNICAL = ["vcp", "box", "flag", "qullamaggie", "marios", "ep", "gapup", "week52", "breakouts", "volume", "pullbacks",
             "breakdowns", "trends", "wheel"]
FUNDAMENTAL = ["canslim", "leaders", "growth", "quality", "dividend", "scorecard", "top"]
NOT_SCREENERS = ["today", "watchlist", "buysetups", "alerts", "backtest", "options", "rotation", "chartviewer", "gainers",
                 "breadth", "secperf", "heatmaps", "calendar", "heatmap", "cards", "putcall", "walls", "analysts", "thirteen",
                 "aaii", "insiders", "headlines", "xly", "financials", "tracker", "company", "divfund", "macro", "secmacro",
                 "histpe", "updates", "help"]


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _js_map(text, name):
    body = text.split("const " + name + " = {", 1)[1].split("};", 1)[0]
    return dict(re.findall(r"(\w+): \"(technical|fundamental)\"", body))


def test_switches_and_block():
    cfg = _cfg()
    assert cfg["features"]["split_tech_fund"] is True
    cv = cfg["chart_viewer"]
    assert cv["group_toggle"] is True and cv["default_group"] == "technical"
    groups = cfg["scanner_groups"]
    assert groups["_note"].strip()
    assert "split_tech_fund" in groups["_note"] and "group_toggle" in cv["_note"] and "default_group" in cv["_note"]


def test_group_mapping():
    groups = {k: v for k, v in _cfg()["scanner_groups"].items() if not k.startswith("_")}
    assert [k for k, v in groups.items() if v == "technical"] == TECHNICAL
    assert [k for k, v in groups.items() if v == "fundamental"] == FUNDAMENTAL
    assert set(groups.values()) == {"technical", "fundamental"}
    # Nick: CANSLIM and Leaders under Fundamental.
    assert groups["canslim"] == "fundamental" and groups["leaders"] == "fundamental"
    # Every key is a real page; pages that are not screeners stay out of both.
    page_ids = {pid for _, pid, _ in build_pages.PAGES}
    assert set(groups) <= page_ids
    assert not set(groups) & set(NOT_SCREENERS)
    assert set(groups) | set(NOT_SCREENERS) == page_ids
    # The defaults the browser uses when settings.csv has no row are the same mapping.
    assert _js_map(_read("site", "js", "desk.js"), "SCANNER_GROUPS") == groups
    assert _js_map(_read("site", "js", "viewer.js"), "DEFAULT_GROUPS") == groups
    # Every Chart Viewer scanner list has a side.
    lists = re.findall(r'\{ id: "(\w+)", label: "[^"]+", short: "[^"]+", file: "[^"]+", kind: "\w+", feature: "[^"]+", scanner: (true|false) \}',
                       _read("site", "js", "viewer.js"))
    assert lists
    for lid, scanner in lists:
        assert (lid in groups) == (scanner == "true"), lid


def test_settings_and_help_rows():
    cfg = _cfg()
    df = tables.settings_rows(cfg)
    got = dict(zip(df["setting"], df["value"]))
    assert got["feature.split_tech_fund"] is True
    assert got["chart_viewer.group_toggle"] is True and got["chart_viewer.default_group"] == "technical"
    for key, value in cfg["scanner_groups"].items():
        if key.startswith("_"):
            assert "scanner_groups." + key not in got
        else:
            assert got["scanner_groups." + key] == value
    settings = _read("data", "settings.csv")
    assert "\nfeature.split_tech_fund,True\n" in settings
    assert "\nchart_viewer.group_toggle,True\n" in settings and "\nchart_viewer.default_group,technical\n" in settings
    for key, value in cfg["scanner_groups"].items():
        if not key.startswith("_"):
            assert "\nscanner_groups.%s,%s\n" % (key, value) in settings, key
    help_csv = _read("data", "help.csv")
    topics = dict(tables.help_rows())
    for topic in ("Technical and Fundamental", "Chart Viewer Technical and Fundamental switch", "Technical and Fundamental settings"):
        assert topic in topics and "\n" + topic + "," in help_csv, topic
    assert "split_tech_fund" in topics["Technical and Fundamental"]
    assert "All technical stocks" in topics["Chart Viewer Technical and Fundamental switch"]
    assert "group_toggle" in topics["Chart Viewer settings"] and "default_group" in topics["Chart Viewer settings"]
    assert "\u2014" not in "".join(topics.values())


def test_off_switch_is_the_old_code_path():
    desk = _read("site", "js", "desk.js")
    viewer = _read("site", "js", "viewer.js")
    # Off (or no settings row) returns the old NAV untouched; the viewer builds the old lists with no group.
    assert "if (!splitOn()) return NAV;" in desk
    assert 'return v != null && String(v).trim().toLowerCase() === "true";' in desk
    assert 'const grouped = !!(D.splitOn && D.splitOn()) && on("group_toggle");' in viewer
    assert 'let group = grouped ? pickGroup(' in viewer and ': "";' in viewer
    assert 'label: group ? "All " + group + " stocks" : "All scanner stocks"' in viewer
    # No new downloads: the viewer still reads only the saved bar files; the pick is saved with localStorage.
    assert re.findall(r'loadCsv\("([^"+]+)', viewer) == ["ohlc/", "ohlc/"]
    assert 'const GROUP_KEY = "desk-cv-group";' in viewer and "localStorage.setItem(GROUP_KEY, next)" in viewer
    assert ".cvgroup{" in _read("site", "css", "desk.css")


def _node(*args, timeout=60, env=None):
    try:
        return subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:
        _skip("node is not installed: " + str(exc))


def test_viewer_group_logic():
    proc = _node(os.path.join("tests", "split_tech_fund_logic.js"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "split tech fund logic ok" in proc.stdout


def test_menu_and_viewer_in_a_browser():
    proc = _node(os.path.join("tests", "split_tech_fund.mjs"), timeout=300, env=dict(os.environ))
    out = proc.stdout + proc.stderr
    if proc.returncode == 2 or "Executable doesn't exist" in out or "Cannot find package 'playwright'" in out:
        _skip("playwright is not installed (set PLAYWRIGHT_ROOT to run the browser check)")
    assert proc.returncode == 0, out
    assert "split tech fund ok" in proc.stdout


if __name__ == "__main__":
    test_switches_and_block()
    test_group_mapping()
    test_settings_and_help_rows()
    test_off_switch_is_the_old_code_path()
    try:
        test_viewer_group_logic()
    except _Skip:
        print("node checks skipped")
    try:
        test_menu_and_viewer_in_a_browser()
    except _Skip as exc:
        print("browser check skipped: " + str(exc))
    print("split tech fund ok")
