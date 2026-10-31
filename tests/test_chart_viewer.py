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
    assert cv["chart_touch_pan"] is True
    assert cv["drag_mode_toggle"] is True and cv["range_chips"] is True
    assert (cv["swipe_min_px"], cv["swipe_max_ms"], cv["swipe_ratio"]) == (80, 300, 1.5)
    assert (cv["range_months"], cv["range_months_phone"]) == (6, 3)
    assert cv["native_fullscreen_ios"] is False
    assert (cv["ma_10"], cv["ma_20"], cv["ma_50"], cv["ma_150"], cv["ma_200"]) == (False, False, True, True, True)
    assert cv["volume"] is True and cv["reason_box"] is True and cv["reason_box_toggle"] is True
    for key in ("list_picker", "fullscreen", "native_fullscreen_ios", "swipe", "flip_toggle", "arrows", "keyboard", "counter", "preload_next",
                "ma_chips", "volume_toggle", "company_line", "day_change", "scanner_links", "drag_mode_toggle", "range_chips", "fit_wide_ranges"):
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
    for topic in ("Chart Viewer", "Chart Viewer swipes", "Chart Viewer lines and reason box", "Chart Viewer settings",
                  "Chart Viewer on iPhone and iPad", "Chart Viewer drag button", "Chart Viewer history and range"):
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


def test_ios_full_screen_uses_the_overlay():
    """iPhone and iPad skip requestFullscreen (Safari's grey X covers the stock name) unless the switch is on."""
    js = _read("site", "js", "viewer.js")
    assert 'on("native_fullscreen_ios")' in js
    assert "native_fullscreen_ios: true" in js  # off when a settings file has no row for it
    assert "nativeFs && req && can" in js
    # The overlay path still sets up the site's own close button and the Esc key.
    assert 'getElementById("cvx").addEventListener("click", exitFull)' in js
    assert 'e.key === "Escape"' in js
    css = _read("site", "css", "desk.css")
    assert ".cv.full.ios{" in css
    for side in ("top", "right", "bottom", "left"):
        assert "padding-" + side + ":env(safe-area-inset-" + side in css, side
    assert "height:100dvh" in css.split(".cv.full{", 1)[1].split("}", 1)[0]
    assert ".cv.full .cv-x{display:block}" in css
    assert "viewport-fit=cover" in _read("site", "chart-viewer.html")
    topics = dict(tables.help_rows())
    assert "native_fullscreen_ios" in topics["Chart Viewer on iPhone and iPad"]
    assert "native_fullscreen_ios" in topics["Chart Viewer settings"]


def test_drag_moves_chart_and_full_history():
    """One-finger drag pans and pinch zooms; the Drag chip and range chips; every saved bar is on the chart."""
    js = _read("site", "js", "viewer.js")
    assert "horzTouchDrag: state.pan" in js and "pinch: state.pan" in js
    assert 'stored("desk-cv-drag-pan", on("chart_touch_pan"))' in js
    assert 'store("desk-cv-drag-pan", state.pan)' in js
    assert "chart.applyOptions({ handleScroll: { horzTouchDrag: state.pan }, handleScale: { pinch: state.pan } })" in js
    assert '"Drag: move chart"' in js and '"Drag: next chart"' in js
    assert js.index('data-tool="flip"') < js.index('data-tool="drag"')
    assert 'on("drag_mode_toggle")' in js and 'on("range_chips")' in js
    # chart_touch_pan now defaults on, so it is not in the off-by-default list.
    off = re.search(r"OFF_BY_DEFAULT = \{([^}]*)\}", js).group(1)
    assert "chart_touch_pan" not in off and "drag_mode_toggle" not in off and "range_chips" not in off
    assert 'cfgNum("swipe_min_px", 80)' in js and 'cfgNum("swipe_max_ms", 300)' in js
    # Swipes are read on the whole viewer. The header row always counts as a bar swipe; the chip bar only when it fits.
    assert 'cv.addEventListener("touchstart"' in js and 'onBar: zone === "bar"' in js
    assert 'e.target.closest(".cv-top")' in js and 'if (zone === "scroll") { start = null; return; }' in js
    # The whole saved file goes on the chart: no slicing of bars before setData.
    assert "price.setData(bars.map(" in js
    assert "bars.slice(" not in js and "rows.slice(" not in js
    # Arrows and keys still change the chart.
    assert 'prev.addEventListener("click", () => go(-1))' in js and 'e.key === "ArrowRight"' in js
    # Only a few parsed bar files stay in memory.
    assert "keepRecent(recent, name, 6)" in js
    assert "forgetCsv:" in _read("site", "js", "desk.js")
    topics = dict(tables.help_rows())
    assert "five years" in topics["Chart Viewer history and range"]
    assert "slow drag" in topics["Chart Viewer swipes"]
    assert "Drag" in _read("site", "js", "pages.js").split("chartviewer: \"", 1)[1].split("\n", 1)[0]


def test_saved_history_is_about_five_years():
    """The bar files the viewer reads hold the job's 5y download, so dragging back has data."""
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "data", "ohlc", "*.csv")))
    if not files:
        _skip("no saved bar files")
    with open(os.path.join(ROOT, "data", "ohlc", "AAPL.csv"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0].startswith("date,")
    first, last = lines[1][:10], lines[-1][:10]
    years = (int(last[:4]) - int(first[:4])) + (int(last[5:7]) - int(first[5:7])) / 12.0
    assert years >= 4.5, (first, last)
    assert 'period="5y"' in _read("stock_desk.py")


def test_overflowing_chip_bar_scrolls_instead_of_changing_chart():
    """iPhone: the chip bar is wider than the screen, so a swipe there scrolls it; only the header row always changes the chart."""
    css = _read("site", "css", "desk.css")
    phone = [b.split("\n}", 1)[0] for b in css.split("@media (max-width:699px){")[1:] if ".cv-tools{" in b.split("\n}", 1)[0]][0]
    assert ".cv-tools{" in phone and "flex-wrap:nowrap" in phone and "overflow-x:auto" in phone
    assert ".cv.full .cv-tools{touch-action:pan-x}" in css
    assert ".cv.full .cv-top{touch-action:none}" in css
    note = _cfg()["chart_viewer"]["_note"]
    assert "header row (ticker, price, counter) always does" in note and "scrolls the chips" in note
    swipes = dict(tables.help_rows())["Chart Viewer swipes"]
    assert "top row (the stock name, price, and counter) always changes the chart" in swipes
    assert "scrolls the buttons" in swipes and "only when all the buttons fit" in swipes


def _playwright_env():
    env = dict(os.environ)
    if env.get("PLAYWRIGHT_ROOT") and os.path.exists(os.path.join(env["PLAYWRIGHT_ROOT"], "index.mjs")):
        return env
    try:
        proc = subprocess.run(["node", "-e", "require.resolve('playwright')"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        _skip("node is not installed: " + str(exc))
    if proc.returncode != 0:
        _skip("playwright is not installed (set PLAYWRIGHT_ROOT to run the iPhone touch check)")
    return env


def test_first_view_refits_and_keeps_a_dragged_range():
    """The first view waits for a 120 px wide chart and is put back on resize, unless the user dragged the chart."""
    js = _read("site", "js", "viewer.js")
    assert "minBarSpacing: minSpacing()" in js and 'cfgNum("min_bar_spacing", 0.3)' in js
    # A range too long to fit (All on a phone) fills the space left of the Why box at the thinnest bars.
    assert 'on("fit_wide_ranges") ? fitRange(from, n - 1, pad, plot, minSpacing())' in js
    cv = _cfg()["chart_viewer"]
    assert cv["fit_wide_ranges"] is True and cv["min_bar_spacing"] == 0.3
    assert "fit_wide_ranges" in dict(tables.help_rows())["Chart Viewer history and range"]
    assert "fit_wide_ranges" in dict(tables.help_rows())["Chart Viewer settings"]
    assert "viewAfterResize(userRange, plotWidth(), 120)" in js
    assert js.count("requestAnimationFrame(() => refit())") == 2  # full screen and resize
    assert "requestAnimationFrame(() => { if (my === token) refit(); })" in js  # after the data loads
    assert 'window.addEventListener("orientationchange"' in js
    # A range chip drops the dragged range; the Vol chip redraw keeps it.
    chip = js.split("if (range) {", 1)[1].split("return;", 1)[0]
    assert "userRange = null;" in chip and "fitView();" in chip
    assert "carryRange = userRange;" in js
    # Only the release of a finger, the mouse, or the wheel on the chart reads a dragged range.
    assert "setTimeout(readUserRange, 120)" in js
    note = _cfg()["chart_viewer"]["_note"]
    assert "kept when the screen turns" in note
    assert "kept when you turn" in dict(tables.help_rows())["Chart Viewer history and range"]


def test_first_view_on_iphone_and_ipad():
    """Real chart, iPhone and iPad portrait and landscape: first view, full screen, turns, narrow-then-wide, drag kept."""
    env = _playwright_env()
    proc = subprocess.run(["node", os.path.join("tests", "chart_viewer_fit.mjs")], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 and "Executable doesn't exist" in proc.stdout + proc.stderr:
        _skip("playwright browser is not installed")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "chart viewer fit ok" in proc.stdout


def test_iphone_portrait_chip_bar_and_header_swipes():
    """Real touches at 390x844: chip bar overflows, a chip bar swipe scrolls and keeps the chart, a header swipe changes it."""
    env = _playwright_env()
    proc = subprocess.run(["node", os.path.join("tests", "chart_viewer_touch.mjs")], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 and "Executable doesn't exist" in proc.stdout + proc.stderr:
        _skip("playwright browser is not installed")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "chart viewer touch ok" in proc.stdout


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
    test_ios_full_screen_uses_the_overlay()
    test_drag_moves_chart_and_full_history()
    try:
        test_saved_history_is_about_five_years()
    except _Skip:
        print("history check skipped")
    test_overflowing_chip_bar_scrolls_instead_of_changing_chart()
    test_first_view_refits_and_keeps_a_dragged_range()
    try:
        test_first_view_on_iphone_and_ipad()
    except _Skip as exc:
        print("first view check skipped: " + str(exc))
    try:
        test_iphone_portrait_chip_bar_and_header_swipes()
    except _Skip as exc:
        print("iphone touch check skipped: " + str(exc))
    try:
        test_scripts_parse()
        test_list_and_swipe_rules()
    except _Skip:
        print("node checks skipped")
    print("chart viewer ok")
