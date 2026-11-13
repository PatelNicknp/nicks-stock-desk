"""MarketSmith style screens: Highest EPS and RS, Minervini 1-Month, Minervini 5-Month.

Built only from data the desk already saves: daily bars (cache/ohlcv.csv.gz),
the quarterly and yearly EPS from SEC EDGAR company facts (cache/quarters.csv
and cache/annual.csv, split-adjusted the same way as the rest of the desk), and
the RS Rating from relative_strength.py. No new downloads and no paid data.

EPS Rating (1 to 99, our close copy of MarketSmith's private number)
    Three parts, each ranked across every stock in the desk's universe that has
    that part, with equal weight:
      1. Latest quarter EPS versus the same quarter a year earlier, in %.
      2. The quarter before that, versus its own year-ago quarter, in %.
      3. Yearly EPS growth over 3 to 5 years, as a yearly compound rate. The
         longest span on file is used (5 years when there, else 4, else 3).
    The average of a stock's part ranks is ranked again and mapped to 1 to 99,
    the same way as the RS Rating. Parts 1 and 3 are required. A stock missing
    one (no year-ago quarter, under 3 years, or a loss or zero EPS at the start
    of the yearly span) has no EPS Rating. It is left blank, never 0.
    Part 2 counts when it is on file. SEC frames skip some quarters (a fourth
    quarter is often only in the 10-K), so the year-ago match for the quarter
    before the latest is missing for some stocks. require_prior_quarter turns
    the strict three-part rule on. eps_parts on each row says how many parts
    were used.
    Year-ago quarter change uses the desk's CANSLIM C rule:
    (now - then) / |then|. A zero year-ago quarter has no change.

Highest EPS and RS
    Desk stocks with both ratings, at or above min_eps_rating and min_rs
    (80 and 80 by default), ranked by EPS Rating + RS Rating, highest first.
    Extended names are dropped. MarketSmith drops stocks more than 5% past
    their buy point. The desk has a buy point only for stocks on a pattern
    scanner (VCP, Box, Flag, Qullamaggie, Marios), so:
      - with a buy point: extended means the close is more than 5% above it;
      - without one (stand-in): extended means the close is more than 25%
        above the 50-day average.
    At most max_rows rows (50 by default).

Minervini 1-Month and 5-Month (Mark Minervini's trend template)
    Simple moving averages of the close: 50, 150, 200 days.
      1. Close above the 150-day and the 200-day.
      2. 150-day above the 200-day.
      3. 200-day higher today than 21 sessions ago (1-Month) or 105 sessions
         ago (5-Month, about 5 months).
      4. 50-day above the 150-day and the 200-day.
      5. Close above the 50-day.
      6. Close at least 30% above the 52-week low.
      7. Close within 25% of the 52-week high.
      8. RS Rating 70 or higher.
    The 52-week high and low use the last 252 daily highs and lows, the same
    window as the VCP trend template. Every rule must pass. Sorted by RS.
"""
import numpy as np
import pandas as pd

import relative_strength

EPS_RS_FILE = "scanner_eps_rs"
MIN1M_FILE = "scanner_minervini_1m"
MIN5M_FILE = "scanner_minervini_5m"

DEFAULTS = {
    "min_eps_rating": 80,
    "min_rs": 80,
    "max_rows": 50,
    "extended_past_pivot_pct": 5.0,
    "extended_above_sma50_pct": 25.0,
    "require_prior_quarter": False,
    "min_years": 3,
    "max_years": 5,
    "template_rs_min": 70,
    "template_above_low_pct": 30.0,
    "template_within_high_pct": 25.0,
    "rising_1m_sessions": 21,
    "rising_5m_sessions": 105,
}

PASS_WORD = "PASSES"
PIVOT_SOURCES = ("scanner_vcp", "scanner_box", "scanner_flag", "scanner_qullamaggie", "scanner_marios")
PIVOT_NAMES = {"scanner_vcp": "VCP", "scanner_box": "Box", "scanner_flag": "Flag",
               "scanner_qullamaggie": "Qullamaggie", "scanner_marios": "Marios"}

EPS_RS_COLS = [
    "rank", "ticker", "company", "sector", "index_membership", "status",
    "eps_rating", "rs", "combined", "strength",
    "eps_q_yoy", "eps_prev_q_yoy", "eps_annual_growth", "eps_growth_years", "eps_parts",
    "latest_quarter", "price", "sma50", "above_sma50_pct", "buy_point", "buy_point_source", "past_buy_point_pct",
    "extended_check", "price_as_of", "reason",
    "rs_label", "rs_note", "data_status", "note", "disclaimer",
]
TEMPLATE_COLS = [
    "rank", "ticker", "company", "sector", "index_membership", "status",
    "rs", "strength", "price", "sma50", "sma150", "sma200", "sma200_ago", "sma200_change_pct",
    "above_low_pct", "off_high_pct", "low52", "high52", "eps_rating",
    "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8",
    "price_as_of", "reason",
    "rs_label", "rs_note", "data_status", "note", "disclaimer",
]


def settings(cfg):
    out = dict(DEFAULTS)
    block = (cfg or {}).get("marketsmith_screens") if isinstance(cfg, dict) else None
    for k, v in (block or {}).items():
        if str(k).startswith("_") or k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], bool):
            out[k] = v if isinstance(v, bool) else str(v).strip().lower() == "true"
            continue
        try:
            out[k] = type(DEFAULTS[k])(v)
        except (TypeError, ValueError):
            pass
    return out


# ---------------------------------------------------------------- EPS Rating
def _frame_key(frame):
    text = str(frame)
    if len(text) == 6 and text.startswith("CY") and text[2:].isdigit():
        return int(text[2:]), 0
    if len(text) == 8 and text.startswith("CY") and text[6] == "Q" and text[2:6].isdigit() and text[7] in "1234":
        return int(text[2:6]), int(text[7])
    return None


def _eps_by_ticker(frame_df, quarterly):
    """{ticker: {(year, q): eps}} for quarterly or yearly rows with a number."""
    out = {}
    if frame_df is None or len(frame_df) == 0 or "eps" not in frame_df.columns or "ticker" not in frame_df.columns:
        return out
    eps = pd.to_numeric(frame_df["eps"], errors="coerce")
    for ticker, frame, val in zip(frame_df["ticker"].astype(str), frame_df["frame"], eps):
        if not np.isfinite(val):
            continue
        key = _frame_key(frame)
        if key is None or (key[1] != 0) != quarterly:
            continue
        out.setdefault(ticker, {})[key] = float(val)
    return out


def _qprev(key, n):
    """The quarter n quarters before key=(year, q)."""
    idx = key[0] * 4 + (key[1] - 1) - n
    return (idx // 4, idx % 4 + 1)


def yoy_change(now, then):
    """CANSLIM C rule: (now - then) / |then| in %. None when then is 0 or missing."""
    if now is None or then is None or not np.isfinite(now) or not np.isfinite(then) or then == 0:
        return None
    return (now - then) / abs(then) * 100.0


def quarter_parts(qmap):
    """(latest_yoy, prior_yoy, latest_key) from {(year, q): eps}. None parts when missing."""
    if not qmap:
        return None, None, None
    latest = max(qmap)
    prior = _qprev(latest, 1)
    a = yoy_change(qmap.get(latest), qmap.get(_qprev(latest, 4)))
    b = yoy_change(qmap.get(prior), qmap.get(_qprev(prior, 4))) if prior in qmap else None
    return a, b, latest


def annual_growth(amap, min_years=3, max_years=5):
    """(compound yearly % growth, years) over the longest span from max_years down to min_years.

    Needs a positive EPS at both ends. None when no span fits.
    """
    if not amap:
        return None, None
    years = sorted(k[0] for k in amap)
    last = years[-1]
    end = amap[(last, 0)]
    for span in range(int(max_years), int(min_years) - 1, -1):
        start = amap.get((last - span, 0))
        if start is None:
            continue
        if start <= 0 or end <= 0:
            return None, span
        return ((end / start) ** (1.0 / span) - 1.0) * 100.0, span
    return None, None


def eps_ratings(quarters, annual, tickers=None, cfg=None):
    """One row per ticker with EPS parts and a 1 to 99 EPS Rating (blank when a part is missing)."""
    spec = settings(cfg)
    qmaps = _eps_by_ticker(quarters, True)
    amaps = _eps_by_ticker(annual, False)
    names = list(dict.fromkeys(str(t) for t in (tickers if tickers is not None else list(qmaps) + list(amaps))))
    rows = []
    for t in names:
        a, b, latest = quarter_parts(qmaps.get(t))
        g, yrs = annual_growth(amaps.get(t), spec["min_years"], spec["max_years"])
        rows.append({
            "ticker": t, "eps_q_yoy": a, "eps_prev_q_yoy": b, "eps_annual_growth": g,
            "eps_growth_years": yrs if g is not None else None,
            "latest_quarter": "" if latest is None else "CY%dQ%d" % latest,
        })
    out = pd.DataFrame(rows, columns=["ticker", "eps_q_yoy", "eps_prev_q_yoy", "eps_annual_growth", "eps_growth_years", "latest_quarter"])
    out["eps_rating"] = np.nan
    out["eps_parts"] = np.nan
    if len(out) == 0:
        return out
    parts = ["eps_q_yoy", "eps_prev_q_yoy", "eps_annual_growth"]
    required = parts if spec["require_prior_quarter"] else ["eps_q_yoy", "eps_annual_growth"]
    pool = out.dropna(subset=required)
    if len(pool):
        ranks = pd.concat([pd.to_numeric(pool[p], errors="coerce").rank(method="average", pct=True) for p in parts], axis=1)
        mean = ranks.mean(axis=1, skipna=True)
        rated = relative_strength.rank_1_to_99(mean)
        out.loc[rated.index, "eps_rating"] = rated.astype(float)
        out.loc[pool.index, "eps_parts"] = ranks.notna().sum(axis=1).astype(float)
    return out


# ---------------------------------------------------------------- price helpers
def _series(frame, ticker):
    if frame is None or ticker not in getattr(frame, "columns", []):
        return None
    s = frame[ticker]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return pd.to_numeric(s, errors="coerce")


def _clean_bars(close, high, low, ticker):
    c = _series(close, ticker)
    if c is None:
        return None
    df = pd.DataFrame({"close": c, "high": _series(high, ticker), "low": _series(low, ticker)})
    df = df.dropna(subset=["close"]).sort_index()
    df = df[df["close"] > 0]
    if len(df) == 0:
        return None
    df["high"] = df["high"].where(df["high"].notna(), df["close"])
    df["low"] = df["low"].where(df["low"].notna(), df["close"])
    return df


def template_check(bars, rs, rising_sessions, spec=None):
    """Minervini trend template on the last bar. Returns a dict, or None when history is short.

    bars: DataFrame with close, high, low (oldest first). rs: RS Rating or None.
    Needs 200 + rising_sessions closes for the 200-day comparison and 252 bars for the 52-week range.
    """
    spec = spec or DEFAULTS
    if bars is None:
        return None
    need = max(200 + int(rising_sessions), 252)
    if len(bars) < need:
        return None
    c = bars["close"].to_numpy(dtype=float)
    sma50 = float(np.mean(c[-50:]))
    sma150 = float(np.mean(c[-150:]))
    sma200 = float(np.mean(c[-200:]))
    k = int(rising_sessions)
    sma200_ago = float(np.mean(c[-200 - k:-k]))
    last = float(c[-1])
    low52 = float(np.nanmin(bars["low"].to_numpy(dtype=float)[-252:]))
    high52 = float(np.nanmax(bars["high"].to_numpy(dtype=float)[-252:]))
    above_low = (last / low52 - 1.0) * 100.0 if low52 > 0 else None
    off_high = (last / high52 - 1.0) * 100.0 if high52 > 0 else None
    rules = [
        last > sma150 and last > sma200,
        sma150 > sma200,
        sma200 > sma200_ago,
        sma50 > sma150 and sma50 > sma200,
        last > sma50,
        above_low is not None and last >= low52 * (1.0 + float(spec["template_above_low_pct"]) / 100.0),
        high52 > 0 and last >= high52 * (1.0 - float(spec["template_within_high_pct"]) / 100.0),
        rs is not None and float(rs) >= float(spec["template_rs_min"]),
    ]
    return {
        "price": last, "sma50": sma50, "sma150": sma150, "sma200": sma200, "sma200_ago": sma200_ago,
        "sma200_change_pct": (sma200 / sma200_ago - 1.0) * 100.0 if sma200_ago > 0 else None,
        "low52": low52, "high52": high52, "above_low_pct": above_low, "off_high_pct": off_high,
        "rules": rules, "passes": all(rules), "asof": bars.index[-1],
    }


def _meta(universe):
    if universe is None or len(universe) == 0 or "ticker" not in universe.columns:
        return {}
    keep = [c for c in ("company", "sector", "index_membership") if c in universe.columns]
    m = universe.drop_duplicates("ticker", keep="last").set_index("ticker")[keep]
    return {str(t): {k: ("" if pd.isna(v) else v) for k, v in r.items()} for t, r in m.iterrows()}


def _r(v, nd=2):
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return round(f, nd) if np.isfinite(f) else ""


def _date(ts):
    try:
        return str(pd.Timestamp(ts).date())
    except Exception:
        return ""


# ---------------------------------------------------------------- Minervini screens
def build_template(close, high, low, universe, rs_lookup, rising_sessions, cfg=None, eps_lookup=None, label=""):
    """Every desk stock passing all 8 template rules. Sorted by RS, highest first."""
    spec = settings(cfg)
    meta = _meta(universe)
    rs_lookup = rs_lookup or {}
    eps_lookup = eps_lookup or {}
    names = list(dict.fromkeys(universe["ticker"].astype(str))) if universe is not None and len(universe) else []
    rows = []
    for t in names:
        rs = rs_lookup.get(t.upper())
        if rs is None:
            continue
        chk = template_check(_clean_bars(close, high, low, t), rs, rising_sessions, spec)
        if chk is None or not chk["passes"]:
            continue
        m = meta.get(t, {})
        months = "1 month" if int(rising_sessions) <= 21 else "%d sessions (about %d months)" % (int(rising_sessions), round(int(rising_sessions) / 21))
        reason = ("All 8 trend template rules pass. RS %d. Close %s is %.0f%% above the 52-week low and %.1f%% under the 52-week high. "
                  "The 200-day is up %.1f%% over %s. 50-day %s, 150-day %s, 200-day %s." % (
                      int(rs), _r(chk["price"]), chk["above_low_pct"], abs(min(chk["off_high_pct"], 0.0)),
                      chk["sma200_change_pct"] or 0.0, months, _r(chk["sma50"]), _r(chk["sma150"]), _r(chk["sma200"])))
        rows.append({
            "ticker": t, "company": m.get("company", ""), "sector": m.get("sector", ""),
            "index_membership": m.get("index_membership", ""), "status": PASS_WORD,
            "rs": int(rs), "strength": int(rs), "price": _r(chk["price"]),
            "sma50": _r(chk["sma50"]), "sma150": _r(chk["sma150"]), "sma200": _r(chk["sma200"]),
            "sma200_ago": _r(chk["sma200_ago"]), "sma200_change_pct": _r(chk["sma200_change_pct"], 2),
            "above_low_pct": _r(chk["above_low_pct"], 1), "off_high_pct": _r(chk["off_high_pct"], 1),
            "low52": _r(chk["low52"]), "high52": _r(chk["high52"]),
            "eps_rating": "" if eps_lookup.get(t) is None else int(eps_lookup[t]),
            **{"r%d" % (i + 1): "PASS" for i in range(8)},
            "price_as_of": _date(chk["asof"]), "reason": reason,
            "data_status": "OK", "note": "",
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    out = out.sort_values(["rs", "off_high_pct", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


# ---------------------------------------------------------------- Highest EPS and RS
def pivot_map(frames):
    """{TICKER: (pivot, source)} from the pattern scanners. VCP first, then Box, Flag, Qullamaggie, Marios."""
    out = {}
    for key in PIVOT_SOURCES:
        f = (frames or {}).get(key)
        if f is None or len(f) == 0 or "ticker" not in f.columns or "pivot" not in f.columns:
            continue
        status = f["status"].astype(str) if "status" in f.columns else pd.Series([""] * len(f), index=f.index)
        piv = pd.to_numeric(f["pivot"], errors="coerce")
        for t, p, s in zip(f["ticker"].astype(str), piv, status):
            if not np.isfinite(p) or p <= 0 or s == "CLOSED":
                continue
            out.setdefault(t.strip().upper(), (float(p), PIVOT_NAMES[key]))
    return out


def build_eps_rs(close, universe, eps_table, rs_lookup, pivots=None, cfg=None):
    """Highest EPS and RS. Returns (rows, counts) where counts says how many were dropped and why."""
    spec = settings(cfg)
    meta = _meta(universe)
    rs_lookup = rs_lookup or {}
    pivots = pivots or {}
    counts = {"rated_both": 0, "over_min": 0, "extended": 0, "listed": 0}
    if eps_table is None or len(eps_table) == 0:
        return pd.DataFrame(), counts
    eps = eps_table.dropna(subset=["eps_rating"]).set_index("ticker")
    names = list(dict.fromkeys(universe["ticker"].astype(str))) if universe is not None and len(universe) else []
    rows = []
    for t in names:
        rs = rs_lookup.get(t.upper())
        if rs is None or t not in eps.index:
            continue
        e = eps.loc[t]
        if isinstance(e, pd.DataFrame):
            e = e.iloc[-1]
        er = int(e["eps_rating"])
        counts["rated_both"] += 1
        if er < int(spec["min_eps_rating"]) or int(rs) < int(spec["min_rs"]):
            continue
        counts["over_min"] += 1
        c = _series(close, t)
        c = c.dropna() if c is not None else None
        if c is None or len(c) < 50:
            continue
        last = float(c.iloc[-1])
        sma50 = float(c.iloc[-50:].mean())
        above50 = (last / sma50 - 1.0) * 100.0 if sma50 > 0 else None
        piv = pivots.get(t.upper())
        past = None
        if piv is not None:
            past = (last / piv[0] - 1.0) * 100.0
            extended = past > float(spec["extended_past_pivot_pct"])
            check = "Buy point %s from %s. Close is %+.1f%% from it. Over %s%% is extended." % (
                _r(piv[0]), piv[1], past, _r(spec["extended_past_pivot_pct"], 1))
        else:
            extended = above50 is not None and above50 > float(spec["extended_above_sma50_pct"])
            check = ("No buy point on file, so the stand-in is used: close is %+.1f%% from the 50-day average. "
                     "Over %s%% is extended." % (above50 or 0.0, _r(spec["extended_above_sma50_pct"], 1)))
        if extended:
            counts["extended"] += 1
            continue
        m = meta.get(t, {})
        combined = er + int(rs)
        reason = ("EPS Rating %d + RS %d = %d. Latest quarter EPS %s versus a year ago, the quarter before %s, "
                  "yearly growth %s over %s years. %s" % (
                      er, int(rs), combined, _pct_txt(e["eps_q_yoy"]), _pct_txt(e["eps_prev_q_yoy"]),
                      _pct_txt(e["eps_annual_growth"]), int(e["eps_growth_years"]), check))
        parts_used = int(e["eps_parts"]) if pd.notna(e.get("eps_parts")) else ""
        rows.append({
            "ticker": t, "company": m.get("company", ""), "sector": m.get("sector", ""),
            "index_membership": m.get("index_membership", ""), "status": PASS_WORD,
            "eps_rating": er, "rs": int(rs), "combined": combined, "strength": round(combined / 2.0, 1),
            "eps_q_yoy": _r(e["eps_q_yoy"], 1), "eps_prev_q_yoy": _r(e["eps_prev_q_yoy"], 1),
            "eps_annual_growth": _r(e["eps_annual_growth"], 1), "eps_growth_years": int(e["eps_growth_years"]),
            "eps_parts": parts_used, "latest_quarter": e.get("latest_quarter", ""), "price": _r(last), "sma50": _r(sma50),
            "above_sma50_pct": _r(above50, 1), "buy_point": "" if piv is None else _r(piv[0]),
            "buy_point_source": "" if piv is None else piv[1], "past_buy_point_pct": _r(past, 1),
            "extended_check": check, "price_as_of": _date(c.index[-1]), "reason": reason,
            "data_status": "OK", "note": "",
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out, counts
    out = out.sort_values(["combined", "eps_rating", "rs", "ticker"], ascending=[False, False, False, True])
    out = out.head(int(spec["max_rows"])).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    counts["listed"] = len(out)
    return out, counts


def _pct_txt(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "not on file"
    if not np.isfinite(f):
        return "not on file"
    return "%+.0f%%" % f
