"""Chart Viewer EPS chip: the EPS Rating on scores.csv, the chip next to RS, its switch, help, and description."""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import stock_desk  # noqa: E402
import tables  # noqa: E402


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _q(ticker, values):
    return [{"ticker": ticker, "frame": f, "eps": v} for f, v in values.items()]


def test_scores_table_has_eps_rating_after_the_rs_columns():
    cols = tables.COLS["scores"]
    assert cols.count("eps_rating") == 1
    assert cols.index("eps_rating") == cols.index("rs_note") + 1
    assert cols[-3:] == ["data_status", "note", "disclaimer"]


def test_attach_eps_rating_is_blank_not_zero():
    frame = pd.DataFrame({"ticker": ["AAA", "bbb", "CCC", "DDD"], "score": [1, 2, 3, 4]})
    ratings = pd.DataFrame({"ticker": ["AAA", "BBB", "DDD"], "eps_rating": [85.0, 42, np.nan]})
    out = stock_desk.attach_eps_rating(frame, ratings)
    assert list(out["eps_rating"]) == [85, 42, "", ""]
    assert "eps_rating" not in frame.columns
    # No ratings at all: the column is there and every cell is blank.
    assert list(stock_desk.attach_eps_rating(frame, None)["eps_rating"]) == ["", "", "", ""]
    assert len(stock_desk.attach_eps_rating(pd.DataFrame(), ratings)) == 0


def test_build_ms_screens_hands_the_same_eps_ratings_to_scores():
    n = 300
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.DataFrame({t: 50 * (1.002 ** np.arange(n)) for t in ("BEST", "MID", "LOW", "NONE")}, index=idx)
    universe = pd.DataFrame({"ticker": ["BEST", "MID", "LOW", "NONE"]})
    rows, ann = [], []
    for t, now, end in (("BEST", 3.0, 4.0), ("MID", 1.5, 2.0), ("LOW", 0.5, 0.8)):
        rows += _q(t, {"CY2026Q2": now, "CY2025Q2": 1.0, "CY2026Q1": now, "CY2025Q1": 1.0})
        ann += _q(t, {"CY2023": 1.0, "CY2026": end})
    quarters, annual = pd.DataFrame(rows), pd.DataFrame(ann)
    frames, _notes = stock_desk.build_ms_screens(close, close * 1.01, close * 0.99, universe, quarters, annual, {}, {},
                                                 {}, {}, asof="2026-08-15")
    got = dict(zip(frames["eps_ratings"]["ticker"], frames["eps_ratings"]["eps_rating"]))
    assert got == {"BEST": 99, "MID": 50, "LOW": 1}
    scores = stock_desk.attach_eps_rating(universe, frames["eps_ratings"])
    assert list(scores["eps_rating"]) == [99, 50, 1, ""]


def test_main_run_puts_eps_rating_on_scores_and_export_keeps_it():
    src = _read("stock_desk.py")
    assert 'frames["eps_ratings"] = pd.DataFrame(' in src
    assert 'scores = attach_eps_rating(scores, ms_frames.get("eps_ratings"))' in src
    assert 'scores = attach_eps_rating(scores, existing[["ticker", "eps_rating"]])' in src


def test_config_switch_help_and_description():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cv = json.load(f)["chart_viewer"]
    assert cv["eps_chip"] is True and cv["eps_chip_green_min"] == 80
    assert "eps_chip" in cv["_note"] and "eps_chip_green_min" in cv["_note"]
    settings = tables.settings_rows(json.loads(_read("config.json")))
    keys = set(settings["setting"]) if hasattr(settings, "columns") else {r[0] for r in settings}
    assert "chart_viewer.eps_chip" in keys and "chart_viewer.eps_chip_green_min" in keys
    helps = dict(tables.help_rows())
    text = helps["Chart Viewer EPS chip"]
    assert "EPS 85" in text and "chart_viewer.eps_chip" in text and "80 or higher" in text and "\u2014" not in text
    assert "eps_chip" in helps["Chart Viewer settings"]
    pages = _read("site", "js", "pages.js")
    assert 'D.viewerOn("eps_chip")) text += " " + EPS_BADGE_DESC' in pages
    assert "The EPS chip, right after the RS chip, is the 1 to 99 EPS Rating" in pages


def test_chip_sits_right_after_the_rs_chip_with_its_own_switch():
    js = _read("site", "js", "viewer.js")
    assert "const chips = rsBadge + epsBadge + " in js
    assert 'on("eps_chip") ? \'<span class="cvchip epschip" id="cveps" hidden></span>\'' in js
    assert 'epsChip(it.eps, cfgNum("eps_chip_green_min", 80))' in js
    assert 'epsEl.classList.toggle("hot", chip.hot)' in js
    assert "eps: epsOf(s.eps_rating)" in js
    css = _read("site", "css", "desk.css")
    # Green uses the theme's --up color, so light mode stays light.
    assert ".cvchip.epschip{" in css and ".cvchip.epschip.hot{color:var(--up);border-color:var(--up)}" in css


def test_chip_rules_in_node():
    try:
        proc = subprocess.run(["node", os.path.join("tests", "eps_chip_check.js")], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        print("node is not installed, eps chip node check skipped")
        return
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "eps chip ok" in proc.stdout


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("eps chip tests ok")
