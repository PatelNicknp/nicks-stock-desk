"""Sector rotation from prices this desk already has.

No new Yahoo request and no new macro source. The 11 SPDR sector ETFs and
SPY are already in the price cache. Breadth, scores, and buy setups come from
tables this job already builds. The 10-year yield and the 10-year minus 2-year
spread are the FRED files the macro page already reads. Dollar, oil, and gold
are not in those files, so they stay off this page.

Relative Rotation Graph (a desk z-score, not the commercial JdK indicator):

    RS = sector ETF close / SPY close, on the same daily, weekly, or monthly bar
    smoothed = SMA(RS, smooth)
    RS-Ratio = 100 + z-score of smoothed versus its rolling mean
    RS-Momentum = 100 + z-score of (RS-Ratio minus RS-Ratio from roc_span bars ago)

The z-score uses the sample standard deviation (ddof=1). A window whose
standard deviation is 0 has z-score 0, so a flat RS sits at 100 and 100.
Quadrants use 100 as the crosshair. The positive side includes 100:

    Leading    RS-Ratio >= 100 and RS-Momentum >= 100
    Weakening  RS-Ratio >= 100 and RS-Momentum < 100
    Lagging    RS-Ratio < 100 and RS-Momentum < 100
    Improving  RS-Ratio < 100 and RS-Momentum >= 100

Weekly bars are Friday week-ends (last session in the week). Monthly bars are
month-ends. Windows are shorter on weekly and monthly bars so the shorter
history still produces a point. They live in config under sector_rotation.

The sector score is a weighted average of the factors that are actually
present, scaled to 0-100. A missing factor is left out of both the numerator
and the denominator. It is not stored as zero.
"""
import numpy as np
import pandas as pd

SPDR = (
    ("XLK", "Technology", "Information Technology"),
    ("XLV", "Health Care", "Health Care"),
    ("XLF", "Financials", "Financials"),
    ("XLI", "Industrials", "Industrials"),
    ("XLC", "Communication Services", "Communication Services"),
    ("XLY", "Consumer Discretionary", "Consumer Discretionary"),
    ("XLP", "Consumer Staples", "Consumer Staples"),
    ("XLE", "Energy", "Energy"),
    ("XLU", "Utilities", "Utilities"),
    ("XLRE", "Real Estate", "Real Estate"),
    ("XLB", "Materials", "Materials"),
)
SPDR_TICKERS = tuple(t[0] for t in SPDR)

QUADRANTS = ("Leading", "Weakening", "Lagging", "Improving")
RRG_POINTS = {"Leading": 100.0, "Improving": 70.0, "Weakening": 40.0, "Lagging": 15.0}

# Daily needs about 95 sessions. Weekly about 62 weeks. Monthly about 29 months.
WINDOWS = {
    "D": {"smooth": 10, "ratio_window": 40, "roc_span": 5, "mom_window": 40},
    "W": {"smooth": 6, "ratio_window": 26, "roc_span": 4, "mom_window": 26},
    "M": {"smooth": 3, "ratio_window": 12, "roc_span": 2, "mom_window": 12},
}
WEIGHTS = {
    "rs_1m": 8.0,
    "rs_3m": 12.0,
    "rs_6m": 10.0,
    "breadth_sma50": 12.0,
    "breadth_sma200": 12.0,
    "near_high": 10.0,
    "buy_setups": 10.0,
    "desk_score": 10.0,
    "buy_share": 8.0,
    "rrg": 8.0,
}
RS_SESSIONS = {"1m": 21, "3m": 63, "6m": 126}
RS_CLIP = 15.0
DESK_CLIP = (-4.0, 12.0)
NEAR_HIGH_PCT = 5.0
W52_BARS = 252
TAIL_KEEP = 12
MACRO_LOOKBACK = 63
YIELD_FLAT = 0.05
LIVE_STATUS = ("READY", "BROKEN OUT today")

NOTE = (
    "RS-Ratio is 100 plus the z-score of smoothed ETF/SPY versus its rolling mean. "
    "RS-Momentum is 100 plus the z-score of the change in RS-Ratio. "
    "This is a desk calculation, not the commercial JdK indicator. "
    "Dollar, oil, and gold are not in the cached prices or the FRED files this desk already keeps, so they are left off. "
    "Rate notes are general tendencies, not a forecast."
)
HISTORY_NOTE = "Backfilled from the cached daily prices of the sector ETFs and SPY. No new download."
TAIL_NOTE = "Last points of the relative-rotation series. tail_index 1 is the oldest point kept."


def _cfg_num(cfg, key, default):
    if not cfg or key not in cfg:
        return default
    try:
        return type(default)(cfg[key])
    except (TypeError, ValueError):
        return default


def windows_from(cfg):
    out = {tf: dict(spec) for tf, spec in WINDOWS.items()}
    raw = (cfg or {}).get("windows") or {}
    for tf, spec in raw.items():
        if tf not in out or not isinstance(spec, dict):
            continue
        for k in ("smooth", "ratio_window", "roc_span", "mom_window"):
            if k in spec:
                try:
                    out[tf][k] = int(spec[k])
                except (TypeError, ValueError):
                    pass
    return out


def weights_from(cfg):
    out = dict(WEIGHTS)
    raw = (cfg or {}).get("weights") or {}
    for k in out:
        if k in raw:
            try:
                out[k] = float(raw[k])
            except (TypeError, ValueError):
                pass
    return out


def quadrant(ratio, momentum):
    """100 sits on the Leading side of both axes."""
    if ratio >= 100 and momentum >= 100:
        return "Leading"
    if ratio >= 100 and momentum < 100:
        return "Weakening"
    if ratio < 100 and momentum >= 100:
        return "Improving"
    return "Lagging"


def _zscore(series, window):
    """Sample z-score versus the trailing window. A zero deviation is 0, not blank."""
    mu = series.rolling(int(window), min_periods=int(window)).mean()
    sd = series.rolling(int(window), min_periods=int(window)).std(ddof=1)
    out = pd.Series(np.nan, index=series.index, dtype=float)
    valid = mu.notna() & sd.notna() & series.notna()
    zero = valid & (sd == 0)
    ok = valid & ~zero
    if zero.any():
        out.loc[zero] = 0.0
    if ok.any():
        out.loc[ok] = ((series - mu) / sd).loc[ok]
    return out


def rrg_from_rs(rs, smooth, ratio_window, roc_span, mom_window):
    """RS-Ratio and RS-Momentum for one relative-strength series.

    rs is ETF/SPY on the bar size already chosen (day, week, or month).
    """
    rs = pd.to_numeric(rs, errors="coerce").dropna()
    rs = rs[np.isfinite(rs) & (rs > 0)]
    if len(rs) == 0:
        return pd.DataFrame(columns=["rs_ratio", "rs_momentum", "quadrant"])
    smooth = max(1, int(smooth))
    ratio_window = max(2, int(ratio_window))
    roc_span = max(1, int(roc_span))
    mom_window = max(2, int(mom_window))
    smoothed = rs.rolling(smooth, min_periods=smooth).mean()
    ratio = 100.0 + _zscore(smoothed, ratio_window)
    roc = ratio - ratio.shift(roc_span)
    momentum = 100.0 + _zscore(roc, mom_window)
    out = pd.DataFrame({"rs_ratio": ratio, "rs_momentum": momentum})
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    if len(out) == 0:
        return out
    out["quadrant"] = [quadrant(r, m) for r, m in zip(out["rs_ratio"], out["rs_momentum"])]
    return out


def to_bars(series, timeframe):
    s = pd.to_numeric(series, errors="coerce").dropna()
    s = s[np.isfinite(s) & (s > 0)]
    if timeframe == "D" or len(s) == 0:
        return s
    rule = "W-FRI" if timeframe == "W" else "ME"
    return s.resample(rule).last().dropna()


def rrg_for_prices(etf, spy, timeframe, windows):
    spec = windows[timeframe]
    e = to_bars(etf, timeframe)
    s = to_bars(spy, timeframe)
    both = pd.concat([e.rename("e"), s.rename("s")], axis=1).dropna()
    both = both[(both["e"] > 0) & (both["s"] > 0)]
    if len(both) == 0:
        return pd.DataFrame(columns=["rs_ratio", "rs_momentum", "quadrant"])
    rs = both["e"] / both["s"]
    return rrg_from_rs(rs, spec["smooth"], spec["ratio_window"], spec["roc_span"], spec["mom_window"])


def describe_change(name, previous, current):
    if not previous or not current or previous == current:
        return "unchanged"
    return "%s moved from %s to %s" % (name, previous, current)


def changed_lines(rows, column):
    out = []
    for row in rows:
        text = str(row.get(column) or "")
        if "moved from" in text:
            out.append(text)
    return out


def _blank(v):
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip().lower() in ("", "nan", "none", "<na>")


def _flag_yes(v):
    if _blank(v):
        return False
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v) == 1
    if isinstance(v, float):
        return v == 1.0
    return str(v).strip().lower() in ("1", "1.0", "yes", "true")


def clip_map(value, lo, hi):
    """Map a number into 0-100, clipped to [lo, hi]. Missing stays missing."""
    if _blank(value):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x) or hi == lo:
        return None
    x = min(float(hi), max(float(lo), x))
    return (x - float(lo)) / (float(hi) - float(lo)) * 100.0


def composite_score(factors, weights):
    """Weighted mean of the factors that have a number. Missing is not zero."""
    num = 0.0
    den = 0.0
    for key, weight in weights.items():
        if weight is None or float(weight) <= 0:
            continue
        value = factors.get(key)
        if _blank(value):
            continue
        num += float(weight) * float(value)
        den += float(weight)
    if den == 0:
        return None
    return num / den


def period_return(series, sessions):
    s = pd.to_numeric(series, errors="coerce").dropna()
    n = int(sessions)
    if len(s) <= n:
        return None
    base = float(s.iloc[-1 - n])
    last = float(s.iloc[-1])
    if base == 0 or not np.isfinite(base) or not np.isfinite(last):
        return None
    return (last / base - 1.0) * 100.0


def excess_return(etf, spy, sessions):
    a = period_return(etf, sessions)
    b = period_return(spy, sessions)
    if a is None or b is None:
        return None
    return a - b


def near_high_tickers(close, high, tickers, bars=W52_BARS, near_pct=NEAR_HIGH_PCT):
    """Tickers whose close is within near_pct of the trailing high, including today.

    The high is the max of the high column over `bars` sessions. A name with
    fewer sessions is left out. It is not treated as far from a high.
    """
    found = set()
    if close is None or high is None or len(getattr(close, "columns", [])) == 0:
        return found
    bars = int(bars)
    for ticker in tickers:
        if ticker not in close.columns or ticker not in high.columns:
            continue
        both = pd.concat([close[ticker].rename("c"), high[ticker].rename("h")], axis=1)
        both = both.apply(pd.to_numeric, errors="coerce").dropna()
        if len(both) < bars:
            continue
        window = both.iloc[-bars:]
        hi = float(window["h"].max())
        last = float(window["c"].iloc[-1])
        if hi <= 0 or not np.isfinite(hi) or not np.isfinite(last):
            continue
        pct_from = (last / hi - 1.0) * 100.0
        if pct_from >= -float(near_pct) - 1e-6:
            found.add(str(ticker))
    return found


def _tickers_of(frame):
    if frame is None or len(frame) == 0 or "ticker" not in getattr(frame, "columns", []):
        return []
    out = []
    for raw in frame["ticker"].tolist():
        if _blank(raw):
            continue
        out.append(str(raw).strip().upper())
    return out


def resolve_buy_tickers(scores, scanners=None, buy_setups=None):
    """Names on a buy setup.

    A dedicated buy-setup table wins when one is passed in (the page that
    lists READY or broken-out names with a BUY verdict and price above both
    moving averages). Until that table exists, the same rule is applied to
    the VCP, box, flag, and CANSLIM scans already on file.
    """
    if buy_setups is not None and len(getattr(buy_setups, "index", [])) and "ticker" in getattr(buy_setups, "columns", []):
        return set(_tickers_of(buy_setups))
    live = set()
    for frame in (scanners or {}).values():
        if frame is None or len(frame) == 0 or "ticker" not in getattr(frame, "columns", []):
            continue
        if "status" not in frame.columns:
            continue
        status = frame["status"].astype(str)
        picked = frame[status.isin(LIVE_STATUS)]
        live.update(_tickers_of(picked))
    if not live or scores is None or len(scores) == 0 or "ticker" not in scores.columns:
        return set()
    table = scores.drop_duplicates("ticker").set_index("ticker")
    out = set()
    for ticker in live:
        if ticker not in table.index:
            continue
        row = table.loc[ticker]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        if str(row.get("verdict") or "") != "BUY":
            continue
        if not _flag_yes(row.get("above_sma50")) or not _flag_yes(row.get("above_sma200")):
            continue
        out.add(ticker)
    return out


def macro_trend(series, lookback=MACRO_LOOKBACK, flat=YIELD_FLAT):
    """Up, down, or flat versus about `lookback` observations ago.

    series is a DataFrame with columns date and v, oldest first. A short
    series stays missing rather than inventing a 3-month change.
    """
    empty = {"last": None, "prev": None, "trend": "missing", "asof": ""}
    if series is None or len(series) == 0 or "v" not in getattr(series, "columns", []):
        return empty
    s = series.copy()
    s["v"] = pd.to_numeric(s["v"], errors="coerce")
    s = s.dropna(subset=["v"])
    if len(s) < 20:
        last = float(s["v"].iloc[-1]) if len(s) else None
        asof = ""
        if len(s) and "date" in s.columns:
            asof = str(pd.Timestamp(s["date"].iloc[-1]).date())
        return {"last": last, "prev": None, "trend": "missing", "asof": asof}
    last = float(s["v"].iloc[-1])
    back = int(lookback)
    prev = float(s["v"].iloc[-1 - back] if len(s) > back else s["v"].iloc[0])
    delta = last - prev
    if abs(delta) < float(flat):
        trend = "flat"
    elif delta > 0:
        trend = "up"
    else:
        trend = "down"
    asof = str(pd.Timestamp(s["date"].iloc[-1]).date()) if "date" in s.columns else ""
    return {"last": last, "prev": prev, "trend": trend, "asof": asof}


def read_fred_cache(cache_dir):
    """Read the two FRED files the macro page already stores. No network."""
    import os
    out = {}
    for sid in ("DGS10", "T10Y2Y"):
        path = os.path.join(cache_dir, "fred_%s.csv" % sid)
        if not os.path.exists(path):
            continue
        frame = pd.read_csv(path)
        if frame.shape[1] < 2:
            continue
        frame = frame.iloc[:, :2].copy()
        frame.columns = ["date", "v"]
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["v"] = pd.to_numeric(frame["v"], errors="coerce")
        frame = frame.dropna(subset=["date", "v"]).sort_values("date")
        if len(frame):
            out[sid] = frame.reset_index(drop=True)
    return out


def _sector_list(sector_etfs):
    by_ticker = {}
    for row in sector_etfs or []:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            by_ticker[ticker] = row
    out = []
    for ticker, name, group in SPDR:
        row = by_ticker.get(ticker) or {}
        out.append({
            "ticker": ticker,
            "name": row.get("name") or name,
            "sector": row.get("group") or group,
        })
    return out


def _members(scores, sector):
    if scores is None or len(scores) == 0 or "sector" not in scores.columns:
        return scores.iloc[0:0] if scores is not None else pd.DataFrame()
    return scores[scores["sector"].astype(str) == str(sector)].copy()


def _mean(series):
    nums = pd.to_numeric(series, errors="coerce").dropna()
    if len(nums) == 0:
        return None
    return float(nums.mean())


def _share(mask, n):
    if not n:
        return None
    return 100.0 * float(mask) / float(n)


def _reason(name, quad_w, rs_3m, breadth200, near_n, buy_n, n_stocks):
    if quad_w:
        lead = "%s is %s on the weekly graph." % (name, quad_w)
    else:
        lead = "%s does not have a weekly quadrant yet." % name
    if rs_3m is None:
        rs_bit = "3-month relative strength versus SPY is not available."
    elif rs_3m > 0.05:
        rs_bit = "It has beaten SPY by %.1f points over 3 months." % rs_3m
    elif rs_3m < -0.05:
        rs_bit = "It has trailed SPY by %.1f points over 3 months." % abs(rs_3m)
    else:
        rs_bit = "It has matched SPY over 3 months."
    if n_stocks:
        breadth = breadth200 if breadth200 is not None else 0.0
        book = "%.0f%% of its %d stocks are above the 200-day average. %d are within 5%% of a 52-week high and %d are on a buy setup." % (
            breadth, int(n_stocks), int(near_n or 0), int(buy_n or 0),
        )
    else:
        book = "None of the scored stocks map to this sector."
    return " ".join((lead, rs_bit, book))


def _macro_fields(fred, lookback, flat):
    dgs = macro_trend(None if not fred else fred.get("DGS10"), lookback, flat)
    curve = macro_trend(None if not fred else fred.get("T10Y2Y"), lookback, flat)
    return {
        "dgs10_last": dgs["last"],
        "dgs10_prev": dgs["prev"],
        "dgs10_trend": dgs["trend"],
        "t10y2y_last": curve["last"],
        "t10y2y_prev": curve["prev"],
        "t10y2y_trend": curve["trend"],
    }


def _num_or_blank(value, digits=4):
    if _blank(value):
        return np.nan
    return round(float(value), digits)


def build(close, high, scores, sector_etfs, scanners=None, buy_setups=None, fred=None, cfg=None):
    """Snapshot, tail points, and backfilled quadrant history.

    Returns a dict of three frames. Callers that turn the feature off should
    pass the empty frames through tables.ensure.
    """
    empty = {
        "sector_rotation": pd.DataFrame(),
        "sector_rotation_tails": pd.DataFrame(),
        "sector_rotation_history": pd.DataFrame(),
        "log": "SPY or the sector ETFs were not in the price cache.",
    }
    if close is None or len(close) == 0 or "SPY" not in getattr(close, "columns", []):
        return empty
    windows = windows_from(cfg)
    weights = weights_from(cfg)
    near_pct = _cfg_num(cfg, "near_high_pct", NEAR_HIGH_PCT)
    w52 = int(_cfg_num(cfg, "w52_bars", W52_BARS))
    tail_keep = int(_cfg_num(cfg, "tail_keep", TAIL_KEEP))
    lookback = int(_cfg_num(cfg, "macro_lookback", MACRO_LOOKBACK))
    flat = float(_cfg_num(cfg, "yield_flat_band", YIELD_FLAT))
    sessions = dict(RS_SESSIONS)
    raw_sessions = (cfg or {}).get("rs_sessions") or {}
    for key in sessions:
        if key in raw_sessions:
            try:
                sessions[key] = int(raw_sessions[key])
            except (TypeError, ValueError):
                pass

    spy = close["SPY"]
    sectors = _sector_list(sector_etfs)
    buy_names = resolve_buy_tickers(scores, scanners, buy_setups)
    macro = _macro_fields(fred, lookback, flat)
    rows = []
    tails = []
    history = []
    skipped = []
    for spec in sectors:
        ticker = spec["ticker"]
        if ticker not in close.columns:
            skipped.append(ticker)
            continue
        series = {}
        for tf in ("D", "W", "M"):
            series[tf] = rrg_for_prices(close[ticker], spy, tf, windows)
        if all(len(series[tf]) == 0 for tf in ("D", "W", "M")):
            skipped.append(ticker)
            continue
        members = _members(scores, spec["sector"])
        n_stocks = int(len(members)) if members is not None else 0
        tickers = []
        if n_stocks and "ticker" in members.columns:
            tickers = [str(t).upper() for t in members["ticker"] if not _blank(t)]
        if n_stocks and "above_sma50" in members.columns:
            b50 = _share(sum(1 for v in members["above_sma50"] if _flag_yes(v)), n_stocks)
        else:
            b50 = None if n_stocks == 0 else None
        if n_stocks and "above_sma200" in members.columns:
            b200 = _share(sum(1 for v in members["above_sma200"] if _flag_yes(v)), n_stocks)
        else:
            b200 = None
        if n_stocks == 0:
            b50 = None
            b200 = None
        if high is None or len(getattr(high, "columns", [])) == 0:
            near = None
            near_share = None
        else:
            near_names = near_high_tickers(close, high, tickers, w52, near_pct) if n_stocks else set()
            near = len(near_names) if n_stocks else 0
            near_share = _share(near, n_stocks)
        buy_n = len(set(tickers) & buy_names) if n_stocks else 0
        buy_share_setup = _share(buy_n, n_stocks)
        score_avg = _mean(members["score"]) if n_stocks and "score" in members.columns else None
        if n_stocks and "verdict" in members.columns:
            buys = int((members["verdict"].astype(str) == "BUY").sum())
            buy_share = _share(buys, n_stocks)
        else:
            buy_share = None
        rs_1m = excess_return(close[ticker], spy, sessions["1m"])
        rs_3m = excess_return(close[ticker], spy, sessions["3m"])
        rs_6m = excess_return(close[ticker], spy, sessions["6m"])
        quad = {}
        last_ratio = {}
        last_mom = {}
        for tf in ("D", "W", "M"):
            frame = series[tf]
            if len(frame) == 0:
                quad[tf] = ""
                last_ratio[tf] = None
                last_mom[tf] = None
                continue
            quad[tf] = str(frame["quadrant"].iloc[-1])
            last_ratio[tf] = float(frame["rs_ratio"].iloc[-1])
            last_mom[tf] = float(frame["rs_momentum"].iloc[-1])
            kept = frame.tail(max(1, tail_keep))
            for i, (dt, point) in enumerate(kept.iterrows(), start=1):
                tails.append({
                    "timeframe": tf,
                    "ticker": ticker,
                    "name": spec["name"],
                    "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                    "rs_ratio": round(float(point["rs_ratio"]), 4),
                    "rs_momentum": round(float(point["rs_momentum"]), 4),
                    "quadrant": point["quadrant"],
                    "tail_index": i,
                    "data_status": "OK",
                    "note": TAIL_NOTE,
                })
            for dt, point in frame.iterrows():
                history.append({
                    "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                    "timeframe": tf,
                    "ticker": ticker,
                    "name": spec["name"],
                    "rs_ratio": round(float(point["rs_ratio"]), 4),
                    "rs_momentum": round(float(point["rs_momentum"]), 4),
                    "quadrant": point["quadrant"],
                    "data_status": "OK",
                    "note": HISTORY_NOTE,
                })
        bonus_quad = quad["W"] or quad["D"]
        rrg_pts = RRG_POINTS.get(bonus_quad)
        factors = {
            "rs_1m": clip_map(rs_1m, -RS_CLIP, RS_CLIP),
            "rs_3m": clip_map(rs_3m, -RS_CLIP, RS_CLIP),
            "rs_6m": clip_map(rs_6m, -RS_CLIP, RS_CLIP),
            "breadth_sma50": b50,
            "breadth_sma200": b200,
            "near_high": near_share,
            "buy_setups": buy_share_setup,
            "desk_score": clip_map(score_avg, DESK_CLIP[0], DESK_CLIP[1]),
            "buy_share": buy_share,
            "rrg": rrg_pts,
        }
        score = composite_score(factors, weights)
        prev_d = str(series["D"]["quadrant"].iloc[-2]) if len(series["D"]) >= 2 else ""
        prev_w = str(series["W"]["quadrant"].iloc[-2]) if len(series["W"]) >= 2 else ""
        row = {
            "ticker": ticker,
            "name": spec["name"],
            "sector": spec["sector"],
            "score": _num_or_blank(score, 4),
            "quadrant_d": quad["D"],
            "quadrant_w": quad["W"],
            "quadrant_m": quad["M"],
            "rs_ratio_w": _num_or_blank(last_ratio["W"]),
            "rs_momentum_w": _num_or_blank(last_mom["W"]),
            "rs_1m": _num_or_blank(rs_1m),
            "rs_3m": _num_or_blank(rs_3m),
            "rs_6m": _num_or_blank(rs_6m),
            "breadth_sma50": _num_or_blank(b50),
            "breadth_sma200": _num_or_blank(b200),
            "n_stocks": n_stocks,
            "near_high_count": np.nan if near is None else int(near),
            "near_high_share": _num_or_blank(near_share),
            "buy_setup_count": int(buy_n),
            "buy_setup_share": _num_or_blank(buy_share_setup),
            "score_avg": _num_or_blank(score_avg),
            "buy_share": _num_or_blank(buy_share),
            "rrg_points": _num_or_blank(rrg_pts, 1),
            "change_daily": describe_change(spec["name"], prev_d, quad["D"]),
            "change_weekly": describe_change(spec["name"], prev_w, quad["W"]),
            "reason": _reason(spec["name"], quad["W"], rs_3m, b200, 0 if near is None else near, buy_n, n_stocks),
            "data_status": "OK",
            "note": NOTE,
        }
        row.update(macro)
        rows.append(row)
    if not rows:
        empty["log"] = "No sector ETF had enough cached history. Skipped %s." % ", ".join(skipped)
        return empty
    snap = pd.DataFrame(rows)
    snap = snap.sort_values(["score", "ticker"], ascending=[False, True], na_position="last")
    snap["rank"] = np.arange(1, len(snap) + 1)
    order = [
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
        "reason", "data_status", "note",
    ]
    snap = snap[order]
    tail_df = pd.DataFrame(tails)
    if len(tail_df):
        tail_df = tail_df.sort_values(["timeframe", "ticker", "tail_index"])
    hist_df = pd.DataFrame(history)
    if len(hist_df):
        hist_df = hist_df.sort_values(["timeframe", "date", "ticker"])
    leading = int((snap["quadrant_w"] == "Leading").sum()) if "quadrant_w" in snap.columns else 0
    macro_bits = []
    if macro["dgs10_trend"] != "missing":
        macro_bits.append("10-year %s" % macro["dgs10_trend"])
    if macro["t10y2y_trend"] != "missing":
        macro_bits.append("10y-2y %s" % macro["t10y2y_trend"])
    macro_txt = ", ".join(macro_bits) if macro_bits else "no 10-year or curve file"
    skip_txt = ", ".join(skipped) if skipped else "none"
    log = "%d sectors, %d weekly Leading. Skipped (no price or not enough history): %s. Macro: %s. Dollar, oil, and gold are not on file." % (
        len(snap), leading, skip_txt, macro_txt,
    )
    return {
        "sector_rotation": snap,
        "sector_rotation_tails": tail_df,
        "sector_rotation_history": hist_df,
        "log": log,
    }


def maybe_buy_frame(setups_mod, frames, scores, close):
    """Use the buy-setup builder when a later version of the desk has one."""
    fn = getattr(setups_mod, "build_buy_setups", None)
    if fn is None or not frames:
        return None
    vcp = frames.get("scanner_vcp")
    box = frames.get("scanner_box")
    flag = frames.get("scanner_flag")
    canslim = frames.get("scanner_canslim")
    try:
        return fn(vcp, box, flag, canslim, scores, close=close)
    except TypeError:
        try:
            return fn(vcp, box, flag, canslim, scores)
        except Exception:
            return None
    except Exception:
        return None
