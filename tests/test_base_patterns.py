"""Base pattern recognition: each pattern on a clean made-up price path, pivots, buy zone, status, switches, and the file."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import base_patterns as bp  # noqa: E402
import tables  # noqa: E402


def path(legs, start=50.0):
    """Daily closes through [(days, end_price), ...], straight lines (or a smooth ease with ('ease', days, price))."""
    out = [start]
    for leg in legs:
        ease = leg[0] == "ease"
        days, end = (leg[1], leg[2]) if ease else leg
        a = out[-1]
        for k in range(1, days + 1):
            u = k / days
            u = (1 - np.cos(np.pi * u)) / 2 if ease else u
            out.append(a + (end - a) * u)
    return np.array(out)


def run(closes, cfg=None):
    n = len(closes)
    idx = pd.bdate_range(end="2026-11-19", periods=n)
    dates = [d.strftime("%Y-%m-%d") for d in idx]
    return bp.rows_for("TEST", dates, closes * 1.004, closes * 0.996, closes, cfg)


def latest(rows):
    return [r for r in rows if r["latest"] == "yes"][0]


def test_flat_base_pivot_is_left_side_high_and_near_pivot_status():
    c = path([(100, 100.0), (8, 92), (8, 99), (8, 93), (10, 98.5)])
    r = latest(run(c))
    assert r["pattern"] == "flat_base"
    assert abs(r["pivot"] - 100 * 1.004) < 0.6
    assert r["depth_pct"] <= 15 and r["length_weeks"] >= 5
    assert r["status"] == "NEAR PIVOT" and r["breakout_date"] == ""
    assert abs(r["buy_point"] - (r["pivot"] + 0.10)) < 1e-6
    assert abs(r["zone_top"] - r["pivot"] * 1.05) < 1e-3


def test_breakout_buy_zone_then_extended_then_below():
    base = [(100, 100.0), (8, 92), (8, 99), (8, 93), (10, 98.5)]
    zone = latest(run(path(base + [(3, 103)])))
    assert zone["pattern"] == "flat_base" and zone["status"] == "BUY ZONE" and zone["breakout_date"] != ""
    assert 0 <= zone["pct_from_pivot"] <= 5
    ext = latest(run(path(base + [(6, 112)])))
    assert ext["status"] == "EXTENDED" and ext["pct_from_pivot"] > 5
    below = latest(run(path(base + [(3, 103), (4, 96)])))
    assert below["status"] == "BELOW PIVOT" and below["pct_from_pivot"] < 0


def test_cup_with_handle_pivot_is_the_handle_peak():
    c = path([(60, 100.0), ("ease", 40, 68), ("ease", 60, 97), (6, 91), (5, 95.5)])
    rows = run(c)
    r = latest(rows)
    assert r["pattern"] == "cup_handle", r
    assert 20 <= r["depth_pct"] <= 50 and r["length_weeks"] >= 6
    assert r["handle_date"] != "" and r["handle_depth_pct"] >= 3
    # Pivot is the handle's peak (about 97), not the left side high (100).
    assert abs(r["pivot"] - 97 * 1.004) < 1.0
    assert r["status"] in ("NEAR PIVOT", "FORMING")


def test_cup_without_handle_pivot_is_the_left_side_high():
    c = path([(60, 100.0), ("ease", 40, 70), ("ease", 60, 99)])
    r = latest(run(c))
    assert r["pattern"] == "cup", r
    assert abs(r["pivot"] - 100 * 1.004) < 0.6
    assert r["handle_date"] == ""


def test_double_bottom_second_low_undercuts_and_pivot_is_the_middle_peak():
    c = path([(60, 100.0), (30, 76), (25, 92), (25, 73), (22, 90)])
    r = latest(run(c))
    assert r["pattern"] == "double_bottom", r
    assert r["first_low_date"] != "" and r["mid_peak_date"] != ""
    assert r["low"] < 76 * 0.996 and abs(r["pivot"] - 92 * 1.004) < 1.0
    assert 10 <= r["depth_pct"] <= 50


def test_ascending_base_three_higher_pullbacks():
    c = path([(300, 60.0), (60, 100.0), (8, 90), (8, 101), (8, 93), (8, 103), (8, 96), (8, 104)])
    r = latest(run(c))
    assert r["pattern"] == "ascending_base", r
    assert 9 <= r["length_weeks"] <= 16
    assert abs(r["pivot"] - 104 * 1.004) < 1.0


def test_ascending_needs_each_low_higher():
    c = path([(300, 60.0), (60, 100.0), (8, 90), (8, 101), (8, 92), (8, 103), (8, 91), (8, 104)])
    assert all(r["pattern"] != "ascending_base" for r in run(c))


def test_ipo_base_only_on_a_young_stock():
    young = path([(20, 30.0), (6, 27), (6, 29.5)], start=20)
    r = latest(run(young))
    assert r["pattern"] == "ipo_base" and 2 <= r["length_weeks"] < 5
    # The same shape after years of history is not an IPO base.
    old = path([(300, 40.0), (20, 30.0), (6, 27), (6, 29.5)], start=20)
    assert all(x["pattern"] != "ipo_base" for x in run(old))


def test_consolidation_is_the_catch_all_for_a_v_shaped_pullback():
    c = path([(60, 100.0), (15, 80), (15, 96)])
    r = latest(run(c))
    assert r["pattern"] == "consolidation", r
    assert r["depth_pct"] > 15


def test_too_deep_or_too_short_is_not_a_base():
    assert run(path([(60, 100.0), (30, 40), (30, 60)])) == []  # 60% drop
    assert run(path([(60, 100.0), (4, 96), (4, 99)])) == []    # under 5 weeks, and not an IPO


def test_each_pattern_has_its_own_switch():
    c = path([(100, 100.0), (8, 92), (8, 99), (8, 93), (10, 98.5)])
    off = {"base_patterns": {"flat_base": False}}
    assert all(r["pattern"] != "flat_base" for r in run(c, off))
    cup = path([(60, 100.0), ("ease", 40, 68), ("ease", 60, 97), (6, 91), (5, 95.5)])
    assert all(r["pattern"] != "cup_handle" for r in run(cup, {"base_patterns": {"cup_handle": False}}))
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    for k in bp.PATTERNS:
        assert cfg["base_patterns"][k] is True
    assert cfg["features"]["base_patterns"] is True


def test_numbers_come_from_config():
    c = path([(100, 100.0), (8, 92), (8, 99), (8, 93), (10, 98.5)])
    wide = latest(run(c, {"base_patterns": {"buy_zone_pct": 8, "buy_point_cents": 25}}))
    assert abs(wide["zone_top"] - wide["pivot"] * 1.08) < 1e-3
    assert abs(wide["buy_point"] - (wide["pivot"] + 0.25)) < 1e-6
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    assert bp.rules(cfg)["cup_min_depth"] == 12.0 and bp.rules(cfg)["buy_zone_pct"] == 5.0


def test_keeps_the_newest_bases_and_marks_one_latest():
    c = path([(100, 100.0), (8, 92), (8, 99), (8, 93), (10, 100.5), (10, 112), (8, 104), (8, 111), (8, 105), (10, 111.5),
              (10, 124), (8, 116), (8, 123), (8, 117), (10, 123.5)])
    rows = run(c)
    assert 1 <= len(rows) <= int(bp.DEFAULTS["max_per_stock"])
    assert sum(1 for r in rows if r["latest"] == "yes") == 1 and rows[-1]["latest"] == "yes"
    assert all(r["status"] == "COMPLETED" for r in rows if r["latest"] == "no")


def test_scan_on_wide_frames_summary_and_export():
    flat = path([(100, 100.0), (8, 92), (8, 99), (8, 93), (10, 98.5)])
    cup = path([(60, 100.0), ("ease", 40, 70), ("ease", 60, 99)])
    n = max(len(flat), len(cup))
    idx = pd.bdate_range(end="2026-11-19", periods=n)

    def pad(a):
        return pd.Series(np.concatenate([np.full(n - len(a), a[0]), a]), index=idx)
    close = pd.DataFrame({"FLAT": pad(flat), "CUPS": pad(cup)})
    frame = bp.scan(close, close * 1.004, close * 0.996, ["FLAT", "CUPS", "NONE"])
    assert list(frame.columns) == bp.COLS
    assert set(frame["ticker"]) == {"FLAT", "CUPS"}
    s = bp.summary(frame)
    assert s["flat_base"]["stocks"] == 1 and s["cup"]["stocks"] == 1
    out = bp.export_frame(frame)
    assert list(out.columns) == tables.COLS["base_patterns"] and set(out["data_status"]) == {"OK"}
    miss = bp.export_frame(pd.DataFrame())
    assert list(miss["data_status"]) == ["MISSING"]
    assert len(bp.export_frame(frame, False)) == 0


def test_published_file_has_only_saved_data_columns_and_no_prices_beyond_pivots():
    p = os.path.join(ROOT, "data", "base_patterns.csv")
    assert os.path.exists(p)
    f = pd.read_csv(p)
    assert list(f.columns) == tables.COLS["base_patterns"]
    ok = f[f["data_status"] == "OK"]
    assert len(ok) > 100 and set(ok["pattern"]) <= set(bp.PATTERNS)
    assert (ok.groupby("ticker")["latest"].apply(lambda s: (s == "yes").sum()) == 1).all()
    assert (ok["pivot"] > 0).all() and (ok["zone_top"] >= ok["pivot"]).all()
    assert os.path.getsize(p) < 1_500_000


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("base pattern tests ok")
