"""RS-Ratio, RS-Momentum, quadrants, the sector score, and quadrant changes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

import sector_rotation as rot


def _expected_rrg(values, smooth, ratio_window, roc_span, mom_window):
    """Independent copy of the z-score formula, written out as loops."""
    rs = np.asarray(values, dtype=float)
    n = len(rs)
    sm = np.full(n, np.nan)
    for i in range(smooth - 1, n):
        sm[i] = rs[i - smooth + 1:i + 1].mean()
    ratio = np.full(n, np.nan)
    for i in range(n):
        window = sm[i - ratio_window + 1:i + 1]
        if len(window) < ratio_window or np.isnan(window).any():
            continue
        mu = window.mean()
        sd = window.std(ddof=1)
        ratio[i] = 100.0 if sd == 0 else 100.0 + (sm[i] - mu) / sd
    roc = np.full(n, np.nan)
    for i in range(roc_span, n):
        if np.isnan(ratio[i]) or np.isnan(ratio[i - roc_span]):
            continue
        roc[i] = ratio[i] - ratio[i - roc_span]
    mom = np.full(n, np.nan)
    for i in range(n):
        window = roc[i - mom_window + 1:i + 1]
        if len(window) < mom_window or np.isnan(window).any():
            continue
        mu = window.mean()
        sd = window.std(ddof=1)
        mom[i] = 100.0 if sd == 0 else 100.0 + (roc[i] - mu) / sd
    return ratio, mom


def test_quadrant_boundaries():
    assert rot.quadrant(100, 100) == "Leading"
    assert rot.quadrant(100.0, 100.0) == "Leading"
    assert rot.quadrant(130, 101) == "Leading"
    assert rot.quadrant(100, 99.999) == "Weakening"
    assert rot.quadrant(140, 40) == "Weakening"
    assert rot.quadrant(99.999, 100) == "Improving"
    assert rot.quadrant(70, 160) == "Improving"
    assert rot.quadrant(99.999, 99.999) == "Lagging"
    assert rot.quadrant(40, 40) == "Lagging"


def test_rrg_matches_an_independent_zscore():
    # Locked point: SMA(2) of 1..10 at the third smoothed window is z = 1, ratio = 101.
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 19, 24, 30]
    smooth, ratio_window, roc_span, mom_window = 2, 3, 1, 3
    idx = pd.bdate_range("2024-01-02", periods=len(values))
    got = rot.rrg_from_rs(pd.Series(values, index=idx), smooth, ratio_window, roc_span, mom_window)
    ratio, mom = _expected_rrg(values, smooth, ratio_window, roc_span, mom_window)
    # The third full ratio window (index 3 of the raw series) is exactly 101.
    assert abs(ratio[3] - 101.0) < 1e-9
    assert len(got) > 0
    # Compare every bar that has both numbers.
    usable = [i for i in range(len(values)) if not np.isnan(ratio[i]) and not np.isnan(mom[i])]
    assert len(got) == len(usable)
    for j, i in enumerate(usable):
        assert abs(float(got["rs_ratio"].iloc[j]) - ratio[i]) < 1e-9
        assert abs(float(got["rs_momentum"].iloc[j]) - mom[i]) < 1e-9
        assert got["quadrant"].iloc[j] == rot.quadrant(ratio[i], mom[i])
    # The locked 101 print is the first ratio, before momentum exists, so it is not a row.
    # Recompute that one bar through the same helper the series uses.
    sm = pd.Series(values, index=idx).rolling(2).mean()
    z = rot._zscore(sm, 3)
    assert abs(float(100 + z.iloc[3]) - 101.0) < 1e-9


def test_flat_rs_sits_at_100_and_leading():
    n = 120
    idx = pd.bdate_range("2020-01-02", periods=n)
    rs = pd.Series(1.5, index=idx)
    spec = rot.WINDOWS["D"]
    got = rot.rrg_from_rs(rs, spec["smooth"], spec["ratio_window"], spec["roc_span"], spec["mom_window"])
    assert len(got) > 0
    assert np.allclose(got["rs_ratio"], 100.0)
    assert np.allclose(got["rs_momentum"], 100.0)
    assert set(got["quadrant"]) == {"Leading"}


def test_rising_rs_finishes_above_100():
    n = 160
    idx = pd.bdate_range("2020-01-02", periods=n)
    rs = pd.Series(np.linspace(1.0, 1.8, n), index=idx)
    spec = rot.WINDOWS["D"]
    got = rot.rrg_from_rs(rs, spec["smooth"], spec["ratio_window"], spec["roc_span"], spec["mom_window"])
    assert float(got["rs_ratio"].iloc[-1]) > 100


def test_weights_sum_to_100_and_missing_is_not_zero():
    assert abs(sum(rot.WEIGHTS.values()) - 100) < 1e-9
    full = {k: 100.0 for k in rot.WEIGHTS}
    assert abs(rot.composite_score(full, rot.WEIGHTS) - 100) < 1e-9
    missing = dict(full)
    missing["rs_1m"] = None
    assert abs(rot.composite_score(missing, rot.WEIGHTS) - 100) < 1e-9
    zeroed = dict(full)
    zeroed["rs_1m"] = 0.0
    # 8 points of weight at 0, the other 92 at 100.
    assert abs(rot.composite_score(zeroed, rot.WEIGHTS) - 92) < 1e-9


def test_leading_bonus_beats_lagging():
    base = {k: 50.0 for k in rot.WEIGHTS}
    lead = dict(base)
    lag = dict(base)
    lead["rrg"] = rot.RRG_POINTS["Leading"]
    lag["rrg"] = rot.RRG_POINTS["Lagging"]
    assert rot.composite_score(lead, rot.WEIGHTS) > rot.composite_score(lag, rot.WEIGHTS)
    assert rot.RRG_POINTS["Leading"] == 100
    assert rot.RRG_POINTS["Improving"] == 70
    assert rot.RRG_POINTS["Weakening"] == 40
    assert rot.RRG_POINTS["Lagging"] == 15


def test_change_detection_sentence():
    assert rot.describe_change("Energy", "Improving", "Leading") == "Energy moved from Improving to Leading"
    assert rot.describe_change("Energy", "Leading", "Leading") == "unchanged"
    assert rot.describe_change("Energy", "", "Leading") == "unchanged"
    rows = [
        {"change_weekly": "Energy moved from Improving to Leading", "change_daily": "unchanged"},
        {"change_weekly": "unchanged", "change_daily": "Utilities moved from Lagging to Improving"},
        {"change_weekly": "unchanged", "change_daily": "unchanged"},
    ]
    assert rot.changed_lines(rows, "change_weekly") == ["Energy moved from Improving to Leading"]
    assert rot.changed_lines(rows, "change_daily") == ["Utilities moved from Lagging to Improving"]


def test_near_high_includes_the_5_percent_line():
    idx = pd.bdate_range("2024-01-02", periods=252)
    high = pd.DataFrame({"AAA": np.full(252, 100.0), "BBB": np.full(252, 100.0)}, index=idx)
    close = high.copy()
    close.iloc[-1, 0] = 95.0  # exactly 5% under the high
    close.iloc[-1, 1] = 94.99
    found = rot.near_high_tickers(close, high, ["AAA", "BBB"], bars=252, near_pct=5)
    assert found == {"AAA"}
    short = close.iloc[:200]
    assert rot.near_high_tickers(short, high.iloc[:200], ["AAA"], bars=252, near_pct=5) == set()


def test_buy_setup_frame_wins_over_the_scanner_fallback():
    scores = pd.DataFrame([
        {"ticker": "AAA", "verdict": "BUY", "above_sma50": 1, "above_sma200": 1},
        {"ticker": "BBB", "verdict": "HOLD", "above_sma50": 1, "above_sma200": 1},
        {"ticker": "CCC", "verdict": "BUY", "above_sma50": 0, "above_sma200": 1},
        {"ticker": "DDD", "verdict": "BUY", "above_sma50": 1, "above_sma200": 1},
    ])
    scanners = {
        "vcp": pd.DataFrame([
            {"ticker": "AAA", "status": "READY"},
            {"ticker": "BBB", "status": "READY"},
            {"ticker": "CCC", "status": "BROKEN OUT today"},
            {"ticker": "DDD", "status": "WATCHING"},
        ]),
    }
    assert rot.resolve_buy_tickers(scores, scanners) == {"AAA"}
    dedicated = pd.DataFrame([{"ticker": "ZZZ"}, {"ticker": ""}])
    assert rot.resolve_buy_tickers(scores, scanners, buy_setups=dedicated) == {"ZZZ"}


def test_macro_trend_up_down_flat_and_short():
    dates = pd.bdate_range("2024-01-02", periods=80)
    up = pd.DataFrame({"date": dates, "v": np.linspace(4.0, 4.5, 80)})
    down = pd.DataFrame({"date": dates, "v": np.linspace(4.5, 4.0, 80)})
    flat = pd.DataFrame({"date": dates, "v": np.full(80, 4.2)})
    short = pd.DataFrame({"date": dates[:5], "v": [1, 2, 3, 4, 9]})
    assert rot.macro_trend(up, lookback=63, flat=0.05)["trend"] == "up"
    assert rot.macro_trend(down, lookback=63, flat=0.05)["trend"] == "down"
    assert rot.macro_trend(flat, lookback=63, flat=0.05)["trend"] == "flat"
    assert rot.macro_trend(short, lookback=63, flat=0.05)["trend"] == "missing"
    assert rot.macro_trend(None)["trend"] == "missing"


def _prices(n=1800):
    idx = pd.bdate_range("2018-01-02", periods=n)
    spy = pd.Series(np.linspace(100, 180, n), index=idx)
    # One sector pulls away, one fades, one tracks.
    xlk = spy * np.linspace(1.0, 1.35, n)
    xle = spy * np.linspace(1.0, 0.75, n)
    xlp = spy * 0.4
    close = pd.DataFrame({"SPY": spy, "XLK": xlk, "XLE": xle, "XLP": xlp})
    high = close * 1.01
    return close, high


def test_build_on_a_long_history_covers_month_bars():
    close, high = _prices()
    scores = pd.DataFrame([
        {"ticker": "AAA", "sector": "Information Technology", "score": 10, "verdict": "BUY", "above_sma50": 1, "above_sma200": 1},
        {"ticker": "BBB", "sector": "Information Technology", "score": 2, "verdict": "AVOID", "above_sma50": 0, "above_sma200": 0},
        {"ticker": "CCC", "sector": "Energy", "score": 6, "verdict": "HOLD", "above_sma50": 1, "above_sma200": 0},
    ])
    # AAA is at the high. Give it a high column equal to the close path's last high.
    high = high.copy()
    high["AAA"] = 100.0
    close = close.copy()
    close["AAA"] = 100.0
    close.iloc[-1, close.columns.get_loc("AAA")] = 96.0
    scanners = {"vcp": pd.DataFrame([{"ticker": "AAA", "status": "READY"}, {"ticker": "CCC", "status": "READY"}])}
    fred = {
        "DGS10": pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=80), "v": np.linspace(4.2, 4.9, 80)}),
        "T10Y2Y": pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=80), "v": np.linspace(0.4, 0.1, 80)}),
    }
    etfs = [
        {"ticker": "XLK", "name": "Technology", "group": "Information Technology"},
        {"ticker": "XLE", "name": "Energy", "group": "Energy"},
        {"ticker": "XLP", "name": "Consumer Staples", "group": "Consumer Staples"},
        {"ticker": "SMH", "name": "Semiconductors", "group": "Information Technology"},
    ]
    out = rot.build(close, high, scores, etfs, scanners=scanners, fred=fred, cfg=None)
    snap = out["sector_rotation"]
    assert set(snap["ticker"]) == {"XLK", "XLE", "XLP"}
    assert "SMH" not in set(snap["ticker"])
    assert set(snap["quadrant_d"]) <= set(rot.QUADRANTS)
    assert set(snap["quadrant_w"]) <= set(rot.QUADRANTS)
    assert set(snap["quadrant_m"]) <= set(rot.QUADRANTS)
    assert snap["quadrant_m"].astype(str).str.len().min() > 0
    assert snap["score"].between(0, 100).all()
    assert list(snap["rank"]) == [1, 2, 3]
    assert snap["score"].iloc[0] >= snap["score"].iloc[-1]
    assert (snap["change_daily"] != "").all()
    assert (snap["change_weekly"] != "").all()
    xlk = snap.set_index("ticker").loc["XLK"]
    assert int(xlk["n_stocks"]) == 2
    assert int(xlk["near_high_count"]) == 1
    assert int(xlk["buy_setup_count"]) == 1
    assert xlk["dgs10_trend"] == "up"
    assert xlk["t10y2y_trend"] == "down"
    assert "Dollar, oil, and gold" in xlk["note"]
    hist = out["sector_rotation_history"]
    assert set(hist["timeframe"]) == {"D", "W", "M"}
    tails = out["sector_rotation_tails"]
    one = tails[(tails.ticker == "XLK") & (tails.timeframe == "W")].sort_values("tail_index")
    assert int(one["tail_index"].iloc[0]) == 1
    assert len(one) == 12
    assert one["date"].iloc[0] < one["date"].iloc[-1]
    # A price that is not cached is skipped, and SPY missing yields nothing.
    assert rot.build(close.drop(columns=["SPY"]), high, scores, etfs)["sector_rotation"].empty


if __name__ == "__main__":
    test_quadrant_boundaries()
    test_rrg_matches_an_independent_zscore()
    test_flat_rs_sits_at_100_and_leading()
    test_rising_rs_finishes_above_100()
    test_weights_sum_to_100_and_missing_is_not_zero()
    test_leading_bonus_beats_lagging()
    test_change_detection_sentence()
    test_near_high_includes_the_5_percent_line()
    test_buy_setup_frame_wins_over_the_scanner_fallback()
    test_macro_trend_up_down_flat_and_short()
    test_build_on_a_long_history_covers_month_bars()
    print("sector rotation ok")
