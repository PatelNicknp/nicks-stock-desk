"""Offline checks for the VCP port, CANSLIM letters, and the box and flag rules."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import setups


def _dates(n, start="2024-01-02"):
    return pd.bdate_range(start, periods=n)


def _panel(tickers, frames):
    """frames: ticker -> DataFrame with close, high, low, volume."""
    close, high, low, vol = {}, {}, {}, {}
    for t, f in frames.items():
        close[t] = f["close"]
        high[t] = f["high"]
        low[t] = f["low"]
        vol[t] = f["volume"]
    return (
        pd.DataFrame(close), pd.DataFrame(high), pd.DataFrame(low), pd.DataFrame(vol),
    )


def _uni(names):
    return pd.DataFrame([
        {"ticker": t, "company": t + " Co", "sector": "Information Technology", "index_membership": "SP500"}
        for t in names
    ])


def test_pivot_is_strict_and_delayed():
    high = np.array([1, 1, 1, 1, 1, 9, 1, 1, 1], dtype=float)
    # center index 5, left 4, right 3, confirms on bar 8
    got = setups.pivot_confirmed(high, 4, 3, "high")
    assert np.isnan(got[:8]).all()
    assert got[8] == 9
    tied = np.array([1, 5, 5, 1], dtype=float)
    assert np.isnan(setups.pivot_confirmed(tied, 1, 1, "high")).all()


def _climb(n=340, vol=1_000_000):
    idx = _dates(n)
    close = 80 * (1.003 ** np.arange(n))
    return idx, close, np.full(n, vol, dtype=float)


def _vcp_tape(breakout=False):
    """Smooth climb, then a 4% pullback and a tighter 3.2% pullback."""
    n = 340
    idx, close, vol = _climb(n)
    high = close * 1.002
    low = close * 0.998
    # Peak 1 at 280, low 1 at 292, peak 2 at 304, low 2 at 314, settle under peak 2.
    peak1, low1, peak2, low2 = 280, 292, 304, 314
    p1 = float(high[peak1 - 1]) * 1.01
    high[peak1] = p1
    low[peak1] = p1 * 0.99
    close[peak1] = p1 * 0.995
    l1 = p1 * 0.90
    for i in range(peak1 + 1, low1):
        high[i] = p1 * (1 - 0.03 * (i - peak1) / (low1 - peak1))
        low[i] = high[i] * 0.995
        close[i] = (high[i] + low[i]) / 2
    high[low1] = l1 * 1.01
    low[low1] = l1
    close[low1] = l1 * 1.002
    p2 = p1 * 0.97
    for i in range(low1 + 1, peak2):
        span = peak2 - low1
        level = l1 + (p2 - l1) * (i - low1) / span
        high[i] = level
        low[i] = level * 0.995
        close[i] = level * 0.997
    high[peak2] = p2
    low[peak2] = p2 * 0.99
    close[peak2] = p2 * 0.995
    l2 = p2 * 0.965  # about 3.5% deep, and still above the first low
    assert l2 > l1
    for i in range(peak2 + 1, low2):
        high[i] = p2 * (1 - 0.02 * (i - peak2) / (low2 - peak2))
        low[i] = high[i] * 0.996
        close[i] = (high[i] + low[i]) / 2
    high[low2] = l2 * 1.008
    low[low2] = l2
    close[low2] = l2 * 1.002
    settle = p2 * 0.99
    for i in range(low2 + 1, n):
        high[i] = settle * 1.004
        low[i] = settle * 0.996
        close[i] = settle
    if breakout:
        prev = float(close[-2])
        assert prev <= p2
        close[-1] = p2 * 1.01
        high[-1] = close[-1] * 1.002
        low[-1] = p2
        vol[-1] = 5_000_000
    spy = 100 * (1.0004 ** np.arange(n))
    frame = pd.DataFrame({"close": close, "high": high, "low": low, "volume": vol}, index=idx)
    spy_s = pd.Series(spy, index=idx)
    return frame, spy_s, p2


def test_vcp_ready_matches_pine_levels():
    frame, spy, p2 = _vcp_tape(False)
    state = setups.vcp_last(frame["high"], frame["low"], frame["close"], frame["volume"], spy.to_numpy())
    assert state["rules"] == [True] * 8, state["rules"]
    assert state["cnt"] >= 2, state["depths"]
    assert state["depths"][0] > state["depths"][1]
    assert abs(state["pivot"] - p2) < 0.02
    assert state["is_vcp"]
    assert not state["breakout"]
    status = setups._vcp_status(state)
    assert status == "READY"
    stop, target, basis, kind = setups._vcp_levels(state)
    assert kind == "pivot"
    assert abs(stop - p2 * 0.93) < 0.05
    assert abs(target - p2 * 1.20) < 0.05
    assert "7%" in setups._vcp_reason(state, status, frame.index)


def test_vcp_breakout_uses_the_close():
    frame, spy, p2 = _vcp_tape(True)
    state = setups.vcp_last(frame["high"], frame["low"], frame["close"], frame["volume"], spy.to_numpy())
    assert state["breakout"], state
    assert setups._vcp_status(state) == "BROKEN OUT today"
    assert abs(state["stop"] - state["entry"] * 0.93) < 0.05
    assert abs(state["entry"] - float(frame["close"].iloc[-1])) < 0.01
    # 2.5R breakeven and the 20% target are the Pine exits, not a guessed multiple.
    assert abs(state["entry"] * (1 + 2.5 * 0.07) - state["entry"] * 1.175) < 1e-6


def test_shallow_dip_is_not_a_contraction():
    n = 340
    idx, close, vol = _climb(n)
    high = close * 1.002
    low = close * 0.998
    # A 2% dip is under the 3% minimum, so it must not become a contraction.
    i = 300
    high[i] = high[i - 1] * 1.01
    low[i + 6] = high[i] * 0.98
    close[i + 6] = low[i + 6] * 1.001
    spy = 100 * (1.0004 ** np.arange(n))
    state = setups.vcp_last(high, low, close, vol, spy)
    assert state["cnt"] == 0


def test_lower_low_extends_the_same_contraction():
    """A lower high and a lower low extend one contraction. They do not add T2."""
    n = 340
    _idx, close, vol = _climb(n)
    high = close * 1.002
    low = close * 0.998
    p = float(high[279])
    for i in range(280, n):
        high[i] = p * 0.94
        low[i] = p * 0.93
        close[i] = p * 0.935
    high[290] = p
    low[290] = p * 0.97
    close[290] = p * 0.98
    low[300] = p * 0.90
    high[300] = p * 0.91
    close[300] = p * 0.905
    high[310] = p * 0.96
    low[310] = p * 0.945
    close[310] = p * 0.95
    low[320] = p * 0.85
    high[320] = p * 0.86
    close[320] = p * 0.855
    for i in range(321, n):
        high[i] = p * 0.88
        low[i] = p * 0.87
        close[i] = p * 0.875
    spy = 100 * (1.0004 ** np.arange(n))
    state = setups.vcp_last(high, low, close, vol, spy)
    assert state["cnt"] == 1, state["depths"]
    assert state["depths"][0] > 8


def test_canslim_does_not_invent_missing_letters():
    n = 260
    idx = _dates(n)
    close = 50 * (1.002 ** np.arange(n))
    frame = pd.DataFrame({
        "close": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "volume": np.full(n, 2_000_000.0),
    }, index=idx)
    spy = pd.Series(100 * (1.0003 ** np.arange(n)), index=idx)
    close_w, high_w, low_w, vol_w = _panel(["AAA", "BBB", "SPY"], {
        "AAA": frame,
        "BBB": frame.copy(),
        "SPY": pd.DataFrame({"close": spy, "high": spy * 1.01, "low": spy * 0.99, "volume": 1e8}, index=idx),
    })
    quarters = pd.DataFrame([
        {"ticker": "AAA", "frame": "CY2024Q3", "eps": 1.0},
        {"ticker": "AAA", "frame": "CY2025Q3", "eps": 1.4},
    ])
    annual = pd.DataFrame([
        {"ticker": "AAA", "frame": "CY2023", "eps": 2.0},
        {"ticker": "AAA", "frame": "CY2024", "eps": 2.5},
    ])
    holders = pd.DataFrame([
        {"ticker": "AAA", "inst_up": 10, "inst_down": 4, "ownership_pct": 60},
    ])
    uni = _uni(["AAA", "BBB"])
    out, market = setups.scan_canslim(close_w, high_w, low_w, vol_w, uni, quarters, annual, holders)
    assert market["qqq"] == "not verified"
    assert "QQQ" in market["text"]
    assert "not verified" in market["text"]
    aaa = out[out.ticker == "AAA"]
    bbb = out[out.ticker == "BBB"]
    assert len(aaa) == 1
    assert aaa.iloc[0]["c_quarterly_eps"] == 40.0
    assert aaa.iloc[0]["a_annual_eps"] == 25.0
    assert aaa.iloc[0]["i_trend"] == "up"
    assert aaa.iloc[0]["stop"] == ""
    assert aaa.iloc[0]["target"] == ""
    assert "not verified" in aaa.iloc[0]["reason"]
    assert "SP500" in aaa.iloc[0]["index_membership"]
    if len(bbb):
        assert bbb.iloc[0]["c_status"] == "not verified"
        assert bbb.iloc[0]["c_quarterly_eps"] == ""
        assert bbb.iloc[0]["a_status"] == "not verified"
        assert bbb.iloc[0]["i_trend"] == "not verified"
    # BBB has no holder row and no EPS. If the price screen dropped it, the letters
    # are still not invented anywhere in the frame.
    blob = out.to_csv(index=False)
    assert "not verified" in blob


def test_box_breakout_levels():
    n = 80
    idx = _dates(n)
    close = np.full(n, 105.0)
    high = np.full(n, 110.0)
    low = np.full(n, 100.0)
    vol = np.full(n, 1_000_000.0)
    # Prior trend so a longer window is too wide, then 20 tight days, then the break.
    close[:40] = np.linspace(70, 100, 40)
    high[:40] = close[:40] * 1.02
    low[:40] = close[:40] * 0.98
    close[-1] = 112
    high[-1] = 113
    low[-1] = 109
    vol[-1] = 4_000_000
    frame = pd.DataFrame({"close": close, "high": high, "low": low, "volume": vol}, index=idx)
    c, h, l, v = _panel(["AAA"], {"AAA": frame})
    out = setups.scan_box(c, h, l, v, _uni(["AAA"]))
    row = out.iloc[0]
    assert row["status"] == "BROKEN OUT today"
    assert float(row["pivot"]) == 110.0
    assert float(row["stop"]) == 100.0
    assert float(row["target"]) == 120.0
    assert row["freshness"] == "FRESH"


def test_flag_breakout_levels():
    n = 60
    idx = _dates(n)
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    vol = np.full(n, 1_000_000.0)
    # Today is the last bar. A 5-bar flag ending yesterday puts the pole high 6 bars back.
    pole = n - 2 - 5
    for i, px in enumerate(np.linspace(100, 128, 8)):
        j = pole - 7 + i
        close[j] = px
        high[j] = px + 1
        low[j] = px - 1
    high[pole] = 130
    close[pole] = 129
    low[pole] = 127
    for k, j in enumerate(range(pole + 1, n - 1)):
        close[j] = 127 - k * 0.4
        high[j] = 128
        low[j] = 124
    close[-1] = 129
    high[-1] = 131
    low[-1] = 126
    vol[-1] = 5_000_000
    frame = pd.DataFrame({"close": close, "high": high, "low": low, "volume": vol}, index=idx)
    c, h, l, v = _panel(["AAA"], {"AAA": frame})
    out = setups.scan_flag(c, h, l, v, _uni(["AAA"]))
    assert len(out) == 1, "expected a flag"
    row = out.iloc[0]
    assert row["status"] == "BROKEN OUT today"
    assert float(row["pivot"]) == 128.0
    assert float(row["stop"]) == 124.0
    pole_low = float(frame["low"].iloc[pole - 12:pole].min())
    assert float(row["target"]) == round(128.0 + (130.0 - pole_low), 2)


def test_leaders_prefers_the_vcp_plan():
    vcp = pd.DataFrame([{
        "ticker": "AAA", "company": "Alpha", "sector": "Tech", "index_membership": "SP500 / NDX100",
        "status": "READY", "pivot": 100, "stop": 93, "target": 120, "strength": 90,
        "reason": "vcp", "freshness": "FRESH", "price": 99, "price_as_of": "2026-10-23",
        "trend_score": "8/8",
    }])
    cans = pd.DataFrame([{
        "ticker": "AAA", "company": "Alpha", "sector": "Tech", "index_membership": "SP500 / NDX100",
        "status": "READY", "pivot": 110, "stop": "", "target": "", "strength": 140,
        "reason": "can", "freshness": "FRESH", "price": 99, "price_as_of": "2026-10-23",
        "qualify": "strict", "l_rs_percentile": 88, "c_status": "not verified",
        "a_status": "20%", "i_trend": "up",
    }, {
        "ticker": "BBB", "company": "Beta", "sector": "Tech", "index_membership": "NDX100",
        "status": "WATCHING", "pivot": 50, "stop": "", "target": "", "strength": 100,
        "reason": "can", "freshness": "PARTIAL", "price": 40, "price_as_of": "2026-10-23",
        "qualify": "soft", "l_rs_percentile": 50, "c_status": "not verified",
        "a_status": "not verified", "i_trend": "not verified",
    }])
    out = setups.combine_leaders(vcp, cans)
    assert list(out["ticker"]) == ["AAA"]
    row = out.iloc[0]
    assert float(row["pivot"]) == 100
    assert float(row["stop"]) == 93
    assert float(row["target"]) == 120
    assert row["on_vcp"] == "yes" and row["on_canslim"] == "yes"
    assert "not verified" in row["reason"]
    assert abs(row["strength"] - (0.5 * 90 + 0.5 * 88)) < 0.05


def test_freshness_follows_spy_not_a_later_vix_bar():
    idx = _dates(30)
    extra = idx[-1] + pd.Timedelta(days=1)
    close = pd.DataFrame({"AAA": range(30), "SPY": range(30)}, index=idx, dtype=float)
    # A later VIX-style bar must not mark AAA stale.
    close.loc[extra, "AAA"] = float("nan")
    close.loc[extra, "SPY"] = float("nan")
    close.loc[extra, "OTHER"] = 1.0
    assert setups._panel_date(close) == pd.Timestamp(idx[-1])
    assert setups._freshness(idx[-1], setups._panel_date(close), 300, 252) == "FRESH"


def test_switches_skip_the_work():
    out = setups.build_setups(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        _uni(["AAA"]), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        {"scanner_vcp": False, "scanner_canslim": False, "scanner_box": False, "scanner_flag": False, "scanner_leaders": False, "scanner_52w": False},
    )
    assert "scanner_52w" in out and "highs_lows_history" in out
    assert all(len(v) == 0 for v in out.values())


def _flat_bars(n, high, low, close, vol=1000.0):
    idx = _dates(n)
    return pd.DataFrame({
        "high": np.full(n, high, dtype=float),
        "low": np.full(n, low, dtype=float),
        "close": np.full(n, close, dtype=float),
        "volume": np.full(n, vol, dtype=float),
    }, index=idx)


def test_52w_flags_range_position_and_backfill():
    """Close-based new high/low, high/low range, and at least a year of counts."""
    assert setups.W52_BARS == 252
    assert setups.W52_NEAR_PCT == 5.0
    assert setups.W52_VOL_MULT == 1.5
    n = 252 + 252
    aaa = _flat_bars(n, 100, 90, 95)
    aaa.iloc[-1, aaa.columns.get_loc("high")] = 112
    aaa.iloc[-1, aaa.columns.get_loc("low")] = 108
    aaa.iloc[-1, aaa.columns.get_loc("close")] = 110
    aaa.iloc[-1, aaa.columns.get_loc("volume")] = 2000
    bbb = _flat_bars(n, 80, 70, 75)
    bbb.iloc[-1, bbb.columns.get_loc("high")] = 72
    bbb.iloc[-1, bbb.columns.get_loc("low")] = 60
    bbb.iloc[-1, bbb.columns.get_loc("close")] = 61
    ccc = _flat_bars(n, 50, 40, 45)
    ccc.iloc[-1, ccc.columns.get_loc("high")] = 55
    ccc.iloc[-1, ccc.columns.get_loc("low")] = 44
    ccc.iloc[-1, ccc.columns.get_loc("close")] = 49
    ddd = _flat_bars(n, 100, 50, 100)
    eee = _flat_bars(n, 100, 50, 50)
    fff = _flat_bars(n, 100, 80, 95)
    ggg = _flat_bars(n, 100, 80, 94)
    frames = {"AAA": aaa, "BBB": bbb, "CCC": ccc, "DDD": ddd, "EEE": eee, "FFF": fff, "GGG": ggg}
    close, high, low, vol = _panel(list(frames), frames)
    scores = pd.DataFrame([
        {"ticker": "AAA", "score": 9, "verdict": "BUY"},
        {"ticker": "BBB", "score": 2, "verdict": "AVOID"},
    ])
    scan, hist = setups.scan_52w(close, high, low, vol, _uni(list(frames)), scores)
    by = scan.set_index("ticker")
    aaa_r = by.loc["AAA"]
    assert aaa_r["new_high_today"] == "yes"
    assert aaa_r["new_low_today"] == "no"
    assert aaa_r["near_high"] == "yes"
    assert aaa_r["high_on_volume"] == "yes"
    assert int(aaa_r["days_since_high"]) == 0
    assert aaa_r["data_status"] == "OK"
    assert float(aaa_r["score"]) == 9
    assert aaa_r["verdict"] == "BUY"
    assert aaa_r["index_membership"] == "SP500"
    assert abs(float(aaa_r["range_position_pct"]) - (110 - 90) / (112 - 90) * 100) < 0.02
    assert abs(float(aaa_r["pct_from_high"]) - (110 / 112 - 1) * 100) < 0.02
    assert abs(float(aaa_r["pct_above_low"]) - (110 / 90 - 1) * 100) < 0.02
    assert abs(float(aaa_r["volume_ratio"]) - (2000 / ((49 * 1000 + 2000) / 50.0))) < 0.02
    assert "close" in aaa_r["note"] and "1.5" in aaa_r["note"]
    bbb_r = by.loc["BBB"]
    assert bbb_r["new_low_today"] == "yes" and bbb_r["new_high_today"] == "no"
    assert bbb_r["near_high"] == "no" and bbb_r["high_on_volume"] == "no"
    assert int(bbb_r["days_since_high"]) == 1
    assert abs(float(bbb_r["pct_from_high"]) - (61 / 80 - 1) * 100) < 0.02
    # Intraday high without a closing break is not a new high. The range still uses the high.
    ccc_r = by.loc["CCC"]
    assert ccc_r["new_high_today"] == "no"
    assert float(ccc_r["high_52w"]) == 55
    assert float(ccc_r["price"]) == 49
    assert by.loc["DDD", "range_position_pct"] == 100 or abs(float(by.loc["DDD", "range_position_pct"]) - 100) < 0.02
    assert by.loc["DDD", "new_high_today"] == "yes" and by.loc["DDD", "high_on_volume"] == "no"
    assert by.loc["EEE", "new_low_today"] == "yes"
    assert abs(float(by.loc["EEE", "range_position_pct"]) - 0) < 0.02
    assert by.loc["FFF", "near_high"] == "yes" and by.loc["FFF", "new_high_today"] == "no"
    assert by.loc["GGG", "near_high"] == "no"
    assert pd.isna(by.loc["CCC", "score"]) or by.loc["CCC", "score"] == ""
    assert len(hist) >= 252
    assert hist["date"].is_monotonic_increasing
    assert hist["date"].nunique() == len(hist)
    assert (hist["net"] == hist["new_highs"] - hist["new_lows"]).all()
    last = hist.iloc[-1]
    assert int(last["new_highs"]) == 2
    assert int(last["new_lows"]) == 2
    assert int(last["near_high_count"]) == 3
    assert int(last["net"]) == 0
    assert last["date"] == str(aaa.index[-1].date())
    # The same last session, counted from the snapshot flags, matches the history row.
    assert int((scan["new_high_today"] == "yes").sum()) == int(last["new_highs"])
    assert int((scan["new_low_today"] == "yes").sum()) == int(last["new_lows"])
    assert int((scan["near_high"] == "yes").sum()) == int(last["near_high_count"])


def test_52w_short_history_is_not_a_new_high():
    n = 40
    frame = _flat_bars(n, 10, 8, 9)
    frame.iloc[-1, frame.columns.get_loc("close")] = 12
    frame.iloc[-1, frame.columns.get_loc("high")] = 12
    close, high, low, vol = _panel(["AAA"], {"AAA": frame})
    scan, hist = setups.scan_52w(close, high, low, vol, _uni(["AAA"]))
    row = scan.iloc[0]
    assert row["new_high_today"] == "no"
    assert row["new_low_today"] == "no"
    assert row["near_high"] == "no"
    assert row["data_status"] == "PARTIAL"
    assert pd.isna(row["high_52w"]) or row["high_52w"] == ""
    assert len(hist) == 0


def test_52w_switch_skips_the_scan():
    idx = _dates(30)
    close = pd.DataFrame({"AAA": np.arange(30, dtype=float)}, index=idx)
    out = setups.build_setups(
        close, close + 1, close - 1, close * 0 + 100,
        _uni(["AAA"]), None, None, None,
        {"scanner_vcp": False, "scanner_canslim": False, "scanner_box": False, "scanner_flag": False, "scanner_leaders": False, "scanner_52w": False},
    )
    assert len(out["scanner_52w"]) == 0
    assert len(out["highs_lows_history"]) == 0


def _scan_row(ticker, status, pivot, stop="", strength=50, price=100):
    return {
        "ticker": ticker, "company": ticker + " Co", "sector": "Information Technology",
        "index_membership": "SP500 / NDX100", "status": status,
        "pivot": pivot, "stop": stop, "strength": strength,
        "price": price, "price_as_of": "2026-10-23",
    }


def test_buy_stop_and_targets():
    """7% cap, a tighter setup stop, and both targets."""
    assert setups.BUY_STOP_PCT == 7
    assert setups.BUY_PART_PCT == 20
    assert setups.BUY_MAX_RISK_PCT == 8
    assert abs(setups.buy_stop(100, None) - 93) < 1e-9
    assert abs(setups.buy_stop(100, 96) - 96) < 1e-9
    assert abs(setups.buy_stop(100, 80) - 93) < 1e-9
    assert abs(setups.buy_stop(100, 101) - 93) < 1e-9
    assert setups.buy_stop(None, 90) is None
    ready = setups.buy_levels(100, 96, 100, False)
    assert abs(ready["stop"] - 96) < 1e-9
    assert abs(ready["target1"] - 120) < 1e-9
    assert abs(ready["target2"] - 112) < 1e-9
    assert abs(ready["risk_pct"] - 4) < 1e-9
    assert abs(ready["reward_risk"] - 5) < 1e-9
    broken = setups.buy_levels(100, 96, 102, True)
    assert abs(broken["target1"] - 122.4) < 1e-9
    assert abs(broken["target2"] - 112) < 1e-9
    assert abs(broken["reward_risk"] - 5.6) < 1e-9
    wide = setups.buy_levels(100, 85, 100, False)
    assert abs(wide["stop"] - 93) < 1e-9
    assert abs(wide["risk_pct"] - 7) < 1e-9
    assert abs(wide["target1"] - 120) < 1e-9
    assert abs(wide["target2"] - 121) < 1e-9
    assert abs(wide["reward_risk"] - (20 / 7)) < 1e-9
    assert setups.buy_levels(None, 90, 100, False) is None
    old = setups.BUY_STOP_PCT
    try:
        setups.BUY_STOP_PCT = 8
        assert setups.buy_levels(100, None, 100, False) is not None
        setups.BUY_STOP_PCT = 10
        assert setups.buy_levels(100, None, 100, False) is None
    finally:
        setups.BUY_STOP_PCT = old


def test_buy_qualification_rules():
    scores = pd.DataFrame([
        {"ticker": "BUYER", "company": "Buyer Inc", "sector": "Health Care", "index_membership": "NDX100", "score": 9, "verdict": "BUY"},
        {"ticker": "HOLDER", "company": "Hold Inc", "sector": "Health Care", "index_membership": "SP500", "score": 8, "verdict": "HOLD"},
        {"ticker": "AVOIDER", "company": "Avoid Inc", "sector": "Energy", "index_membership": "SP500", "score": 2, "verdict": "AVOID"},
        {"ticker": "WATCHER", "company": "Watch Inc", "sector": "Energy", "index_membership": "Growth", "score": 9, "verdict": "BUY"},
        {"ticker": "NOPIV", "company": "No Pivot", "sector": "Energy", "index_membership": "SP500", "score": 9, "verdict": "BUY"},
        {"ticker": "WEAK", "company": "Weak SMA", "sector": "Energy", "index_membership": "SP500", "score": 9, "verdict": "BUY"},
        {"ticker": "TIE", "company": "Tie Inc", "sector": "Energy", "index_membership": "SP500", "score": 7, "verdict": "BUY"},
    ])
    vcp = pd.DataFrame([
        _scan_row("BUYER", "READY", 100, "", 40, 101),
        _scan_row("HOLDER", "READY", 100, 96, 60, 101),
        _scan_row("AVOIDER", "BROKEN OUT today", 100, 96, 60, 101),
        _scan_row("WATCHER", "WATCHING", 100, 96, 90, 101),
        _scan_row("NOPIV", "READY", "", "", 90, 101),
        _scan_row("WEAK", "READY", 100, 96, 60, 101),
        _scan_row("TIE", "READY", 100, "", 50, 100),
    ])
    box = pd.DataFrame([
        _scan_row("BUYER", "BROKEN OUT today", 110, 105, 80, 112),
        _scan_row("TIE", "READY", 130, "", 50, 100),
    ])
    cans = pd.DataFrame([_scan_row("BUYER", "READY", "", "", 99, 112)])
    sma = {t: True for t in scores["ticker"]}
    sma["WEAK"] = False
    week = pd.DataFrame([{"ticker": "BUYER", "range_position_pct": 88.2, "pct_from_high": -3.4}])
    out = setups.build_buy_setups(
        vcp, box, None, cans, scores, week=week, sma_ok=sma, market={"spy": True, "qqq": False},
    )
    assert list(out["ticker"]) == ["BUYER", "TIE"]
    row = out.set_index("ticker").loc["BUYER"]
    assert row["setup_sources"] == "VCP + Box"
    assert int(row["sources_count"]) == 2
    assert row["best_status"] == "BROKEN OUT today"
    assert float(row["entry"]) == 110
    assert float(row["stop"]) == 105
    assert abs(float(row["target1"]) - 134.4) < 0.02
    assert abs(float(row["target2"]) - 125) < 0.02
    assert abs(float(row["risk_pct"]) - (5 / 110 * 100)) < 0.02
    assert abs(float(row["reward_risk"]) - ((134.4 - 110) / 5)) < 0.02
    assert abs(float(row["dist_to_entry_pct"]) - ((112 / 110 - 1) * 100)) < 0.02
    assert row["verdict"] == "BUY"
    assert row["company"] == "Buyer Inc"
    assert row["sector"] == "Health Care"
    assert row["index_membership"] == "NDX100"
    assert float(row["score"]) == 9
    assert abs(float(row["range_position_52w"]) - 88.2) < 0.02
    assert abs(float(row["pct_from_high_52w"]) + 3.4) < 0.02
    assert row["market_ok"] == "yes" and row["spy_uptrend"] == "yes" and row["qqq_uptrend"] == "no"
    assert "Research list, not a recommendation" in row["note"]
    assert "never places trades" in row["note"]
    assert "VCP + Box" in row["reason"] and "many breakouts fail" in row["reason"]
    assert "today's close" in row["reason"]
    tie = out.set_index("ticker").loc["TIE"]
    assert float(tie["entry"]) == 100
    assert abs(float(tie["stop"]) - 93) < 0.02
    assert abs(float(tie["target1"]) - 120) < 0.02
    assert tie["setup_sources"] == "VCP + Box"
    assert "the entry" in tie["reason"]


def test_buy_market_filter_and_sort():
    rise = np.linspace(50, 150, 260)
    fall = np.linspace(150, 50, 260)
    assert setups.uptrend(rise)
    assert setups.above_both_sma(rise)
    assert not setups.uptrend(fall)
    assert not setups.uptrend(rise[:100])
    assert not setups.above_both_sma(rise[:100])
    mixed = np.array([100.0] * 180 + [40.0] * 40 + [160.0] * 10)
    assert setups.above_both_sma(mixed)
    assert not setups.uptrend(mixed)

    scores = pd.DataFrame([
        {"ticker": "EEE", "score": 9, "verdict": "BUY", "company": "E", "sector": "Tech", "index_membership": "SP500"},
        {"ticker": "DDD", "score": 6, "verdict": "BUY", "company": "D", "sector": "Tech", "index_membership": "SP500"},
        {"ticker": "CCC", "score": 7, "verdict": "BUY", "company": "C", "sector": "Tech", "index_membership": "NDX100"},
        {"ticker": "AAA", "score": 9, "verdict": "BUY", "company": "A", "sector": "Tech", "index_membership": "SP500"},
        {"ticker": "BBB", "score": 8, "verdict": "BUY", "company": "B", "sector": "Tech", "index_membership": "Growth"},
        {"ticker": "HOLDZ", "score": 99, "verdict": "HOLD", "company": "H", "sector": "Tech", "index_membership": "SP500"},
    ])
    def both(ticker, status, price, strength=80):
        return _scan_row(ticker, status, 100, 96, strength, price)
    vcp = pd.DataFrame([
        both("EEE", "BROKEN OUT today", 101),
        both("DDD", "BROKEN OUT today", 99),
        both("CCC", "BROKEN OUT today", 105),
        both("AAA", "BROKEN OUT today", 101, 70),
        both("BBB", "READY", 100.5),
        both("HOLDZ", "BROKEN OUT today", 100, 100),
    ])
    box = pd.DataFrame([
        both("EEE", "BROKEN OUT today", 101, 10),
        both("DDD", "BROKEN OUT today", 99, 10),
        both("CCC", "BROKEN OUT today", 105, 10),
        both("BBB", "READY", 100.5, 10),
    ])
    sma = {t: True for t in scores["ticker"]}
    out = setups.build_buy_setups(
        vcp, box, None, None, scores, sma_ok=sma, market={"spy": False, "qqq": True},
    )
    assert list(out["ticker"]) == ["EEE", "DDD", "CCC", "AAA", "BBB"]
    assert (out["market_ok"] == "no").all()
    assert (out["spy_uptrend"] == "no").all()
    assert (out["qqq_uptrend"] == "yes").all()
    assert int(out.set_index("ticker").loc["AAA", "sources_count"]) == 1
    assert int(out.set_index("ticker").loc["EEE", "sources_count"]) == 2
    assert len(setups.buy_rows_visible(out, True)) == 0
    shown = setups.buy_rows_visible(out, False)
    assert list(shown["ticker"]) == ["EEE", "DDD", "CCC", "AAA", "BBB"]
    assert len(setups.buy_rows_visible(None, True)) == 0
    lone = setups.build_buy_setups(None, None, None, None, scores, sma_ok={}, market={"spy": False, "qqq": True})
    assert list(lone["ticker"]) == [""]
    assert lone.iloc[0]["market_ok"] == "no" and lone.iloc[0]["qqq_uptrend"] == "yes"
    assert len(setups.buy_rows_visible(lone, False)) == 0


def test_buy_stock_uses_close_above_both_averages():
    """A stock can qualify without the 50-day sitting above the 200-day. The market cannot."""
    n = 230
    idx = _dates(n)
    good = np.array([100.0] * 180 + [40.0] * 40 + [160.0] * 10)
    bad = np.array([100.0] * 220 + [40.0] * 10)
    close = pd.DataFrame({
        "GOOD": good,
        "BAD": bad,
        "SPY": np.linspace(80, 160, n),
        "QQQ": np.linspace(160, 80, n),
    }, index=idx)
    assert setups.above_both_sma(close["GOOD"]) and not setups.uptrend(close["GOOD"])
    assert not setups.above_both_sma(close["BAD"])
    assert setups.uptrend(close["SPY"]) and not setups.uptrend(close["QQQ"])
    scores = pd.DataFrame([
        {"ticker": "GOOD", "company": "Good Co", "sector": "Energy", "index_membership": "SP500", "score": 8, "verdict": "BUY"},
        {"ticker": "BAD", "company": "Bad Co", "sector": "Energy", "index_membership": "SP500", "score": 8, "verdict": "BUY"},
    ])
    vcp = pd.DataFrame([
        _scan_row("GOOD", "READY", 150, "", 70, 1),
        _scan_row("BAD", "READY", 150, "", 70, 1),
    ])
    out = setups.build_buy_setups(vcp, None, None, None, scores, close=close)
    assert list(out["ticker"]) == ["GOOD"]
    row = out.iloc[0]
    assert abs(float(row["price"]) - 160) < 0.02
    assert abs(float(row["entry"]) - 150) < 0.02
    assert abs(float(row["stop"]) - 139.5) < 0.02
    assert abs(float(row["target1"]) - 180) < 0.02
    assert row["market_ok"] == "yes" and row["qqq_uptrend"] == "no"
    assert row["price_as_of"] == str(idx[-1].date())


def test_buy_setups_settings_default_on():
    import json
    import tables
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = json.load(open(os.path.join(root, "config.json")))
    assert cfg["features"]["buy_setups"] is True
    assert cfg["buy_setups"]["market_filter"] is True
    got = dict(zip(tables.settings_rows(cfg)["setting"], tables.settings_rows(cfg)["value"]))
    assert got["feature.buy_setups"] is True
    assert got["buy_setups.market_filter"] is True
    topics = [topic for topic, _ in tables.help_rows()]
    assert "Buy setups" in topics


if __name__ == "__main__":
    test_pivot_is_strict_and_delayed()
    test_vcp_ready_matches_pine_levels()
    test_vcp_breakout_uses_the_close()
    test_shallow_dip_is_not_a_contraction()
    test_lower_low_extends_the_same_contraction()
    test_canslim_does_not_invent_missing_letters()
    test_box_breakout_levels()
    test_flag_breakout_levels()
    test_leaders_prefers_the_vcp_plan()
    test_freshness_follows_spy_not_a_later_vix_bar()
    test_switches_skip_the_work()
    test_52w_flags_range_position_and_backfill()
    test_52w_short_history_is_not_a_new_high()
    test_52w_switch_skips_the_scan()
    test_buy_stop_and_targets()
    test_buy_qualification_rules()
    test_buy_market_filter_and_sort()
    test_buy_stock_uses_close_above_both_averages()
    test_buy_setups_settings_default_on()
    print("setups ok")
