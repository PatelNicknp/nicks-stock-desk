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


def test_stockbee_time_stop_is_a_switch():
    flat = [(57.5, 58.3, 57.6, 58.1)] + [(58.1, 58.4, 57.7, 58.1)] * 5
    row = _row(_tape(after=flat), cfg={"episodic_pivot": {"breakeven_after_partial": False}})
    assert row["status"] == "CLOSED" and "time stop" in row["exit_reason"]
    row = _row(_tape(after=flat), cfg={"episodic_pivot": {"time_stop": False, "breakeven_after_partial": False}})
    assert row["status"] == "IN TRADE"


def test_close_under_the_ep_low_ends_the_watch():
    row = _row(_tape(after=[(56.0, 56.5, 54.0, 54.5)]))
    assert row["status"] == "CLOSED"
    assert "EP-day low" in row["exit_reason"]


def test_too_wide_stop_stays_listed_but_not_a_buy():
    row = _row(_tape(ep_bar=(56.0, 62.0, 52.0, 61.0, 4_000_000.0)))
    assert row["status"] == "EP TODAY - CONFIRMED"
    assert row["stop_check"] == "Too wide, skip"
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
    assert p["nick_min_price"] == 0 and p["nick_min_mcap_usd"] == 0 and p["nick_min_avgvol_30d"] == 0
    assert p["nick_max_perf_3m_pct"] == 0 and p["nick_require_earnings"] is False
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_require_earnings": True}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_min_price": 60}})) == 0
    assert len(_scan(f, cfg={"episodic_pivot": {"nick_min_avgvol_30d": 2_000_000}})) == 0
    # Market cap: unknown fails the switch; a known cap above it passes and shows as a column.
    on = {"episodic_pivot": {"nick_min_mcap_usd": 500_000_000}}
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


# Buy setups and config

def test_buy_setups_take_only_ready_ep_rows():
    def rec(t, status, buy, check):
        return {"ticker": t, "status": status, "entry": 100.0, "pivot": 100.0, "stop": 96.0, "strength": 50, "stop_check": check,
                "buy_status": buy, "company": t, "sector": "Tech", "index_membership": "SP500", "price": 99, "price_as_of": "2026-10-29"}
    epf = pd.DataFrame([rec("GOOD", "DAY 2-5 WATCH", "READY", "OK"), rec("FADE", "EP FADED", "", "OK"),
                        rec("WIDE", "EP TODAY - CONFIRMED", "", "Too wide, skip")])
    scores = pd.DataFrame([{"ticker": t, "verdict": "BUY", "score": 9} for t in ("GOOD", "FADE", "WIDE")])
    out = setups.build_buy_setups(None, None, None, None, scores, sma_ok={"GOOD": True, "FADE": True, "WIDE": True},
                                  market={"spy": True, "qqq": True}, ep=epf)
    assert list(out["ticker"]) == ["GOOD"]
    assert out.iloc[0]["setup_sources"] == "EP" and out.iloc[0]["best_status"] == "READY"
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
