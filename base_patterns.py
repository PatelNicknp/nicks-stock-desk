"""Base pattern recognition for the Chart Viewer, copied from the published O'Neil / MarketSmith rules.

MarketSurge's own code is private, so this follows the public MarketSmith Pattern Recognition manual
(depth, length, pivot) and will not match MarketSurge on every stock. Research only, never a trade signal.

Rules used (weeks are 5 trading days, depth is left side high to the lowest low):
  Cup with handle      6 to 65 weeks, depth 12 to 50% (8% in MarketSmith, but under 15% it reads as a flat base),
                       the right side climbs back at least 65% of the way up, then a handle: 5 to 40 days, 3 to 25%
                       pullback that stays in the upper half of the cup. Pivot is the handle's peak.
  Cup (no handle)      same cup, no handle yet and the right side back within 15% of the depth of the left high. Pivot is the left side high.
  Double bottom        7 to 65 weeks, depth 10 to 50%, a W whose second low undercuts the first. Pivot is the middle peak.
  Flat base            5 to 65 weeks, depth 15% or less. Pivot is the left side high.
  Ascending base       9 to 16 weeks, three pullbacks of 6 to 25% with each low higher than the one before. Pivot is the high of the base.
  IPO base             2 to 5 weeks, depth 40% or less, only on a stock with about a year of history or less. Pivot is the left side high.
  Consolidation        5 to 65 weeks, depth 35% or less, within 10% of the left side high, and none of the above. Pivot is the left side high.
The left side high is a 100 day high. A base ends the day price trades above its pivot. The buy point is the
pivot plus 10 cents, and the buy zone is the pivot up to 5% above it (MarketSmith's Pivot Range).
"""
import os

import numpy as np
import pandas as pd

PATTERNS = ["cup_handle", "cup", "double_bottom", "flat_base", "ascending_base", "ipo_base", "consolidation"]
LABELS = {
    "cup_handle": "Cup with handle",
    "cup": "Cup",
    "double_bottom": "Double bottom",
    "flat_base": "Flat base",
    "ascending_base": "Ascending base",
    "ipo_base": "IPO base",
    "consolidation": "Consolidation",
}
SWITCHES = {p: p for p in PATTERNS}

DEFAULTS = {
    "lookback_bars": 520,          # left side highs from the last ~2 years
    "left_high_days": 100,
    "max_per_stock": 2,
    "buy_zone_pct": 5.0,
    "buy_point_cents": 10.0,
    "cup_min_weeks": 6, "cup_max_weeks": 65, "cup_min_depth": 12.0, "cup_max_depth": 50.0,
    "cup_recover_handle": 0.65, "cup_recover_plain": 0.85,
    "handle_min_days": 5, "handle_max_days": 40, "handle_min_depth": 3.0, "handle_max_depth": 25.0,
    "double_min_weeks": 7, "double_max_weeks": 65, "double_min_depth": 10.0, "double_max_depth": 50.0,
    "flat_min_weeks": 5, "flat_max_weeks": 65, "flat_max_depth": 15.0,
    "asc_min_weeks": 9, "asc_max_weeks": 16, "asc_min_pullback": 6.0, "asc_max_pullback": 25.0,
    "ipo_min_weeks": 2, "ipo_max_weeks": 5, "ipo_max_depth": 40.0, "ipo_max_history_days": 260,
    "consolidation_max_depth": 35.0, "consolidation_near_pct": 10.0,
}

COLS = [
    "ticker", "pattern", "latest", "status", "start_date", "end_date", "left_high", "low", "low_date",
    "depth_pct", "length_weeks", "pivot", "buy_point", "zone_top", "pct_from_pivot", "breakout_date",
    "handle_date", "handle_depth_pct", "first_low_date", "mid_peak_date",
]


def rules(cfg=None):
    out = dict(DEFAULTS)
    block = (cfg or {}).get("base_patterns") or {}
    for k in DEFAULTS:
        if k in block and block[k] is not None and not isinstance(block[k], bool):
            try:
                out[k] = float(block[k])
            except (TypeError, ValueError):
                pass
    out["on"] = {p: bool(block.get(p, True)) for p in PATTERNS}
    return out


def _next_greater(hi):
    n = len(hi)
    ng = np.full(n, n, dtype=int)
    stack = []
    for j in range(n):
        while stack and hi[j] > hi[stack[-1]]:
            ng[stack.pop()] = j
        stack.append(j)
    return ng


def _zigzag(hi, lo, thr):
    """Swing points [(index, price, 'H' or 'L')] with a thr (fraction) reversal."""
    n = len(hi)
    pts = []
    d = None
    hh, ll = (0, hi[0]), (0, lo[0])
    for k in range(1, n):
        if hi[k] > hh[1]:
            hh = (k, hi[k])
        if lo[k] < ll[1]:
            ll = (k, lo[k])
        if d is None:
            if hh[0] < k and lo[k] <= hh[1] * (1 - thr):
                pts.append((hh[0], hh[1], "H")); d = "down"; ll = (k, lo[k])
            elif ll[0] < k and hi[k] >= ll[1] * (1 + thr):
                pts.append((ll[0], ll[1], "L")); d = "up"; hh = (k, hi[k])
        elif d == "down":
            if hi[k] >= ll[1] * (1 + thr):
                pts.append((ll[0], ll[1], "L")); d = "up"; hh = (k, hi[k])
        else:
            if lo[k] <= hh[1] * (1 - thr):
                pts.append((hh[0], hh[1], "H")); d = "down"; ll = (k, lo[k])
    if d == "down":
        pts.append((ll[0], ll[1], "L"))
    elif d == "up":
        pts.append((hh[0], hh[1], "H"))
    return pts


def _weeks(bars):
    return bars / 5.0


def _cup(i, e0, m, hi, lo, ng, n, R):
    L = hi[i]
    low = lo[m]
    depth = (L - low) / L * 100.0
    if not (R["cup_min_depth"] <= depth <= R["cup_max_depth"]):
        return None
    if m - i < 12 or e0 - m < 10:
        return None
    seg_lo = lo[i:e0 + 1]
    band = low + (L - low) / 3.0
    if (seg_lo <= band).sum() < max(5, 0.10 * len(seg_lo)):
        return None  # a V, not a rounded bottom
    thr = low + R["cup_recover_handle"] * (L - low)
    after = np.nonzero(hi[m + 1:e0 + 1] >= thr)[0]
    if not len(after):
        return None
    cur = m + 1 + int(after[0])
    handle = None
    while cur <= e0:
        nx = int(ng[cur])
        bo = nx if nx < n else None
        stop = bo if bo is not None else n
        hlen = stop - cur - 1
        if hlen >= R["handle_min_days"]:
            hl_idx = cur + 1 + int(np.argmin(lo[cur + 1:cur + 1 + hlen]))
            hdepth = (hi[cur] - lo[hl_idx]) / hi[cur] * 100.0
            ok = (hlen <= R["handle_max_days"] and R["handle_min_depth"] <= hdepth <= R["handle_max_depth"]
                  and lo[hl_idx] >= low + 0.5 * (L - low) and cur - i + 1 >= 25)
            if ok:
                handle = {"peak": cur, "depth": hdepth, "bo": bo}
            break
        if nx > e0:
            break
        cur = nx
    if handle:
        end = (handle["bo"] - 1) if handle["bo"] is not None else n - 1
        end = min(end, e0)
        wk = _weeks(end - i + 1)
        if not (R["cup_min_weeks"] <= wk <= R["cup_max_weeks"]):
            return None
        return {"pattern": "cup_handle", "end": end, "pivot": float(hi[handle["peak"]]), "handle_idx": handle["peak"],
                "handle_depth": handle["depth"], "low_idx": m}
    rim = float(hi[m:e0 + 1].max())
    if rim < low + R["cup_recover_plain"] * (L - low):
        return None
    wk = _weeks(e0 - i + 1)
    if not (R["cup_min_weeks"] <= wk <= R["cup_max_weeks"]):
        return None
    return {"pattern": "cup", "end": e0, "pivot": float(L), "low_idx": m}


def _double_bottom(i, e0, m, hi, lo, n, R):
    L = hi[i]
    b2 = m
    depth = (L - lo[b2]) / L * 100.0
    if not (R["double_min_depth"] <= depth <= R["double_max_depth"]):
        return None
    lo_rng = i + 5
    hi_rng = b2 - 10
    if hi_rng <= lo_rng:
        return None
    b1 = lo_rng + int(np.argmin(lo[lo_rng:hi_rng + 1]))
    if not (lo[b2] < lo[b1] and (lo[b1] - lo[b2]) / lo[b1] <= 0.20):
        return None
    if (L - lo[b1]) / L < 0.08:
        return None
    p = b1 + 1 + int(np.argmax(hi[b1 + 1:b2]))
    P = float(hi[p])
    if (P - lo[b1]) / lo[b1] < 0.10:
        return None
    if not (0.2 <= (p - i) / max(1, (b2 - i)) <= 0.85):
        return None
    if float(hi[b2:e0 + 1].max()) < lo[b2] + 0.5 * (P - lo[b2]) and e0 - b2 < 15:
        return None
    end = e0
    over = np.nonzero(hi[b2 + 1:e0 + 1] > P)[0]
    if len(over):
        end = b2 + 1 + int(over[0]) - 1
    if end - b2 < 3:
        return None
    wk = _weeks(end - i + 1)
    if not (R["double_min_weeks"] <= wk <= R["double_max_weeks"]):
        return None
    return {"pattern": "double_bottom", "end": end, "pivot": P, "low_idx": b2, "first_low_idx": b1, "mid_idx": p}


def _classify(i, e0, hi, lo, cl, ng, n, R):
    on = R["on"]
    bars = e0 - i + 1
    wk = _weeks(bars)
    L = float(hi[i])
    seg_lo = lo[i:e0 + 1]
    m = i + int(np.argmin(seg_lo))
    depth = (L - lo[m]) / L * 100.0
    if wk > R["flat_max_weeks"] or bars < 8:
        return None
    if on["ipo_base"] and n <= R["ipo_max_history_days"] and R["ipo_min_weeks"] <= wk < R["ipo_max_weeks"] and depth <= R["ipo_max_depth"]:
        return {"pattern": "ipo_base", "end": e0, "pivot": L, "low_idx": m}
    if bars < 25:
        return None
    found = None
    if on["double_bottom"]:
        found = _double_bottom(i, e0, m, hi, lo, n, R)
    if not found and (on["cup_handle"] or on["cup"]):
        c = _cup(i, e0, m, hi, lo, ng, n, R)
        if c and on[c["pattern"]]:
            found = c
    if not found and depth <= R["flat_max_depth"] and wk >= R["flat_min_weeks"] and on["flat_base"]:
        if cl[e0] >= lo[m] + 0.35 * (L - lo[m]):
            found = {"pattern": "flat_base", "end": e0, "pivot": L, "low_idx": m}
    if not found and on["consolidation"] and depth <= R["consolidation_max_depth"] and wk >= R["flat_min_weeks"] \
            and cl[e0] >= L * (1 - R["consolidation_near_pct"] / 100.0):
        found = {"pattern": "consolidation", "end": e0, "pivot": L, "low_idx": m}
    return found


def _ascending(hi, lo, n, R, close_last):
    """Latest ascending base ending at the last bar, or a few days before a breakout."""
    max_bars = int(R["asc_max_weeks"] * 5)
    min_bars = int(R["asc_min_weeks"] * 5)
    for back in range(0, 16):
        e = n - 1 - back
        s = max(0, e - max_bars - 4)
        if e - s < min_bars:
            return None
        pts = _zigzag(hi[s:e + 1], lo[s:e + 1], R["asc_min_pullback"] / 100.0)
        pts = [(k + s, p, t) for k, p, t in pts]
        pulls = []
        for a, b in zip(pts, pts[1:]):
            if a[2] == "H" and b[2] == "L":
                d = (a[1] - b[1]) / a[1] * 100.0
                if R["asc_min_pullback"] <= d <= R["asc_max_pullback"]:
                    pulls.append((a, b, d))
        if len(pulls) < 3:
            continue
        last3 = pulls[-3:]
        lows = [x[1][1] for x in last3]
        if not (lows[0] < lows[1] < lows[2]):
            continue
        # The three pullbacks must be back to back, not separated by another full swing.
        start = last3[0][0][0]
        wk = _weeks(e - start + 1)
        if not (R["asc_min_weeks"] <= wk <= R["asc_max_weeks"]):
            continue
        # Each rally between pullbacks must climb back near the prior high (a staircase, not a slide).
        if last3[1][0][1] < last3[0][0][1] * 0.97 or last3[2][0][1] < last3[1][0][1] * 0.97:
            continue
        pivot = float(hi[start:e + 1].max())
        if float(close_last) < pivot * 0.85:
            continue
        lowest = float(lows[0])
        return {"pattern": "ascending_base", "start": start, "end": e, "pivot": pivot,
                "low_idx": last3[0][1][0], "depth": (pivot - lowest) / pivot * 100.0}
    return None


def detect_bases(dates, high, low, close, cfg=None):
    """Bases found on one stock, oldest first. Each is a dict ready for rows_for (indexes into the arrays)."""
    R = rules(cfg)
    hi = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    cl = np.asarray(close, dtype=float)
    n = len(cl)
    if n < 30 or not np.isfinite(hi).all() or not np.isfinite(lo).all():
        return []
    ng = _next_greater(hi)
    roll = pd.Series(hi).rolling(int(R["left_high_days"]), min_periods=1).max().values
    first = max(0, n - int(R["lookback_bars"]))
    out = []
    last_end = -1
    for i in range(first, n - 9):
        if hi[i] < roll[i] or i <= last_end:
            continue
        e0 = int(ng[i]) - 1 if ng[i] < n else n - 1
        if e0 - i + 1 < 8:
            continue
        found = _classify(i, e0, hi, lo, cl, ng, n, R)
        if found:
            found["start"] = i
            out.append(found)
            last_end = found["end"]
    if R["on"]["ascending_base"]:
        asc = _ascending(hi, lo, n, R, cl[-1])
        if asc:
            keep = []
            blocked = False
            for b in out:
                if b["end"] >= asc["start"]:
                    if b["pattern"] in ("flat_base", "consolidation"):
                        continue
                    blocked = True
                keep.append(b)
            if not blocked:
                out = keep + [asc]
    out.sort(key=lambda b: b["start"])
    return out[-int(R["max_per_stock"]):]


def _status(b, hi, cl, n, R, latest):
    pivot = b["pivot"]
    over = np.nonzero(hi[b["end"] + 1:] > pivot)[0]
    bo = b["end"] + 1 + int(over[0]) if len(over) else None
    c = float(cl[-1])
    pct = (c / pivot - 1.0) * 100.0
    zone = R["buy_zone_pct"]
    if not latest:
        return "COMPLETED", bo, pct
    if bo is None:
        return ("NEAR PIVOT" if pct >= -zone else "FORMING"), None, pct
    if n - 1 - bo > 60:
        return "COMPLETED", bo, pct
    if pct < 0:
        return "BELOW PIVOT", bo, pct
    return ("BUY ZONE" if pct <= zone else "EXTENDED"), bo, pct


def rows_for(ticker, dates, high, low, close, cfg=None):
    R = rules(cfg)
    hi = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    cl = np.asarray(close, dtype=float)
    n = len(cl)
    bases = detect_bases(dates, hi, lo, cl, cfg)
    rows = []
    for k, b in enumerate(bases):
        latest = k == len(bases) - 1
        s = b["start"]
        left = float(hi[s]) if b["pattern"] != "ascending_base" else float(hi[s:b["end"] + 1].max())
        low_idx = b["low_idx"]
        status, bo, pct = _status(b, hi, cl, n, R, latest)
        pivot = round(float(b["pivot"]), 4)
        lowest = float(lo[s:b["end"] + 1].min())
        depth = b.get("depth")
        if depth is None:
            depth = (left - lowest) / left * 100.0
        rows.append({
            "ticker": ticker, "pattern": b["pattern"], "latest": "yes" if latest else "no",
            "status": status, "start_date": dates[s], "end_date": dates[b["end"]], "left_high": round(left, 4),
            "low": round(lowest, 4), "low_date": dates[low_idx], "depth_pct": round(depth, 1),
            "length_weeks": round(_weeks(b["end"] - s + 1), 1), "pivot": pivot,
            "buy_point": round(pivot + R["buy_point_cents"] / 100.0, 4), "zone_top": round(pivot * (1 + R["buy_zone_pct"] / 100.0), 4),
            "pct_from_pivot": round(pct, 2), "breakout_date": dates[bo] if bo is not None else "",
            "handle_date": dates[b["handle_idx"]] if "handle_idx" in b else "",
            "handle_depth_pct": round(b["handle_depth"], 1) if "handle_depth" in b else "",
            "first_low_date": dates[b["first_low_idx"]] if "first_low_idx" in b else "",
            "mid_peak_date": dates[b["mid_idx"]] if "mid_idx" in b else "",
        })
    return rows


def scan(close, high, low, tickers=None, cfg=None):
    """DataFrame (COLS) for the wide close/high/low frames the desk run already holds (index dates, columns tickers)."""
    rows = []
    names = list(tickers) if tickers is not None else list(close.columns)
    for t in names:
        if t not in close.columns or t not in high.columns or t not in low.columns:
            continue
        d = pd.DataFrame({"c": close[t], "h": high[t], "l": low[t]}).dropna()
        if len(d) < 30:
            continue
        dates = [x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x)[:10] for x in d.index]
        rows += rows_for(str(t), dates, d["h"].values, d["l"].values, d["c"].values, cfg)
    return pd.DataFrame(rows, columns=COLS)


def scan_ohlc_dir(ohlc_dir, tickers=None, cfg=None):
    """Same scan, read from the saved data/ohlc/<T>.csv files (no download). Used by the command line and tests."""
    rows = []
    names = tickers or sorted(f[:-4] for f in os.listdir(ohlc_dir) if f.endswith(".csv"))
    for t in names:
        path = os.path.join(ohlc_dir, t + ".csv")
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path).dropna(subset=["high", "low", "close"])
        if len(d) < 30:
            continue
        rows += rows_for(t, [str(x)[:10] for x in d["date"]], d["high"].values, d["low"].values, d["close"].values, cfg)
    return pd.DataFrame(rows, columns=COLS)


def export_frame(frame, feature_on=True):
    """Frame for data/base_patterns.csv: the bases with data_status OK, one MISSING row when none were found, empty when off."""
    cols = COLS + ["data_status"]
    if not feature_on:
        return pd.DataFrame(columns=cols)
    if frame is None or not len(frame):
        return pd.DataFrame([{"data_status": "MISSING"}], columns=cols)
    out = frame.copy()
    out["data_status"] = "OK"
    return out[cols]


def summary(frame):
    """{pattern: stocks whose latest base is that pattern} and how many of those are forming, near, or in the buy zone."""
    if frame is None or not len(frame):
        return {}
    last = frame[frame["latest"] == "yes"]
    out = {}
    for p in PATTERNS:
        g = last[last["pattern"] == p]
        out[p] = {"stocks": int(len(g)), "actionable": int(g["status"].isin(["NEAR PIVOT", "BUY ZONE"]).sum())}
    return out


def main(argv=None):
    """python base_patterns.py: rebuild data/base_patterns.csv from the saved data/ohlc files. No download."""
    import json
    import sys
    root = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(root, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    frame = scan_ohlc_dir(os.path.join(root, "data", "ohlc"), cfg=cfg)
    out = export_frame(frame)
    out.to_csv(os.path.join(root, "data", "base_patterns.csv"), index=False, na_rep="")
    sys.stdout.write("bases %d stocks %d\n" % (len(frame), frame["ticker"].nunique() if len(frame) else 0))
    for k, v in summary(frame).items():
        sys.stdout.write("%s %s\n" % (k, v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
