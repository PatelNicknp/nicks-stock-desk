"""Score math, verdicts, targets, alerts, and the honest headline."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import scoring

CFG = {
    "flat_band_pct": 0.05, "buy_at": 8, "hold_at": 4, "downgrade_extended_below": 9,
    "min_fin_for_buy": 5, "stop_atr_mult": 2.0, "target_rr": 2.5,
    "analyst_strong_at": 1.8, "analyst_buy_at": 2.5, "analyst_sell_at": 3.8,
    "analyst_strong_sell_at": 4.5, "min_analysts_for_strong": 5,
}


def test_points_direction_and_missing():
    assert scoring.points_vs_avg(8, 12, False, 0.05) == 1   # cheaper P/E
    assert scoring.points_vs_avg(20, 12, False, 0.05) == -1  # richer P/E
    assert scoring.points_vs_avg(12.2, 12, False, 0.05) == 0  # inside 5 percent
    assert scoring.points_vs_avg(0.20, 0.10, True, 0.05) == 1  # faster growth
    assert scoring.points_vs_avg(None, 12, False, 0.05) is None
    assert scoring.points_vs_avg(8, None, False, 0.05) is None
    # missing must not become a zero point
    assert scoring.nansum_strict([1, None, -1]) == 0
    assert scoring.nansum_strict([None, None]) is None


def test_score_is_sum_of_parts_and_targets():
    fin = {
        "ttm_pe": 8, "ttm_pe_avg": 12, "ps": 2, "ps_avg": 4, "de": 0.2, "de_avg": 0.8,
        "pfcf": 10, "pfcf_avg": 16, "rev_growth": 0.20, "rev_growth_avg": 0.10,
        "eps_growth": 0.15, "eps_growth_avg": 0.08, "roe": 0.25, "roe_avg": 0.15,
        "div_yield": 0.02, "div_yield_avg": 0.01,
        "eps": 2.0, "fcf_per_share": 3.0, "pfcf_avg": 16,
    }
    mkt = {"price": 40, "sma20": 38, "sma50": 35, "sma100": 30, "sma200": 28,
           "rsi": 58, "rsi_prev": 50, "atr": 1.0, "high252": 50}
    extra = {"forward_pe": 10, "analyst_mean": 1.5, "analyst_n": 12,
             "target_median": 55, "target_mean": 50,
             "inst_up": 100, "inst_down": 10, "insider_buys": 2, "insider_sells": 0,
             "eps_flag": "beat", "rev_flag": None, "sector_excess": 0.05}
    row = scoring.score_components(fin, mkt, extra, CFG)
    parts = [row["pts_tech"], row["pts_fin"], row["pts_sent"], row["pts_earnings"], row["pts_sector"]]
    assert row["score"] == scoring.nansum_strict(parts)
    assert row["pts_forward_pe"] == 1
    assert row["pts_rev_growth"] == 1
    assert row["pts_analyst"] == 2
    assert row["verdict"] == "BUY"
    assert row["target_analyst"] == 55
    assert row["target_analyst_kind"] == "median"
    assert abs(row["target_pfcf"] - 16 * 3.0) < 1e-9
    # 15% growth -> fair P/E 15, EPS 2 -> 30
    assert abs(row["target_peg"] - 30) < 1e-9
    assert row["target_blend_n"] == 3
    assert "BUY" in row["reason"]
    assert row["entry_low"] is not None and row["stop"] < row["entry_low"]


def test_missing_pfcf_is_not_zero():
    fin = {"ttm_pe": 8, "ttm_pe_avg": 12, "pfcf": None, "pfcf_avg": 16,
           "rev_growth": None, "rev_growth_avg": None}
    mkt = {"price": 40, "sma20": 38, "sma50": 35, "sma100": 30, "sma200": 28,
           "rsi": 55, "rsi_prev": 60, "atr": 1.0, "high252": 42}
    extra = {"forward_pe": None, "analyst_mean": None, "analyst_n": None,
             "target_median": None, "target_mean": None,
             "inst_up": None, "inst_down": None, "insider_buys": None, "insider_sells": None,
             "eps_flag": None, "rev_flag": None, "sector_excess": None}
    row = scoring.score_components(fin, mkt, extra, CFG)
    assert row["pts_pfcf"] is None
    assert row["pts_rev_growth"] is None
    assert row["target_pfcf"] is None
    assert row["target_peg"] is None
    assert row["verdict"] != "BUY"  # not enough financials, and score is small


def test_extended_downgrade_and_avoid():
    assert scoring.decide_verdict(8, "Extended", 7, 100, 80, CFG) == "HOLD"
    assert scoring.decide_verdict(10, "Extended", 7, 100, 80, CFG) == "BUY"
    assert scoring.decide_verdict(6, "Downtrend", 7, 70, 80, CFG) == "AVOID"
    assert scoring.decide_verdict(3, "Sideways", 7, 100, 80, CFG) == "AVOID"


def test_industry_excludes_self_and_needs_peers():
    df = pd.DataFrame({
        "sector": ["Tech"] * 5,
        "ttm_pe": [10, 12, 14, 16, 40],
        "ticker": list("ABCDE"),
    })
    # only one spec column present; others skipped
    out = scoring.add_industry(df, 0.05)
    # peer median for the cheap name should be the other four, not pulled only by itself
    assert out.loc[out.ticker == "A", "pts_ttm_pe_ind"].iloc[0] == 1
    thin = df.iloc[:3].copy()
    thin = scoring.add_industry(thin, 0.05)
    assert thin["pts_ttm_pe_ind"].isna().all()


def test_grade_and_headline_and_tone():
    grade, note = scoring.grade_earnings(["beat", "beat", "beat", "miss"], 1)
    assert grade == "A"
    grade, _ = scoring.grade_earnings(["miss", "miss", "miss"], -1)
    assert grade == "F"
    grade, note = scoring.grade_earnings([], None)
    assert grade is None and "No earnings" in note
    assert "No clear edge" in scoring.edge_headline(8, 10, 45, -1)
    assert "No clear edge" in scoring.edge_headline(10.2, 10, 51, 0.2)
    assert "modest edge" in scoring.edge_headline(14, 10, 60, 2)
    assert scoring.headline_tone("Company beats and raises guidance")[0] == 1
    assert scoring.headline_tone("Regulator opens a probe")[0] == -1


def test_alerts_and_wheel_columns_live_in_tables():
    curr = pd.DataFrame([
        {"ticker": "AAA", "verdict": "BUY", "score": 9, "timing": "Breakout", "price": 10, "stop": 8,
         "in_holdings": "no", "insider_buys_3m": 0},
        {"ticker": "BBB", "verdict": "AVOID", "score": 1, "timing": "Downtrend", "price": 7, "stop": 8,
         "in_holdings": "yes", "insider_buys_3m": 2},
    ])
    prev = pd.DataFrame([
        {"ticker": "AAA", "verdict": "HOLD", "score": 5, "timing": "Uptrend", "price": 9, "stop": 8, "insider_buys_3m": 0},
        {"ticker": "BBB", "verdict": "HOLD", "score": 5, "timing": "Uptrend", "price": 9, "stop": 8, "insider_buys_3m": 0},
    ])
    alerts = scoring.build_alerts(curr, prev, jump=2, buy_at=8, hold_at=4)
    kinds = {(a["ticker"], a["kind"]) for a in alerts}
    assert ("AAA", "verdict_change") in kinds
    assert ("AAA", "breakout") in kinds
    assert ("BBB", "below_stop") in kinds
    assert ("BBB", "insider_buy") in kinds


def test_no_broker_order_api_in_source():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    banned = ("api.alpaca", "place_order", "/v2/orders", "ib_insync")
    for name in ("stock_desk.py", "scoring.py", "tables.py", "fundamentals.py", "netutil.py"):
        text = open(os.path.join(root, name)).read().lower()
        for b in banned:
            assert b not in text, name


if __name__ == "__main__":
    test_points_direction_and_missing()
    test_score_is_sum_of_parts_and_targets()
    test_missing_pfcf_is_not_zero()
    test_extended_downgrade_and_avoid()
    test_industry_excludes_self_and_needs_peers()
    test_grade_and_headline_and_tone()
    test_alerts_and_wheel_columns_live_in_tables()
    test_no_broker_order_api_in_source()
    print("scoring ok")
