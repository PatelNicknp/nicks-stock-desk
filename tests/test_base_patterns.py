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


UP = [(200, 60.0), (100, 100.0)]  # over a year of history and the prior uptrend every base needs: 60 to 100


def test_flat_base_pivot_is_left_side_high_and_near_pivot_status():
    c = path(UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)])
    r = latest(run(c))
    assert r["pattern"] == "flat_base"
    assert abs(r["pivot"] - 100 * 1.004) < 0.6
    assert r["depth_pct"] <= 15 and r["length_weeks"] >= 5
    assert r["status"] == "NEAR PIVOT" and r["breakout_date"] == ""
    assert abs(r["buy_point"] - (r["pivot"] + 0.10)) < 1e-6
    assert abs(r["zone_top"] - r["pivot"] * 1.05) < 1e-3
    assert r["prior_uptrend_pct"] >= 30 and r["stage"] == 1 and r["stage_label"] == "1"


def test_every_base_needs_a_prior_uptrend_unless_switched_off():
    flat = [(8, 92), (8, 99), (8, 93), (10, 98.5)]
    sideways = path([(300, 100.0)] + flat, start=95.0)  # only 5% up before the base
    assert all(r["pattern"] != "flat_base" for r in run(sideways))
    r = latest(run(sideways, {"base_patterns": {"require_prior_uptrend": False}}))
    assert r["pattern"] == "flat_base"


def test_breakout_buy_zone_then_extended_then_below():
    base = UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)]
    zone = latest(run(path(base + [(3, 103)])))
    assert zone["pattern"] == "flat_base" and zone["status"] == "BUY ZONE" and zone["breakout_date"] != ""
    assert 0 <= zone["pct_from_pivot"] <= 5
    ext = latest(run(path(base + [(6, 112)])))
    assert ext["status"] == "EXTENDED" and ext["pct_from_pivot"] > 5
    below = latest(run(path(base + [(3, 103), (4, 96)])))
    assert below["status"] == "BELOW PIVOT" and below["pct_from_pivot"] < 0


def test_failed_when_it_closes_7_to_8_pct_under_the_pivot_after_breakout():
    base = UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)]
    r = latest(run(path(base + [(3, 103), (6, 91)])))
    assert r["status"] == "FAILED" and r["failed_date"] != ""
    off = latest(run(path(base + [(3, 103), (6, 91)]), {"base_patterns": {"mark_failed": False}}))
    assert off["status"] != "FAILED" and off["failed_date"] == ""


def test_breakout_volume_is_checked_against_the_50_day_average():
    base = UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)]
    c = path(base + [(3, 103)])
    n = len(c)
    idx = pd.bdate_range(end="2026-11-19", periods=n)
    dates = [d.strftime("%Y-%m-%d") for d in idx]
    bo = int(np.argmax(c > 100 * 1.004))
    loud = np.full(n, 1000.0); loud[bo] = 1600.0
    quiet = np.full(n, 1000.0); quiet[bo] = 1200.0
    a = latest(bp.rows_for("T", dates, c * 1.004, c * 0.996, c, None, loud))
    b = latest(bp.rows_for("T", dates, c * 1.004, c * 0.996, c, None, quiet))
    assert a["breakout_volume_ok"] == "yes" and a["breakout_volume_pct"] >= 40
    assert b["breakout_volume_ok"] == "no" and b["breakout_volume_pct"] < 40


def test_cup_with_handle_pivot_is_the_handle_peak():
    c = path(UP + [("ease", 40, 72), ("ease", 60, 97), (6, 91), (5, 95.5)])
    rows = run(c)
    r = latest(rows)
    assert r["pattern"] == "cup_handle", r
    assert 12 <= r["depth_pct"] <= 33 and 7 <= r["length_weeks"] <= 65
    assert r["handle_date"] != "" and 2 <= r["handle_depth_pct"] <= 12
    assert r["rim_date"] != "" and r["handle_low_date"] != ""
    # Pivot is the handle's peak (about 97), not the left side high (100).
    assert abs(r["pivot"] - 97 * 1.004) < 1.0
    assert r["status"] in ("NEAR PIVOT", "FORMING")


def test_handle_must_sit_in_the_upper_half_of_the_cup():
    c = path(UP + [("ease", 40, 72), ("ease", 60, 97), (6, 82), (5, 86)])  # handle falls under the cup's midpoint (86)
    assert all(r["pattern"] != "cup_handle" for r in run(c))


def test_handle_must_drift_down_not_up():
    up = path(UP + [("ease", 40, 72), ("ease", 60, 96.5), (3, 92), (10, 95.5)])  # the handle's lows climb (wedges up)
    assert all(r["pattern"] != "cup_handle" for r in run(up))
    loose = latest(run(up, {"base_patterns": {"handle_drift_down": False}}))
    assert loose["pattern"] == "cup_handle", loose


def test_cup_without_handle_pivot_is_the_left_side_high():
    c = path(UP + [("ease", 40, 74), ("ease", 60, 99)])
    r = latest(run(c))
    assert r["pattern"] == "cup", r
    assert abs(r["pivot"] - 100 * 1.004) < 0.6
    assert r["handle_date"] == ""


def test_v_shaped_drop_is_not_a_cup():
    c = path(UP + [(25, 75), (25, 99)])
    assert all(r["pattern"] not in ("cup", "cup_handle", "saucer") for r in run(c))


def test_cup_deeper_than_33_pct_only_in_a_bear_market():
    c = path(UP + [("ease", 40, 58), ("ease", 60, 99)])  # 42% deep
    assert all(r["pattern"] not in ("cup", "cup_handle") for r in run(c))
    n = len(c)
    idx = pd.bdate_range(end="2026-11-19", periods=n)
    dates = [d.strftime("%Y-%m-%d") for d in idx]
    spy = pd.Series(path([(200, 450.0), (100, 500.0), ("ease", 40, 380), ("ease", 60, 480)], start=400.0), index=dates)
    r = latest(bp.rows_for("T", dates, c * 1.004, c * 0.996, c, None, None, spy))
    assert r["pattern"] in ("cup", "saucer") and r["deep_base"] == "yes", r
    strict = bp.rows_for("T", dates, c * 1.004, c * 0.996, c, {"base_patterns": {"allow_deep_in_bear": False}}, None, spy)
    assert all(x["pattern"] not in ("cup", "cup_handle") for x in strict)


def test_saucer_is_a_longer_shallower_cup():
    c = path(UP + [("ease", 60, 82), ("ease", 70, 99)])  # 18% deep, about 26 weeks
    r = latest(run(c))
    assert r["pattern"] == "saucer", r
    assert r["length_weeks"] >= 20 and r["depth_pct"] <= 25


def test_double_bottom_second_low_undercuts_and_pivot_is_the_middle_peak():
    c = path(UP + [(30, 78), (25, 92), (25, 76), (22, 90)])
    r = latest(run(c))
    assert r["pattern"] == "double_bottom", r
    assert r["first_low_date"] != "" and r["mid_peak_date"] != ""
    assert r["low"] < 78 * 0.996 and abs(r["pivot"] - 92 * 1.004) < 1.0
    assert 12 <= r["depth_pct"] <= 33 and r["length_weeks"] >= 7


def test_ascending_base_three_higher_pullbacks():
    c = path([(300, 60.0), (60, 100.0), (8, 88), (8, 101), (8, 91), (8, 103), (8, 93), (8, 104)])
    r = latest(run(c))
    assert r["pattern"] == "ascending_base", r
    assert 9 <= r["length_weeks"] <= 16 and r["depth_pct"] <= 25
    assert abs(r["pivot"] - 104 * 1.004) < 1.0


def test_ascending_needs_each_low_higher():
    c = path([(300, 60.0), (60, 100.0), (8, 88), (8, 101), (8, 90), (8, 103), (8, 89), (8, 104)])
    assert all(r["pattern"] != "ascending_base" for r in run(c))


def test_ipo_base_only_on_a_young_stock():
    young = path([(20, 30.0), (12, 26), (10, 29.5)], start=20)
    r = latest(run(young))
    assert r["pattern"] == "ipo_base" and 3 <= r["length_weeks"] <= 25
    # The same shape after years of history is not an IPO base.
    old = path([(300, 40.0), (20, 30.0), (12, 26), (10, 29.5)], start=20)
    assert all(x["pattern"] != "ipo_base" for x in run(old))


def test_consolidation_is_off_and_no_longer_a_catch_all():
    tight = path(UP + [(10, 90), (10, 97), (10, 89), (10, 96)])  # an 11% range that fits... a flat base
    assert all(r["pattern"] != "consolidation" for r in run(tight))
    v = path(UP + [(15, 80), (15, 96)])
    assert all(r["pattern"] != "consolidation" for r in run(v))
    loose = path(UP + [(15, 84), (15, 96), (15, 85), (15, 97)])  # 16% deep: too deep for flat, no cup or W
    cfg = {"base_patterns": {"consolidation": True, "flat_base": False, "cup": False, "cup_handle": False, "saucer": False,
                             "double_bottom": False}}
    on = [r for r in run(loose, cfg) if r["pattern"] == "consolidation"]
    assert on and on[-1]["depth_pct"] <= 20


def test_too_deep_or_too_short_is_not_a_base():
    assert run(path(UP + [(30, 40), (30, 60)])) == []  # 60% drop
    assert run(path(UP + [(4, 96), (4, 99)])) == []    # under 5 weeks, and not an IPO


def test_pinned_price_is_not_a_base():
    pinned = path(UP + [(15, 99), (15, 99.8), (10, 99.2)])  # under 3% deep for 8 weeks, a pending deal
    assert run(pinned) == []


def test_stage_count_letters_and_reset_on_undercut():
    first = [(8, 92), (8, 99), (8, 93), (10, 98.5), (4, 102)]          # base 1, breaks out to 102
    second = [(8, 95), (8, 101), (8, 96), (10, 101.5), (4, 104)]       # forms before a 20% gain: 1(b)
    rows = run(path(UP + first + second), {"base_patterns": {"max_per_stock": 5}})
    labels = [r["stage_label"] for r in rows]
    assert labels[:2] == ["1", "1(b)"], labels
    third = [(20, 130), (8, 120), (8, 129), (8, 121), (10, 129)]       # up 25% past the pivot first: Stage 2
    rows = run(path(UP + first + third), {"base_patterns": {"max_per_stock": 5}})
    assert [r["stage_label"] for r in rows][-1] == "2", rows
    crash = [(20, 130), (25, 70), (130, 140), (8, 128), (8, 138), (8, 129), (10, 138)]  # undercuts base 1's low: reset
    rows = run(path(UP + first + crash), {"base_patterns": {"max_per_stock": 5}})
    assert rows[-1]["stage_label"] == "1", rows
    off = run(path(UP + first + second), {"base_patterns": {"count_stages": False}})
    assert all(r["stage_label"] == "" for r in off)


def test_each_pattern_has_its_own_switch():
    c = path(UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)])
    off = {"base_patterns": {"flat_base": False}}
    assert all(r["pattern"] != "flat_base" for r in run(c, off))
    cup = path(UP + [("ease", 40, 72), ("ease", 60, 97), (6, 91), (5, 95.5)])
    assert all(r["pattern"] != "cup_handle" for r in run(cup, {"base_patterns": {"cup_handle": False}}))
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    for k in bp.PATTERNS:
        assert cfg["base_patterns"][k] is (k != "consolidation")
    for k in bp.FLAGS:
        assert cfg["base_patterns"][k] is True
    assert cfg["features"]["base_patterns"] is True


def test_a_one_bar_spike_wick_does_not_set_the_low_or_depth():
    c = path(UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)])
    n = len(c)
    idx = pd.bdate_range(end="2026-11-19", periods=n)
    dates = [d.strftime("%Y-%m-%d") for d in idx]
    hi, lo = c * 1.004, c * 0.996
    k = n - 20
    lo = lo.copy(); lo[k] = c[k] * 0.80  # one intraday flush 20% under the close
    r = latest(bp.rows_for("T", dates, hi, lo, c, None))
    assert r["pattern"] == "flat_base" and r["depth_pct"] <= 10, r
    raw = bp.rows_for("T", dates, hi, lo, c, {"base_patterns": {"robust_bounds": False}})
    assert all(x["pattern"] != "flat_base" or x["depth_pct"] > 15 for x in raw)
    clipped = bp.robust_lows(hi, lo, c, bp.rules())
    assert clipped[k] > lo[k] and clipped[k] <= c[k]
    # A real multi-day drop keeps its lows.
    assert np.allclose(np.delete(clipped, k), np.delete(lo, k))


def test_base_starts_at_the_tightest_left_side_high():
    # Two tops at about the same price: the base starts at the later one, so the deep early dip is not in it.
    c = path(UP + [(10, 84), (12, 99.5), (8, 93), (8, 99), (8, 94), (10, 98.8)])
    r = latest(run(c))
    assert r["pattern"] == "flat_base" and r["depth_pct"] < 8, r
    assert abs(r["pivot"] - 99.5 * 1.004) < 0.6  # the later top, not the first one at 100
    # Measured from the first top the region is 16% deep with a V in it: no base at all.
    assert all(x["pattern"] != "flat_base" for x in run(c, {"base_patterns": {"prefer_tight": False}}))


def test_ascending_base_lists_its_pullbacks_and_depth_is_the_deepest_pullback():
    c = path([(300, 60.0), (60, 100.0), (8, 88), (8, 101), (8, 91), (8, 103), (8, 93), (8, 104)])
    r = latest(run(c))
    assert r["pattern"] == "ascending_base"
    lows = r["pullback_low_dates"].split(";")
    highs = r["pullback_high_dates"].split(";")
    assert len(lows) == 3 and len(highs) == 3 and lows == sorted(lows) and highs[0] < lows[0]
    assert 10 <= r["depth_pct"] <= 20


def test_numbers_come_from_config():
    c = path(UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)])
    wide = latest(run(c, {"base_patterns": {"buy_zone_pct": 8, "buy_point_cents": 25}}))
    assert abs(wide["zone_top"] - wide["pivot"] * 1.08) < 1e-3
    assert abs(wide["buy_point"] - (wide["pivot"] + 0.25)) < 1e-6
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    assert bp.rules(cfg)["cup_min_depth"] == 12.0 and bp.rules(cfg)["buy_zone_pct"] == 5.0


def test_keeps_the_newest_bases_and_marks_one_latest():
    c = path(UP + [(8, 92), (8, 99), (8, 93), (10, 100.5), (10, 112), (8, 104), (8, 111), (8, 105), (10, 111.5),
              (10, 124), (8, 116), (8, 123), (8, 117), (10, 123.5)])
    rows = run(c)
    assert 1 <= len(rows) <= int(bp.DEFAULTS["max_per_stock"])
    assert sum(1 for r in rows if r["latest"] == "yes") == 1 and rows[-1]["latest"] == "yes"
    assert all(r["status"] in ("COMPLETED", "FAILED") for r in rows if r["latest"] == "no")


def test_scan_on_wide_frames_summary_and_export():
    flat = path(UP + [(8, 92), (8, 99), (8, 93), (10, 98.5)])
    cup = path(UP + [("ease", 40, 74), ("ease", 60, 99)])
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
