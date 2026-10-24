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
        {"scanner_vcp": False, "scanner_canslim": False, "scanner_box": False, "scanner_flag": False, "scanner_leaders": False},
    )
    assert all(len(v) == 0 for v in out.values())


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
    print("setups ok")
