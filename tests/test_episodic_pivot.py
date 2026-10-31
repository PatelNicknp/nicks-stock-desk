"""Offline checks for the Episodic Pivot scan. Synthetic tapes on fixed dates, a fixed 'now' when needed, no downloads, no clock."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import episodic_pivot as ep  # noqa: E402
import setups  # noqa: E402

START = "2025-01-01"


def _tape(ep_bar=(56.0, 58.0, 55.0, 57.5, 4_000_000.0), after=None, quiet=150):
    """Quiet bars near 50 (2% range, 1M shares), one EP bar (open, high, low, close, volume), then `after` bars."""
    o, h, l, c, v = [], [], [], [], []
    for i in range(quiet):
        px = 50.0 + 0.3 * np.sin(i / 3.0)
        o.append(px); h.append(px * 1.02); l.append(px * 0.98); c.append(px); v.append(1_000_000.0)
    c[-1] = 50.0
    if ep_bar is not None:
        o.append(ep_bar[0]); h.append(ep_bar[1]); l.append(ep_bar[2]); c.append(ep_bar[3]); v.append(ep_bar[4])
    for b in (after or []):
        o.append(b[0]); h.append(b[1]); l.append(b[2]); c.append(b[3]); v.append(b[4] if len(b) > 4 else 1_500_000.0)
    idx = pd.bdate_range(START, periods=len(c))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def _scan(frame, cfg=None, earnings=None, info=None, now_et=None, quarters=None):
    uni = pd.DataFrame([{"ticker": "AAA", "company": "AAA Co", "sector": "Industrials", "index_membership": "SP500"}])
    w = lambda col: frame[[col]].rename(columns={col: "AAA"})
    return ep.scan_ep(w("close"), w("high"), w("low"), w("volume"), w("open"), uni, cfg,
                      earnings=earnings, quarters=quarters, info=info, now_et=now_et)


def _row(frame, **kw):
    out = _scan(frame, **kw)
    assert len(out) == 1, out
    return out.iloc[0]


def _day(frame, i):
    return frame.index[i]


# Detection

def test_confirmed_ep_levels_and_buy_flag():
    row = _row(_tape())
    assert row["status"] == "EP TODAY - CONFIRMED"
    assert abs(float(row["gap_pct"]) - 12.0) < 1e-9
    assert float(row["rvol"]) >= 3.0
    assert float(row["entry"]) == 58.0 and float(row["stop"]) == 55.0
    assert row["entry_basis"] == "EP-day high" and row["stop_basis"] == "EP-day low"
    assert row["stop_check"] == "OK" and float(row["risk_vs_adr"]) <= 1.5
    assert row["buy_status"] == "READY"
    assert row["catalyst_tag"] == "Non-earnings - check news"
    assert "Check the news" in row["reason"] or "check the news" in row["reason"]


def test_small_gap_or_low_volume_is_not_an_ep():
    assert len(_scan(_tape(ep_bar=(54.0, 56.0, 53.5, 55.5, 4_000_000.0)))) == 0  # 8% gap
    assert len(_scan(_tape(ep_bar=(56.0, 58.0, 55.0, 57.5, 2_000_000.0)))) == 0  # 2x volume
    # Stockbee close-to-close switch: an 8% gap that closes up 11% counts when sb_close_change_pct is 8.
    f = _tape(ep_bar=(54.0, 56.0, 53.5, 55.5, 4_000_000.0))
    assert _row(f, cfg={"episodic_pivot": {"sb_close_change_pct": 8}})["status"] == "EP TODAY - CONFIRMED"


def test_faded_close_is_not_a_buy():
    row = _row(_tape(ep_bar=(56.0, 58.0, 54.0, 54.5, 4_000_000.0)))
    assert row["status"] == "EP FADED"
    assert row["buy_status"] == ""


def test_forming_uses_pace_and_the_early_volume_test():
    f = _tape(ep_bar=(56.0, 57.0, 55.5, 56.8, 1_200_000.0))
    today = f.index[-1]
    at_1020 = pd.Timestamp(today.date()).tz_localize("America/New_York") + pd.Timedelta(hours=10, minutes=20)
    row = _row(f, now_et=at_1020)
    assert row["status"] == "EP TODAY - FORMING"
    assert row["buy_status"] == ""
    assert row["stop_basis"] == "today's low so far"
    # Early test off: 1.2M shares by 10:20 is a pace of 6x (20% of a day expected), still forming.
    assert _row(f, now_et=at_1020, cfg={"episodic_pivot": {"early_volume_test": False}})["status"] == "EP TODAY - FORMING"
    # Early test alone (pace bar raised out of reach) passes only in the first run window.
    hard = {"episodic_pivot": {"rvol_min": 50}}
    assert _row(f, now_et=at_1020, cfg=hard)["status"] == "EP TODAY - FORMING"
    assert len(_scan(f, now_et=at_1020 + pd.Timedelta(hours=1), cfg=hard)) == 0
    # At 14:20, 1.2M shares is only about 1.9x pace and the early window is over: no row.
    at_1420 = at_1020 + pd.Timedelta(hours=4)
    assert len(_scan(f, now_et=at_1420)) == 0
    # Under the open while forming: no row.
    g = _tape(ep_bar=(56.0, 57.0, 55.0, 55.5, 1_200_000.0))
    assert len(_scan(g, now_et=at_1020)) == 0 or _row(g, now_et=at_1020)["status"] != "EP TODAY - FORMING"


def test_time_helpers_take_a_fixed_time():
    curve = ep.EP_DEFAULTS["volume_curve"]
    t = pd.Timestamp("2026-10-29 10:20", tz="America/New_York")
    assert ep.volume_share(t, curve) == 0.20
    assert ep.volume_share(pd.Timestamp("2026-10-29 15:30", tz="America/New_York"), curve) == 0.75
    assert ep.bar_is_partial(pd.Timestamp("2026-10-29"), t)
    assert not ep.bar_is_partial(pd.Timestamp("2026-10-29"), pd.Timestamp("2026-10-29 16:05", tz="America/New_York"))
    assert not ep.bar_is_partial(pd.Timestamp("2026-10-28"), t)
    assert not ep.bar_is_partial(pd.Timestamp("2026-10-29"), None)


# Watch, trigger, and the trade

def test_day_two_to_five_watch():
    row = _row(_tape(after=[(57.4, 57.9, 56.5, 57.2), (57.2, 57.8, 56.6, 57.5)]))
    assert row["status"] == "DAY 2-5 WATCH"
    assert row["buy_status"] == "READY"
    assert int(row["days_since_ep"]) == 2


def test_trigger_partial_breakeven_and_trail():
    after = [(57.5, 58.6, 57.2, 58.4), (58.5, 59.5, 58.2, 59.3), (59.3, 60.5, 59.0, 60.3), (60.3, 61.5, 60.0, 61.2)]
    row = _row(_tape(after=after))
    assert row["status"] == "IN TRADE"
    assert float(row["fill"]) == 58.0
    assert int(row["days_in_trade"]) == 3
    assert row["signal"] == "SELL PART"
    assert row["stop_basis"] == "breakeven" and float(row["stop"]) == 58.0
    assert row["buy_status"] == ""
    # The first close under the trail average after the partial ends it (10-day here, by lowering trail_fast_adr_pct).
    up = after + [(61.0 + k, 62.0 + k, 60.5 + k, 61.5 + k) for k in range(12)]
    fast = {"episodic_pivot": {"trail_fast_adr_pct": 3}}
    row = _row(_tape(after=up), cfg=fast)
    assert row["status"] == "IN TRADE" and row["trail_with"] == "10-day"
    row = _row(_tape(after=up + [(70.0, 70.2, 63.5, 64.0)]), cfg=fast)
    assert row["status"] == "CLOSED"
    assert "10-day" in row["exit_reason"]
    assert float(row["result_pct"]) > 0


def test_stockbee_time_stop_only_flags():
    # Fill at 58.0 on the first bar after the EP, then flat closes at 58.1 for 6 sessions: never 1 ADR above the fill.
    flat = [(57.5, 58.3, 57.6, 58.1)] + [(58.1, 58.4, 57.7, 58.1)] * 6
    off_be = {"breakeven_after_partial": False}
    row = _row(_tape(after=flat), cfg={"episodic_pivot": off_be})
    assert row["status"] == "IN TRADE"  # never closes on the time stop
    assert int(row["days_in_trade"]) == 6 and row["signal"] == "NO FOLLOW-THROUGH"
    assert "No follow-through: not up 1 normal day's move after 5 sessions (Stockbee's time stop)." in row["reason"]
    assert row["exit_reason"] == "" and row["buy_status"] == ""
    # Day 5 is still in the partial window: SELL PART shows first, the reason carries the flag.
    row = _row(_tape(after=flat[:-1]), cfg={"episodic_pivot": off_be})
    assert row["status"] == "IN TRADE" and int(row["days_in_trade"]) == 5 and row["signal"] == "SELL PART"
    assert "No follow-through" in row["reason"]
    # Day 4: too early for the flag.
    row = _row(_tape(after=flat[:-2]), cfg={"episodic_pivot": off_be})
    assert "No follow-through" not in row["reason"]
    # Switch off: no flag.
    row = _row(_tape(after=flat), cfg={"episodic_pivot": dict(off_be, time_stop_flag=False)})
    assert row["status"] == "IN TRADE" and row["signal"] == "HOLD" and "No follow-through" not in row["reason"]
    # A best close one ADR above the fill clears the flag.
    run = [(57.5, 58.3, 57.6, 58.1), (58.1, 61.5, 58.0, 61.0)] + [(60.0, 60.5, 59.5, 60.0)] * 5
    row = _row(_tape(after=run), cfg={"episodic_pivot": off_be})
    assert row["status"] == "IN TRADE" and row["signal"] == "HOLD" and "No follow-through" not in row["reason"]


def test_time_stop_keys_use_india_names():
    p = ep.ep_cfg(None)
    assert p["time_stop_flag"] is True and p["time_stop_days"] == 5 and p["time_stop_adr_mult"] == 1.0
    assert "time_stop" not in p and "time_stop_adr" not in p


def test_close_under_the_ep_low_ends_the_watch():
    row = _row(_tape(after=[(56.0, 56.5, 54.0, 54.5)]))
    assert row["status"] == "CLOSED"
    assert "EP-day low" in row["exit_reason"]


def test_too_wide_stop_stays_listed_but_not_a_buy():
    row = _row(_tape(ep_bar=(56.0, 62.0, 52.0, 61.0, 4_000_000.0)))
    assert row["status"] == "EP TODAY - CONFIRMED"
    assert row["stop_check"] == "Too wide, skip"
    assert row["buy_status"] == ""
    # stop_width_check off: the same row is OK and READY.
    row = _row(_tape(ep_bar=(56.0, 62.0, 52.0, 61.0, 4_000_000.0)), cfg={"episodic_pivot": {"stop_width_check": False}})
    assert row["stop_check"] == "OK" and row["buy_status"] == "READY"


def test_confirm_needs_upper_half_and_above_open():
    # Upper half of the day (dcr 60%) but under the open: faded by default.
    f = _tape(ep_bar=(57.8, 58.0, 55.0, 56.8, 4_000_000.0))
    assert _row(f)["status"] == "EP FADED"
    assert _row(f, cfg={"episodic_pivot": {"confirm_close_above_open": False}})["status"] == "EP TODAY - CONFIRMED"
    # Above the open but in the lower half: faded unless the upper-half switch is off.
    g = _tape(ep_bar=(55.2, 58.0, 55.0, 56.0, 4_000_000.0))
    assert _row(g)["status"] == "EP FADED"
    assert _row(g, cfg={"episodic_pivot": {"close_upper_half_for_confirm": False}})["status"] == "EP TODAY - CONFIRMED"
    assert ep.EP_DEFAULTS["confirm_close_above_open"] is True


def test_gap_and_volume_switches():
    small = _tape(ep_bar=(56.0, 58.0, 55.0, 57.5, 2_000_000.0))  # 2x volume
    assert len(_scan(small)) == 0
    assert _row(small, cfg={"episodic_pivot": {"rvol_filter": False}})["status"] == "EP TODAY - CONFIRMED"
    # Gap trigger off with the close-move rule off: nothing counts.
    assert len(_scan(_tape(), cfg={"episodic_pivot": {"gap_trigger": False}})) == 0
    # Gap trigger off, Stockbee close move on: the 15% close move alone still counts.
    assert _row(_tape(), cfg={"episodic_pivot": {"gap_trigger": False, "sb_close_change_pct": 8}})["status"] == "EP TODAY - CONFIRMED"


def test_broke_out_today_feeds_buy_setups():
    # Day 2: high 58.6 crosses the EP-day high 58.0 today.
    row = _row(_tape(after=[(57.5, 58.6, 57.2, 58.4)]))
    assert row["status"] == "IN TRADE" and int(row["days_in_trade"]) == 0
    assert row["buy_status"] == "BROKEN OUT today"
    assert float(row["entry"]) == 58.0 and row["entry_basis"] == "EP-day high"
    bf = ep.ep_buy_frame(_scan(_tape(after=[(57.5, 58.6, 57.2, 58.4)])))
    assert list(bf["status"]) == ["BROKEN OUT today"] and float(bf.iloc[0]["pivot"]) == 58.0
    # One session later it is just IN TRADE, no longer on Buy setups.
    row = _row(_tape(after=[(57.5, 58.6, 57.2, 58.4), (58.4, 58.9, 58.1, 58.7)]))
    assert row["status"] == "IN TRADE" and row["buy_status"] == ""
    # A wide stop keeps a breakout off Buy setups.
    wide = _tape(ep_bar=(56.0, 62.0, 52.0, 61.0, 4_000_000.0), after=[(61.0, 62.5, 60.5, 62.2)])
    row = _row(wide)
    assert row["status"] == "IN TRADE" and row["stop_check"] == "Too wide, skip" and row["buy_status"] == ""


def test_delayed_breakout_is_not_a_buy_setup():
    # Faded EP, then a tight 5-day range, then a move above it today: a delayed trigger, not on Buy setups.
    after = [(54.6, 55.2, 54.4, 54.9)] * 5 + [(55.0, 55.8, 54.9, 55.6)]
    row = _row(_tape(ep_bar=(56.0, 58.0, 54.0, 54.5, 4_000_000.0), after=after))
    assert row["status"] == "IN TRADE" and row["entry_basis"] == "tight-range high after the EP"
    assert row["buy_status"] == ""


# Catalyst and Nick's switches

def _earn(dt, actual=1.2, est=1.0, surprise=20.0):
    return pd.DataFrame([{"ticker": "AAA", "earnings_dt": dt, "eps_estimate": est, "eps_actual": actual, "surprise_pct": surprise}])


def test_earnings_link_after_close_and_before_open():
    f = _tape()
    prev, d = f.index[-2].date(), f.index[-1].date()
    row = _row(f, earnings=_earn("%s 16:05:00-04:00" % prev))
    assert row["catalyst_tag"] == "Earnings EP" and row["report_timing"] == "after close the day before"
    assert float(row["surprise_pct"]) == 20.0
    row = _row(f, earnings=_earn("%s 07:00:00-04:00" % d, actual=None, surprise=None))
    assert row["report_timing"] == "before open"
    assert row["surprise_pct"].startswith("Pending")
    row = _row(f, earnings=_earn("%s 07:00:00-04:00" % (f.index[-10].date())))
    assert row["catalyst_tag"] == "Non-earnings - check news"


def test_nick_switches_default_off_and_work():
    f = _tape()
    p = ep.ep_cfg(None)
    switches = ("nick_gap_filter", "nick_rvol_filter", "nick_price_floor", "nick_min_mcap", "nick_min_avg_volume",
                "nick_max_perf_3m", "nick_require_earnings", "nick_require_catalyst", "nick_require_flat_base")
    assert all(p[k] is False for k in switches)
    assert p["nick_gap_min_pct"] == 10 and p["nick_rvol_min"] == 3 and p["nick_min_price"] == 5
    assert p["nick_min_mcap_usd"] == 500_000_000 and p["nick_avg_volume_days"] == 30 and p["nick_min_avg_volume_shares"] == 500_000
    assert p["nick_max_perf_3m_pct"] == 30 and p["nick_min_catalyst_score"] == 2 and p["nick_flat_base_grade"] == "A"
    # Numbers alone do nothing while the switch is off.
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_min_price": 60, "nick_min_avg_volume_shares": 2_000_000}})) == 1
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_require_earnings": True}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_price_floor": True, "nick_min_price": 60}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_price_floor": True}})) == 1  # $50 passes $5
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_min_avg_volume": True, "nick_min_avg_volume_shares": 2_000_000}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_min_avg_volume": True}})) == 1  # 1M passes 500K
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_gap_filter": True, "nick_gap_min_pct": 15}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_gap_filter": True}})) == 1  # 12% gap
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_rvol_filter": True, "nick_rvol_min": 5}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_rvol_filter": True}})) == 1  # 4x volume
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_max_perf_3m": True}})) == 1  # flat before the gap
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_max_perf_3m": True, "nick_max_perf_3m_pct": -5}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_require_flat_base": True}})) == 1  # grade A
    # Catalyst score: no earnings and no quarters is 0, under 2.
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_require_catalyst": True}})) == 0
    d = f.index[-1]
    earn = _earn("%s 07:00:00-04:00" % d.date())  # linked + 20% beat = 2
    assert len(_scan(f, earnings=earn, cfg={"episodic_pivot": {"nick_require_catalyst": True}})) == 1
    assert len(_scan(f, earnings=earn, cfg={"episodic_pivot": {"nick_require_catalyst": True, "nick_min_catalyst_score": 3}})) == 0
    # Market cap: unknown fails the switch; a known cap above it passes and shows as a column.
    on = {"episodic_pivot": {"nick_min_mcap": True}}
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_min_mcap_usd": 500_000_000}})) == 1
    assert len(_scan(f, cfg=on)) == 0
    info = pd.DataFrame([{"ticker": "AAA", "market_cap": 2_000_000_000, "analyst_count": 3}])
    row = _row(f, cfg=on, info=info)
    assert float(row["market_cap"]) == 2_000_000_000 and row["small_young_tag"] == "under $10B"
    assert "analysts" in row["reason"]


def test_growth_and_acceleration_from_filed_quarters():
    f = _tape()
    d = f.index[-1]
    q = pd.DataFrame([
        {"ticker": "AAA", "frame": "a", "revenue": 100.0, "eps": 1.0, "end": "2024-03-31", "filed": "2024-05-01"},
        {"ticker": "AAA", "frame": "b", "revenue": 100.0, "eps": 1.0, "end": "2024-06-30", "filed": "2024-08-01"},
        {"ticker": "AAA", "frame": "c", "revenue": 110.0, "eps": 1.1, "end": "2025-03-31", "filed": "2025-05-01"},
        {"ticker": "AAA", "frame": "d", "revenue": 140.0, "eps": 1.5, "end": "2025-06-30", "filed": "2025-07-15"},
    ])
    g = ep.quarter_growth(q, "AAA", d)
    assert abs(g["rev_yoy"] - 40.0) < 1e-6 and abs(g["eps_yoy"] - 50.0) < 1e-6 and g["rev_accel"] is True
    row = _row(f, quarters=q, earnings=_earn("%s 07:00:00-04:00" % d.date()))
    assert int(row["catalyst_score"]) == 4


def test_neglect_grade_ranks():
    row = _row(_tape())
    assert row["neglect_grade"] == "A"
    # Thresholds are config numbers: a negative A cap pushes a flat stock to B, a negative B cap to C.
    assert _row(_tape(), cfg={"episodic_pivot": {"neglect_a_max_63d_pct": -5}})["neglect_grade"] == "B"
    assert _row(_tape(), cfg={"episodic_pivot": {"neglect_a_max_63d_pct": -5, "neglect_b_max_63d_pct": -5}})["neglect_grade"] == "C"


def test_catalyst_check_switch():
    f = _tape()
    d = f.index[-1]
    row = _row(f, earnings=_earn("%s 07:00:00-04:00" % d.date()), cfg={"episodic_pivot": {"catalyst_check": False}})
    assert row["catalyst_tag"] == "Non-earnings - check news" and row["catalyst_score"] == ""


def test_trail_switches():
    after = [(57.5, 58.6, 57.2, 58.4), (58.5, 59.5, 58.2, 59.3)]
    # Before the partial the trail is not used by default; with trail_after_partial_only off a close under it ends the trade.
    dip = after + [(59.0, 59.2, 58.3, 58.5)]
    cfg = {"trail_fast_adr_pct": 3, "trail_fast_ma": 2, "breakeven_after_partial": False}
    assert _row(_tape(after=dip), cfg={"episodic_pivot": cfg})["status"] == "IN TRADE"
    row = _row(_tape(after=dip), cfg={"episodic_pivot": dict(cfg, trail_after_partial_only=False)})
    assert row["status"] == "CLOSED" and "2-day" in row["exit_reason"]
    p = ep.ep_cfg(None)
    assert p["trail_fast_ma"] == 10 and p["trail_slow_ma"] == 20 and p["trail_after_partial_only"] is True


# Buy setups and config

def test_buy_setups_take_only_ready_ep_rows():
    def rec(t, status, buy, check):
        return {"ticker": t, "status": status, "entry": 100.0, "pivot": 100.0, "stop": 96.0, "strength": 50, "stop_check": check,
                "buy_status": buy, "company": t, "sector": "Tech", "index_membership": "SP500", "price": 99, "price_as_of": "2026-10-29"}
    epf = pd.DataFrame([rec("GOOD", "DAY 2-5 WATCH", "READY", "OK"), rec("FADE", "EP FADED", "", "OK"),
                        rec("WIDE", "EP TODAY - CONFIRMED", "", "Too wide, skip"),
                        rec("BRKO", "IN TRADE", "BROKEN OUT today", "OK"), rec("HELD", "IN TRADE", "", "OK"),
                        rec("DLYD", "DELAYED EP WATCH", "", "OK")])
    names = ("GOOD", "FADE", "WIDE", "BRKO", "HELD", "DLYD")
    scores = pd.DataFrame([{"ticker": t, "verdict": "BUY", "score": 9} for t in names])
    out = setups.build_buy_setups(None, None, None, None, scores, sma_ok={t: True for t in names},
                                  market={"spy": True, "qqq": True}, ep=epf)
    assert sorted(out["ticker"]) == ["BRKO", "GOOD"]
    by = out.set_index("ticker")
    assert by.loc["GOOD", "setup_sources"] == "EP" and by.loc["GOOD", "best_status"] == "READY"
    assert by.loc["BRKO", "best_status"] == "BROKEN OUT today" and float(by.loc["BRKO", "entry"]) == 100.0
    assert "broke out today" in by.loc["BRKO", "reason"]
    assert "EP" in setups.BUY_SETUP_ORDER


def test_config_block_matches_defaults():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["features"]["scanner_ep"] is True
    for k, v in ep.EP_DEFAULTS.items():
        assert cfg["episodic_pivot"][k] == v, k
    src = open(os.path.join(ROOT, "stock_desk.py"), encoding="utf-8").read()
    assert '"market_cap": inf.get("marketCap")' in src


if __name__ == "__main__":
    names = sorted(k for k, v in list(globals().items()) if k.startswith("test_") and callable(v))
    for name in names:
        globals()[name]()
    print("episodic pivot ok (%d tests)" % len(names))
