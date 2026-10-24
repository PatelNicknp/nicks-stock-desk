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
    # 221 is about 4.8x a 45.69 price, so it stays on the row and leaves the blend.
    wide = dict(fin)
    wide["pfcf_avg"] = 221.03 / 3.0
    wide["fcf_per_share"] = 3.0
    wide_mkt = dict(mkt)
    wide_mkt["price"] = 45.69
    wide_row = scoring.score_components(wide, wide_mkt, extra, CFG)
    assert abs(wide_row["target_pfcf"] - 221.03) < 0.02
    assert wide_row["target_blend_n"] == 2
    assert abs(wide_row["target_blended"] - (55 + 30) / 2.0) < 1e-6
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


def test_sector_fallback_fills_roe_points_and_the_score():
    df = pd.DataFrame({
        "ticker": ["ADSK"],
        "roe": [0.48],
        "roe_avg": [np.nan],
        "pts_roe": [np.nan],
        "pts_roe_ind": [1],
        "de": [0.4],
        "de_avg": [0.5],
        "pts_de": [1],
        "pts_de_ind": [0],
        "pts_tech": [2],
        "pts_sent": [1],
        "pts_earnings": [1],
        "pts_sector": [1],
        "pts_forward_pe": [1],
        "pts_ttm_pe": [np.nan],
        "pts_ps": [np.nan],
        "pts_pfcf": [np.nan],
        "pts_rev_growth": [1],
        "pts_eps_growth": [1],
        "pts_div_yield": [0],
        "timing": ["Uptrend"],
        "price": [100],
        "stop": [80],
        "verdict": ["BUY"],
        "reason": [""],
        "n_fin": [4],
    })
    out = scoring.apply_sector_point_fallback(df, CFG)
    assert int(out.loc[0, "pts_roe"]) == 1
    # fin points that exist: forward 1, de 1, rev 1, eps 1, roe 1, div 0 = 5
    assert int(out.loc[0, "pts_fin"]) == 5
    assert int(out.loc[0, "score"]) == 10
    assert "its sector" in out.loc[0, "reason"]


def test_duplicate_backtest_window_is_dropped():
    rows = [
        {"window": "5y", "start": "2022-09-30", "end": "2026-10-23", "months": 50},
        {"window": "full", "start": "2022-09-30", "end": "2026-10-23", "months": 50},
    ]
    kept = scoring._unique_windows(rows)
    assert [r["window"] for r in kept] == ["5y"]


def test_pullbacks_skip_avoid_and_blank_entries():
    import tables
    df = pd.DataFrame([
        {"ticker": "OK", "above_sma200": 1, "above_sma50": 1, "timing": "Pullback", "rsi14": 40,
         "verdict": "BUY", "entry_low": 10, "entry_high": 11, "dist_52w_high_pct": -5, "day_pct": 1,
         "above_sma20": 1, "above_sma100": 1, "score": 8},
        {"ticker": "NO", "above_sma200": 1, "above_sma50": 1, "timing": "Pullback", "rsi14": 40,
         "verdict": "AVOID", "entry_low": np.nan, "entry_high": np.nan, "dist_52w_high_pct": -5, "day_pct": 1,
         "above_sma20": 1, "above_sma100": 1, "score": 2},
    ])
    _, _, pb, _, _ = tables.technical_pages(df)
    got = dict(zip(pb["ticker"], pb["passes"]))
    assert got["OK"] == "yes"
    assert got["NO"] == "no"


def test_ownership_cap():
    import stock_desk
    assert stock_desk.cap_ownership(140.5) == (100.0, True)
    assert stock_desk.cap_ownership(80) == (80.0, False)
    assert stock_desk.cap_ownership(None) == (None, False)


def test_ownership_uses_sec_shares_not_a_cap():
    import stock_desk
    pct, over = stock_desk.ownership_percent(283040169, 439000000, 201, 140.52)
    assert over is False
    assert abs(pct - (283040169 / 439000000 * 100)) < 0.02
    mcd, mcd_over = stock_desk.ownership_percent(603835580, 716.4, 708, 85.33)
    assert mcd_over is False
    assert 80 < mcd < 90
    # SEC shares are one class here. The larger Nasdaq count is the denominator.
    vmrk, vmrk_over = stock_desk.ownership_percent(857253691, 383878000, 774, 110.8)
    assert vmrk_over is True
    assert vmrk < 120
    still, over2 = stock_desk.ownership_percent(84320994, 66581000, 63, 133.53)
    assert over2 is True
    assert still > 100
    assert stock_desk.filer_name("Fmr Llc") == "FMR LLC"
    assert stock_desk.filer_name("Blackrock, Inc.") == "BlackRock, Inc."
    rows = stock_desk._latest_holder_rows([
        {"ticker": "A", "owner": "Vanguard", "shares": 1, "as_of": "12/31/2025"},
        {"ticker": "A", "owner": "BlackRock, Inc.", "shares": 2, "as_of": "6/30/2026"},
        {"ticker": "A", "owner": "BlackRock, Inc.", "shares": 9, "as_of": "12/31/2025"},
    ])
    assert len(rows) == 1
    assert rows[0]["shares"] == 2


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
    test_sector_fallback_fills_roe_points_and_the_score()
    test_duplicate_backtest_window_is_dropped()
    test_pullbacks_skip_avoid_and_blank_entries()
    test_ownership_cap()
    test_ownership_uses_sec_shares_not_a_cap()
    test_no_broker_order_api_in_source()
    print("scoring ok")
