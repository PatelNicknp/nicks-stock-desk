"""Turn scored rows into one CSV per Looker page.

Pages are pre-aggregated here so Looker only filters and draws.
Missing numbers stay blank. A feed that cannot be built is one MISSING row with a note.
"""
import numpy as np
import pandas as pd
import fundamentals as fund
from scoring import FIN_SPECS, grade_earnings, headline_tone, beat_flag

DISCLAIMER = "Research only. Not a recommendation to buy or sell. This desk never places trades. Stocks only, no option contracts."

# How a macro surprise maps onto each sector ETF. +1 means a "good" surprise helps that ETF.
MACRO_WEIGHT = {
    "XLK": {"Growth": 1, "Inflation": -1, "Jobs": 0},
    "XLV": {"Growth": 0, "Inflation": -1, "Jobs": 0},
    "XLF": {"Growth": 1, "Inflation": 1, "Jobs": 1},
    "XLI": {"Growth": 1, "Inflation": 0, "Jobs": 1},
    "XLC": {"Growth": 1, "Inflation": -1, "Jobs": 0},
    "XLY": {"Growth": 1, "Inflation": -1, "Jobs": 1},
    "XLP": {"Growth": -1, "Inflation": 0, "Jobs": 0},
    "XLE": {"Growth": 0, "Inflation": 1, "Jobs": 0},
    "XLU": {"Growth": -1, "Inflation": -1, "Jobs": 0},
    "XLRE": {"Growth": 0, "Inflation": -1, "Jobs": 0},
    "XLB": {"Growth": 1, "Inflation": 1, "Jobs": 0},
    "SMH": {"Growth": 1, "Inflation": -1, "Jobs": 0},
    "XBI": {"Growth": 0, "Inflation": -1, "Jobs": 0},
    "KRE": {"Growth": 1, "Inflation": 1, "Jobs": 1},
    "XHB": {"Growth": 1, "Inflation": -1, "Jobs": 1},
    "XRT": {"Growth": 1, "Inflation": -1, "Jobs": 1},
    "XOP": {"Growth": 0, "Inflation": 1, "Jobs": 0},
    "ITA": {"Growth": 1, "Inflation": 0, "Jobs": 0},
    "XME": {"Growth": 1, "Inflation": 1, "Jobs": 0},
}

INDUSTRY_ETF = (
    ("semiconductor", "SMH"),
    ("biotech", "XBI"),
    ("regional bank", "KRE"),
    ("homebuild", "XHB"),
    ("retail", "XRT"),
    ("oil & gas", "XOP"),
    ("aerospace", "ITA"),
    ("metal", "XME"),
)


def blank_row(columns, status, note):
    row = {c: "" for c in columns}
    row["data_status"] = status
    row["note"] = note
    if "disclaimer" in columns:
        row["disclaimer"] = DISCLAIMER
    return row


def _cell_blank(v):
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (ValueError, TypeError):
        pass
    if isinstance(v, str) and v.strip().lower() in ("", "nan", "none", "<na>"):
        return True
    return False


def flag_blank_columns(df):
    """OK is wrong when a measured column is blank on every row.

    A one-row MISSING placeholder stays MISSING. An alerts info row is a
    message, not a broken feed. note and disclaimer may be empty.
    """
    if df is None or len(df) == 0 or "data_status" not in df.columns:
        return df
    status = df["data_status"].astype(str)
    if len(df) == 1 and status.iloc[0] == "MISSING":
        return df
    if "kind" in df.columns and len(df) == 1 and str(df.iloc[0].get("kind") or "") == "info":
        return df
    measured = [c for c in df.columns if c not in ("note", "disclaimer", "data_status")]
    blanks = [c for c in measured if df[c].map(_cell_blank).all()]
    if not blanks:
        return df
    out = df.copy()
    all_blank = len(blanks) == len(measured)
    new_status = "MISSING" if all_blank else "PARTIAL"
    def _next(s):
        if s in ("MISSING", "CACHED"):
            return s
        return new_status
    out["data_status"] = status.map(_next)
    extra = "Blank on every row: " + ", ".join(blanks) + ". A blank is missing data, not zero."
    notes = out["note"].map(lambda v: "" if _cell_blank(v) else str(v).strip())
    out["note"] = np.where(notes.eq(""), extra, notes + " " + extra)
    return out


def ensure(df, columns, status_if_empty, note):
    if df is None or len(df) == 0:
        return pd.DataFrame([blank_row(columns, status_if_empty, note)])
    out = df.copy()
    for c in columns:
        if c not in out.columns:
            out[c] = ""
    if "disclaimer" in columns:
        out["disclaimer"] = DISCLAIMER
    if "data_status" in columns and (out["data_status"].eq("").all() or out["data_status"].isna().all()):
        out["data_status"] = "OK"
    out = out[columns]
    out = flag_blank_columns(out)
    return out


def _off(columns):
    return pd.DataFrame(columns=columns)


# Column orders are the Looker headers. Do not rename them after the Sheet is connected.
COLS = {}

COLS["scores"] = [
    "rank", "ticker", "company", "sector", "industry", "index_membership", "universe", "price", "day_pct", "price_as_of",
    "score", "confidence", "verdict", "reason",
    "pts_tech", "pts_fin", "pts_sent", "pts_earnings", "pts_sector",
    "pts_trend", "pts_oscillator",
    "pts_forward_pe", "pts_ttm_pe", "pts_ps", "pts_de", "pts_pfcf",
    "pts_rev_growth", "pts_eps_growth", "pts_roe", "pts_div_yield",
    "pts_analyst", "pts_institutional", "pts_insider",
    "forward_pe", "forward_pe_avg", "ttm_pe", "ttm_pe_avg", "ps", "ps_avg", "de", "de_avg",
    "pfcf", "pfcf_avg", "rev_growth", "rev_growth_avg", "eps_growth", "eps_growth_avg",
    "roe", "roe_avg", "div_yield", "div_yield_avg", "forward_pe_avg_basis", "fin_avg_years", "fundamentals_basis", "fundamentals_filed",
    "ind_forward_pe", "pts_forward_pe_ind", "ind_ttm_pe", "pts_ttm_pe_ind", "ind_ps", "pts_ps_ind",
    "ind_de", "pts_de_ind", "ind_pfcf", "pts_pfcf_ind", "ind_rev_growth", "pts_rev_growth_ind",
    "ind_eps_growth", "pts_eps_growth_ind", "ind_roe", "pts_roe_ind", "ind_div_yield", "pts_div_yield_ind",
    "analyst_mean", "analyst_count", "target_analyst", "target_analyst_kind", "target_pfcf", "target_peg", "target_blended", "target_blend_n",
    "entry_low", "entry_high", "stop", "trade_target", "reward_risk",
    "timing", "sma_alignment", "rsi14", "rs_spy_3m", "dist_52w_high_pct", "volume_ratio",
    "above_sma20", "above_sma50", "above_sma100", "above_sma200",
    "next_earnings", "missing_fields", "missing_count",
    "price_status", "fundamentals_status", "analyst_status", "holders_status",
    "data_status", "note", "disclaimer",
]

# Breakdown columns the scorecard table uses. Status and the disclaimer are not repeated on every row.
COLS["score_details"] = ["ticker", "group_name", "item", "points", "points_label", "now_value", "avg_value", "vs_industry"]
COLS["market_today"] = [
    "spy_price", "spy_day_pct", "qqq_day_pct", "buy_count",
    "breadth_sma20", "breadth_sma50", "breadth_sma100", "breadth_sma200",
    "breadth_sma50_week_ago", "advancers", "decliners", "universe_n", "highs_52w", "lows_52w",
    "put_call", "put_call_ma5", "put_call_zone", "put_call_name", "vix",
    "fred_dgs10", "fred_t10y2y", "xly_xlp", "updated_pt", "price_as_of",
    "data_status", "note", "disclaimer",
]
COLS["sectors"] = ["ticker", "name", "group_name", "day_pct", "week_pct", "month_pct", "month3_pct", "ytd_pct", "rs_3m_pct", "score_avg", "n_stocks", "pct_above_sma50", "macro_growth", "macro_inflation", "macro_jobs", "macro_score", "data_status", "note", "disclaimer"]
COLS["breadth_history"] = ["date", "pct_above_sma20", "pct_above_sma50", "pct_above_sma100", "pct_above_sma200", "data_status", "note", "disclaimer"]
COLS["alerts"] = ["ticker", "kind", "text", "score", "score_prev", "verdict", "verdict_prev", "price", "data_status", "note", "disclaimer"]
COLS["score_changes"] = ["ticker", "company", "price", "day_pct", "score", "score_prev", "score_change", "verdict", "data_status", "note", "disclaimer"]
COLS["portfolio"] = ["ticker", "company", "shares", "avg_cost", "price", "day_pct", "value", "cost", "gain", "gain_pct", "weight_pct", "score", "score_week_ago", "score_week_change", "verdict", "stop", "status", "example", "data_status", "note", "disclaimer"]
COLS["portfolio_summary"] = ["value", "day_pnl", "day_pnl_pct", "total_gain", "total_gain_pct", "avg_score", "needs_attention", "n_holdings", "example_warning", "data_status", "note", "disclaimer"]
COLS["watchlist"] = ["ticker", "company", "price", "day_pct", "score", "verdict", "entry_low", "entry_high", "distance_to_entry_pct", "timing", "note_input", "data_status", "note", "disclaimer"]
# Chart columns only. Full daily history stays in cache/ohlcv.csv.gz, not in this file.
COLS["prices"] = ["date", "ticker", "close", "sma20", "sma50", "entry_low", "entry_high", "stop", "trade_target"]
COLS["news"] = ["ticker", "kind", "headline", "summary", "publisher", "link", "published", "data_status", "note", "disclaimer"]
COLS["scanner_growth"] = ["ticker", "company", "sector", "price", "score", "verdict", "rev_growth", "eps_growth", "rs_spy_3m", "passes", "why", "data_status", "note", "disclaimer"]
COLS["scanner_quality"] = ["ticker", "company", "sector", "price", "score", "verdict", "roe", "de", "pts_roe", "pts_de", "passes", "why", "data_status", "note", "disclaimer"]
COLS["scanner_dividend"] = ["ticker", "company", "sector", "price", "score", "verdict", "div_yield", "div_yield_avg", "pts_div_yield", "passes", "why", "data_status", "note", "disclaimer"]
COLS["scanner_wheel"] = ["ticker", "company", "sector", "price", "score", "verdict", "timing", "rsi14", "above_sma200", "dollar_volume", "passes", "why", "data_status", "note", "disclaimer"]
_SETUP = ["ticker", "company", "sector", "index_membership", "status", "pivot", "stop", "target", "strength", "reason", "freshness", "price", "price_as_of"]
COLS["scanner_vcp"] = _SETUP + [
    "trail", "trend_score", "contractions", "depths", "volume_ok", "in_trade", "stop_basis",
    "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8",
    "data_status", "note", "disclaimer",
]
COLS["scanner_canslim"] = _SETUP + [
    "c_quarterly_eps", "c_status", "a_annual_eps", "a_status",
    "n_pct_from_high", "n_status", "s_adv", "s_status",
    "l_rs_percentile", "l_status", "i_trend", "i_status",
    "m_market", "m_spy", "m_qqq", "m_status", "qualify", "vcp_heuristic",
    "data_status", "note", "disclaimer",
]
COLS["scanner_box"] = _SETUP + ["range_days", "range_width_pct", "volume_ratio", "data_status", "note", "disclaimer"]
COLS["scanner_breakdown"] = _SETUP + [
    "range_days", "range_width_pct", "volume_ratio", "sma50", "sma200", "entry",
    "data_status", "note", "disclaimer",
]
COLS["scanner_volume"] = [
    "ticker", "company", "sector", "index_membership", "price", "change_pct", "direction",
    "volume", "avg_volume_50", "volume_ratio", "spike", "streak_days", "streak",
    "avg_volume_10", "dryup_ratio", "high_3m", "pct_from_high", "quiet",
    "sma50", "sma200", "vs_sma50", "vs_sma200", "reason", "freshness", "price_as_of",
    "data_status", "note", "disclaimer",
]
COLS["options_ideas"] = [
    "ticker", "company", "setup", "direction", "strikes", "expiry", "dte",
    "cost", "max_profit", "max_loss", "breakeven", "move_pct",
    "price_check", "price_score", "liquidity",
    "exit_plan", "sizing", "education",
    "side", "long_strike", "short_strike", "debit", "spot", "stop", "sma50", "target",
    "market_ok", "narrowed", "quote_as_of", "price_as_of",
    "data_status", "note", "disclaimer",
]
COLS["options_skipped"] = ["ticker", "company", "side", "reason", "market_ok", "data_status", "note", "disclaimer"]
COLS["scanner_flag"] = _SETUP + ["pole_pct", "flag_bars", "retrace_pct", "volume_ratio", "data_status", "note", "disclaimer"]
COLS["scanner_leaders"] = _SETUP + [
    "vcp_status", "canslim_status", "vcp_strength", "canslim_strength", "on_vcp", "on_canslim",
    "data_status", "note", "disclaimer",
]
# high_52w and low_52w are the high and low columns. new_high_today and new_low_today are the close.
COLS["scanner_52w"] = [
    "ticker", "company", "sector", "index_membership", "price", "price_as_of",
    "high_52w", "low_52w", "pct_from_high", "pct_above_low", "range_position_pct",
    "new_high_today", "new_low_today", "near_high", "high_on_volume", "volume_ratio",
    "days_since_high", "score", "verdict", "data_status", "note", "disclaimer",
]
COLS["highs_lows_history"] = [
    "date", "new_highs", "new_lows", "near_high_count", "net", "data_status", "note", "disclaimer",
]
COLS["buy_setups"] = [
    "ticker", "company", "sector", "index_membership", "price", "price_as_of",
    "setup_sources", "sources_count", "best_status", "entry", "stop", "target1", "target2",
    "risk_pct", "reward_risk", "dist_to_entry_pct", "score", "verdict",
    "range_position_52w", "pct_from_high_52w", "reason", "market_ok", "spy_uptrend", "qqq_uptrend",
    "data_status", "note", "disclaimer",
]
COLS["earnings_calendar"] = ["ticker", "company", "next_earnings", "when_hint", "days_away", "last_eps_actual", "last_eps_estimate", "last_surprise_pct", "last_1d_move_pct", "avg_1d_move_pct", "n_past", "owns", "data_status", "note", "disclaimer"]
COLS["earnings_heatmap"] = ["ticker", "quarter", "eps_flag", "rev_flag", "label", "heat", "data_status", "note", "disclaimer"]
COLS["earnings_cards"] = ["ticker", "company", "grade", "summary", "sources", "data_status", "note", "disclaimer"]
COLS["earnings_history"] = ["ticker", "earnings_date", "eps_estimate", "eps_actual", "surprise_pct", "move_1d_pct", "data_status", "note", "disclaimer"]
COLS["put_call"] = ["date", "name", "value", "ma5", "fear_line", "greed_line", "zone", "data_status", "note", "disclaimer"]
COLS["option_walls"] = ["ticker", "expiry", "side", "strike", "open_interest", "volume", "is_wall", "nearest_expiry", "data_status", "note", "disclaimer"]
COLS["analyst_ratings"] = ["ticker", "company", "analyst_mean", "analyst_count", "pts_analyst", "target_analyst", "target_analyst_kind", "price", "upside_pct", "data_status", "note", "disclaimer"]
COLS["institutional_13f"] = ["ticker", "row_type", "owner", "increased_shares", "decreased_shares", "holders", "ownership_pct", "shares", "share_change", "as_of", "pts_institutional", "data_status", "note", "disclaimer"]
COLS["aaii_sentiment"] = ["as_of", "bullish_pct", "neutral_pct", "bearish_pct", "data_status", "note", "disclaimer"]
COLS["insider_trading"] = ["ticker", "buys_3m", "sells_3m", "pts_insider", "data_status", "note", "disclaimer"]
COLS["headline_sentiment"] = ["ticker", "headline", "publisher", "link", "published", "tone", "tone_note", "data_status", "note", "disclaimer"]
COLS["xly_xlp"] = ["date", "xly", "xlp", "ratio", "ratio_sma50", "zone", "data_status", "note", "disclaimer"]
COLS["financials_summary"] = ["ticker", "sector", "metric", "direction", "now_value", "avg_3y", "pts_vs_self", "industry_median", "pts_vs_industry", "data_status", "note", "disclaimer"]
COLS["earnings_tracker"] = ["ticker", "earnings_date", "eps_estimate", "eps_actual", "surprise_pct", "result", "data_status", "note", "disclaimer"]
COLS["company_financials"] = ["ticker", "fy_end", "filed", "revenue", "gross_profit", "op_income", "net_income", "eps", "gross_margin", "operating_margin", "net_margin", "fcf", "pe", "ps", "pfcf", "data_status", "note", "disclaimer"]
COLS["dividend_scanner"] = ["ticker", "company", "sector", "price", "div_yield", "div_yield_avg", "dps", "pts_div_yield", "verdict", "data_status", "note", "disclaimer"]
COLS["macro_screener"] = ["country", "category", "indicator", "date", "actual", "forecast", "surprise", "signal", "data_status", "note", "disclaimer"]
COLS["sector_macro"] = ["ticker", "name", "macro_growth", "macro_inflation", "macro_jobs", "macro_score", "plain_english", "data_status", "note", "disclaimer"]
COLS["sector_rotation"] = [
    "ticker", "name", "sector", "score", "rank",
    "quadrant_d", "quadrant_w", "quadrant_m",
    "rs_ratio_w", "rs_momentum_w",
    "rs_1m", "rs_3m", "rs_6m",
    "breadth_sma50", "breadth_sma200", "n_stocks",
    "near_high_count", "near_high_share",
    "buy_setup_count", "buy_setup_share",
    "score_avg", "buy_share", "rrg_points",
    "change_daily", "change_weekly",
    "dgs10_last", "dgs10_prev", "dgs10_trend",
    "t10y2y_last", "t10y2y_prev", "t10y2y_trend",
    "reason", "data_status", "note", "disclaimer",
]
COLS["sector_rotation_tails"] = [
    "timeframe", "ticker", "name", "date", "rs_ratio", "rs_momentum", "quadrant", "tail_index",
    "data_status", "note", "disclaimer",
]
COLS["sector_rotation_history"] = [
    "date", "timeframe", "ticker", "name", "rs_ratio", "rs_momentum", "quadrant",
    "data_status", "note", "disclaimer",
]
COLS["historical_pe"] = ["date", "desk_median_trailing_pe", "n", "official_sp500_pe", "official_status", "data_status", "note", "disclaimer"]
COLS["breakouts"] = ["ticker", "company", "sector", "price", "dist_52w_high_pct", "volume_ratio", "score", "verdict", "data_status", "note", "disclaimer"]
COLS["trends"] = ["ticker", "company", "sector", "price", "trend_label", "sma_alignment", "above_sma20", "above_sma50", "above_sma100", "above_sma200", "score", "data_status", "note", "disclaimer"]
COLS["pullbacks"] = ["ticker", "company", "sector", "price", "rsi14", "entry_low", "entry_high", "score", "verdict", "passes", "why", "data_status", "note", "disclaimer"]
COLS["gainers_losers"] = ["side", "ticker", "company", "sector", "price", "day_pct", "score", "verdict", "data_status", "note", "disclaimer"]
COLS["sector_performance"] = ["sector", "day_pct", "week_pct", "month_pct", "month3_pct", "ytd_pct", "pct_above_sma50", "score_avg", "n", "data_status", "note", "disclaimer"]
COLS["heatmaps"] = ["ticker", "company", "sector", "ret_1d", "ret_1w", "ret_1m", "ret_ytd", "above_sma20", "above_sma50", "above_sma100", "above_sma200", "data_status", "note", "disclaimer"]
COLS["freshness"] = ["field", "n_missing", "n_present", "data_status", "note", "disclaimer"]
COLS["updates_log"] = ["source", "status", "latest", "note", "checked_pt"]
COLS["help"] = ["topic", "plain_english"]
COLS["settings"] = ["setting", "value"]
COLS["universe"] = ["ticker", "company", "sector", "index_membership", "in_sp500", "in_ndx100", "in_growth", "data_status", "note", "disclaimer"]
COLS["backtest_summary"] = ["window", "start", "end", "months", "top20_cagr_pct", "spy_cagr_pct", "bottom20_cagr_pct", "top20_total_pct", "spy_total_pct", "bottom20_total_pct", "top20_max_drawdown_pct", "spy_max_drawdown_pct", "hit_rate_12w_pct", "top_bucket_excess_12w_pct", "headline", "is_headline", "data_status", "note", "disclaimer"]
COLS["backtest_buckets"] = ["horizon", "bucket", "bucket_order", "n", "avg_return_pct", "avg_spy_pct", "excess_pct", "hit_rate_pct", "data_status", "note", "disclaimer"]
COLS["backtest_equity"] = ["date", "top20", "spy", "bottom20", "data_status", "note", "disclaimer"]
COLS["backtest_yearly"] = ["year", "top20_pct", "spy_pct", "difference_pct", "hit_rate_12w_pct", "signals", "data_status", "note", "disclaimer"]
COLS["backtest_notes"] = ["item", "detail", "data_status", "note", "disclaimer"]


def _date_cell(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    try:
        if pd.isna(v):
            return ""
    except (ValueError, TypeError):
        return ""
    try:
        return str(pd.Timestamp(v).date())
    except Exception:
        return str(v)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x):
        return None
    return x


def _yn(flag):
    return 1 if flag else 0


def missing_fields(row):
    fields = []
    for key, _ in FIN_SPECS:
        if _num(row.get(key)) is None or _num(row.get("pts_" + key)) is None:
            # a present value with no points means the baseline was missing
            if _num(row.get(key)) is None or _num(row.get(key + "_avg")) is None:
                fields.append(key)
    for key in ("pts_analyst", "pts_institutional", "pts_insider", "pts_earnings", "pts_trend", "pts_sector"):
        if row.get(key) is None or (isinstance(row.get(key), float) and not np.isfinite(row.get(key))):
            fields.append(key)
    return fields


def score_details(scores):
    rows = []
    items = [
        ("Technical", "Trend vs 20-day and 50-day", "pts_trend", None, None),
        ("Technical", "Oscillator (RSI-14)", "pts_oscillator", "rsi14", None),
        ("Financials", "Forward P/E (lower is better)", "pts_forward_pe", "forward_pe", "forward_pe_avg"),
        ("Financials", "Trailing P/E (lower is better)", "pts_ttm_pe", "ttm_pe", "ttm_pe_avg"),
        ("Financials", "Price / sales (lower is better)", "pts_ps", "ps", "ps_avg"),
        ("Financials", "Debt / equity (lower is better)", "pts_de", "de", "de_avg"),
        ("Financials", "Price / free cash flow (lower is better)", "pts_pfcf", "pfcf", "pfcf_avg"),
        ("Financials", "Revenue growth (higher is better)", "pts_rev_growth", "rev_growth", "rev_growth_avg"),
        ("Financials", "EPS growth (higher is better)", "pts_eps_growth", "eps_growth", "eps_growth_avg"),
        ("Financials", "Return on equity (higher is better)", "pts_roe", "roe", "roe_avg"),
        ("Financials", "Dividend yield (higher is better)", "pts_div_yield", "div_yield", "div_yield_avg"),
        ("Sentiment", "Analyst rating", "pts_analyst", "analyst_mean", None),
        ("Sentiment", "Institutional 13F trend", "pts_institutional", None, None),
        ("Sentiment", "Insider buys vs sells", "pts_insider", None, None),
        ("Earnings", "Latest earnings vs estimate", "pts_earnings", None, None),
        ("Sector", "Sector vs S&P 500, 3 months", "pts_sector", "rs_spy_3m", None),
    ]
    for _, r in scores.iterrows():
        for group, item, pts, now, avg in items:
            p = r.get(pts)
            missing_pt = p is None or p == "" or (isinstance(p, (float, np.floating)) and not np.isfinite(p))
            try:
                missing_pt = missing_pt or bool(pd.isna(p))
            except (ValueError, TypeError):
                pass
            label = "n/a" if missing_pt else points_label(p)
            ind = ""
            if pts.startswith("pts_") and "ind_" + pts[4:] in scores.columns:
                ind = r.get("pts_" + pts[4:] + "_ind") if False else r.get("pts_" + pts.replace("pts_", "") + "_ind", "")
            rows.append({
                "ticker": r["ticker"], "group_name": group, "item": item,
                "points": "" if label == "n/a" else int(p), "points_label": label,
                "now_value": r.get(now) if now else "", "avg_value": r.get(avg) if avg else "",
                "vs_industry": "" if ind is None else ind,
            })
    return pd.DataFrame(rows)


def points_label(p):
    """Words, so a sheet does not turn '+1' into a number. The points column stays numeric."""
    n = int(p)
    if n > 0:
        return "plus %d" % n
    if n < 0:
        return "minus %d" % abs(n)
    return "zero"


def _passes_frame(df, cols):
    return df


def scanners(scores, cfg):
    g = scores.copy()
    growth_cut = cfg["growth_min_pct"]
    g["passes"] = np.where(
        g["rev_growth"].map(_num).ge(growth_cut) & g["verdict"].ne("AVOID") & g["rev_growth"].notna(),
        "yes", "no")
    g["why"] = np.where(g["passes"].eq("yes"), "Revenue growth is at least the screen level and the label is not AVOID.", "Does not pass the growth screen.")
    q = scores.copy()
    q["passes"] = np.where((q["pts_roe"] == 1) & (q["de"].map(_num).fillna(99) < cfg["quality_max_de"]) & q["verdict"].ne("AVOID"), "yes", "no")
    q["why"] = np.where(
        q["passes"].eq("yes"),
        "Return on equity point is +1 and debt/equity is under the desk limit. Debt points compare to the sector and can be -1. The label is not AVOID.",
        "Does not pass the quality screen.")
    d = scores.copy()
    d["passes"] = np.where(d["div_yield"].map(_num).ge(cfg["dividend_min_pct"]) & d["verdict"].ne("AVOID"), "yes", "no")
    d["why"] = np.where(d["passes"].eq("yes"), "Dividend yield clears the screen and the label is not AVOID.", "Does not pass the dividend screen.")
    w = scores.copy()
    dv = w["dollar_volume"].map(_num) if "dollar_volume" in w.columns else pd.Series(np.nan, index=w.index)
    w["dollar_volume"] = dv
    w["passes"] = np.where(
        w["verdict"].ne("AVOID") & (w["above_sma200"] == 1) & w["rsi14"].map(_num).lt(70) & dv.ge(cfg["wheel_min_dollar_volume"]) & ~w["timing"].isin(["Extended", "Downtrend"]),
        "yes", "no")
    w["why"] = np.where(
        w["passes"].eq("yes"),
        "Liquid stock in an uptrend that is not extended.",
        "Does not pass the wheel stock screen.")
    w["why"] = w["why"] + " Stock screen only. This is not an option contract."
    return g, q, d, w


def _reaction_table(earnings, close):
    """1-day move after each report. After 4pm Eastern, the move is the next session."""
    rows = []
    if earnings is None or len(earnings) == 0 or close is None or close.empty:
        return pd.DataFrame(rows)
    idx = close.index
    for _, r in earnings.iterrows():
        ts = pd.Timestamp(r["earnings_dt"])
        if ts.tzinfo is not None:
            ts = ts.tz_convert("America/New_York").tz_localize(None)
        day = ts.normalize()
        if ts.hour >= 16:
            day = day + pd.Timedelta(days=1)
        i = idx.searchsorted(day)
        move = np.nan
        if 0 < i < len(idx):
            t = r["ticker"]
            if t in close.columns:
                a, b = close.iloc[i - 1][t], close.iloc[i][t]
                if pd.notna(a) and pd.notna(b) and a > 0:
                    move = (b / a - 1) * 100
        result = beat_flag(_num(r.get("eps_actual")), _num(r.get("eps_estimate")))
        rows.append({
            "ticker": r["ticker"],
            "earnings_date": str(pd.Timestamp(r["earnings_dt"]).date()) if pd.notna(r["earnings_dt"]) else "",
            "eps_estimate": r.get("eps_estimate"),
            "eps_actual": r.get("eps_actual"),
            "surprise_pct": r.get("surprise_pct"),
            "result": result,
            "move_1d_pct": None if not np.isfinite(move) else round(float(move), 2),
            "has_actual": pd.notna(r.get("eps_actual")),
            "earnings_dt": r["earnings_dt"],
        })
    return pd.DataFrame(rows)


def earnings_pages(scores, earnings, close, holdings):
    hist = _reaction_table(earnings, close)
    if hist.empty:
        return {}, hist
    cal_rows, heat_rows, card_rows = [], [], []
    owns = set(holdings or [])
    names = scores.set_index("ticker")["company"].to_dict() if len(scores) else {}
    growth_pts = scores.set_index("ticker")["pts_rev_growth"].to_dict() if len(scores) else {}
    for t, g in hist.groupby("ticker"):
        g = g.sort_values("earnings_dt")
        past = g[g["has_actual"] == True]
        future = g[g["has_actual"] == False]
        moves = past["move_1d_pct"].dropna()
        avg = float(moves.tail(8).mean()) if len(moves) else np.nan
        last = past.iloc[-1] if len(past) else None
        nxt = future.iloc[0] if len(future) else None
        days = ""
        when = ""
        nxt_s = ""
        if nxt is not None and pd.notna(nxt["earnings_dt"]):
            ts = pd.Timestamp(nxt["earnings_dt"])
            if ts.tzinfo is not None:
                ts_et = ts.tz_convert("America/New_York")
                when = "after close" if ts_et.hour >= 16 else "before or during the session"
                days = int((ts_et.tz_localize(None).normalize() - pd.Timestamp.now().normalize()).days)
            nxt_s = str(ts.date())
        cal_rows.append({
            "ticker": t, "company": names.get(t, ""), "next_earnings": nxt_s, "when_hint": when, "days_away": days,
            "last_eps_actual": None if last is None else last["eps_actual"],
            "last_eps_estimate": None if last is None else last["eps_estimate"],
            "last_surprise_pct": None if last is None else last["surprise_pct"],
            "last_1d_move_pct": None if last is None else last["move_1d_pct"],
            "avg_1d_move_pct": None if not np.isfinite(avg) else round(avg, 2),
            "n_past": int(len(past)), "owns": "yes" if t in owns else "no",
        })
        flags = []
        for _, row in past.tail(4).iloc[::-1].iterrows():
            flag = beat_flag(_num(row["eps_actual"]), _num(row["eps_estimate"]))
            flags.append(flag)
            label = {"beat": "eps beat, revenue n/a", "miss": "eps miss, revenue n/a", "inline": "eps inline, revenue n/a"}.get(flag, "incomplete")
            heat = {"beat": 1, "miss": -1, "inline": 0}.get(flag, "")
            heat_rows.append({"ticker": t, "quarter": row["earnings_date"], "eps_flag": flag or "", "rev_flag": "", "label": label, "heat": heat})
        grade, summary = grade_earnings(flags, growth_pts.get(t))
        card_rows.append({
            "ticker": t, "company": names.get(t, ""), "grade": grade or "",
            "summary": summary,
            "sources": "Yahoo Finance earnings dates. Revenue vs estimate is not in that free feed, so revenue is left blank.",
        })
    return {
        "calendar": pd.DataFrame(cal_rows),
        "heatmap": pd.DataFrame(heat_rows),
        "cards": pd.DataFrame(card_rows),
        "history": hist,
    }, hist


def financials_long(scores):
    rows = []
    labels = {
        "forward_pe": ("Forward P/E", "lower"),
        "ttm_pe": ("Trailing P/E", "lower"),
        "ps": ("Price / sales", "lower"),
        "de": ("Debt / equity", "lower"),
        "pfcf": ("Price / free cash flow", "lower"),
        "rev_growth": ("Revenue growth %", "higher"),
        "eps_growth": ("EPS growth %", "higher"),
        "roe": ("Return on equity %", "higher"),
        "div_yield": ("Dividend yield %", "higher"),
    }
    for _, r in scores.iterrows():
        for key, (label, direction) in labels.items():
            avg = r.get(key + "_avg")
            pts = r.get("pts_" + key)
            note = ""
            # A sector fallback used to be written into the own-history column.
            if key in ("roe", "de") and _cell_blank(avg) and not _cell_blank(pts):
                note = "sector fallback"
                pts = ""
            rows.append({
                "ticker": r["ticker"], "sector": r.get("sector"), "metric": label, "direction": direction,
                "now_value": r.get(key), "avg_3y": avg, "pts_vs_self": pts,
                "industry_median": r.get("ind_" + key), "pts_vs_industry": r.get("pts_" + key + "_ind"),
                "note": note,
            })
    return pd.DataFrame(rows)


def _multiple(price, denominator):
    """Price (or market cap) over a fundamental. Blank when either side is missing or not positive."""
    if price is None or denominator is None or not np.isfinite(price) or price <= 0 or denominator <= 0:
        return None
    value = round(float(price) / float(denominator), 4)
    # A ratio that rounds to zero is a unit mismatch (shares in millions, revenue in dollars). Leave it blank.
    if value <= 0:
        return None
    return value


def company_rows(annual, close):
    rows = []
    if annual is None or len(annual) == 0:
        return pd.DataFrame(rows)
    closes = {}
    if close is not None and hasattr(close, "columns"):
        for t in pd.unique(annual["ticker"]):
            if t in close.columns:
                closes[t] = pd.to_numeric(close[t], errors="coerce").dropna()
    for _, r in annual.iterrows():
        rev, gp, oi, ni = _num(r.get("revenue")), _num(r.get("gross_profit")), _num(r.get("op_income")), _num(r.get("net_income"))
        fcf = None
        if _num(r.get("ocf")) is not None and _num(r.get("capex")) is not None:
            fcf = _num(r.get("ocf")) - _num(r.get("capex"))
        gm = gp / rev if rev and gp is not None and rev > 0 else None
        om = oi / rev if rev and oi is not None and rev > 0 else None
        nm = ni / rev if rev and ni is not None and rev > 0 else None
        eps = _num(r.get("eps"))
        shares = _num(r.get("shares"))
        filed = r.get("filed")
        known = None
        if not _cell_blank(filed):
            try:
                known = pd.Timestamp(filed) + pd.Timedelta(days=1)
            except Exception:
                known = None
        px = fund._price_on_or_after(closes.get(r["ticker"]), known)
        if px is not None and not np.isfinite(px):
            px = None
        mcap = px * shares if px is not None and shares is not None else None
        rows.append({
            "ticker": r["ticker"],
            "fy_end": _date_cell(r.get("fy_end") if not _cell_blank(r.get("fy_end")) else r.get("end")),
            "filed": _date_cell(filed),
            "revenue": rev, "gross_profit": gp, "op_income": oi, "net_income": ni,
            "eps": eps,
            "gross_margin": None if gm is None else round(gm * 100, 2),
            "operating_margin": None if om is None else round(om * 100, 2),
            "net_margin": None if nm is None else round(nm * 100, 2),
            "fcf": fcf,
            "pe": fund.guard_multiple(_multiple(px, eps)),
            "ps": _multiple(mcap, rev),
            "pfcf": _multiple(mcap, fcf),
        })
    return pd.DataFrame(rows)


def mark_nearest_expiry(df, today=None):
    """Flag the expiry on or after today for each ticker. No chain download.

    If every expiry is already past, the latest one is the nearest. The flag
    is the text true or false so it is not stored as 1 or 0.
    """
    if df is None or len(df) == 0 or "expiry" not in df.columns:
        return df
    out = df.copy()
    day = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.now().normalize()
    exp = pd.to_datetime(out["expiry"], errors="coerce")
    out["nearest_expiry"] = "false"
    for _, idx in out.groupby(out["ticker"].astype(str)).groups.items():
        dates = exp.loc[idx]
        future = dates[dates >= day]
        if len(future):
            pick = future.min()
        else:
            past = dates.dropna()
            if not len(past):
                continue
            pick = past.max()
        out.loc[dates[dates == pick].index, "nearest_expiry"] = "true"
    return out


def macro_tables(econ, sector_etfs):
    if econ is None or len(econ) == 0:
        return pd.DataFrame(), pd.DataFrame()
    released = econ[econ["signal"].notna()] if "signal" in econ.columns else econ
    screener = released.copy()
    # latest signal per category
    sig = {}
    if len(released):
        for cat, g in released.groupby("category"):
            sig[cat] = int(np.sign(g["signal"].sum())) if g["signal"].sum() != 0 else 0
    rows = []
    for etf in sector_etfs:
        w = MACRO_WEIGHT.get(etf["ticker"], {})
        if not sig or not w:
            rows.append({"ticker": etf["ticker"], "name": etf["name"], "macro_growth": "", "macro_inflation": "", "macro_jobs": "", "macro_score": "", "plain_english": "No mapped macro surprise."})
            continue
        parts = {}
        for cat in ("Growth", "Inflation", "Jobs"):
            parts[cat] = sig.get(cat, 0) * w.get(cat, 0)
        score = parts["Growth"] + parts["Inflation"] + parts["Jobs"]
        rows.append({
            "ticker": etf["ticker"], "name": etf["name"],
            "macro_growth": parts["Growth"], "macro_inflation": parts["Inflation"], "macro_jobs": parts["Jobs"],
            "macro_score": score,
            "plain_english": "Rule of thumb from the latest surprises. It is not a forecast.",
        })
    return screener, pd.DataFrame(rows)


def put_call_table(pcr, fear, greed):
    if pcr is None or len(pcr) == 0:
        return pd.DataFrame()
    df = pcr.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["name", "date"])
    df["ma5"] = df.groupby("name")["value"].transform(lambda s: s.rolling(5, min_periods=1).mean())
    df["fear_line"] = fear
    df["greed_line"] = greed
    def zone(v):
        if v is None or not np.isfinite(v):
            return ""
        if v >= fear:
            return "Fear"
        if v <= greed:
            return "Greed"
        return "Neutral"
    df["zone"] = df["ma5"].map(zone)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def xly_xlp_table(close):
    if close is None or "XLY" not in close.columns or "XLP" not in close.columns:
        return pd.DataFrame()
    df = pd.DataFrame({"xly": close["XLY"], "xlp": close["XLP"]}).dropna()
    if df.empty:
        return pd.DataFrame()
    df["ratio"] = df["xly"] / df["xlp"]
    df["ratio_sma50"] = df["ratio"].rolling(50).mean()
    df["zone"] = np.where(df["ratio"] > df["ratio_sma50"], "Risk on", "Risk off")
    df = df.dropna(subset=["ratio"]).tail(260).reset_index()
    date_col = "date" if "date" in df.columns else df.columns[0]
    df["date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    return df[["date", "xly", "xlp", "ratio", "ratio_sma50", "zone"]]


def historical_pe(close, prepared):
    rows = []
    if close is None or close.empty or not prepared:
        return pd.DataFrame()
    idx = close.index
    month_ends = idx.to_series().groupby(idx.to_period("M")).max().tolist()
    for d in month_ends[-120:]:
        pes = []
        for t, prep in prepared.items():
            if t not in close.columns or prep is None or len(prep) == 0:
                continue
            known = prep[prep["known_on"] <= d]
            if known.empty:
                continue
            eps = known.iloc[-1].get("eps")
            price = close.at[d, t]
            try:
                eps = float(eps)
                price = float(price)
            except (TypeError, ValueError):
                continue
            if np.isfinite(eps) and eps > 0 and np.isfinite(price) and price > 0:
                pe = price / eps
                if 0 < pe < 2000:
                    pes.append(pe)
        if len(pes) < 20:
            continue
        rows.append({
            "date": str(pd.Timestamp(d).date()),
            "desk_median_trailing_pe": round(float(np.median(pes)), 2),
            "n": len(pes),
            "official_sp500_pe": "",
            "official_status": "MISSING",
        })
    return pd.DataFrame(rows)


def technical_pages(scores):
    br = scores[scores["dist_52w_high_pct"].map(_num).ge(-1)].copy() if "dist_52w_high_pct" in scores.columns else scores.iloc[0:0]
    tr = scores.copy()
    def trend_label(r):
        flags = [r.get("above_sma20"), r.get("above_sma50"), r.get("above_sma100"), r.get("above_sma200")]
        if all(f == 1 for f in flags):
            return "Uptrend"
        if all(f == 0 for f in flags if f in (0, 1)) and all(f in (0, 1) for f in flags):
            return "Downtrend"
        return "Mixed"
    tr["trend_label"] = tr.apply(trend_label, axis=1)
    pb = scores.copy()
    has_entry = pb["entry_low"].map(_num).notna() & pb["entry_high"].map(_num).notna() if "entry_low" in pb.columns else False
    pb["passes"] = np.where(
        (pb["above_sma200"] == 1) & (pb["above_sma50"] == 1) & pb["timing"].isin(["Pullback", "In entry zone"])
        & pb["rsi14"].map(_num).lt(70) & pb["verdict"].ne("AVOID") & has_entry,
        "yes", "no")
    pb["why"] = np.where(pb["passes"].eq("yes"), "Uptrend structure with price back near the entry area.", "Not a pullback setup.")
    gl = []
    s2 = scores.dropna(subset=["day_pct"]).sort_values("day_pct", ascending=False)
    for _, r in s2.head(15).iterrows():
        gl.append({**r.to_dict(), "side": "gainer"})
    for _, r in s2.tail(15).iterrows():
        gl.append({**r.to_dict(), "side": "loser"})
    heat = scores.copy()
    heat["ret_1d"] = heat["day_pct"]
    heat["ret_1w"] = heat.get("ret_1w")
    heat["ret_1m"] = heat.get("ret_1m")
    heat["ret_ytd"] = heat.get("ret_ytd")
    return br, tr, pb, pd.DataFrame(gl), heat


def sector_perf(scores):
    rows = []
    if scores is None or len(scores) == 0:
        return pd.DataFrame()
    for sector, g in scores.groupby(scores["sector"].fillna("Unknown")):
        rows.append({
            "sector": sector,
            "day_pct": round(float(pd.to_numeric(g["day_pct"], errors="coerce").mean()), 2),
            "week_pct": _mean(g, "ret_1w"),
            "month_pct": _mean(g, "ret_1m"),
            "month3_pct": _mean(g, "ret_3m"),
            "ytd_pct": _mean(g, "ret_ytd"),
            "pct_above_sma50": round(float((g["above_sma50"] == 1).mean()) * 100, 1) if "above_sma50" in g else "",
            "score_avg": _mean(g, "score"),
            "n": int(len(g)),
        })
    return pd.DataFrame(rows)


def _mean(g, col):
    if col not in g.columns:
        return ""
    s = pd.to_numeric(g[col], errors="coerce").dropna()
    if not len(s):
        return ""
    return round(float(s.mean()), 2)


def etf_sectors(close, scores, sector_etfs, macro_df):
    rows = []
    macro = macro_df.set_index("ticker") if macro_df is not None and len(macro_df) else None
    for etf in sector_etfs:
        t = etf["ticker"]
        rec = {"ticker": t, "name": etf["name"], "group_name": etf.get("group", etf["name"])}
        if close is not None and t in close.columns:
            s = close[t].dropna()
            if len(s) > 5:
                rec["day_pct"] = _ret(s, 1)
                rec["week_pct"] = _ret(s, 5)
                rec["month_pct"] = _ret(s, 21)
                rec["month3_pct"] = _ret(s, 63)
                rec["ytd_pct"] = _ytd(s)
                if "SPY" in close.columns:
                    spy = close["SPY"].reindex(s.index).dropna()
                    both = s.reindex(spy.index).dropna()
                    if len(both) > 63 and len(spy) > 63:
                        rec["rs_3m_pct"] = round((both.iloc[-1] / both.iloc[-64] - spy.iloc[-1] / spy.iloc[-64]) * 100, 2)
        members = _members(scores, etf)
        if len(members):
            rec["score_avg"] = _mean(members, "score")
            rec["n_stocks"] = int(len(members))
            rec["pct_above_sma50"] = round(float((members["above_sma50"] == 1).mean()) * 100, 1)
        if macro is not None and t in macro.index:
            m = macro.loc[t]
            for k in ("macro_growth", "macro_inflation", "macro_jobs", "macro_score"):
                rec[k] = m.get(k)
        rows.append(rec)
    return pd.DataFrame(rows)


def _members(scores, etf):
    if scores is None or len(scores) == 0:
        return scores.iloc[0:0]
    group = etf.get("group")
    base = scores[scores["sector"] == group] if group else scores.iloc[0:0]
    ticker = etf["ticker"]
    if ticker in ("XLK", "XLV", "XLF", "XLI", "XLC", "XLY", "XLP", "XLE", "XLU", "XLRE", "XLB"):
        return base
    key = etf["name"].lower()
    ind = scores["industry"].fillna("").str.lower() if "industry" in scores.columns else pd.Series("", index=scores.index)
    for needle, code in INDUSTRY_ETF:
        if code == ticker:
            extra = scores[ind.str.contains(needle)]
            return pd.concat([base, extra]).drop_duplicates("ticker")
    return base


def _ret(s, n):
    if len(s) <= n or s.iloc[-1 - n] == 0:
        return ""
    return round(float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100, 2)


def _ytd(s):
    year = s.index[-1].year
    sub = s[s.index.year == year]
    if len(sub) < 2 or sub.iloc[0] == 0:
        return ""
    return round(float(sub.iloc[-1] / sub.iloc[0] - 1) * 100, 2)


def breadth_history(close):
    """Share of stocks above each moving average, on sessions where stocks traded.

    A holiday that only has a VIX print used to leave one blank row in the price
    panel. The next 20, 50, 100, and 200 sessions then had no average, and those
    missing readings were stored as 0. Missing stays blank. A stock with no price
    or no average that day is left out of the count. It is not treated as below.
    """
    if close is None or close.empty:
        return pd.DataFrame()
    drop = [c for c in list(MACRO_WEIGHT) + ["SPY", "^VIX", "QQQ"] if c in close.columns]
    px = close.drop(columns=drop, errors="ignore")
    if px.shape[1] == 0:
        return pd.DataFrame()
    traded = px.notna().sum(axis=1)
    if int(traded.max()) == 0:
        return pd.DataFrame()
    # Half the usual names, and at least 20. That drops a holiday row and keeps a normal session.
    floor = max(20, int(traded.max() * 0.5))
    px = px.loc[traded >= floor]
    if px.empty:
        return pd.DataFrame()
    shares = {}
    for n, name in ((20, "pct_above_sma20"), (50, "pct_above_sma50"), (100, "pct_above_sma100"), (200, "pct_above_sma200")):
        sma = px.rolling(n, min_periods=n).mean()
        valid = px.notna() & sma.notna()
        count = valid.sum(axis=1)
        above = (px > sma) & valid
        share = above.sum(axis=1) / count.where(count >= 20)
        shares[name] = share * 100
    ready = shares["pct_above_sma20"].dropna()
    if ready.empty:
        return pd.DataFrame()
    idx = px.index[px.index >= ready.index[0]][-140:]
    rows = []
    for d in idx:
        row = {"date": str(pd.Timestamp(d).date())}
        for name, series in shares.items():
            v = series.loc[d]
            if pd.notna(v):
                row[name] = round(float(v), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def market_row(close, breadth, pcr_df, fred, xratio, updated, asof, n, scores):
    row = {"updated_pt": updated, "price_as_of": asof, "universe_n": n}
    if close is not None and "SPY" in close.columns:
        s = close["SPY"].dropna()
        if len(s):
            row["spy_price"] = round(float(s.iloc[-1]), 2)
            if len(s) > 1 and s.iloc[-2]:
                row["spy_day_pct"] = round(float(s.iloc[-1] / s.iloc[-2] - 1) * 100, 2)
    # QQQ is filled only when that ETF is already in the price file. No separate download.
    if close is not None and "QQQ" in close.columns:
        q = close["QQQ"].dropna()
        if len(q) > 1 and q.iloc[-2]:
            row["qqq_day_pct"] = round(float(q.iloc[-1] / q.iloc[-2] - 1) * 100, 2)
    if close is not None and "^VIX" in close.columns:
        v = close["^VIX"].dropna()
        if len(v):
            row["vix"] = round(float(v.iloc[-1]), 2)
    if breadth is not None and len(breadth):
        last = breadth.iloc[-1]
        for k in ("pct_above_sma20", "pct_above_sma50", "pct_above_sma100", "pct_above_sma200"):
            row[k.replace("pct_above_", "breadth_")] = last.get(k)
        if len(breadth) > 5:
            row["breadth_sma50_week_ago"] = breadth.iloc[-6].get("pct_above_sma50")
    if scores is not None and len(scores):
        if "verdict" in scores.columns:
            row["buy_count"] = int((scores["verdict"].astype(str) == "BUY").sum())
        day = pd.to_numeric(scores["day_pct"], errors="coerce")
        row["advancers"] = int((day > 0).sum())
        row["decliners"] = int((day < 0).sum())
        dist = pd.to_numeric(scores["dist_52w_high_pct"], errors="coerce")
        row["highs_52w"] = int((dist >= -1).sum())
        # lows: price near 252-day low is not in dist. leave blank if we didn't compute it
        if "near_low" in scores.columns:
            row["lows_52w"] = int(scores["near_low"].sum())
    if pcr_df is not None and len(pcr_df):
        eq = pcr_df[pcr_df["name"] == "EQUITY PUT/CALL RATIO"]
        use = eq if len(eq) else pcr_df
        last = use.iloc[-1]
        row["put_call"] = last.get("value")
        row["put_call_ma5"] = last.get("ma5")
        row["put_call_zone"] = last.get("zone")
        row["put_call_name"] = last.get("name")
    if fred:
        row["fred_dgs10"] = fred.get("DGS10")
        row["fred_t10y2y"] = fred.get("T10Y2Y")
    if xratio is not None and len(xratio):
        row["xly_xlp"] = round(float(xratio.iloc[-1]["ratio"]), 3)
    return pd.DataFrame([row])


def freshness_table(scores):
    fields = [k for k, _ in FIN_SPECS] + ["pts_analyst", "pts_institutional", "pts_insider", "pts_earnings", "pts_trend", "pts_sector"]
    rows = []
    n = len(scores)
    for f in fields:
        if f not in scores.columns or n == 0:
            rows.append({"field": f, "n_missing": n, "n_present": 0})
            continue
        present = pd.to_numeric(scores[f], errors="coerce").notna().sum()
        rows.append({"field": f, "n_missing": int(n - present), "n_present": int(present)})
    return pd.DataFrame(rows)


def help_rows():
    return [
        ("What this is", "Nick's Stock Desk is a research screen for stocks. It does not place trades and it does not connect to a broker. Nothing here is a recommendation to buy or sell."),
        ("Stocks only", "The wheel page is a stock screen. The put and call walls page is market mood only. The Options page is education on debit spreads. It does not place a trade and it does not connect to a broker."),
        ("The score", "Each financial measure is +1, 0, or -1 versus that company's own recent history. Lower is better for forward P/E, trailing P/E, price/sales, debt/equity, and price/free cash flow. Higher is better for revenue growth, EPS growth, return on equity, and dividend yield. Analyst rating can be +2 to -2. Funds, insiders, the price trend, the oscillator, the latest earnings report, and the sector each add a small point. The score is the sum of the points we actually have."),
        ("Missing data", "A missing number is left blank and marked n/a. It is not stored as zero and it does not add or subtract a point. The freshness page counts the blanks."),
        ("Forward P/E history", "Free data does not include a history of forward estimates. The baseline for forward P/E is the 3-year average of year-end trailing P/E. The column forward_pe_avg_basis says so."),
        ("Versus the industry", "The industry figure is the middle value of the other stocks in the same sector inside this desk's universe. It is not a paid industry database. If fewer than four peers have a number, the comparison is blank."),
        ("Verdicts", "BUY, HOLD, and AVOID are research labels. A high score that is extended, in a downtrend, or missing most of its financials is labeled HOLD instead of BUY. Entry, stop, and target are a plan for study, not an order."),
        ("Targets", "You will see an analyst target (median if we have it, otherwise the mean), a price/free-cash-flow target, a PEG-style target, and a blend of whichever of those exist. The trade target is separate: it is an entry-zone plan using the recent daily range."),
        ("Backtest", "Once a month the job asks what the score would have been using only data that was already public, then looks at the next 1, 4, and 12 weeks. Read the headline on the backtest page. If it says there is no clear edge, believe that. Past results are not future results. Delisted stocks are not in the test."),
        ("13F and insiders", "The 13F page is a summary: how many shares were increased versus decreased in the latest public holdings summary, plus a few of the largest holders. It is not a reprint of every fund, which is why the page stays fast. Insider points use open-market buy and sell counts from the last three months."),
        ("Put/call and walls", "The put/call ratio is the CBOE equity ratio, with a 5-day average. Lines mark fear and greed. Option walls are open interest by strike for a short focus list, refreshed once a day. They are sentiment, not a trade."),
        ("AAII", "AAII does not offer a free machine-readable survey. That page stays marked MISSING on purpose. We do not guess the number. Use the put/call page for a free mood gauge."),
        ("Official S&P 500 P/E", "There is no free official daily S&P 500 earnings series this desk can rely on, and FRED is often blocked on the computer that updates the files. The historical P/E chart is the median trailing P/E of the stocks on this desk. The official column stays MISSING."),
        ("Macro", "The macro page compares the latest published number with the forecast for a short list of US reports, then applies a simple, written-down map to each sector ETF. It is a sketch, not a forecast."),
        ("Rate limits", "Prices are downloaded in batches. Fundamentals, analyst ratings, 13F, insider counts, and option chains are fetched at most once a day and reused until the next session. If a source fails, the previous file is kept and the updates log says CACHED."),
        ("The lists", "The desk scores the S&P 500, the Nasdaq-100, and a short growth list. A stock in more than one list appears once. index_membership shows SP500, NDX100, and Growth together, so you can filter the page. Each list has an on/off switch in config.json. Your holdings and watchlist are always included."),
        ("VCP scanner", "This page follows Nick's TradingView indicator: the 8-point trend template, the contraction count, the buy point, and the exit (7% stop, move to breakeven after 2.5 times the risk, sell part at 20%, trail a close under the 20-day average, climax warning at 25% in 10 days). READY means the template is 8 of 8 and price is still under the buy point. BROKEN OUT today means today's close crossed that point on big volume. Before a buy prints, the stop and target are the same percents measured from the buy point. The indicator itself waits for the breakout close. trend_score is written as '8 of 8' so a sheet does not read it as a date."),
        ("CANSLIM scanner", "C and A are the year-ago EPS change from the cached filings. N is how close the price is to its 52-week closing high. S is the 20-day average volume. L is the relative-strength percentile versus SPY inside this universe. I is the cached institutional increase versus decrease. M is SPY, and QQQ when that price is already on file, versus the 21, 50, and 200 day averages. A blank that says not verified was not in the cache. It is not a guess. This page does not set a stop or a target."),
        ("Box and flag", "A box is a tight sideways range that closes out the top on above-average volume. A flag is a sharp rise, a short shallow pause, then a close above the pause on volume. Stop and target are the pattern levels described on the page. These two are desk rules. They are not the TradingView indicator."),
        ("Breakdowns", "A breakdown is the box turned over. The close is under the 50-day average, the 50-day is under the 200-day, and the 200-day is not rising. The base is a 20 to 60 day range that tightens, no wider than 10%. BROKEN DOWN today means the close is under that low on volume at least 1.4 times the 50-day average. WATCHING means the close is within 3% of that low, or under it without that volume. The chart shows the base low and a stop at the base high. The scan uses cached prices only."),
        ('High volume', "Volume is how many shares changed hands. This page looks only at the daily prices and volume the desk already saves. Nothing extra is downloaded. Volume spike today: a stock traded at least 2 times its normal amount today (you can switch to 1.5, 3, or 5 times). Normal means the average of the 50 trading days before today. Up or down on volume: BUYING in green means the price closed higher on that big day. SELLING in red means it closed lower. Unusual volume streak: volume was above normal 3 or more days in a row. Quiet before a move: trading has gone very quiet (the last 10 days are under 0.6 times normal) while the price is within 5% of its 3-month high and above its 50-day average. Quiet spells like that sometimes come before a bigger move, up or down. During market hours today's volume is still adding up, so spikes look smaller until the close. Tap a row to see the price chart with volume bars and an amber line for the 50-day average volume. Research only. The switch is scanner_volume in config.json."),
        ("Options", "Education, not financial advice. The Options page lists a call debit spread for each of the first 15 buy setups, including names greyed by the market filter, and a put debit spread for the first 15 breakdowns, with BROKEN DOWN today first. Expiry is 45 to 60 days, or 30 to 75 when that is the only window. The long strike is about 0.55 to 0.65 delta. The short strike is about 0.30 delta, or the setup target when that price is closer to the stock. The debit has to be at most 40% of the width. A name is skipped for earnings before expiry, implied vol more than 1.3 times the 20-day realized vol, open interest under 500, a wide bid-ask, a stock under $10, or average volume under 1 million. Price Check compares the debit with a blend of 20-day and 60-day realized vol and at-the-money implied vol: CHEAP under 0.9, FAIR from 0.9 to 1.2, OVERPAYING above 1.2. Quotes are Cboe's free delayed feed, refreshed on a full run and around 10:30 and 3:30 ET, not every hour. If that feed fails, the last good quotes stay and the page shows their as-of time. Greeks are computed here. This desk never places a trade and it does not connect to a broker."),
        ("Leaders", "Leaders puts a VCP that is ready or broken out today together with a strict CANSLIM qualify. A name on both uses the VCP buy point, stop, and target. A name on only one still shows, and any missing letter stays not verified."),
        ("52-week highs and lows", "The 52-week high is the highest intraday high of the last 252 trading sessions, and the 52-week low is the lowest intraday low. A new high today means the close is at or above the prior 252-session high. A new low today means the close is at or below the prior 252-session low. A stock can touch a new intraday high and still not count if it does not close there. Near the high means the close is within 5% of that high. That band is the zone Minervini prefers. A high on volume is a new high with volume at least 1.5 times the 50-day average. The page is research only. It does not place trades or send alerts. The count chart is built from the same cached daily bars."),
        ("Buy setups", "Research list, not a recommendation. This desk never places trades. A stock is listed when VCP, Box, Flag, or CANSLIM is READY or BROKEN OUT today, the verdict is BUY, the close is above the 50-day and the 200-day averages, and the risk from the entry to the stop is 8% or less. HOLD and AVOID stay off the list. The market filter, on by default, also requires SPY to be in an uptrend: the close above its 50-day and 200-day averages, and the 50-day above the 200-day. QQQ is shown the same way and does not decide the list. When SPY is not in an uptrend the list is empty and the page can still show those names greyed. Entry is the buy point of the strongest scanner that agrees. VCP uses the Minervini pivot. The stop is the tighter of 7% under the entry or the setup's own stop, and it is never above the entry. Target 1 is 20% above the entry, or 20% above the breakout close. Target 2 is the entry plus three times the dollar risk. Many breakouts fail, which is why the stop is always shown. No alerts are sent."),
        ("Sector rotation", "The graph compares the 11 SPDR sector ETFs with SPY using prices already in the cache. No new download. RS is the ETF close divided by SPY. RS-Ratio is 100 plus the z-score of that ratio, after a moving average, versus its own rolling mean. RS-Momentum is 100 plus the z-score of the change in RS-Ratio. Sample standard deviation, and a flat window scores 0 so the line sits at 100. 100 is the center and counts as the strong side. Leading is top right, Weakening bottom right, Lagging bottom left, Improving top left. Daily, weekly, and monthly use sector_rotation.windows (daily 10/40/5/40, weekly 6/26/4/26, monthly 3/12/2/12 for smooth, ratio window, change span, and momentum window). The score is 0 to 100. It blends 1, 3, and 6 month relative strength (21, 63, and 126 sessions, ETF return minus SPY, clipped from -15 to +15 points), the share of the sector's stocks above the 50-day and the 200-day, the share within 5% of a 252-session high, the share on a buy setup, the average desk score clipped from -4 to 12, the share of BUY verdicts, and a weekly quadrant bonus (Leading 100, Improving 70, Weakening 40, Lagging 15). A buy setup here is a name on the buy-setups list when that list is built. Otherwise it is READY or broken out today on VCP, box, flag, or CANSLIM, with verdict BUY and price above both averages. Weights are sector_rotation.weight.* and they are renormalized over the factors that exist. A missing factor is not a zero. The 10-year yield and the 10-year minus 2-year spread are the only macro series on file. Dollar, oil, and gold are not, so the page says they are missing. The tendency notes are general history, not a forecast. This page does not send a notification."),
        ('What the company does', "Under a stock's name, next to its chart, you will see one short line that says what the company does, like Makes iPhones and Macs and runs the App Store. These lines are written once and saved in data/company_blurbs.csv. They are not downloaded every hour. If a stock has no line, nothing is shown. The switch is company_blurbs in config.json."),
        ("Your list", "Edit input/holdings.csv and input/my_watchlist.csv to change the portfolio and the watchlist. Example rows are marked example=yes. Replace them with your own shares and cost. The desk still will not place a trade."),
        ('Missed updates', 'The desk updates on New York market time all year, Monday to Friday: every hour from 10:15 to 17:15 ET, plus the big evening update at 18:30 ET. In Pacific time that is 7:15 AM to 2:15 PM, and 3:30 PM, in summer and winter. GitHub sometimes skips or delays a scheduled update. A small watchdog checks four times an hour. If an update was due, none is running or waiting, and none started for that time slot, it starts exactly one make-up update of the same kind. It never adds extra runs, never retries a run that failed, and does not make up a slot more than 3 hours old. Some runs in the Actions list stop after a few seconds. That is on purpose: they are the clock-change twin of a real slot. The switch is self_heal_schedule in config.json. Turn it off and only the regular schedule runs.'),
        ("Updates log", "OK means the source answered and its columns have values. PARTIAL means a column is blank on every row. CACHED means this run failed and an older copy was used. MISSING means there is no copy at all. A blank cell is missing data. It is not a zero."),
        ("The Google Sheet", "The sheet is filled by the Desk menu, not by IMPORTDATA. Desk > Refresh data now copies each file into the tab with the same name. Desk > Install hourly auto-refresh reloads about once an hour. The Setup tab shows the time of the last refresh. A blank cell means the number was missing. It is not a zero."),
    ]


def settings_rows(cfg):
    rows = [{"setting": "feature." + k, "value": v} for k, v in cfg["features"].items()]
    buy_cfg = cfg.get("buy_setups") or {}
    rows.append({"setting": "buy_setups.market_filter", "value": buy_cfg.get("market_filter", True)})
    for k, v in (cfg.get("indexes") or {}).items():
        rows.append({"setting": "index." + k, "value": v})
    for k, v in cfg.get("scoring", {}).items():
        rows.append({"setting": "scoring." + k, "value": v})
    rot = cfg.get("sector_rotation") or {}
    for tf, spec in (rot.get("windows") or {}).items():
        if isinstance(spec, dict):
            for key, value in spec.items():
                rows.append({"setting": "sector_rotation.windows.%s.%s" % (tf, key), "value": value})
    for key, value in (rot.get("weights") or {}).items():
        rows.append({"setting": "sector_rotation.weight." + str(key), "value": value})
    for key in ("near_high_pct", "w52_bars", "tail_keep", "macro_lookback", "yield_flat_band"):
        if key in rot:
            rows.append({"setting": "sector_rotation." + key, "value": rot[key]})
    rows.append({"setting": "label", "value": DISCLAIMER})
    return pd.DataFrame(rows)
