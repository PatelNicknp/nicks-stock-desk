"""Offline checks for the Qullamaggie and Marios breakout scans. Synthetic tapes on fixed dates only, no downloads, no clock."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import setups  # noqa: E402


def _tape(today="breakout", after=None, ready_close=None, bo=None, first_half_low=None):
    """120 quiet bars near 100, a 50% run in 30 bars, a 20-bar base with higher lows and drying volume, then today.

    today: "breakout" (high crosses the base high) or "ready" (closes under it).
    after: (open, high, low, close) bars added after today.
    bo: (open_offset, high_offset, low_offset, close_offset) for the breakout bar, relative to the base high.
    """
    o, h, l, c, v = [], [], [], [], []

    def bar(cl, w, vol=1_000_000.0):
        c.append(cl); h.append(cl * (1 + w)); l.append(cl * (1 - w)); o.append(cl); v.append(vol)

    for i in range(120):
        bar(100.0 + 0.5 * np.sin(i), 0.025)
    for px in np.linspace(101, 150, 30):
        bar(px, 0.025)
    for i in range(10):
        bar(148.0 + i * 0.2, 0.03)
    for i in range(10):
        bar(150.0 + i * 0.1, 0.012, vol=600_000.0 if i >= 5 else 1_000_000.0)
    if first_half_low is not None:
        l[-15] = first_half_low  # a deep low late in the base, so the second half has the lower low
    pivot = max(h[-24:])
    if today == "breakout":
        oo, hh, ll, cc = bo or (0.5, 6.0, -1.0, 5.0)
        o.append(pivot + oo); h.append(pivot + hh); l.append(pivot + ll); c.append(pivot + cc); v.append(2_000_000.0)
    else:
        cl = ready_close if ready_close is not None else pivot - 2.0
        o.append(cl); h.append(min(cl + 1.0, pivot - 0.01)); l.append(cl - 1.0); c.append(cl); v.append(700_000.0)
    for bar_ in (after or []):
        o.append(bar_[0]); h.append(bar_[1]); l.append(bar_[2]); c.append(bar_[3]); v.append(1_000_000.0)
    idx = pd.bdate_range("2025-01-01", periods=len(c))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx), pivot


def _scan(frame, marios=False, cfg=None, others=None, scores=None):
    names = ["AAA"] + list((others or {}).keys())
    uni = pd.DataFrame([{"ticker": t, "company": t + " Co", "sector": "Industrials", "index_membership": "SP500"} for t in names])

    def wide(col):
        d = frame[[col]].rename(columns={col: "AAA"})
        for t, f in (others or {}).items():
            d[t] = f[col].reindex(d.index)
        return d
    fn = setups.scan_marios if marios else setups.scan_qullamaggie
    out = fn(wide("close"), wide("high"), wide("low"), wide("volume"), uni, cfg, opn=wide("open"), scores=scores)
    return out[out["ticker"] == "AAA"] if len(out) else out


def _row(frame, **kw):
    out = _scan(frame, **kw)
    assert len(out) == 1, out
    return out.iloc[0]


# Entry

def test_day_high_trigger_fill_and_stop():
    frame, pivot = _tape()
    row = _row(frame)
    assert row["status"] == "BROKEN OUT today"
    assert abs(float(row["pivot"]) - round(pivot, 2)) < 1e-9
    assert abs(float(row["entry"]) - round(pivot + 0.5, 2)) < 1e-9  # opened above the base high, so fill is the open
    assert abs(float(row["stop"]) - round(pivot - 1.0, 2)) < 1e-9  # the day's low
    assert row["confirmed_close"] == "yes"
    assert row["volume_flag"] == "yes"
    assert row["higher_lows"] == "yes"


def test_fill_is_the_pivot_when_it_opens_below():
    frame, pivot = _tape(bo=(-2.0, 3.0, -2.5, -0.5))
    row = _row(frame)
    assert row["status"] == "BROKEN OUT today"
    assert abs(float(row["entry"]) - round(pivot, 2)) < 1e-9
    assert row["confirmed_close"] == "no"


def test_no_trigger_when_yesterday_already_crossed():
    frame, pivot = _tape(after=[(0, 0, 0, 0)])
    # Make the new bar another day above the pivot: yesterday's high was already over it.
    frame.iloc[-1] = [pivot + 6.0, pivot + 8.0, pivot + 5.5, pivot + 7.5, 1_000_000.0]
    row = _row(frame)
    assert row["status"] != "BROKEN OUT today"


def test_low_volume_breakout_still_counts_but_ranks_lower():
    frame, _ = _tape()
    frame.iloc[-1, frame.columns.get_loc("volume")] = 900_000.0
    row = _row(frame)
    assert row["status"] == "BROKEN OUT today"
    assert row["volume_flag"] == "no"
    assert float(row["strength"]) < float(_row(_tape()[0])["strength"])


def test_ready_within_one_adr():
    frame, pivot = _tape(today="ready", ready_close=None)
    row = _row(frame)
    assert row["status"] == "READY"
    frame, pivot = _tape(today="ready", ready_close=pivot * 0.88)
    out = _scan(frame)
    assert len(out) == 0 or out.iloc[0]["status"] != "READY"


# Gates

def test_higher_lows_rule_and_switch():
    frame, _ = _tape(first_half_low=None)
    assert _row(frame)["status"] == "BROKEN OUT today"
    frame, _ = _tape(first_half_low=None)
    # A lower low in the second half of the base breaks the rule.
    frame.iloc[-5, frame.columns.get_loc("low")] = 140.0
    out = _scan(frame)
    assert len(out) == 0 or out.iloc[0]["status"] != "BROKEN OUT today"
    off = {"qullamaggie": {"higher_lows": False, "base_range_cap": False, "base_start_upper": False, "tighten_check": False}}
    assert _row(frame, cfg=off)["status"] == "BROKEN OUT today"


def test_leader_gate_needs_top_three_percent():
    frame, _ = _tape()
    # 40 stocks that all ran harder push AAA out of the top 3% on every window.
    others = {}
    for i in range(40):
        f = frame.copy()
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(np.linspace(1, 3 + i * 0.01, len(f)), axis=0)
        others["S%02d" % i] = f
    assert len(_scan(frame, others=others)) == 0
    row = _row(frame, others=others, cfg={"qullamaggie": {"leader_gate": False}})
    assert row["status"] == "BROKEN OUT today"
    assert float(row["leader_top_pct"]) > 3.0


def test_adr_and_price_gates():
    frame, _ = _tape()
    assert len(_scan(frame, cfg={"qullamaggie": {"adr_min_pct": 9.0}})) == 0
    assert len(_scan(frame, cfg={"qullamaggie": {"min_price": 500.0}})) == 0
    assert len(_scan(frame, cfg={"qullamaggie": {"min_price": 500.0, "price_filter": False}})) == 1


def test_traded_value_switch_defaults_off():
    frame, _ = _tape()
    row = _row(frame)
    # About 160 dollars times about 1 million shares a day: roughly $150 million, shown in $ millions.
    assert 50 < float(row["traded_value_usd_m"]) < 300
    assert len(_scan(frame, cfg={"qullamaggie": {"traded_value_gate": True, "min_traded_value_usd": 1e9}})) == 0
    assert len(_scan(frame, cfg={"qullamaggie": {"traded_value_gate": True, "min_traded_value_usd": 1e6}})) == 1
    assert "price_band" not in row.index


def test_prior_run_needed():
    frame, _ = _tape()
    assert len(_scan(frame, cfg={"qullamaggie": {"run_min_pct": 90}})) == 0


def test_desk_base_rules_are_switches():
    frame, _ = _tape()
    assert len(_scan(frame, cfg={"qullamaggie": {"base_max_range_pct": 1.0}})) == 0
    assert len(_scan(frame, cfg={"qullamaggie": {"base_max_range_pct": 1.0, "base_range_cap": False}})) == 1


# Stop cap

def test_stop_cap_too_wide_and_a_plus():
    frame, _ = _tape()
    assert _row(frame)["stop_check"] == "A+"
    wide, pivot = _tape(bo=(0.5, 6.0, -12.0, 5.0))
    row = _row(wide)
    assert row["status"] == "BROKEN OUT today"
    assert row["stop_check"] == "Too wide, skip"
    assert float(row["stop_adr"]) > 1.0
    assert _row(wide, cfg={"qullamaggie": {"stop_cap": False}})["stop_check"] == "OK"


def test_too_wide_is_left_out_of_buy_setups():
    empty = pd.DataFrame()

    def rec(t, check):
        return {"ticker": t, "status": "BROKEN OUT today", "pivot": 100.0, "stop": 97.0, "strength": 60, "stop_check": check,
                "company": t, "sector": "Tech", "index_membership": "SP500", "price": 101, "price_as_of": "2026-10-29"}
    qm = pd.DataFrame([rec("GOOD", "A+"), rec("WIDE", "Too wide, skip"), dict(rec("OLD", "OK"), status="IN TRADE")])
    scores = pd.DataFrame([{"ticker": t, "verdict": "BUY", "score": 9} for t in ("GOOD", "WIDE", "OLD")])
    out = setups.build_buy_setups(empty, empty, empty, empty, scores, sma_ok={"GOOD": True, "WIDE": True, "OLD": True},
                                  market={"spy": True, "qqq": True}, qullamaggie=qm, marios=qm)
    assert list(out["ticker"]) == ["GOOD"]
    assert float(out.iloc[0]["risk_pct"]) <= 8.0


# Exits and the trade record

def _qm_after(pivot, closes):
    return [(c, c + 1.0, c - 1.0, c) for c in closes]


def test_qullamaggie_partial_breakeven_then_trail_exit():
    _, pivot = _tape()
    frame, _ = _tape(after=_qm_after(pivot, [pivot + 6, pivot + 8, pivot + 10]))
    row = _row(frame)
    assert row["status"] == "IN TRADE"
    assert row["partial_flag"] == "Sell 1/3 to 1/2"
    assert row["stop_basis"] == "breakeven"
    assert abs(float(row["stop"]) - float(row["entry"])) < 1e-9
    down = [pivot + 6, pivot + 8, pivot + 10, pivot + 11, pivot + 12, pivot + 4]
    frame, _ = _tape(after=[(c, c + 1.0, c - 0.5, c) for c in down])
    row = _row(frame)
    assert row["status"] == "CLOSED"
    assert "10-day" in row["exit_reason"]
    assert row["exit_date"] == str(frame.index[-1].date())


def _between_10_and_20(after):
    """A close that lands under the 10-day but above the 20-day on the new bar."""
    for c in np.linspace(175, 140, 351):
        frame, _ = _tape(after=after + [(c, c + 0.5, c - 0.2, c)])
        s10 = frame["close"].rolling(10).mean().iloc[-1]
        s20 = frame["close"].rolling(20).mean().iloc[-1]
        if s20 < c < s10:
            return frame
    raise AssertionError("no close between the averages")


def test_qullamaggie_sma20_switch():
    up = [(c, c + 1.0, c - 0.5, c) for c in (160, 162, 164, 165, 166, 168, 170)]
    frame = _between_10_and_20(up)
    row = _row(frame)
    assert row["status"] == "CLOSED"
    assert "10-day" in row["exit_reason"]
    row = _row(frame, cfg={"qullamaggie": {"trail_use_sma20": True}})
    assert row["status"] == "IN TRADE"
    assert row["trail_with"] == "20-day"


def test_closed_on_stop_with_reason_and_date():
    frame, _ = _tape(after=[(157.0, 157.5, 147.0, 149.0)])
    row = _row(frame)
    assert row["status"] == "CLOSED"
    assert "low" in row["exit_reason"]
    assert row["exit_date"] == str(frame.index[-1].date())
    assert "CLOSED on" in row["reason"]


def test_marios_partial_at_adr_then_ladder():
    frame, pivot = _tape()
    b = _row(frame, marios=True)
    lo, hi = float(b["target_low"]), float(b["target_high"])
    assert hi > lo > float(b["entry"])
    up = [(pivot + 6, lo + 1.0, pivot + 5, lo - 1.0)]
    row = _row(_tape(after=up)[0], marios=True)
    assert row["status"] == "IN TRADE"
    assert row["partial_hit"] == "yes"
    assert row["stop_basis"] == "breakeven"
    # A close under the 20-day ends the trade.
    frame3, _ = _tape(after=up + [(pivot + 1, pivot + 1.5, pivot + 0.6, pivot + 0.7), (pivot + 0.7, pivot + 0.8, 140.0, 141.0)])
    row = _row(frame3, marios=True)
    assert row["status"] == "CLOSED"


def test_marios_sell_third_signal():
    frame, pivot = _tape()
    up = [(pivot + 6, pivot + 8, pivot + 5.5, pivot + 7)] + [(c, c + 0.5, c - 0.5, c) for c in np.linspace(pivot + 7, pivot + 12, 8)]
    f1, _ = _tape(after=up)
    r1 = _row(f1, marios=True)
    t10, t20 = float(r1["trail10"]), float(r1["trail20"])
    assert t10 > t20
    c = t20 + (t10 - t20) * 0.3
    f2, _ = _tape(after=up + [(c + 0.3, c + 0.5, max(c - 0.3, float(r1["stop"]) + 0.01), c)])
    r2 = _row(f2, marios=True)
    assert r2["status"] == "IN TRADE"
    assert r2["trail_signal"] == "SELL 1/3"
    assert r2["sold_third_date"] == str(f2.index[-1].date())


def test_marios_weak_day_one_close():
    frame, pivot = _tape(bo=(0.5, 6.0, -1.0, 0.6))
    assert _row(frame, marios=True)["weak_close"] == "yes"
    frame, pivot = _tape()
    assert _row(frame, marios=True)["weak_close"] == "no"


def test_marios_settings_differ():
    p = setups._marios_cfg(None)
    q = setups._qm_cfg(None)
    assert p["adr_min_pct"] == 2.5 and q["adr_min_pct"] == 3.5
    assert p["run_lookback_max"] == 126 and q["run_lookback_max"] == 63
    assert p["volume_dry_up_gate"] is True and q["volume_dry_up_gate"] is False
    assert not hasattr(setups, "marios_trail_len")


def test_display_cap():
    after = [(c, c + 1.0, c - 0.5, c) for c in np.linspace(160, 220, 70)]
    frame, _ = _tape(after=after)
    out = _scan(frame)
    assert len(out) == 0 or out.iloc[0]["status"] not in ("IN TRADE", "CLOSED")


def test_track_trades_switch():
    frame, pivot = _tape(after=[(c, c + 1.0, c - 1.0, c) for c in (160, 162, 164)])
    assert _row(frame)["status"] == "IN TRADE"
    out = _scan(frame, cfg={"qullamaggie": {"track_trades": False}})
    assert len(out) == 0 or out.iloc[0]["status"] != "IN TRADE"


# Context columns

def test_adr_target_math():
    high = np.full(20, 105.0)
    low = np.full(20, 100.0)
    assert abs(setups.marios_adr_pct(high, low, 20) - 5.0) < 1e-9
    lo, hi = setups.marios_targets(200.0, 4.0, 2.5, 3.0)
    assert abs(lo - 220.0) < 1e-9 and abs(hi - 224.0) < 1e-9
    assert setups.marios_adr_pct(high[:5], low[:5], 20) is None


def test_sizing_and_cap():
    p = setups._qm_cfg(None)
    s = setups._sizing(100.0, 98.0, p)  # 5000 risk / 2 = 2500 shares, cap 25% = 2500 shares
    assert s["shares"] == 2500
    s = setups._sizing(100.0, 99.5, p)
    assert s["shares"] == 2500 and s["position_pct"] == 25.0
    s = setups._sizing(100.0, 90.0, p)
    assert s["shares"] == 500


def test_earnings_flag_and_market_light():
    frame, _ = _tape()
    nxt = pd.bdate_range(frame.index[-1], periods=3)[-1]
    row = _row(frame, scores=pd.DataFrame([{"ticker": "AAA", "next_earnings": str(nxt.date())}]))
    assert row["earnings_soon"] == "yes"
    close = pd.DataFrame({"SPY": np.linspace(100, 130, 80), "QQQ": np.linspace(100, 130, 80)})
    light, text = setups.qm_market_light(close, setups._qm_cfg(None))
    assert light == "green" and "SPY" in text and "QQQ" in text
    close["QQQ"] = np.linspace(130, 100, 80)
    light, text = setups.qm_market_light(close, setups._qm_cfg(None))
    assert light == "yellow"
    close["SPY"] = np.linspace(130, 100, 80)
    assert setups.qm_market_light(close, setups._qm_cfg(None))[0] == "red"


def test_switches_turn_the_scans_off():
    out = setups.build_setups(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        pd.DataFrame([{"ticker": "AAA"}]), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        {"scanner_vcp": False, "scanner_canslim": False, "scanner_box": False, "scanner_flag": False,
         "scanner_leaders": False, "scanner_52w": False, "scanner_breakdown": False, "scanner_volume": False,
         "scanner_qullamaggie": False, "scanner_marios": False},
    )
    assert len(out["scanner_qullamaggie"]) == 0 and len(out["scanner_marios"]) == 0


def test_config_has_every_switch_and_number():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["features"]["scanner_qullamaggie"] is True
    assert cfg["features"]["scanner_marios"] is True
    for k, v in setups.QM_DEFAULTS.items():
        assert cfg["qullamaggie"][k] == v, k
    for k, v in setups.MARIOS_DEFAULTS.items():
        assert cfg["marios"][k] == v, k
    assert cfg["qullamaggie"]["traded_value_gate"] is False
    assert "price_band_flag" not in cfg["qullamaggie"] and "min_traded_value_cr" not in cfg["qullamaggie"]
    assert cfg["qullamaggie"]["leader_top_pct"] == 3.0


def test_chart_lines_and_buy_order():
    frame, _ = _tape()
    row = _row(frame)
    assert float(row["trail10"]) > 0 and float(row["trail20"]) > 0
    order = setups.BUY_SETUP_ORDER
    assert order.index("Qullamaggie") < order.index("Marios") < order.index("CANSLIM")


if __name__ == "__main__":
    names = sorted(k for k, v in list(globals().items()) if k.startswith("test_") and callable(v))
    for name in names:
        globals()[name]()
    print("qullamaggie and marios ok (%d tests)" % len(names))
