"""Gap Up scanner for the US desk. Research only: it never places a trade.

A true gap: the open is at least 3% above the previous day's high (min_gap_filter; off, any size). Gap-day volume is at least 1.5 times the
average of the 50 sessions before the gap day. The stock must hold: no close since the gap day below the
gap day's low (a close equal to the low still holds). Gap days from the last 21 trading days, today included.
The newest holding gap decides the row. Cached daily bars only (cache/ohlcv.csv.gz). No new downloads.
"""
import numpy as np
import pandas as pd

import setups
from setups import _num, _round

GAP_UP_DEFAULTS = {
    "lookback_days": 21,
    "true_gap_only": True,
    "min_gap_filter": True,
    "min_gap_pct": 3.0,
    "volume_filter": True,
    "vol_mult": 1.5,
    "vol_avg_days": 50,
    "price_floor": True,
    "min_price": 5.0,
    "liquidity_floor": True,
    "liquidity_days": 50,
    "min_dollar_volume": 3000000.0,
    "hold_rule": True,
    "skip_stale": True,
    "sma_fast": 50,
    "sma_slow": 200,
    "show_other_scanners": True,
}

GAP_TODAY = "GAP UP today"
GAP_HOLDING = "GAP HOLDING"
GAP_NOTE = (
    "Gap Up: the open is at least 3% above the previous day's high (a true gap), on at least 1.5 times the "
    "50-day average volume, and no close since then below the gap day's low. Gap days from the last 21 trading days. "
    "Cached daily bars only. No new downloads. Research only. This desk never places trades."
)

# Other scanners a stock is in, with the Chart Viewer's short names. include_watching on, include_closed off.
PATTERN_FILES = (
    ("VCP", "scanner_vcp"), ("CANSLIM", "scanner_canslim"), ("Box", "scanner_box"), ("Flag", "scanner_flag"),
    ("Qullamaggie", "scanner_qullamaggie"), ("Marios", "scanner_marios"), ("EP", "scanner_ep"),
    ("Leaders", "scanner_leaders"), ("Breakdown", "scanner_breakdown"),
)
PASS_FILES = (("Growth", "scanner_growth"), ("Quality", "scanner_quality"), ("Dividend", "scanner_dividend"), ("Wheel", "scanner_wheel"))


def gap_cfg(cfg):
    out = dict(GAP_UP_DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("gap_up") or {}).items() if not str(k).startswith("_")})
    return out


def _yes(v):
    return str(v).strip().lower() in ("yes", "true", "1")


def _prior_mean(arr, i, n):
    """Mean of the n values before bar i. None when any is missing or there are fewer than n."""
    if n <= 0 or i < n:
        return None
    seg = arr[i - n:i]
    if not np.isfinite(seg).all():
        return None
    m = float(seg.mean())
    return m if m > 0 else None


def find_gap(o, h, l, c, v, p):
    """Index of the newest gap day in the window that passes every rule that is on, or None.

    Bars are oldest first and the last bar is today. Returns (i, volume average) or (None, None)."""
    n = len(c)
    t = n - 1
    look = max(1, int(p["lookback_days"]))
    avg_n = int(p["vol_avg_days"])
    lo = max(1, t - look + 1)
    for i in range(t, lo - 1, -1):
        prev_h, prev_c, op = h[i - 1], c[i - 1], o[i]
        if not (np.isfinite(op) and np.isfinite(prev_h) and np.isfinite(prev_c) and prev_h > 0 and prev_c > 0):
            continue
        base = prev_h if p["true_gap_only"] else prev_c
        if not op > base:
            continue
        # min_gap_pct is a whole percent (3.0 means 3%). A tiny tolerance keeps an exact 3% gap in despite float rounding.
        if p["min_gap_filter"] and (op / base - 1.0) * 100.0 + 1e-9 < float(p["min_gap_pct"]):
            continue
        avg = _prior_mean(v, i, avg_n)
        if p["volume_filter"]:
            if avg is None or not np.isfinite(v[i]) or v[i] < float(p["vol_mult"]) * avg:
                continue
        if p["hold_rule"]:
            after = c[i + 1:t + 1]
            if len(after) and (not np.isfinite(after).all() or (after < l[i]).any()):
                continue
        return i, avg
    return None, None


def scan_gap_up(close, high, low, vol, opn, universe, cfg=None):
    """One row per stock with a holding gap up in the last lookback_days sessions. No network, no clock."""
    p = gap_cfg(cfg)
    rows = []
    if close is None or len(close) == 0 or opn is None or len(getattr(opn, "columns", [])) == 0 or universe is None or len(universe) == 0:
        return pd.DataFrame(rows)
    panel = setups._panel_date(close)
    names = list(universe["ticker"]) if "ticker" in universe.columns else []
    fast, slow = int(p["sma_fast"]), int(p["sma_slow"])
    liq_n = int(p["liquidity_days"])
    for ticker in names:
        if ticker not in close.columns or ticker not in opn.columns:
            continue
        frame = pd.DataFrame({
            "open": opn[ticker], "close": close[ticker],
            "high": high[ticker] if ticker in high.columns else np.nan,
            "low": low[ticker] if ticker in low.columns else np.nan,
            "volume": vol[ticker] if ticker in vol.columns else np.nan,
        }).dropna(subset=["open", "close", "high", "low"])
        n = len(frame)
        if n < 2:
            continue
        if p["skip_stale"] and panel is not None and pd.Timestamp(frame.index[-1]).normalize() < pd.Timestamp(panel).normalize():
            continue
        o = frame["open"].to_numpy(dtype=float)
        h = frame["high"].to_numpy(dtype=float)
        l = frame["low"].to_numpy(dtype=float)
        c = frame["close"].to_numpy(dtype=float)
        v = frame["volume"].to_numpy(dtype=float)
        t = n - 1
        last = float(c[t])
        if p["price_floor"] and not last >= float(p["min_price"]):
            continue
        dv = None
        if n >= liq_n and liq_n > 0:
            seg = (c * v)[-liq_n:]
            if np.isfinite(seg).all():
                dv = float(seg.mean())
        if p["liquidity_floor"] and (dv is None or dv < float(p["min_dollar_volume"])):
            continue
        i, avg = find_gap(o, h, l, c, v, p)
        if i is None:
            continue
        gap_pct = (o[i] / h[i - 1] - 1.0) * 100.0
        gap_close_pct = (o[i] / c[i - 1] - 1.0) * 100.0
        mult = v[i] / avg if avg else None
        hold = float(l[i])
        above_hold = (last / hold - 1.0) * 100.0 if hold > 0 else None
        rng = h[t] - l[t]
        pos = (last - l[t]) / rng * 100.0 if rng > 0 else None
        s_fast = float(np.mean(c[-fast:])) if n >= fast else None
        s_slow = float(np.mean(c[-slow:])) if n >= slow else None
        low_close = float(np.min(c[i:t + 1]))
        days_ago = t - i
        meta = setups._meta_row(universe, ticker)
        gap_date = str(pd.Timestamp(frame.index[i]).date())
        row = {
            "ticker": ticker, "company": meta["company"], "sector": meta["sector"], "index_membership": meta["index_membership"],
            "status": GAP_TODAY if days_ago == 0 else GAP_HOLDING,
            "gap_date": gap_date, "days_ago": days_ago,
            "gap_pct": _round(gap_pct, 2), "gap_vs_close_pct": _round(gap_close_pct, 2),
            "volume_mult": _round(mult, 2), "gap_volume": int(round(v[i])) if np.isfinite(v[i]) else "",
            "avg_volume_50": int(round(avg)) if avg else "",
            "hold_level": _round(hold), "gap_open": _round(o[i]), "gap_high": _round(h[i]), "gap_close": _round(c[i]),
            "prev_high": _round(h[i - 1]), "prev_close": _round(c[i - 1]),
            "price": _round(last), "pct_above_hold": _round(above_hold, 2),
            "close_pos_pct": _round(pos, 0), "lowest_close_since": _round(low_close),
            "above_sma50": "" if s_fast is None else ("yes" if last > s_fast else "no"),
            "above_sma200": "" if s_slow is None else ("yes" if last > s_slow else "no"),
            "sma50": _round(s_fast), "sma200": _round(s_slow),
            "dollar_volume_50d_m": _round(dv / 1e6 if dv is not None else None, 1),
            "other_scanners": "",
            "freshness": setups._freshness(frame.index[-1], panel, n, max(int(p["vol_avg_days"]) + 2, slow)),
            "price_as_of": str(pd.Timestamp(frame.index[-1]).date()),
            "data_status": "OK", "note": GAP_NOTE,
        }
        row["reason"] = _reason(row, p)
        rows.append(row)
    return sort_rows(pd.DataFrame(rows))


def sort_rows(df):
    """Newest gap first, then the bigger gap, then ticker."""
    if df is None or len(df) == 0:
        return df if df is not None else pd.DataFrame()
    out = df.copy()
    out["_g"] = pd.to_numeric(out["gap_pct"], errors="coerce")
    out = out.sort_values(["gap_date", "_g", "ticker"], ascending=[False, False, True], kind="mergesort")
    return out.drop(columns="_g").reset_index(drop=True)


def _fmt(x, nd=2):
    x = _num(x)
    return "" if x is None else ("%." + str(nd) + "f") % x


def _reason(row, p):
    when = "today" if row["days_ago"] == 0 else ("%d trading day%s ago" % (row["days_ago"], "" if row["days_ago"] == 1 else "s"))
    bits = ["Gapped up %s%% over the prior day's high (%s%% over the prior close) on %s, %s." % (
        _fmt(row["gap_pct"]), _fmt(row["gap_vs_close_pct"]), row["gap_date"], when)]
    if _num(row["volume_mult"]) is not None:
        bits.append("Volume was %sx the %d-day average." % (_fmt(row["volume_mult"], 1), int(p["vol_avg_days"])))
    if p["hold_rule"]:
        if row["days_ago"] == 0:
            bits.append("The hold level is the gap-day low %s." % _fmt(row["hold_level"]))
        else:
            bits.append("No close since then below the gap-day low %s (lowest close %s)." % (_fmt(row["hold_level"]), _fmt(row["lowest_close_since"])))
    bits.append("Last close %s is %s%% above the hold level." % (_fmt(row["price"]), _fmt(row["pct_above_hold"], 1)))
    return " ".join(bits)


def _in_frame(df, test):
    out = set()
    if df is None or len(df) == 0 or "ticker" not in df.columns:
        return out
    for _, r in df.iterrows():
        t = str(r.get("ticker") or "").strip().upper()
        if not t or str(r.get("data_status") or "") == "MISSING":
            continue
        if test(r):
            out.add(t)
    return out


def scanner_membership(frames):
    """{ticker: [short names]} for the scanners each stock is on, the way the Chart Viewer counts them."""
    frames = frames or {}
    sets = []

    def status_ok(r):
        s = str(r.get("status") if r.get("status") is not None else "").strip()
        return bool(s) and s.lower() != "nan" and s != "CLOSED"

    for label, key in PATTERN_FILES:
        sets.append((label, _in_frame(frames.get(key), status_ok)))
    sets.append(("High volume", _in_frame(frames.get("scanner_volume"), lambda r: _yes(r.get("spike")) or _yes(r.get("streak")) or _yes(r.get("quiet")))))
    sets.append(("52-week", _in_frame(frames.get("scanner_52w"), lambda r: _yes(r.get("new_high_today")) or _yes(r.get("new_low_today")) or _yes(r.get("near_high")))))
    for label, key in PASS_FILES:
        sets.append((label, _in_frame(frames.get(key), lambda r: _yes(r.get("passes")))))
    out = {}
    for label, names in sets:
        for t in names:
            out.setdefault(t, []).append(label)
    return out


def attach_other_scanners(gap, frames, cfg=None):
    """Fill other_scanners (comma list) on the gap rows. Buy setups are not a scanner and are left out."""
    if gap is None or len(gap) == 0:
        return gap
    p = gap_cfg(cfg)
    out = gap.copy()
    if not p["show_other_scanners"]:
        out["other_scanners"] = ""
        return out
    member = scanner_membership(frames)
    out["other_scanners"] = [", ".join(member.get(str(t).upper(), [])) for t in out["ticker"]]
    return out
