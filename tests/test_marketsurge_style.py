"""MarketSurge-style chart (chart_viewer.marketsurge_style): switches, settings, help, EPS markers file, and wiring."""
import json
import os
import subprocess
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import eps_marks  # noqa: E402
import tables  # noqa: E402

STYLE_KEYS = ["marketsurge_style", "ms_log_scale", "ms_hide_why", "rs_rating_label", "swing_labels", "swing_label_bars", "swing_label_min_move_pct",
              "eps_markers", "pivot_header", "ms_range_months", "ms_range_months_phone", "ms_right_space_pct",
              "breakout_arrows", "ms_shade_max_weeks", "pattern_fill", "ms_zone_bars", "ms_pivot_line_bars",
              "include_box", "scanner_pivot_bars"]


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _cfg():
    return json.loads(_read("config.json"))


def test_each_style_piece_has_a_switch_and_is_documented():
    cfg = _cfg()
    cv = cfg["chart_viewer"]
    for k in STYLE_KEYS:
        assert k in cv, k
        assert k in cv["_note"], k
    for k in ("marketsurge_style", "ms_log_scale", "rs_rating_label", "swing_labels", "eps_markers", "pivot_header"):
        assert cv[k] is True, k
    assert cv["ms_range_months"] == 12 and cv["ms_range_months_phone"] == 6
    # MarketSurge draws bases as thin lines: no fill unless pattern_fill is turned on, a small buy zone, a short pivot line.
    assert cv["include_box"] is False and cv["scanner_pivot_bars"] == 15
    assert "include_box: true" in _read("site", "js", "viewer.js").split("const OFF_BY_DEFAULT")[1].split("\n")[0]
    assert cv["pattern_fill"] is False and cv["ms_zone_bars"] == 12 and cv["ms_pivot_line_bars"] == 10
    src = _read("site", "js", "viewer.js")
    assert "pattern_fill: true" in src[src.index("const OFF_BY_DEFAULT"):src.index("function on(key)")]
    assert 'fill: on("pattern_fill")' in src and "flags.zoneBars" in src and "flags.pivotBars" in src
    assert cfg["features"]["eps_marks"] is True
    for k in ("quarters", "fresh_days", "default_lag_days", "match_days"):
        assert k in cfg["eps_marks"] and k in cfg["eps_marks"]["_note"], k
    rows = tables.settings_rows(cfg)
    got = dict(zip(rows["setting"], rows["value"]))
    settings = _read("data", "settings.csv")
    for k in STYLE_KEYS:
        assert got["chart_viewer." + k] == cv[k], k
        assert "\nchart_viewer." + k + "," in settings, k
    for k in ("quarters", "fresh_days", "default_lag_days", "match_days"):
        assert "\neps_marks." + k + "," in settings, k
    assert "\nfeature.eps_marks,True" in settings
    helps = dict(tables.help_rows())
    topic = "Chart Viewer MarketSurge style"
    assert topic in helps and "\n" + topic + "," in _read("data", "help.csv")
    for phrase in ("marketsurge_style", "RS Rating", "EPS +36%", "from Pivot", "no side panel", "private"):
        assert phrase in helps[topic], phrase
    assert "\u2014" not in helps[topic]
    assert "marketsurge_style" in helps["Chart Viewer settings"]
    pages = _read("site", "js", "pages.js")
    assert 'D.viewerOn("marketsurge_style")) text += " " + MS_STYLE_DESC' in pages


def _hist(rows):
    return pd.DataFrame(rows, columns=["ticker", "frame", "kind", "eps", "start", "end", "filed", "source"])


def test_eps_marks_report_day_and_year_over_year_change():
    hist = _hist([
        ["aaa", "CY2025Q1", "Q", 1.00, "", "2025-03-31", "2026-05-01", "sec"],   # restated later: filed is not the report day
        ["AAA", "CY2025Q2", "Q", 1.10, "", "2025-06-30", "2025-08-05", "sec"],
        ["AAA", "CY2025Q3", "Q", 1.20, "", "2025-09-30", "2025-11-04", "sec"],
        ["AAA", "CY2026Q1", "Q", 1.36, "", "2026-03-31", "2026-05-01", "sec"],
        ["AAA", "CY2026Q2", "Q", 0.99, "", "2026-06-30", "2026-08-04", "sec"],
        ["AAA", "CY2025", "A", 4.0, "", "2025-12-31", "2026-02-20", "sec"],
        ["BBB", "CY2025Q2", "Q", -0.5, "", "2025-06-30", "2025-08-01", "sec"],
        ["BBB", "CY2026Q2", "Q", 0.3, "", "2026-06-30", "2026-08-01", "sec"],
    ])
    earn = pd.DataFrame([["AAA", "2026-07-29", 0.9, 0.99]], columns=["ticker", "earnings_date", "eps_estimate", "eps_actual"])
    out = eps_marks.build(hist, earn, {})
    a = out[out["ticker"] == "AAA"].set_index("date")
    assert list(out.columns) == eps_marks.COLS
    assert "2025-05-05" in a.index  # 2025-03-31 plus the usual 35-day lag, not the 2026 restatement
    assert a.loc["2026-05-01", "yoy_pct"] == 36
    assert a.loc["2026-07-29", "yoy_pct"] == -10  # the real report day from earnings_history wins
    assert pd.isna(a.loc["2025-08-05", "yoy_pct"])
    b = out[out["ticker"] == "BBB"]
    assert len(b) == 2 and b["yoy_pct"].isna().all()  # a year-ago loss gives no percent
    assert not (out["date"] == "2026-02-20").any()  # annual rows are not markers
    few = eps_marks.build(hist, None, {"eps_marks": {"quarters": 2}})
    assert len(few[few["ticker"] == "AAA"]) == 2


def test_eps_marks_export_and_published_file():
    assert list(eps_marks.export_frame(pd.DataFrame(), True)["data_status"]) == ["MISSING"]
    assert len(eps_marks.export_frame(pd.DataFrame(), False)) == 0
    assert tables.COLS["eps_marks"] == eps_marks.COLS + ["data_status"]
    path = os.path.join(ROOT, "data", "eps_marks.csv")
    df = pd.read_csv(path)
    assert list(df.columns) == eps_marks.COLS + ["data_status"]
    assert len(df) > 1000 and df["ticker"].nunique() > 500
    assert os.path.getsize(path) < 1_500_000
    assert "open" not in df.columns and "close" not in df.columns  # EPS only, no prices
    code = _read("eps_marks.py")
    assert "requests" not in code and "urlopen" not in code and "yfinance" not in code and "massive" not in code.lower()
    desk = _read("stock_desk.py")
    assert '"eps_marks": eps_marks.export_frame(epsm, features.get("eps_marks", True))' in desk
    assert "eps_marks.build(read_csv(os.path.join(cache, EPS_HISTORY_FILE)), hist_q, cfg)" in desk


def test_viewer_wiring_for_the_style():
    js = _read("site", "js", "viewer.js")
    assert 'function msStyle() { return on("ms_look") && on("marketsurge_style"); }' in js
    for key in ("ms_log_scale", "ms_hide_why", "rs_rating_label", "swing_labels", "eps_markers", "pivot_header"):
        assert 'on("%s")' % key in js, key
    assert 'D.loadCsv("eps_marks.csv")' in js
    assert "price.attachPrimitive(msMarksOverlay(" in js and "rsSeries.attachPrimitive(lab)" in js
    assert 'chart.priceScale("right", 1).applyOptions({ mode: LC.PriceScaleMode.Normal' in js
    assert "fetch(" not in js and "sidepanel" not in js.lower()
    css = _read("site", "css", "desk.css")
    assert ".cv.ms .cvchip.rschip" in css and ".cv.ms .cvpiv{" in css


def test_eps_marks_cli_rebuilds_the_same_file(tmp_path):
    if not os.path.exists(os.path.join(ROOT, "cache", "eps_history.csv")):
        return
    before = _read("data", "eps_marks.csv")
    proc = subprocess.run([sys.executable, "eps_marks.py"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    assert _read("data", "eps_marks.csv") == before
