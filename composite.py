"""Composite Rating, 1 to 99, a close copy of the IBD idea: one number that blends earnings, price strength,
how close the stock is to its high, and the quality of its sales and margins.

IBD's own formula is private. Ours uses only data the desk already has, and every weight is in config.json
(composite block). Each piece is turned into a 0 to 100 percentile across the whole desk, the pieces that exist
are blended with their weights, and the blend is ranked across the desk again so the final 1 to 99 spreads out
the same way the RS Rating and EPS Rating do.

  EPS Rating               30%   scores.eps_rating (ms_screens.eps_ratings), already 1 to 99
  RS Rating                30%   scores.rs (relative_strength), already 1 to 99
  Close to 52-week high    15%   percentile of dist_52w_high_pct (0 is at the high, the more negative the worse)
  Sales growth             15%   latest quarter's sales versus a year ago (saved SEC quarters); else the yearly rev_growth
  Margins                  10%   net margin over the last four quarters; else ROE

Missing pieces are left out and the other weights are scaled up to fill. A stock needs the RS Rating and at
least min_parts pieces in all (default 3), otherwise it has no Composite Rating. It is never shown as 0.
Research only. Not a trade signal.
"""
import numpy as np
import pandas as pd

DEFAULTS = {
    "w_eps": 0.30,
    "w_rs": 0.30,
    "w_high": 0.15,
    "w_sales": 0.15,
    "w_margin": 0.10,
    "min_parts": 3,
}


def settings(cfg=None):
    out = dict(DEFAULTS)
    block = (cfg or {}).get("composite") or {}
    for k in DEFAULTS:
        if k in block and block[k] is not None:
            try:
                out[k] = float(block[k]) if k != "min_parts" else int(block[k])
            except (TypeError, ValueError):
                pass
    return out


def _pct_rank(series):
    """0 to 100 percentile within the column; NaN stays NaN."""
    s = pd.to_numeric(series, errors="coerce")
    r = s.rank(pct=True, method="average")
    return (r * 100.0).where(s.notna())


def fundamentals_inputs(quarters):
    """ticker, sales_growth (latest quarter vs a year ago, %), net_margin (last four quarters, %) from the saved quarters."""
    cols = ["ticker", "sales_growth", "net_margin"]
    if quarters is None or not len(quarters) or not {"ticker", "frame", "revenue"} <= set(quarters.columns):
        return pd.DataFrame(columns=cols)
    q = quarters.copy()
    q["ticker"] = q["ticker"].astype(str).str.strip().str.upper()
    q["revenue"] = pd.to_numeric(q["revenue"], errors="coerce")
    q["net_income"] = pd.to_numeric(q["net_income"], errors="coerce") if "net_income" in q.columns else np.nan
    q = q[q["frame"].astype(str).str.match(r"^CY\d{4}Q[1-4]$")].drop_duplicates(["ticker", "frame"], keep="last")
    q["key"] = q["frame"].str.slice(2, 6).astype(int) * 4 + q["frame"].str.slice(7, 8).astype(int)
    rows = []
    for t, g in q.groupby("ticker", sort=False):
        g = g.sort_values("key")
        keys = dict(zip(g["key"], zip(g["revenue"], g["net_income"])))
        top = int(g["key"].iloc[-1])
        growth = np.nan
        now, prev = keys.get(top), keys.get(top - 4)
        if now and prev and pd.notna(now[0]) and pd.notna(prev[0]) and prev[0] > 0:
            growth = (now[0] / prev[0] - 1.0) * 100.0
        margin = np.nan
        last4 = [keys.get(top - i) for i in range(4)]
        if all(x is not None and pd.notna(x[0]) and pd.notna(x[1]) for x in last4):
            rev = sum(x[0] for x in last4)
            if rev > 0:
                margin = sum(x[1] for x in last4) / rev * 100.0
        rows.append((t, growth, margin))
    return pd.DataFrame(rows, columns=cols)


def composite_ratings(scores, quarters=None, cfg=None):
    """Series of 1 to 99 Composite Ratings aligned to scores.index (NaN when a stock cannot be rated)."""
    st = settings(cfg)
    if scores is None or not len(scores):
        return pd.Series(dtype=float)
    df = pd.DataFrame(index=scores.index)
    df["ticker"] = scores["ticker"].astype(str).str.strip().str.upper()
    num = lambda c: pd.to_numeric(scores[c], errors="coerce") if c in scores.columns else pd.Series(np.nan, index=scores.index)
    eps, rs, off = num("eps_rating"), num("rs"), num("dist_52w_high_pct")
    fin = fundamentals_inputs(quarters).drop_duplicates("ticker").set_index("ticker")
    sales = df["ticker"].map(fin["sales_growth"]) if len(fin) else pd.Series(np.nan, index=scores.index)
    margin = df["ticker"].map(fin["net_margin"]) if len(fin) else pd.Series(np.nan, index=scores.index)
    sales = sales.where(sales.notna(), num("rev_growth"))
    margin = margin.where(margin.notna(), num("roe"))
    # A rating of 0 or below 1 is not a rating.
    eps = eps.where((eps >= 1) & (eps <= 99))
    rs = rs.where((rs >= 1) & (rs <= 99))
    parts = {
        "w_eps": eps,
        "w_rs": rs,
        "w_high": _pct_rank(off),
        "w_sales": _pct_rank(sales.clip(-100, 500)),
        "w_margin": _pct_rank(margin.clip(-100, 100)),
    }
    total = pd.Series(0.0, index=scores.index)
    weight = pd.Series(0.0, index=scores.index)
    count = pd.Series(0, index=scores.index)
    for key, vals in parts.items():
        w = float(st[key])
        if w <= 0:
            continue
        have = vals.notna()
        total = total + vals.fillna(0.0) * w * have
        weight = weight + w * have
        count = count + have.astype(int)
    blend = (total / weight.where(weight > 0)).where(rs.notna() & (count >= int(st["min_parts"])))
    ranked = blend.rank(pct=True, method="average")
    out = (1.0 + ranked * 98.0).round()
    return out.where(blend.notna()).clip(1, 99)


def attach(scores, quarters=None, cfg=None):
    """Copy of scores with composite_rating (integer, blank when missing, never 0)."""
    out = scores.copy()
    if not len(out):
        out["composite_rating"] = []
        return out
    comp = composite_ratings(out, quarters, cfg)
    out["composite_rating"] = ["" if pd.isna(v) else int(v) for v in comp]
    return out
