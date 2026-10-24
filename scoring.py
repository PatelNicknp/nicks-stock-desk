"""Desk score, verdicts, targets, alerts, and the honest backtest.

The score adds only the parts we actually have. A missing part is left out.
It is not stored as zero, and it is not shown as zero.
"""
import numpy as np
import pandas as pd

FIN_SPECS = [
    ("forward_pe", False),
    ("ttm_pe", False),
    ("ps", False),
    ("de", False),
    ("pfcf", False),
    ("rev_growth", True),
    ("eps_growth", True),
    ("roe", True),
    ("div_yield", True),
]
PERCENT_FIELDS = {
    "day_pct", "rev_growth", "rev_growth_avg", "eps_growth", "eps_growth_avg",
    "roe", "roe_avg", "div_yield", "div_yield_avg", "rs_spy_3m", "dist_52w_high_pct",
    "gross_margin", "operating_margin", "net_margin", "gain_pct", "day_pnl_pct",
    "ret_1d", "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_ytd",
    "breadth_sma20", "breadth_sma50", "breadth_sma100", "breadth_sma200",
    "pct_above_sma50", "excess_3m",
}


def points_vs_avg(now, avg, higher_is_better, band=0.05):
    """+1 / 0 / -1 versus the company's own baseline. None when either side is missing."""
    if now is None or avg is None:
        return None
    try:
        now = float(now)
        avg = float(avg)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(now) or not np.isfinite(avg):
        return None
    if abs(avg) < 1e-12:
        if abs(now) < 1e-12:
            return 0
        better = (now > 0) if higher_is_better else (now < 0)
        return 1 if better else -1
    rel = now / avg - 1.0
    if abs(rel) <= band:
        return 0
    improved = (rel > 0) if higher_is_better else (rel < 0)
    return 1 if improved else -1


def nansum_strict(values):
    nums = []
    for v in values:
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if np.isfinite(x):
            nums.append(x)
    if not nums:
        return None
    return int(round(sum(nums)))


def analyst_points(mean, count, cfg):
    if mean is None or not np.isfinite(mean):
        return None
    n = 0 if count is None or not np.isfinite(count) else int(count)
    if mean <= cfg["analyst_strong_at"] and n >= cfg["min_analysts_for_strong"]:
        return 2
    if mean <= cfg["analyst_buy_at"]:
        return 1
    if mean >= cfg["analyst_strong_sell_at"]:
        return -2
    if mean >= cfg["analyst_sell_at"]:
        return -1
    return 0


def institutional_points(increased, decreased):
    if increased is None or decreased is None:
        return None
    if not np.isfinite(increased) or not np.isfinite(decreased):
        return None
    if increased > decreased * 1.10:
        return 1
    if decreased > increased * 1.10:
        return -1
    return 0


def insider_points(buys, sells):
    if buys is None or sells is None:
        return None
    if not np.isfinite(buys) or not np.isfinite(sells):
        return None
    if buys >= 1 and buys > sells:
        return 1
    if sells >= 5 and sells > buys * 2:
        return -1
    return 0


def trend_points(price, sma20, sma50):
    if any(v is None or not np.isfinite(v) for v in (price, sma20, sma50)):
        return None
    if price > sma20 and price > sma50:
        return 1
    if price < sma20 and price < sma50:
        return -1
    return 0


def oscillator_points(rsi, rsi_prev):
    if rsi is None or not np.isfinite(rsi):
        return None
    rising = rsi_prev is not None and np.isfinite(rsi_prev) and rsi > rsi_prev
    if 45 <= rsi <= 70 and rising:
        return 1
    if rsi >= 75 or rsi <= 30:
        return -1
    return 0


def sector_points(excess):
    """excess is a decimal (0.03 = 3 percent)."""
    if excess is None or not np.isfinite(excess):
        return None
    if excess > 0.02:
        return 1
    if excess < -0.02:
        return -1
    return 0


def earnings_points(eps_flag, rev_flag):
    """eps_flag / rev_flag are 'beat', 'miss', 'inline', or None."""
    known = [f for f in (eps_flag, rev_flag) if f in ("beat", "miss", "inline")]
    if not known:
        return None
    if eps_flag in ("beat", "miss", "inline") and rev_flag in ("beat", "miss", "inline"):
        if eps_flag == "beat" and rev_flag == "beat":
            return 1
        if eps_flag == "miss" and rev_flag == "miss":
            return -1
        return 0
    flag = known[0]
    if flag == "beat":
        return 1
    if flag == "miss":
        return -1
    return 0


def beat_flag(actual, estimate, band=0.01):
    if actual is None or estimate is None:
        return None
    if not np.isfinite(actual) or not np.isfinite(estimate) or estimate == 0:
        return None
    rel = actual / estimate - 1
    if rel > band:
        return "beat"
    if rel < -band:
        return "miss"
    return "inline"


def timing_flag(price, sma20, sma50, sma200, high252, entry_low, entry_high, rsi):
    if any(v is None or not np.isfinite(v) for v in (price, sma20, sma50)):
        return None
    if price < sma50 and sma20 < sma50:
        return "Downtrend"
    if high252 is not None and np.isfinite(high252) and high252 > 0 and price >= high252 * 0.99:
        return "Breakout"
    if entry_low is not None and entry_high is not None and entry_low <= price <= entry_high * 1.005:
        return "In entry zone"
    if sma20 > sma50 and price < sma20 and price >= sma50 * 0.99:
        return "Pullback"
    extended = price > sma20 * 1.08 or (rsi is not None and np.isfinite(rsi) and rsi >= 70)
    if extended:
        return "Extended"
    if price > sma20 and sma20 > sma50:
        return "Uptrend"
    return "Sideways"


def plan_levels(price, sma20, sma50, atr, target_rr, stop_atr):
    if any(v is None or not np.isfinite(v) or v <= 0 for v in (sma20, atr)):
        return None, None, None, None
    entry_high = float(sma20)
    if sma50 is not None and np.isfinite(sma50) and sma50 < sma20:
        entry_low = float(min(sma20, max(sma50, sma20 - atr)))
    else:
        entry_low = float(sma20 - atr)
    if entry_low >= entry_high:
        entry_low = entry_high - atr
    entry_low = max(entry_low, 0.01)
    stop = entry_low - stop_atr * atr
    if stop <= 0 or stop >= entry_low:
        stop = entry_low * 0.93
    mid = (entry_low + entry_high) / 2.0
    risk = mid - stop
    trade_target = mid + target_rr * risk if risk > 0 else None
    return entry_low, entry_high, stop, trade_target


def valuation_targets(fin, target_median, target_mean):
    """Analyst, P/FCF, and PEG-style targets. Missing stays missing."""
    analyst = None
    kind = None
    if target_median is not None and np.isfinite(target_median) and target_median > 0:
        analyst, kind = float(target_median), "median"
    elif target_mean is not None and np.isfinite(target_mean) and target_mean > 0:
        analyst, kind = float(target_mean), "mean"
    pfcf_t = None
    if fin.get("pfcf_avg") and fin.get("fcf_per_share") and fin["pfcf_avg"] > 0 and fin["fcf_per_share"] > 0:
        pfcf_t = float(fin["pfcf_avg"] * fin["fcf_per_share"])
    peg_t = None
    g = fin.get("eps_growth")
    eps = fin.get("eps")
    if g is not None and eps is not None and eps > 0 and 0.05 <= g <= 0.40:
        # Fair P/E equals the growth rate in percent (a 15% grower is compared with a P/E of 15).
        peg_t = float(eps * (g * 100.0))
    parts = [x for x in (analyst, pfcf_t, peg_t) if x is not None]
    blended = float(np.mean(parts)) if parts else None
    return analyst, kind, pfcf_t, peg_t, blended, len(parts)


def decide_verdict(score, timing, n_fin, price, stop, cfg):
    if score is None:
        return None
    if score >= cfg["buy_at"]:
        verdict = "BUY"
    elif score >= cfg["hold_at"]:
        verdict = "HOLD"
    else:
        verdict = "AVOID"
    if verdict == "BUY" and timing == "Extended" and score < cfg["downgrade_extended_below"]:
        verdict = "HOLD"
    if verdict == "BUY" and timing == "Downtrend":
        verdict = "HOLD"
    if verdict == "BUY" and n_fin < cfg["min_fin_for_buy"]:
        verdict = "HOLD"
    if price is not None and stop is not None and np.isfinite(price) and np.isfinite(stop) and price < stop and score < cfg["buy_at"]:
        verdict = "AVOID"
    return verdict


def _phrase(points, good, bad):
    if points is None:
        return None
    if points > 0:
        return good
    if points < 0:
        return bad
    return None


def plain_reason(row):
    """One plain-English line. Research label, not an order."""
    bits = []
    mapping = [
        ("pts_rev_growth", "revenue is growing faster than this company's own history", "revenue is growing slower than this company's own history"),
        ("pts_eps_growth", "earnings are growing faster than its own history", "earnings are growing slower than its own history"),
        ("pts_roe", "return on equity is above its own history", "return on equity is below its own history"),
        ("pts_forward_pe", "the forward P/E is cheaper than its own history", "the forward P/E is richer than its own history"),
        ("pts_ttm_pe", "the trailing P/E is cheaper than its own history", "the trailing P/E is richer than its own history"),
        ("pts_ps", "price to sales is cheaper than its own history", "price to sales is richer than its own history"),
        ("pts_de", "debt is lighter than its own history", "debt is heavier than its own history"),
        ("pts_pfcf", "price to free cash flow is cheaper than its own history", "price to free cash flow is richer than its own history"),
        ("pts_div_yield", "the dividend yield is above its own history", "the dividend yield is below its own history"),
        ("pts_trend", "the price is above both the 20-day and 50-day averages", "the price is below both the 20-day and 50-day averages"),
        ("pts_oscillator", "the oscillator is rising and not overbought", "the oscillator is stretched or weak"),
        ("pts_analyst", "analysts lean positive", "analysts lean negative"),
        ("pts_institutional", "funds added shares last quarter", "funds cut shares last quarter"),
        ("pts_insider", "insiders have been buying", "insiders have been selling"),
        ("pts_earnings", "the latest report beat estimates", "the latest report missed estimates"),
        ("pts_sector", "its sector has been stronger than the S&P 500", "its sector has been weaker than the S&P 500"),
    ]
    for key, good, bad in mapping:
        phrase = _phrase(row.get(key), good, bad)
        if phrase and key == "pts_analyst" and row.get(key) == 2:
            phrase = "analysts lean strongly positive"
        if phrase:
            bits.append(phrase)
    if not bits:
        lead = "There is not enough fresh data to describe a driver"
    else:
        shown = bits[:3]
        lead = shown[0][0].upper() + shown[0][1:]
        if len(shown) > 1:
            lead = lead + ", and " + ", and ".join(shown[1:])
    timing = row.get("timing")
    verdict = row.get("verdict")
    if verdict == "AVOID":
        tail = "The research label is AVOID."
    elif timing == "In entry zone":
        tail = "Price is inside the entry zone. The research label is %s." % (verdict or "unset")
    elif timing in ("Extended", "Breakout"):
        tail = "Price is extended, so the plan waits for a dip into the entry zone rather than chasing. The research label is %s." % (verdict or "unset")
    elif timing == "Downtrend":
        tail = "The trend is down. The research label is %s." % (verdict or "unset")
    elif row.get("n_fin") is not None and row.get("n_fin") < 5:
        tail = "A lot of the valuation data is missing, so it is left blank rather than scored as zero. The research label is %s." % (verdict or "unset")
    else:
        tail = "The research label is %s." % (verdict or "unset")
    text = lead + ". " + tail
    return text[:420]


def sma_alignment(price, sma20, sma50, sma100, sma200):
    parts = []
    for label, sma in (("20", sma20), ("50", sma50), ("100", sma100), ("200", sma200)):
        if sma is None or not np.isfinite(sma) or price is None:
            parts.append("%s n/a" % label)
        elif price > sma:
            parts.append("above %s" % label)
        else:
            parts.append("below %s" % label)
    return ", ".join(parts)


def confidence(n_fin):
    if n_fin is None:
        return None
    if n_fin >= 7:
        return "High"
    if n_fin >= 5:
        return "Medium"
    return "Low"


def score_components(fin, mkt, extra, cfg):
    """Return the internal (decimal) score record for one stock."""
    band = cfg["flat_band_pct"]
    pts = {}
    now_map = {
        "forward_pe": extra.get("forward_pe"),
        "ttm_pe": fin.get("ttm_pe"),
        "ps": fin.get("ps"),
        "de": fin.get("de"),
        "pfcf": fin.get("pfcf"),
        "rev_growth": fin.get("rev_growth"),
        "eps_growth": fin.get("eps_growth"),
        "roe": fin.get("roe"),
        "div_yield": fin.get("div_yield"),
    }
    avg_map = {
        "forward_pe": fin.get("ttm_pe_avg"),  # proxy: free data has no history of forward estimates
        "ttm_pe": fin.get("ttm_pe_avg"),
        "ps": fin.get("ps_avg"),
        "de": fin.get("de_avg"),
        "pfcf": fin.get("pfcf_avg"),
        "rev_growth": fin.get("rev_growth_avg"),
        "eps_growth": fin.get("eps_growth_avg"),
        "roe": fin.get("roe_avg"),
        "div_yield": fin.get("div_yield_avg"),
    }
    for key, higher in FIN_SPECS:
        pts[key] = points_vs_avg(now_map[key], avg_map[key], higher, band)
    pts_trend = trend_points(mkt.get("price"), mkt.get("sma20"), mkt.get("sma50"))
    pts_osc = oscillator_points(mkt.get("rsi"), mkt.get("rsi_prev"))
    pts_an = analyst_points(extra.get("analyst_mean"), extra.get("analyst_n"), cfg)
    pts_inst = institutional_points(extra.get("inst_up"), extra.get("inst_down"))
    pts_ins = insider_points(extra.get("insider_buys"), extra.get("insider_sells"))
    pts_earn = earnings_points(extra.get("eps_flag"), extra.get("rev_flag"))
    pts_sec = sector_points(extra.get("sector_excess"))
    tech = nansum_strict([pts_trend, pts_osc])
    fin_pts = nansum_strict([pts[k] for k, _ in FIN_SPECS])
    sent = nansum_strict([pts_an, pts_inst, pts_ins])
    score = nansum_strict([tech, fin_pts, sent, pts_earn, pts_sec])
    n_fin = sum(1 for k, _ in FIN_SPECS if pts[k] is not None)
    entry_low, entry_high, stop, trade_target = plan_levels(
        mkt.get("price"), mkt.get("sma20"), mkt.get("sma50"), mkt.get("atr"),
        cfg["target_rr"], cfg["stop_atr_mult"])
    timing = timing_flag(
        mkt.get("price"), mkt.get("sma20"), mkt.get("sma50"), mkt.get("sma200"),
        mkt.get("high252"), entry_low, entry_high, mkt.get("rsi"))
    analyst_t, analyst_kind, pfcf_t, peg_t, blended, blend_n = valuation_targets(
        fin, extra.get("target_median"), extra.get("target_mean"))
    verdict = decide_verdict(score, timing, n_fin, mkt.get("price"), stop, cfg)
    reward = None
    if trade_target and entry_low and entry_high and stop:
        mid = (entry_low + entry_high) / 2.0
        risk = mid - stop
        if risk > 0:
            reward = (trade_target - mid) / risk
    show_entry_low, show_entry_high, show_target = entry_low, entry_high, trade_target
    if verdict == "AVOID":
        show_entry_low = show_entry_high = show_target = None
    row = {
        "score": score,
        "pts_tech": tech, "pts_fin": fin_pts, "pts_sent": sent,
        "pts_earnings": pts_earn, "pts_sector": pts_sec,
        "pts_trend": pts_trend, "pts_oscillator": pts_osc,
        "pts_analyst": pts_an, "pts_institutional": pts_inst, "pts_insider": pts_ins,
        "n_fin": n_fin,
        "timing": timing,
        "entry_low": show_entry_low, "entry_high": show_entry_high,
        "stop": stop, "trade_target": show_target, "reward_risk": reward,
        "target_analyst": analyst_t, "target_analyst_kind": analyst_kind,
        "target_pfcf": pfcf_t, "target_peg": peg_t,
        "target_blended": blended, "target_blend_n": blend_n,
        "verdict": verdict,
        "forward_pe_avg_basis": "3-year average of year-end trailing P/E (forward P/E history is not free)",
    }
    for key, _ in FIN_SPECS:
        row["pts_" + key] = pts[key]
        row[key] = now_map[key]
        row[key + "_avg"] = avg_map[key]
    row["sma_alignment"] = sma_alignment(
        mkt.get("price"), mkt.get("sma20"), mkt.get("sma50"), mkt.get("sma100"), mkt.get("sma200"))
    row["confidence"] = confidence(n_fin)
    row["reason"] = plain_reason(row)
    return row


def add_industry(df, band):
    """Peer median inside the sector. Needs at least 4 other stocks with a value."""
    if df is None or len(df) == 0:
        return df
    out = df.copy()
    for key, higher in FIN_SPECS:
        ind_col = "ind_" + key
        pts_col = "pts_" + key + "_ind"
        out[ind_col] = np.nan
        out[pts_col] = np.nan
        if key not in out.columns or "sector" not in out.columns:
            continue
        for sector, idx in out.groupby("sector").groups.items():
            ids = list(idx)
            vals = out.loc[ids, key]
            for i in ids:
                others = vals.drop(labels=[i]).dropna()
                if len(others) < 4:
                    continue
                med = float(others.median())
                out.at[i, ind_col] = med
                pt = points_vs_avg(out.at[i, key], med, higher, band)
                if pt is not None:
                    out.at[i, pts_col] = pt
    return out


def grade_earnings(eps_flags, rev_growth_pts):
    """Rule-based A-F card. Returns (grade or None, note)."""
    flags = [f for f in eps_flags if f in ("beat", "miss", "inline")]
    if not flags:
        return None, "No earnings history in the free feed."
    last = flags[0]
    beats = sum(1 for f in flags if f == "beat")
    misses = sum(1 for f in flags if f == "miss")
    rate = beats / len(flags)
    growth_ok = rev_growth_pts is not None and rev_growth_pts >= 0
    if last == "miss" and misses >= 2 and rev_growth_pts is not None and rev_growth_pts < 0:
        grade = "F"
    elif last == "miss" and rate < 0.5:
        grade = "D"
    elif rate >= 0.75 and last == "beat":
        grade = "A" if growth_ok or rev_growth_pts is None else "B"
    elif rate >= 0.5 and last != "miss":
        grade = "B"
    elif last == "beat":
        grade = "C"
    else:
        grade = "C" if rate >= 0.25 else "D"
    note = "%d of the last %d reports beat the earnings estimate." % (beats, len(flags))
    if rev_growth_pts is None:
        note += " Revenue vs the company's own history was not available, so it was not scored as zero."
    return grade, note


def headline_tone(title):
    t = (title or "").lower()
    pos = ("beat", "beats", "raise", "raises", "upgrade", "record", "surge", "jump", "approval", "win ")
    neg = ("miss", "misses", "downgrade", "lawsuit", "probe", "investigation", "recall", "plunge", "layoff", "fraud", "cuts ", "cut ")
    if any(w in t for w in pos) and not any(w in t for w in neg):
        return 1, "Positive words in the headline."
    if any(w in t for w in neg) and not any(w in t for w in pos):
        return -1, "Negative words in the headline."
    if any(w in t for w in pos) and any(w in t for w in neg):
        return 0, "The headline mixes positive and negative words."
    return 0, "No strong positive or negative words. Headline only."


def build_alerts(curr, prev, jump, buy_at, hold_at):
    """New or changed verdicts and score crossings versus the previous run. No messages are sent."""
    rows = []
    if prev is None or len(prev) == 0 or curr is None or len(curr) == 0:
        return rows
    prev_i = prev.set_index("ticker")
    for _, r in curr.iterrows():
        t = r["ticker"]
        if t not in prev_i.index:
            if r.get("verdict"):
                rows.append(_alert(t, "new_stock", "First score for %s is %s (%s)." % (t, r.get("score"), r.get("verdict")), r))
            continue
        p = prev_i.loc[t]
        if isinstance(p, pd.DataFrame):
            p = p.iloc[-1]
        rv, pv = r.get("verdict"), p.get("verdict")
        if rv and pv and rv != pv:
            rows.append(_alert(t, "verdict_change", "%s changed from %s to %s." % (t, pv, rv), r, p))
        rs, ps = _f(r.get("score")), _f(p.get("score"))
        if rs is not None and ps is not None and abs(rs - ps) >= jump:
            rows.append(_alert(t, "score_jump", "%s score moved from %s to %s." % (t, int(ps), int(rs)), r, p))
        if rs is not None and ps is not None:
            for line, name in ((buy_at, "buy line"), (hold_at, "hold line")):
                if (ps < line <= rs) or (rs < line <= ps):
                    rows.append(_alert(t, "score_cross", "%s crossed the %s (%s)." % (t, name, line), r, p))
                    break
        if r.get("timing") == "Breakout" and p.get("timing") != "Breakout":
            rows.append(_alert(t, "breakout", "%s moved to a 52-week high area." % t, r, p))
        if r.get("timing") == "In entry zone" and p.get("timing") != "In entry zone":
            rows.append(_alert(t, "entry_zone", "%s pulled into the entry zone." % t, r, p))
        ib, pb = _f(r.get("insider_buys_3m")), _f(p.get("insider_buys_3m"))
        if ib is not None and ib >= 1 and (pb is None or ib > pb) and r.get("in_holdings") == "yes":
            rows.append(_alert(t, "insider_buy", "%s shows more insider buys than the last run." % t, r, p))
        price, stop = _f(r.get("price")), _f(r.get("stop"))
        pprice, pstop = _f(p.get("price")), _f(p.get("stop"))
        if r.get("in_holdings") == "yes" and price and stop and price < stop and not (pprice and pstop and pprice < pstop):
            rows.append(_alert(t, "below_stop", "%s closed under its stop level." % t, r, p))
    return rows


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x):
        return None
    return x


def _alert(ticker, kind, text, row, prev=None):
    return {
        "ticker": ticker,
        "kind": kind,
        "text": text,
        "score": row.get("score"),
        "score_prev": None if prev is None else prev.get("score"),
        "verdict": row.get("verdict"),
        "verdict_prev": None if prev is None else prev.get("verdict"),
        "price": row.get("price"),
    }


def edge_headline(top_cagr, spy_cagr, hit_12w, excess_12w):
    """Say there is an edge only when several measures agree. Otherwise say so."""
    if top_cagr is None or spy_cagr is None or hit_12w is None or excess_12w is None:
        return "Not enough history to judge the score."
    gap = top_cagr - spy_cagr
    if gap > 1.0 and hit_12w > 52 and excess_12w > 0.5:
        return "A modest edge shows up in this test. Read the limits before trusting it."
    if gap < 0 and hit_12w < 50:
        return "No clear edge: higher scores did not beat the S&P 500 in this test."
    if abs(gap) < 1.0 and abs(excess_12w) < 0.5:
        return "No clear edge: the gap versus the S&P 500 is small enough to be noise."
    return "Mixed: some measures beat the S&P 500 and some do not. Do not treat this as proof."


def run_backtest(close, prepared, quarters, sector_etf, etf_close, spy, band, cost=0.001):
    """Monthly point-in-time test. Analyst, insider, 13F, and earnings surprise are excluded.

    Those series do not have free history. The test uses only prices and filings
    whose known_on date is on or before the signal date.
    """
    notes = [
        ("Trading costs included", "Yes. 0.1 percent when a stock is bought and 0.1 percent when it is sold."),
        ("Uses only data known at the time", "Yes for prices and for SEC filings (usable the day after the filed date)."),
        ("Analyst, insider, 13F, earnings surprise", "Not in this test. Free history of those series is not available, so they are left out rather than filled in."),
        ("Includes delisted stocks", "No. The universe is today's members. That tilts the test up. Results are not a promise."),
        ("Look-ahead", "A filing is ignored until the day after it was filed. Forward returns are measured after the signal date."),
        ("Fundamentals used", "Latest annual report, or trailing four quarters when those quarters were already public."),
        ("12-week windows", "They overlap, so the number of signals is not a set of independent 12-week bets."),
        ("Past results", "Do not guarantee future results. This desk never places a trade."),
    ]
    empty = {
        "summary": pd.DataFrame(),
        "buckets": pd.DataFrame(),
        "equity": pd.DataFrame(),
        "yearly": pd.DataFrame(),
        "notes": pd.DataFrame(notes, columns=["item", "detail"]),
    }
    if close is None or close.empty or spy not in close.columns:
        return empty
    px = close.sort_index().copy()
    spy_px = px[spy].dropna()
    idx = px.index
    month_ends = idx.to_series().groupby(idx.to_period("M")).max().tolist()
    month_ends = [d for d in month_ends if d in idx]
    if len(month_ends) < 8:
        return empty
    sma20 = px.rolling(20).mean()
    sma50 = px.rolling(50).mean()
    rsi = _rsi(px)
    rsi_prev = rsi.shift(5)
    ret63 = px.pct_change(63)
    loc = {d: i for i, d in enumerate(idx)}
    prep_idx = {}
    for t, prep in prepared.items():
        if prep is None or len(prep) == 0:
            continue
        prep_idx[t] = (prep, prep["known_on"].to_numpy())
    tickers = [t for t in px.columns if t != spy and t in prep_idx]
    records = []
    books = []  # (date, top, bot)
    for d in month_ends:
        i = loc[d]
        if i < 200:
            continue
        spy_ex = _at(ret63, d, spy)
        row_scores = []
        for t in tickers:
            price = _at(px, d, t)
            if price is None:
                continue
            prep, known = prep_idx[t]
            k = int(np.searchsorted(known, np.datetime64(d), side="right")) - 1
            if k < 0:
                continue
            fin = metrics_from_prepared_row(prep.iloc[k], price, quarters.get(t) if quarters else None, d)
            pt = {}
            for key, higher in FIN_SPECS:
                if key == "forward_pe":
                    pt[key] = None  # no historical forward P/E
                    continue
                pt[key] = points_vs_avg(fin.get(key), fin.get(key + "_avg"), higher, band)
            n_fin = sum(1 for k2, _ in FIN_SPECS if k2 != "forward_pe" and pt[k2] is not None)
            if n_fin < 4:
                continue
            tech = nansum_strict([
                trend_points(price, _at(sma20, d, t), _at(sma50, d, t)),
                oscillator_points(_at(rsi, d, t), _at(rsi_prev, d, t)),
            ])
            etf = sector_etf.get(t)
            excess = None
            if etf and etf in px.columns and spy_ex is not None:
                er = _at(ret63, d, etf)
                if er is not None:
                    excess = er - spy_ex
            sec = sector_points(excess)
            score = nansum_strict([tech, nansum_strict([pt[k2] for k2, _ in FIN_SPECS if k2 != "forward_pe"]), sec])
            if score is None:
                continue
            fwd = {}
            for name, step in (("1w", 5), ("4w", 21), ("12w", 63)):
                j = i + step
                if j < len(idx) and np.isfinite(px.iloc[i][t]) and np.isfinite(px.iloc[j][t]) and px.iloc[i][t] > 0:
                    fwd[name] = float(px.iloc[j][t] / px.iloc[i][t] - 1)
                    if np.isfinite(px.iloc[i][spy]) and np.isfinite(px.iloc[j][spy]) and px.iloc[i][spy] > 0:
                        fwd[name + "_spy"] = float(px.iloc[j][spy] / px.iloc[i][spy] - 1)
            row_scores.append((t, score, fwd))
        if len(row_scores) < 30:
            continue
        row_scores.sort(key=lambda x: x[1], reverse=True)
        top = [t for t, _, _ in row_scores[:20]]
        bot = [t for t, _, _ in row_scores[-20:]]
        books.append((d, top, bot))
        for t, score, fwd in row_scores:
            rec = {"date": d, "ticker": t, "score": score}
            rec.update(fwd)
            records.append(rec)
    if not records:
        return empty
    sig = pd.DataFrame(records)
    # Words, not '1-3' or '10+', so a sheet does not turn the bucket into a date.
    sig["bucket"] = pd.cut(
        sig["score"], [-99, 0, 3, 5, 7, 9, 99],
        labels=list(BUCKET_LABELS),
    )
    buckets = []
    for horizon in ("1w", "4w", "12w"):
        sub = sig.dropna(subset=[horizon, horizon + "_spy"])
        for bucket, g in sub.groupby("bucket", observed=False):
            excess = g[horizon] - g[horizon + "_spy"]
            label = str(bucket)
            empty = len(g) == 0
            buckets.append({
                "horizon": horizon,
                "bucket": label,
                "bucket_order": BUCKET_ORDER.get(label),
                "n": int(len(g)),
                "avg_return_pct": None if empty else round(float(g[horizon].mean()) * 100, 2),
                "avg_spy_pct": None if empty else round(float(g[horizon + "_spy"].mean()) * 100, 2),
                "excess_pct": None if empty else round(float(excess.mean()) * 100, 2),
                "hit_rate_pct": None if empty else round(float((excess > 0).mean()) * 100, 1),
            })
    equity_rows, yearly_rows, summary_rows = _books(px, spy, books, cost, sig, buckets)
    return {
        "summary": pd.DataFrame(summary_rows),
        "buckets": pd.DataFrame(buckets),
        "equity": pd.DataFrame(equity_rows),
        "yearly": pd.DataFrame(yearly_rows),
        "notes": pd.DataFrame(notes, columns=["item", "detail"]),
    }


def metrics_from_prepared_row(row, price, quarters, asof):
    """Thin wrapper so the backtest and the live score share metrics_asof."""
    from fundamentals import metrics_asof
    prep = row.to_frame().T
    # metrics_asof filters known_on <= asof. The caller already picked the row.
    # Rebuild a one-row frame that is known.
    one = pd.DataFrame([row])
    return metrics_asof(one, asof, price, quarters)


# Display names for score buckets. '1-3' is a date in Google Sheets.
BUCKET_LABELS = (
    "Scores 0 or below",
    "Scores 1 to 3",
    "Scores 4 to 5",
    "Scores 6 to 7",
    "Scores 8 to 9",
    "Scores 10 or more",
)
BUCKET_ORDER = {label: i + 1 for i, label in enumerate(BUCKET_LABELS)}


def _books(px, spy, books, cost, sig, buckets):
    equity_rows = []
    if not books:
        return [], [], []
    top_eq = bot_eq = spy_eq = 10000.0
    prev_top, prev_bot = set(), set()
    top_rets, bot_rets, spy_rets = [], [], []
    dates = []
    started = False
    for n, (d, top, bot) in enumerate(books):
        if n + 1 >= len(books):
            break
        d2 = books[n + 1][0]
        tr = _basket_return(px, top, d, d2)
        br = _basket_return(px, bot, d, d2)
        sr = _basket_return(px, [spy], d, d2)
        if tr is None or br is None or sr is None:
            continue
        if not started:
            # The curve is compounded from 10,000. Write that start, then the first return.
            equity_rows.append({
                "date": str(pd.Timestamp(d).date()),
                "top20": 10000.0,
                "spy": 10000.0,
                "bottom20": 10000.0,
            })
            started = True
        top_cost = _turnover(prev_top, set(top), cost, first=(len(dates) == 0))
        bot_cost = _turnover(prev_bot, set(bot), cost, first=(len(dates) == 0))
        spy_cost = cost if len(dates) == 0 else 0.0
        top_eq *= (1 + tr - top_cost)
        bot_eq *= (1 + br - bot_cost)
        spy_eq *= (1 + sr - spy_cost)
        dates.append(d2)
        equity_rows.append({
            "date": str(pd.Timestamp(d2).date()),
            "top20": round(top_eq, 2),
            "spy": round(spy_eq, 2),
            "bottom20": round(bot_eq, 2),
        })
        top_rets.append((d2, tr - top_cost))
        bot_rets.append((d2, br - bot_cost))
        spy_rets.append((d2, sr - spy_cost))
        prev_top, prev_bot = set(top), set(bot)
    summary_rows = []
    yearly_rows = []
    if not dates:
        return equity_rows, yearly_rows, summary_rows
    end = pd.Timestamp(dates[-1])
    for label, years in (("3y", 3), ("5y", 5), ("full", None)):
        if years:
            start_cut = end - pd.DateOffset(years=years)
            mask_dates = [i for i, d in enumerate(dates) if pd.Timestamp(d) >= start_cut]
        else:
            mask_dates = list(range(len(dates)))
        if len(mask_dates) < 6:
            continue
        summary_rows.append(_window_summary(label, dates, mask_dates, top_rets, spy_rets, bot_rets, sig, buckets))
    # yearly from the full top-20 path
    by_year = {}
    for d, r in top_rets:
        by_year.setdefault(pd.Timestamp(d).year, []).append(("top", r))
    for d, r in spy_rets:
        by_year.setdefault(pd.Timestamp(d).year, []).append(("spy", r))
    for year, items in sorted(by_year.items()):
        top_r = np.prod([1 + r for name, r in items if name == "top"]) - 1
        spy_r = np.prod([1 + r for name, r in items if name == "spy"]) - 1
        sub = sig[pd.to_datetime(sig["date"]).dt.year == year]
        hit = np.nan
        if len(sub) and "12w" in sub.columns:
            both = sub.dropna(subset=["12w", "12w_spy"])
            if len(both):
                hit = float((both["12w"] > both["12w_spy"]).mean()) * 100
        yearly_rows.append({
            "year": int(year),
            "top20_pct": round(float(top_r) * 100, 2),
            "spy_pct": round(float(spy_r) * 100, 2),
            "difference_pct": round(float(top_r - spy_r) * 100, 2),
            "hit_rate_12w_pct": None if not np.isfinite(hit) else round(hit, 1),
            "signals": int(len(sub)),
        })
    # mark the headline window
    prefer = "5y" if any(r["window"] == "5y" for r in summary_rows) else (summary_rows[-1]["window"] if summary_rows else None)
    for r in summary_rows:
        r["is_headline"] = "yes" if r["window"] == prefer else "no"
    if prefer:
        head = next(r for r in summary_rows if r["window"] == prefer)
        text = edge_headline(head["top20_cagr_pct"], head["spy_cagr_pct"], head["hit_rate_12w_pct"], head["top_bucket_excess_12w_pct"])
        for r in summary_rows:
            r["headline"] = text if r["window"] == prefer else ""
    return equity_rows, yearly_rows, summary_rows


def _window_summary(label, dates, mask_dates, top_rets, spy_rets, bot_rets, sig, buckets):
    def chain(rets):
        eq = 1.0
        for i in mask_dates:
            eq *= 1 + rets[i][1]
        return eq
    top_eq, spy_eq, bot_eq = chain(top_rets), chain(spy_rets), chain(bot_rets)
    d0 = pd.Timestamp(dates[mask_dates[0]])
    d1 = pd.Timestamp(dates[mask_dates[-1]])
    years = max((d1 - d0).days / 365.25, 0.25)
    def cagr(eq):
        return (eq ** (1 / years) - 1) * 100
    def maxdd(rets):
        eq = 1.0
        peak = 1.0
        worst = 0.0
        for i in mask_dates:
            eq *= 1 + rets[i][1]
            peak = max(peak, eq)
            worst = min(worst, eq / peak - 1)
        return worst * 100
    start = dates[mask_dates[0]]
    sub = sig[pd.to_datetime(sig["date"]) >= pd.Timestamp(start)]
    hit = np.nan
    if "12w" in sub.columns:
        both = sub.dropna(subset=["12w", "12w_spy"])
        top = both[both["score"] >= 8] if len(both) else both
        base = top if len(top) >= 20 else both
        if len(base):
            hit = float((base["12w"] > base["12w_spy"]).mean()) * 100
    excess = np.nan
    for label in ("Scores 10 or more", "Scores 8 to 9"):
        for b in buckets:
            if b["horizon"] == "12w" and b["bucket"] == label and b.get("excess_pct") is not None:
                excess = b["excess_pct"]
                break
        if np.isfinite(excess):
            break
    return {
        "window": label,
        "start": str(pd.Timestamp(dates[mask_dates[0]]).date()),
        "end": str(d1.date()),
        "months": len(mask_dates),
        "top20_cagr_pct": round(cagr(top_eq), 2),
        "spy_cagr_pct": round(cagr(spy_eq), 2),
        "bottom20_cagr_pct": round(cagr(bot_eq), 2),
        "top20_total_pct": round((top_eq - 1) * 100, 2),
        "spy_total_pct": round((spy_eq - 1) * 100, 2),
        "bottom20_total_pct": round((bot_eq - 1) * 100, 2),
        "top20_max_drawdown_pct": round(maxdd(top_rets), 2),
        "spy_max_drawdown_pct": round(maxdd(spy_rets), 2),
        "hit_rate_12w_pct": None if not np.isfinite(hit) else round(hit, 1),
        "top_bucket_excess_12w_pct": None if not np.isfinite(excess) else round(float(excess), 2),
        "headline": "",
        "is_headline": "no",
    }


def _basket_return(px, names, d1, d2):
    rets = []
    for t in names:
        if t not in px.columns:
            continue
        a, b = px.at[d1, t], px.at[d2, t]
        if pd.notna(a) and pd.notna(b) and a > 0:
            rets.append(b / a - 1)
    if not rets:
        return None
    return float(np.mean(rets))


def _turnover(prev, curr, cost, first):
    if first or not prev:
        return cost  # buy the book once
    sold = len(prev - curr) / max(len(prev), 1)
    return sold * 2 * cost  # sell the old names and buy the new ones


def _at(frame, date, ticker):
    try:
        v = frame.at[date, ticker]
    except KeyError:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x):
        return None
    return x


def _rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)
