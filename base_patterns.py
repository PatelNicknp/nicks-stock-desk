"""Base pattern recognition for the Chart Viewer, copied from the published O'Neil / MarketSmith rules.

MarketSurge's own code is private, so this follows the public O'Neil and MarketSmith Pattern Recognition rules
(depth, length, prior uptrend, pivot) and will not match MarketSurge on every stock. Research only, never a trade signal.

Rules used (weeks are 5 trading days, depth is the left side high down to the lowest low; every number is in the
base_patterns block of config.json):
  Prior uptrend        every base except an IPO base needs the left side high at least prior_uptrend_pct (30%) above
                       the lowest low of the prior_uptrend_bars (130, about 6 months) before it (require_prior_uptrend).
  Cup with handle      7 to 65 weeks, 12 to 33% deep (up to 50% when the market was in a correction of
                       bear_market_drawdown or more at the cup's low; flagged deep_base, allow_deep_in_bear). A rounded
                       bottom (not a V). The right side climbs back at least cup_recover_handle of the way, then a handle
                       of 5 to 30 days that drifts down (handle_drift_down), is 2 to 12% deep (15% in a weak market),
                       stays in the upper half of the cup, and holds the 10-week line (handle_above_10wk). Pivot is the
                       handle's high.
  Cup (no handle)      the same cup with the right side back within cup_recover_plain of the depth. Pivot is the left side high.
  Saucer               a cup that is longer (saucer_min_weeks, 20, or more) and shallower (saucer_max_depth, 25%, or less),
                       with or without a handle. Pivot as for the cup.
  Double bottom        7 to 65 weeks, 12 to 33% deep (50% in a weak market), a W whose second low undercuts the first
                       (by double_max_undercut or less). Pivot is the middle peak.
  Flat base            5 to 65 weeks, 15% deep or less (and min_depth, 3%, or more: a pinned price is a pending deal,
                       not a base). Pivot is the base high.
  Ascending base       9 to 16 weeks, three pullbacks of 10 to 20% each, each low higher than the one before, and the
                       whole base asc_max_depth (25%) deep or less. Pivot is the base high.
  IPO base             3 to 25 weeks, up to 50% deep, on a stock with about a year of history or less. No prior uptrend.
  Consolidation        off by default (it used to be a catch-all): only a tight range (consolidation_max_depth) of
                       5 weeks or more after a prior uptrend that fits nothing above.
Base count (count_stages): bases since the last major low. A base whose low undercuts the prior base's low, or a dip
below that low between them, starts again at Stage 1. The next base counts as a new stage only when the stock rose
stage_new_pct (20%) above the prior base's pivot first; otherwise it is the same stage with a letter: 2, 2(b), 2(c).
Breakout: the first close above the pivot after the base. breakout_volume_ok is yes when that day's volume is
breakout_volume_pct (40%) or more above the 50-day average volume. A base fails (mark_failed) when price closes
failed_pct (7.5%) or more below the pivot within failed_window_bars (40) of the breakout, before it gained
failed_unless_gain_pct (20%). The buy point is the pivot plus 10 cents, and the buy zone is
the pivot up to 5% above it (MarketSmith's Pivot Range).
"""
import os

import numpy as np
import pandas as pd

PATTERNS = ["cup_handle", "cup", "saucer", "double_bottom", "flat_base", "ascending_base", "ipo_base", "consolidation"]
LABELS = {
    "cup_handle": "Cup with handle",
    "cup": "Cup",
    "saucer": "Saucer",
    "double_bottom": "Double bottom",
    "flat_base": "Flat base",
    "ascending_base": "Ascending base",
    "ipo_base": "IPO base",
    "consolidation": "Consolidation",
}
SWITCHES = {p: p for p in PATTERNS}
# Patterns that are on unless the config turns them on or off. Consolidation is off: it is no longer a catch-all.
PATTERN_DEFAULT_ON = {p: p != "consolidation" for p in PATTERNS}
# Rule switches (true or false in the base_patterns block).
FLAGS = {
    "require_prior_uptrend": True,
    "allow_deep_in_bear": True,
    "handle_above_10wk": True,
    "handle_drift_down": True,
    "count_stages": True,
    "mark_failed": True,
    "robust_bounds": True,   # a one-bar spike wick does not set a base's low or depth
    "prefer_tight": True,    # of several left-side highs at about the same price, start at the one giving the tightest base
}

DEFAULTS = {
    "spike_atr_mult": 1.0,         # a low more than this many ATRs under the 2 bars each side is a spike, clipped there
    "spike_neighbors": 2,
    "tight_start_pct": 3.0,        # later highs within this % of the left-side high can start the base instead
    "lookback_bars": 300,          # bases shown end in the last ~14 months
    "count_lookback_bars": 1300,   # bases counted for the stage, about 5 years
    "left_high_days": 100,
    "max_per_stock": 2,
    "buy_zone_pct": 5.0,
    "buy_point_cents": 10.0,
    "prior_uptrend_pct": 30.0, "prior_uptrend_bars": 130,
    "bear_market_drawdown": 15.0,
    "cup_min_weeks": 7, "cup_max_weeks": 65, "cup_min_depth": 12.0, "cup_max_depth": 33.0, "cup_max_depth_bear": 50.0,
    "cup_round_band": 0.25, "cup_round_min_share": 0.27,
    "cup_recover_handle": 0.80, "cup_recover_plain": 0.90,
    "handle_min_days": 5, "handle_max_days": 30, "handle_min_depth": 2.0, "handle_max_depth": 12.0, "handle_max_depth_bear": 15.0, "handle_wedge_tol": 1.5,
    "saucer_min_weeks": 20, "saucer_max_depth": 25.0,
    "double_min_weeks": 7, "double_max_weeks": 65, "double_min_depth": 12.0, "double_max_depth": 33.0,
    "double_max_depth_bear": 50.0, "double_max_undercut": 15.0,
    "flat_min_weeks": 5, "flat_max_weeks": 65, "flat_max_depth": 15.0,
    "min_depth": 3.0,              # flat, IPO, and tight ranges shallower than this are a pinned price (a pending deal), not a base
    "asc_min_weeks": 9, "asc_max_weeks": 16, "asc_min_pullback": 10.0, "asc_max_pullback": 20.0, "asc_max_depth": 25.0, "asc_high_tolerance": 1.0,
    "ipo_min_weeks": 3, "ipo_max_weeks": 25, "ipo_max_depth": 50.0, "ipo_max_history_days": 260,
    "consolidation_min_weeks": 5, "consolidation_max_depth": 20.0,
    "stage_new_pct": 20.0,
    "breakout_volume_pct": 40.0,
    "failed_pct": 7.5,
    "failed_window_bars": 40,
    "failed_unless_gain_pct": 20.0,
    "completed_after_bars": 60,
}

COLS = [
    "ticker", "pattern", "latest", "status", "start_date", "end_date", "left_high", "low", "low_date",
    "depth_pct", "length_weeks", "pivot", "buy_point", "zone_top", "pct_from_pivot", "breakout_date",
    "handle_date", "handle_depth_pct", "first_low_date", "mid_peak_date",
    "rim_date", "handle_low_date", "stage", "stage_label", "deep_base", "prior_uptrend_pct",
    "breakout_volume_pct", "breakout_volume_ok", "failed_date", "pullback_low_dates", "pullback_high_dates",
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
    out["on"] = {p: bool(block.get(p, PATTERN_DEFAULT_ON[p])) for p in PATTERNS}
    for k, v in FLAGS.items():
        out[k] = bool(block.get(k, v))
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


def robust_lows(hi, lo, cl, R):
    """Lows with one-bar spike wicks clipped: a low more than spike_atr_mult ATRs (14-day) under the lowest low of the
    spike_neighbors bars on each side is raised to that line (never above the bar's close). A real multi-day drop keeps
    its lows, because its neighbors are low too."""
    lo = np.asarray(lo, dtype=float)
    if not R.get("robust_bounds", True) or len(lo) < 5:
        return lo.copy()
    hi = np.asarray(hi, dtype=float)
    cl = np.asarray(cl, dtype=float)
    pc = np.concatenate([[cl[0]], cl[:-1]])
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    k = max(1, int(R["spike_neighbors"]))
    s = pd.Series(lo)
    left = s.shift(1).rolling(k, min_periods=1).min()
    right = s[::-1].shift(1).rolling(k, min_periods=1).min()[::-1]
    nb = np.fmin(left.values, right.values)
    line = nb - R["spike_atr_mult"] * atr
    clip = np.isfinite(line) & (lo < line)
    out = lo.copy()
    out[clip] = np.minimum(line[clip], np.maximum(cl[clip], lo[clip]))
    return np.maximum(out, lo)


def _weeks(bars):
    return bars / 5.0


class _Ctx:
    """Arrays and rules for one stock."""

    def __init__(self, hi, lo, cl, vol, mkt_dd, R):
        self.hi, self.lo, self.cl, self.vol, self.R = hi, lo, cl, vol, R
        self.n = len(cl)
        self.ng = _next_greater(hi)
        self.sma50 = pd.Series(cl).rolling(50, min_periods=50).mean().values
        self.mkt_dd = mkt_dd

    def weak_market(self, idx):
        """True when the market (SPY) was bear_market_drawdown or more below its 1-year high at that bar."""
        if not self.R["allow_deep_in_bear"] or self.mkt_dd is None:
            return False
        v = self.mkt_dd[idx]
        return bool(np.isfinite(v) and v <= -self.R["bear_market_drawdown"])

    def prior_uptrend(self, i):
        bars = int(self.R["prior_uptrend_bars"])
        a = max(0, i - bars)
        if i - a < 20:
            return None
        base = float(np.min(self.lo[a:i + 1]))
        return (float(self.hi[i]) / base - 1.0) * 100.0 if base > 0 else None


def _handle(C, cup_lo, L, low, cur, e0, weak):
    """Handle starting at the right side peak cur: (dict or None, why)."""
    R, hi, lo, cl = C.R, C.hi, C.lo, C.cl
    nx = int(C.ng[cur])
    bo = nx if nx < C.n else None
    stop = bo if bo is not None else C.n
    hlen = stop - cur - 1
    if hlen < R["handle_min_days"]:
        return None, "short"
    if hlen > R["handle_max_days"]:
        return None, "long"
    hl = cur + 1 + int(np.argmin(lo[cur + 1:cur + 1 + hlen]))
    hdepth = (hi[cur] - lo[hl]) / hi[cur] * 100.0
    maxd = R["handle_max_depth_bear"] if weak else R["handle_max_depth"]
    if not (R["handle_min_depth"] <= hdepth <= maxd):
        return None, "depth"
    if lo[hl] < low + 0.5 * (L - low):
        return None, "lower half"
    if R["handle_above_10wk"]:
        s = C.sma50[cur + 1:cur + 1 + hlen]
        c = cl[cur + 1:cur + 1 + hlen]
        ok = np.isfinite(s)
        if ok.any() and float(np.min(c[ok] - s[ok] * 0.99)) < 0:
            return None, "under 10-week line"
    if R["handle_drift_down"] and hlen >= 4:
        # Drifting down, not wedging up: the back half of the handle undercuts (or about matches) the front half's low.
        seg = lo[cur + 1:cur + 1 + hlen]
        half = len(seg) // 2
        if float(seg[half:].min()) > float(seg[:half].min()) * (1.0 + R["handle_wedge_tol"] / 100.0):
            return None, "wedges up"
    return {"peak": cur, "depth": hdepth, "bo": bo, "low": hl}, ""


def _cup(C, i, e0, m):
    R, hi, lo = C.R, C.hi, C.lo
    L = hi[i]
    low = lo[m]
    depth = (L - low) / L * 100.0
    weak = C.weak_market(m)
    maxd = R["cup_max_depth_bear"] if weak else R["cup_max_depth"]
    if not (R["cup_min_depth"] <= depth <= maxd):
        return None
    if m - i < 10 or e0 - m < 10:
        return None
    seg_lo = lo[i:e0 + 1]
    band = low + (L - low) * R["cup_round_band"]
    if (seg_lo <= band).sum() < max(5, R["cup_round_min_share"] * len(seg_lo)):
        return None  # a V, not a rounded bottom: too little time spent near the low
    deep = depth > R["cup_max_depth"]
    thr = low + R["cup_recover_handle"] * (L - low)
    after = np.nonzero(hi[m + 1:e0 + 1] >= thr)[0]
    if not len(after):
        return None
    cur = m + 1 + int(after[0])
    handle = None
    while cur <= e0:
        h, why = _handle(C, seg_lo, L, low, cur, e0, weak)
        if h:
            handle = h
            break
        nx = int(C.ng[cur])
        if why != "short" or nx > e0:
            break
        cur = nx
    if handle:
        end = (handle["bo"] - 1) if handle["bo"] is not None else C.n - 1
        end = min(end, e0)
        wk = _weeks(end - i + 1)
        if not (R["cup_min_weeks"] <= wk <= R["cup_max_weeks"]):
            return None
        out = {"pattern": "cup_handle", "end": end, "pivot": float(hi[handle["peak"]]), "handle_idx": handle["peak"],
               "handle_depth": handle["depth"], "handle_low_idx": handle["low"], "rim_idx": handle["peak"], "low_idx": m, "deep": deep}
    else:
        rim_i = m + int(np.argmax(hi[m:e0 + 1]))
        if hi[rim_i] < low + R["cup_recover_plain"] * (L - low):
            return None
        wk = _weeks(e0 - i + 1)
        if not (R["cup_min_weeks"] <= wk <= R["cup_max_weeks"]):
            return None
        out = {"pattern": "cup", "end": e0, "pivot": float(L), "low_idx": m, "rim_idx": rim_i, "deep": deep}
    if R["on"]["saucer"] and wk >= R["saucer_min_weeks"] and depth <= R["saucer_max_depth"]:
        out["pattern"] = "saucer"
    return out


def _double_bottom(C, i, e0, m):
    R, hi, lo = C.R, C.hi, C.lo
    L = hi[i]
    b2 = m
    depth = (L - lo[b2]) / L * 100.0
    weak = C.weak_market(b2)
    maxd = R["double_max_depth_bear"] if weak else R["double_max_depth"]
    if not (R["double_min_depth"] <= depth <= maxd):
        return None
    lo_rng = i + 5
    hi_rng = b2 - 10
    if hi_rng <= lo_rng:
        return None
    b1 = lo_rng + int(np.argmin(lo[lo_rng:hi_rng + 1]))
    if not (lo[b2] < lo[b1] and (lo[b1] - lo[b2]) / lo[b1] * 100.0 <= R["double_max_undercut"]):
        return None
    if (L - lo[b1]) / L < 0.08:
        return None
    p = b1 + 1 + int(np.argmax(hi[b1 + 1:b2]))
    P = float(hi[p])
    if (P - lo[b1]) / lo[b1] < 0.10 or (P - lo[b2]) / P < 0.08:
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
    return {"pattern": "double_bottom", "end": end, "pivot": P, "low_idx": b2, "first_low_idx": b1, "mid_idx": p,
            "deep": depth > R["double_max_depth"]}


def _classify(C, i, e0):
    R, hi, lo, cl, n = C.R, C.hi, C.lo, C.cl, C.n
    on = R["on"]
    bars = e0 - i + 1
    wk = _weeks(bars)
    L = float(hi[i])
    if not L > 0:
        return None
    m = i + int(np.argmin(lo[i:e0 + 1]))
    depth = (L - lo[m]) / L * 100.0
    if wk > max(R["flat_max_weeks"], R["cup_max_weeks"]) or bars < 10:
        return None
    if depth < R["min_depth"]:
        return None
    if on["ipo_base"] and n <= R["ipo_max_history_days"] and R["ipo_min_weeks"] <= wk <= R["ipo_max_weeks"] \
            and depth <= R["ipo_max_depth"] and i < R["ipo_max_history_days"]:
        return {"pattern": "ipo_base", "end": e0, "pivot": L, "low_idx": m, "prior": None}
    prior = C.prior_uptrend(i)
    if R["require_prior_uptrend"] and (prior is None or prior < R["prior_uptrend_pct"]):
        return None
    if bars < 25:
        return None
    found = None
    if on["double_bottom"]:
        found = _double_bottom(C, i, e0, m)
    if not found and (on["cup_handle"] or on["cup"] or on["saucer"]):
        c = _cup(C, i, e0, m)
        if c and on[c["pattern"]]:
            found = c
    if not found and on["flat_base"] and depth <= R["flat_max_depth"] and R["flat_min_weeks"] <= wk <= R["flat_max_weeks"]:
        if cl[e0] >= lo[m] + 0.35 * (L - lo[m]):
            found = {"pattern": "flat_base", "end": e0, "pivot": L, "low_idx": m}
    if not found and on["consolidation"] and depth <= R["consolidation_max_depth"] and wk >= R["consolidation_min_weeks"] \
            and cl[e0] >= lo[m] + 0.5 * (L - lo[m]):
        found = {"pattern": "consolidation", "end": e0, "pivot": L, "low_idx": m}
    if found:
        found["prior"] = prior
    return found


def _ascending(C):
    """Latest ascending base ending at the last bar, or a few days before a breakout."""
    R, hi, lo, n = C.R, C.hi, C.lo, C.n
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
        start = last3[0][0][0]
        wk = _weeks(e - start + 1)
        if not (R["asc_min_weeks"] <= wk <= R["asc_max_weeks"]):
            continue
        # Each rally between pullbacks climbs to a higher high (a staircase, not a slide).
        tol = 1.0 + R["asc_high_tolerance"] / 100.0
        if not (last3[0][0][1] < last3[1][0][1] * tol and last3[1][0][1] < last3[2][0][1] * tol):
            continue
        prior = C.prior_uptrend(start)
        if R["require_prior_uptrend"] and (prior is None or prior < R["prior_uptrend_pct"]):
            continue
        pivot = float(hi[start:e + 1].max())
        if float(C.cl[-1]) < pivot * 0.85:
            continue
        lowest = float(lows[0])
        # The whole base, base high down to the first pullback's low, stays a base and not an advance.
        if (pivot - lowest) / pivot * 100.0 > R["asc_max_depth"]:
            continue
        return {"pattern": "ascending_base", "start": start, "end": e, "pivot": pivot,
                "low_idx": last3[0][1][0], "pullback_lows": [x[1][0] for x in last3],
                "pullback_highs": [x[0][0] for x in last3],
                # Depth is the deepest of the three pullbacks, the real range of the base, not the climb across it.
                "depth": max(x[2] for x in last3), "prior": prior}
    return None


def _market_drawdown(dates, market):
    """SPY's % below its 1-year closing high on each stock date, or None when there is no market series."""
    if market is None or not len(market):
        return None
    s = pd.Series(market).dropna()
    s.index = [str(x)[:10] for x in s.index]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    dd = (s / s.rolling(252, min_periods=20).max() - 1.0) * 100.0
    return dd.reindex(sorted(set(dates) | set(dd.index))).ffill().reindex(list(dates)).values


def _stages(bases, hi, lo, R):
    """Stage count per base, oldest first: (number, letter) where letter 0 is the first base of that stage."""
    prev = None
    stage, letter = 0, 0
    for b in bases:
        low = float(lo[b["start"]:b["end"] + 1].min())
        if prev is None:
            stage, letter = 1, 0
        else:
            plow = prev["_low"]
            between = lo[prev["end"] + 1:b["start"] + 1]
            undercut = low < plow or (len(between) and float(between.min()) < plow)
            if undercut:
                stage, letter = 1, 0
            else:
                rng = hi[prev["end"] + 1:b["start"] + 1]
                peak = float(rng.max()) if len(rng) else float(hi[b["start"]])
                if peak >= prev["pivot"] * (1 + R["stage_new_pct"] / 100.0):
                    stage, letter = stage + 1, 0
                else:
                    letter += 1
        b["_low"] = low
        b["stage"] = stage
        b["stage_label"] = str(stage) + ("(%s)" % chr(ord("a") + min(letter, 25)) if letter else "")
        prev = b


def _base_depth(C, b):
    s, e = b["start"], b["end"]
    top = float(C.hi[s])
    return (top - float(C.lo[s:e + 1].min())) / top * 100.0 if top > 0 else 999.0


def _tighter(C, i, e0, found):
    """MarketSurge starts a base at the true left-side high, the peak right before the correction. When the stock topped
    out at about the same price more than once (within tight_start_pct), try each later top as the start and keep the
    tightest valid base, the one with the smallest depth (ties go to the later, shorter one)."""
    R, hi = C.R, C.hi
    floor = hi[i] * (1 - R["tight_start_pct"] / 100.0)
    best, best_d = found, (_base_depth(C, found) if found else np.inf)
    run_max = -np.inf
    cands = []
    for j in range(e0, i, -1):  # a later top must be the highest from there to the end of the base
        if hi[j] >= run_max:
            run_max = hi[j]
            # A real later top: a swing high (the highest of 2 bars each side) after a dip of min_depth or more.
            if hi[j] >= floor and e0 - j + 1 >= 10 and hi[j] >= hi[max(i, j - 2):j + 3].max() \
                    and C.lo[i:j].min() <= hi[j] * (1 - R["min_depth"] / 100.0):
                cands.append(j)
    for j in sorted(cands):
        f = _classify(C, j, e0)
        if not f:
            continue
        f["start"] = j
        d = _base_depth(C, f)
        if d <= best_d + 1e-9:
            best, best_d = f, d
    return best


def detect_bases(dates, high, low, close, cfg=None, volume=None, market=None):
    """Bases found on one stock, oldest first, the last max_per_stock of them. Dicts ready for rows_for."""
    R = rules(cfg)
    hi = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    cl = np.asarray(close, dtype=float)
    n = len(cl)
    if n < 30 or not np.isfinite(hi).all() or not np.isfinite(lo).all():
        return []
    vol = np.asarray(volume, dtype=float) if volume is not None else None
    lo = robust_lows(hi, lo, cl, R)
    C = _Ctx(hi, lo, cl, vol, _market_drawdown(dates, market), R)
    roll = pd.Series(hi).rolling(int(R["left_high_days"]), min_periods=1).max().values
    first = max(0, n - int(max(R["count_lookback_bars"], R["lookback_bars"])))
    out = []
    last_end = -1
    for i in range(first, n - 9):
        if hi[i] < roll[i] or i <= last_end:
            continue
        e0 = int(C.ng[i]) - 1 if C.ng[i] < n else n - 1
        if e0 - i + 1 < 10:
            continue
        found = _classify(C, i, e0)
        if found:
            found["start"] = i
        if R["prefer_tight"] and (found is None or found["pattern"] in ("flat_base", "consolidation", "ipo_base", "cup", "saucer", "double_bottom")):
            found = _tighter(C, i, e0, found)
        if found:
            out.append(found)
            last_end = found["end"]
    if R["on"]["ascending_base"]:
        asc = _ascending(C)
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
    if R["count_stages"]:
        _stages(out, hi, C.lo, R)
    out = [b for b in out if b["end"] >= n - int(R["lookback_bars"])]
    return out[-int(R["max_per_stock"]):]


def _breakout(b, C, next_start):
    """(breakout index or None, volume % above the 50-day average, failure index or None)."""
    R, cl, vol = C.R, C.cl, C.vol
    pivot = b["pivot"]
    stop = next_start if next_start is not None else C.n
    over = np.nonzero(cl[b["end"] + 1:stop] > pivot)[0]
    if not len(over):
        return None, None, None
    bo = b["end"] + 1 + int(over[0])
    vpct = None
    if vol is not None and bo >= 1:
        prev = vol[max(0, bo - 50):bo]
        prev = prev[np.isfinite(prev)]
        if len(prev) >= 10 and prev.mean() > 0 and np.isfinite(vol[bo]):
            vpct = (vol[bo] / prev.mean() - 1.0) * 100.0
    fail = None
    if R["mark_failed"]:
        # O'Neil's sell rule: a close failed_pct below the pivot within failed_window_bars of the breakout, before the
        # stock gained failed_unless_gain_pct. A drop after a real advance is not a failed base.
        win_end = min(stop, bo + 1 + int(R["failed_window_bars"]))
        under = np.nonzero(cl[bo + 1:win_end] <= pivot * (1 - R["failed_pct"] / 100.0))[0]
        if len(under):
            f = bo + 1 + int(under[0])
            if float(C.hi[bo:f + 1].max()) < pivot * (1 + R["failed_unless_gain_pct"] / 100.0):
                fail = f
    return bo, vpct, fail


def _status(b, C, latest, bo, fail):
    R = C.R
    pivot = b["pivot"]
    pct = (float(C.cl[-1]) / pivot - 1.0) * 100.0
    zone = R["buy_zone_pct"]
    if fail is not None:
        return "FAILED", pct
    if not latest:
        return "COMPLETED", pct
    if bo is None:
        return ("NEAR PIVOT" if pct >= -zone else "FORMING"), pct
    if C.n - 1 - bo > R["completed_after_bars"]:
        return "COMPLETED", pct
    if pct < 0:
        return "BELOW PIVOT", pct
    return ("BUY ZONE" if pct <= zone else "EXTENDED"), pct


def rows_for(ticker, dates, high, low, close, cfg=None, volume=None, market=None):
    R = rules(cfg)
    hi = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    cl = np.asarray(close, dtype=float)
    n = len(cl)
    bases = detect_bases(dates, hi, lo, cl, cfg, volume, market)
    if not bases:
        return []
    lo = robust_lows(hi, lo, cl, R)
    C = _Ctx(hi, lo, cl, np.asarray(volume, dtype=float) if volume is not None else None, None, R)
    rows = []
    for k, b in enumerate(bases):
        latest = k == len(bases) - 1
        nxt = bases[k + 1]["start"] if k + 1 < len(bases) else None
        s = b["start"]
        left = float(hi[s]) if b["pattern"] != "ascending_base" else float(hi[s:b["end"] + 1].max())
        bo, vpct, fail = _breakout(b, C, nxt)
        status, pct = _status(b, C, latest, bo, fail)
        pivot = round(float(b["pivot"]), 4)
        lowest = float(lo[s:b["end"] + 1].min()) if b["pattern"] != "ascending_base" else float(lo[b["low_idx"]])
        depth = b.get("depth")
        if depth is None:
            depth = (left - lowest) / left * 100.0
        d = lambda key: dates[b[key]] if key in b and b[key] is not None else ""  # noqa: E731
        rows.append({
            "ticker": ticker, "pattern": b["pattern"], "latest": "yes" if latest else "no",
            "status": status, "start_date": dates[s], "end_date": dates[b["end"]], "left_high": round(left, 4),
            "low": round(lowest, 4), "low_date": dates[b["low_idx"]], "depth_pct": round(depth, 1),
            "length_weeks": round(_weeks(b["end"] - s + 1), 1), "pivot": pivot,
            "buy_point": round(pivot + R["buy_point_cents"] / 100.0, 4), "zone_top": round(pivot * (1 + R["buy_zone_pct"] / 100.0), 4),
            "pct_from_pivot": round(pct, 2), "breakout_date": dates[bo] if bo is not None else "",
            "handle_date": d("handle_idx"),
            "handle_depth_pct": round(b["handle_depth"], 1) if "handle_depth" in b else "",
            "first_low_date": d("first_low_idx"), "mid_peak_date": d("mid_idx"),
            "rim_date": d("rim_idx"), "handle_low_date": d("handle_low_idx"),
            "stage": b.get("stage", ""), "stage_label": b.get("stage_label", ""),
            "deep_base": "yes" if b.get("deep") else "",
            "prior_uptrend_pct": round(b["prior"], 1) if b.get("prior") is not None else "",
            "breakout_volume_pct": round(vpct, 0) if vpct is not None else "",
            "breakout_volume_ok": ("yes" if vpct >= R["breakout_volume_pct"] else "no") if vpct is not None else "",
            "failed_date": dates[fail] if fail is not None else "",
            "pullback_low_dates": ";".join(dates[k] for k in b.get("pullback_lows", [])),
            "pullback_high_dates": ";".join(dates[k] for k in b.get("pullback_highs", [])),
        })
    return rows


def scan(close, high, low, tickers=None, cfg=None, volume=None, market=None):
    """DataFrame (COLS) for the wide close/high/low (and volume) frames the desk run already holds (index dates,
    columns tickers). market is SPY's close for the weak-market depth allowance."""
    rows = []
    names = list(tickers) if tickers is not None else list(close.columns)
    if market is None and "SPY" in close.columns:
        market = close["SPY"]
    for t in names:
        if t not in close.columns or t not in high.columns or t not in low.columns:
            continue
        cols = {"c": close[t], "h": high[t], "l": low[t]}
        d = pd.DataFrame(cols).dropna()
        if len(d) < 30:
            continue
        v = None
        if volume is not None and t in volume.columns:
            v = volume[t].reindex(d.index).values
        dates = [x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x)[:10] for x in d.index]
        rows += rows_for(str(t), dates, d["h"].values, d["l"].values, d["c"].values, cfg, v, market)
    return pd.DataFrame(rows, columns=COLS)


def _read_market(ohlc_dir):
    p = os.path.join(os.path.dirname(ohlc_dir.rstrip("/")), "index_ohlc", "SPY.csv")
    if not os.path.exists(p):
        return None
    m = pd.read_csv(p).dropna(subset=["close"])
    return pd.Series(m["close"].values, index=[str(x)[:10] for x in m["date"]])


def scan_ohlc_dir(ohlc_dir, tickers=None, cfg=None):
    """Same scan, read from the saved data/ohlc/<T>.csv files and data/index_ohlc/SPY.csv (no download)."""
    rows = []
    market = _read_market(ohlc_dir)
    names = tickers or sorted(f[:-4] for f in os.listdir(ohlc_dir) if f.endswith(".csv"))
    for t in names:
        path = os.path.join(ohlc_dir, t + ".csv")
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path).dropna(subset=["high", "low", "close"])
        if len(d) < 30:
            continue
        v = d["volume"].values if "volume" in d.columns else None
        rows += rows_for(t, [str(x)[:10] for x in d["date"]], d["high"].values, d["low"].values, d["close"].values, cfg, v, market)
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
    """{pattern: stocks whose latest base is that pattern} and how many of those are near the pivot or in the buy zone."""
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
