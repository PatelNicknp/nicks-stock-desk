"""Pattern scanners from prices and cached fundamentals. No network calls.

VCP rules are the defaults in reference/nicks_minervini_with_exit_strategy.pine.
CANSLIM rules follow reference/canslim_vcp_nse_run.py, with SPY (and QQQ when
it is already in the price cache) in place of the Nifty. Box and flag rules
are desk pattern rules; the thresholds are named below and in the README.
A missing input is left blank and marked "not verified". Numbers are never filled in.
"""
import numpy as np
import pandas as pd

from tables import DISCLAIMER

# Input defaults from Nick's Pine script. Do not retune these to "improve" the scan.
PINE = {
    "lookback": 100,
    "piv_l": 4,
    "piv_r": 3,
    "min_bars": 2,
    "base_tol_pct": 5.0,
    "min_depth_pct": 3.0,
    "max_t": 4,
    "vol_len": 50,
    "vol_mult": 1.5,
    "stop_pct": 7.0,
    "be_r": 2.5,
    "part_pct": 20.0,
    "climax_pct": 25.0,
    "climax_bars": 10,
    "trail_len": 20,
    "require_all": True,
}

# NSE scan constants, kept so the US page matches that method.
NSE_ADV_MIN = 200_000
NSE_RS_LONG = 126
NSE_RS_SHORT = 63
NSE_NEAR_HIGH = -15.0  # percent from the 52-week closing high
NSE_RS_STRICT = 55.0
NSE_RS_SOFT = 40.0

# Desk pattern rules. These are not in the Pine file.
BOX_MIN_DAYS = 15
BOX_MAX_DAYS = 40
BOX_MAX_WIDTH = 0.10
BOX_MAX_DRIFT = 0.05
BOX_NEAR = 0.02
FLAG_POLE_MIN = 0.15
FLAG_POLE_MAX_BARS = 12
FLAG_POLE_MIN_BARS = 3
FLAG_MIN_BARS = 3
FLAG_MAX_BARS = 15
FLAG_MAX_RETRACE = 0.50
FLAG_NEAR = 0.02
# Big volume uses the same 1.5x 50-day average as the Pine script's volMult.
VOL_MULT = PINE["vol_mult"]
VOL_LEN = PINE["vol_len"]

# 52-week page. The high and low use each session's high and low columns.
# A new high or new low is the close versus the prior 252 sessions, so an
# intraday poke through the old high does not count unless the close holds it.
W52_BARS = 252
W52_NEAR_PCT = 5.0
W52_VOL_MULT = 1.5  # new 52-week high on volume at least this many times the 50-day average
W52_VOL_LEN = VOL_LEN

# Buy setups. The 7% and 20% match the Pine script stop and sell-part.
BUY_STOP_PCT = PINE["stop_pct"]
BUY_PART_PCT = PINE["part_pct"]
BUY_MAX_RISK_PCT = 8.0
BUY_TARGET2_R = 3.0
BUY_SETUP_ORDER = ("VCP", "Box", "Flag", "Qullamaggie", "Marios", "EP", "CANSLIM")
BUY_LIVE_STATUS = ("READY", "BROKEN OUT today")

VCP_NOTE = (
    "Stop and target before a buy apply the indicator's 7% and 20% to the pivot. "
    "On the buy bar they use that bar's close. A swing confirms 3 bars later. "
    "A tie for the high or low is not a pivot."
)
BOX_NOTE = (
    "Desk rule, not the Pine script: a 15 to 40 day range no wider than 10% "
    "whose first and last closes drift by 5% or less, then a close through the range high "
    "on volume above 1.5 times the 50-day average."
)
# Breakdown is the box turned over. The window is 20 to 60 sessions. Volume
# has to be at least 1.4 times the 50-day average to count as broken down.
BREAK_MIN_DAYS = 20
BREAK_MAX_DAYS = 60
BREAK_MAX_WIDTH = 0.10
BREAK_MAX_DRIFT = 0.05
BREAK_NEAR = 0.03
BREAK_VOL_MULT = 1.4
BREAKDOWN_NOTE = (
    "Desk rule: close under the 50-day and the 50-day under the 200-day, with the 200-day not rising. "
    "The base is the longest 20 to 60 day range, ending yesterday, no wider than 10%, "
    "with the first and last closes drifting by 5% or less, and the second half tighter than the first. "
    "BROKEN DOWN today is a close under that low on volume at least 1.4 times the 50-day average. "
    "WATCHING is within 3% of that low, or a close under it without that volume. "
    "The stop is the base high. The target is the entry minus twice the risk up to that high."
)
FLAG_NOTE = (
    "Desk rule, not the Pine script: a pole of at least 15% in 3 to 12 sessions, "
    "then a 3 to 15 day flag that retraces less than half the pole, "
    "then a close through the flag high on volume above 1.5 times the 50-day average."
)

NOT_VERIFIED = "not verified"
# High volume scanner. Cached daily bars only. No new downloads.
HV_AVG_LEN = 50          # average volume over the 50 sessions before the day being checked
HV_LIST_MIN = 1.5        # rows are written from 1.5x so the page can filter 1.5x / 2x / 3x / 5x
HV_SPIKE = 2.0           # default spike line
HV_STREAK_MIN = 3        # days in a row above the 50-day average
HV_QUIET_LEN = 10        # recent window for the dry-up check
HV_QUIET_MAX = 0.6       # 10-day average under 0.6x the 50-day average
HV_HIGH_LEN = 63         # "recent high" = highest high of the last 63 sessions (about 3 months)
HV_NEAR_HIGH = 0.05      # within 5% of that high
HIGH_VOLUME_NOTE = (
    "Built from the saved daily prices and volume. No extra download. "
    "Volume ratio is today's volume divided by the average of the 50 sessions before today. "
    "During market hours today's volume is still adding up."
)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x):
        return None
    return x


def _round(v, nd=2):
    x = _num(v)
    if x is None:
        return ""
    return round(x, nd)


def _sma(arr, n):
    return pd.Series(np.asarray(arr, dtype=float)).rolling(n, min_periods=n).mean().to_numpy()


def _rolling_max(arr, n):
    return pd.Series(np.asarray(arr, dtype=float)).rolling(n, min_periods=n).max().to_numpy()


def _rolling_min(arr, n):
    return pd.Series(np.asarray(arr, dtype=float)).rolling(n, min_periods=n).min().to_numpy()


def pivot_confirmed(src, left, right, mode):
    """Price of a TradingView pivot, placed on the confirmation bar (right bars later).

    The center bar must be strictly beyond every bar in the left and right windows.
    An equal neighbor is not a pivot. That is ta.pivothigh / ta.pivotlow.
    """
    src = np.asarray(src, dtype=float)
    n = len(src)
    out = np.full(n, np.nan)
    if n < left + right + 1:
        return out
    for i in range(left + right, n):
        c = i - right
        p = src[c]
        if not np.isfinite(p):
            continue
        leftw = src[c - left:c]
        rightw = src[c + 1:c + 1 + right]
        if not np.isfinite(leftw).all() or not np.isfinite(rightw).all():
            continue
        if mode == "high":
            if p > leftw.max() and p > rightw.max():
                out[i] = p
        elif p < leftw.min() and p < rightw.min():
            out[i] = p
    return out


def _shift_div(arr, bars):
    out = np.full(len(arr), np.nan)
    if bars <= 0 or len(arr) <= bars:
        return out
    base = arr[:-bars]
    now = arr[bars:]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[bars:] = now / base - 1.0
    return out


def _trend_arrays(close, high, low, spy):
    n = len(close)
    sma50 = _sma(close, 50)
    sma150 = _sma(close, 150)
    sma200 = _sma(close, 200)
    sma200_ago = np.full(n, np.nan)
    sma200_ago[20:] = sma200[:-20]
    low52 = _rolling_min(low, 252)
    high52 = _rolling_max(high, 252)
    r1 = (close > sma150) & (close > sma200)
    r2 = sma150 > sma200
    r3 = sma200 > sma200_ago
    r4 = (sma50 > sma150) & (sma50 > sma200)
    r5 = close > sma50
    r6 = close >= low52 * 1.30
    r7 = close >= high52 * 0.75
    stock6 = _shift_div(close, 126)
    stock12 = _shift_div(close, 252)
    spy6 = _shift_div(spy, 126)
    spy12 = _shift_div(spy, 252)
    r8 = np.isfinite(spy12) & (stock6 > spy6) & (stock12 > spy12)
    rules = [r1, r2, r3, r4, r5, r6, r7, r8]
    score = np.zeros(n, dtype=int)
    for r in rules:
        score += r.astype(int)
    return {
        "sma50": sma50, "sma150": sma150, "sma200": sma200,
        "score": score, "rules": rules, "high52": high52, "low52": low52,
    }


def _base_from(h_depth, h_high, h_bar, h_low, h_low_bar):
    """Current shrinking run, oldest to newest. Mirrors the Pine base and run loops."""
    if not h_high:
        return [], [], [], [], []
    base_idx = -1
    tol = 1.0 + PINE["base_tol_pct"] / 100.0
    for i, hi in enumerate(h_high):
        if base_idx < 0 or hi > h_high[base_idx] * tol:
            base_idx = i
    c_depth = list(h_depth[base_idx:])
    c_high = list(h_high[base_idx:])
    c_bar = list(h_bar[base_idx:])
    c_low = list(h_low[base_idx:])
    c_low_bar = list(h_low_bar[base_idx:])
    run_start = len(c_depth) - 1
    if run_start > 0:
        while run_start > 0 and c_depth[run_start - 1] > c_depth[run_start]:
            run_start -= 1
    run_start = max(run_start, len(c_depth) - PINE["max_t"])
    return (
        c_depth[run_start:], c_high[run_start:], c_bar[run_start:],
        c_low[run_start:], c_low_bar[run_start:],
    )


def vcp_last(high, low, close, volume, spy):
    """Run Nick's indicator through the last bar. Returns the live state.

    The state machine follows the Pine order: new swing high, then a swing low
    that either extends the prior contraction or starts a new one, then the
    lookback trim, then the buy check, then the exit check, then a new buy.
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    spy = np.asarray(spy, dtype=float)
    n = len(close)
    if n == 0:
        return None
    ph = pivot_confirmed(high, PINE["piv_l"], PINE["piv_r"], "high")
    pl = pivot_confirmed(low, PINE["piv_l"], PINE["piv_r"], "low")
    trend = _trend_arrays(close, high, low, spy)
    avg_vol = _sma(volume, PINE["vol_len"])
    trail = _sma(close, PINE["trail_len"])
    piv_r = PINE["piv_r"]
    lookback = PINE["lookback"]
    min_depth = PINE["min_depth_pct"]
    min_bars = PINE["min_bars"]

    h_depth, h_high, h_bar, h_low, h_low_bar = [], [], [], [], []
    last_high = np.nan
    last_high_bar = -1
    last_type = 0
    in_trade = False
    entry = np.nan
    stop_lvl = np.nan
    be_done = False
    part_done = False
    climax_done = False
    entry_bar = -1
    prev_pivot = np.nan
    c_depth, c_high = [], []
    cnt = 0
    pivot = np.nan
    is_vcp = False
    broke = False
    big_vol = False

    for i in range(n):
        changed = False
        if np.isfinite(ph[i]):
            phv = float(ph[i])
            if last_type != 1 or not np.isfinite(last_high) or phv > last_high:
                last_high = phv
                last_high_bar = i - piv_r
            last_type = 1
            changed = True
        if np.isfinite(pl[i]) and last_type == 1 and np.isfinite(last_high):
            plv = float(pl[i])
            depth = (last_high - plv) / last_high * 100.0
            if h_high and last_high <= h_high[-1] and plv < h_low[-1]:
                prev_high = h_high[-1]
                h_depth[-1] = (prev_high - plv) / prev_high * 100.0
                h_low[-1] = plv
                h_low_bar[-1] = i - piv_r
                last_type = -1
                changed = True
            elif depth >= min_depth and (i - piv_r) - last_high_bar >= min_bars:
                h_depth.append(depth)
                h_high.append(float(last_high))
                h_bar.append(int(last_high_bar))
                h_low.append(plv)
                h_low_bar.append(i - piv_r)
                last_type = -1
                changed = True
        if h_bar and i - h_bar[0] > lookback:
            while h_bar and i - h_bar[0] > lookback:
                h_depth.pop(0)
                h_high.pop(0)
                h_bar.pop(0)
                h_low.pop(0)
                h_low_bar.pop(0)
            changed = True
        if changed or i == n - 1:
            c_depth, c_high, _, _, _ = _base_from(h_depth, h_high, h_bar, h_low, h_low_bar)
            cnt = len(c_depth)
            pivot = c_high[-1] if cnt else np.nan
        score_i = int(trend["score"][i])
        if PINE["require_all"]:
            trend_ok = score_i == 8
        else:
            trend_ok = bool(trend["rules"][0][i] and trend["rules"][1][i])
        is_vcp = cnt >= 2 and trend_ok
        big_vol = bool(np.isfinite(avg_vol[i]) and np.isfinite(volume[i]) and volume[i] > avg_vol[i] * PINE["vol_mult"])
        cross = (
            np.isfinite(pivot) and np.isfinite(prev_pivot)
            and np.isfinite(close[i]) and i > 0 and np.isfinite(close[i - 1])
            and close[i - 1] <= prev_pivot and close[i] > pivot
        )
        broke = bool(np.isfinite(pivot) and cross and big_vol and is_vcp)

        if in_trade:
            risk = entry * PINE["stop_pct"] / 100.0
            if (not be_done) and np.isfinite(high[i]) and high[i] >= entry + PINE["be_r"] * risk:
                stop_lvl = max(stop_lvl, entry)
                be_done = True
            if (not part_done) and np.isfinite(high[i]) and high[i] >= entry * (1.0 + PINE["part_pct"] / 100.0):
                part_done = True
            if (
                not climax_done and i - entry_bar >= 3 and i >= PINE["climax_bars"]
                and np.isfinite(close[i]) and np.isfinite(close[i - PINE["climax_bars"]])
                and close[i] >= close[i - PINE["climax_bars"]] * (1.0 + PINE["climax_pct"] / 100.0)
                and close[i] > entry
            ):
                climax_done = True
            stop_hit = bool(np.isfinite(close[i]) and close[i] < stop_lvl)
            trail_hit = False
            if not stop_hit and i - entry_bar >= 3 and np.isfinite(trail[i]) and np.isfinite(trail[i - 1]):
                trail_hit = bool(close[i] < trail[i] and close[i - 1] >= trail[i - 1])
            if stop_hit or trail_hit:
                in_trade = False
        if broke and not in_trade:
            in_trade = True
            entry = float(close[i])
            stop_lvl = entry * (1.0 - PINE["stop_pct"] / 100.0)
            be_done = False
            part_done = False
            climax_done = False
            entry_bar = i
        prev_pivot = pivot

    rules_now = [bool(r[-1]) for r in trend["rules"]]
    return {
        "score": int(trend["score"][-1]),
        "rules": rules_now,
        "cnt": cnt,
        "depths": [round(float(d), 1) for d in c_depth],
        "highs": [float(h) for h in c_high],
        "pivot": float(pivot) if np.isfinite(pivot) else None,
        "is_vcp": bool(is_vcp),
        "breakout": bool(broke),
        "big_vol": bool(big_vol),
        "in_trade": bool(in_trade),
        "entry": float(entry) if np.isfinite(entry) else None,
        "entry_bar": int(entry_bar),
        "stop": float(stop_lvl) if np.isfinite(stop_lvl) else None,
        "be_done": bool(be_done),
        "part_done": bool(part_done),
        "climax_done": bool(climax_done),
        "trail": float(trail[-1]) if np.isfinite(trail[-1]) else None,
        "close": float(close[-1]),
        "bars": n,
        "high52": float(trend["high52"][-1]) if np.isfinite(trend["high52"][-1]) else None,
    }


def _vcp_status(state):
    if state["cnt"] <= 0 and not state["in_trade"]:
        return None
    if state["breakout"]:
        return "BROKEN OUT today"
    if state["in_trade"]:
        return "WATCHING"
    if state["is_vcp"] and state["pivot"] is not None and state["close"] <= state["pivot"]:
        return "READY"
    if state["is_vcp"] or state["cnt"] >= 2 or state["in_trade"] or (state["cnt"] == 1 and state["score"] >= 6):
        return "WATCHING"
    return None


def _vcp_levels(state):
    """Stop, target, and the price those percents were applied to."""
    if state["in_trade"] and state["entry"] is not None and state["stop"] is not None:
        target = state["entry"] * (1.0 + PINE["part_pct"] / 100.0)
        return state["stop"], target, state["entry"], "buy"
    if state["pivot"] is not None:
        stop = state["pivot"] * (1.0 - PINE["stop_pct"] / 100.0)
        target = state["pivot"] * (1.0 + PINE["part_pct"] / 100.0)
        return stop, target, state["pivot"], "pivot"
    return None, None, None, ""


def _vcp_reason(state, status, dates):
    depths = ", ".join("%s%%" % d for d in state["depths"]) or "none yet"
    score = state["score"]
    bits = ["Trend template %d/8." % score, "Contractions: %s." % depths]
    if state["pivot"] is not None:
        bits.append("Buy point %s." % _round(state["pivot"]))
    if status == "BROKEN OUT today":
        bits.append("Today's close crossed above the buy point on volume above 1.5 times the 50-day average, with the trend template at 8 of 8 and at least two tightening pullbacks.")
    elif status == "READY":
        bits.append("The trend template is 8 of 8 and the pullbacks are tightening. Price has not closed through the buy point yet.")
    elif state["is_vcp"] and state["pivot"] is not None and state["close"] > state["pivot"] and not state["big_vol"]:
        bits.append("Price is through the buy point, but volume was not 1.5 times the 50-day average, so the indicator did not print a buy today.")
    elif state["cnt"] >= 2 and score < 8:
        failed = [str(i + 1) for i, ok in enumerate(state["rules"]) if not ok]
        bits.append("Pullbacks are tightening, but the trend template is not 8 of 8. Still open: rule %s." % ", ".join(failed))
    elif state["cnt"] == 1:
        bits.append("One pullback so far. The indicator needs a second, tighter one before it will call this a VCP.")
    if state["in_trade"] and state["entry"] is not None:
        when = ""
        if dates is not None and 0 <= state["entry_bar"] < len(dates):
            when = " on %s" % pd.Timestamp(dates[state["entry_bar"]]).date()
        extra = ""
        if state["be_done"]:
            extra += " The stop has moved to breakeven."
        if state["part_done"]:
            extra += " The 20% sell-part level has been touched."
        if state["climax_done"]:
            extra += " The climax warning has printed."
        bits.append("A buy printed at %s%s.%s" % (_round(state["entry"]), when, extra))
    elif state["pivot"] is not None:
        bits.append("No buy has printed, so the 7% stop and the 20% sell-part target are measured from the buy point. The indicator switches them to the breakout close once the buy prints.")
    bits.append("After the buy, the stop moves to breakeven once the gain reaches 2.5 times the initial risk. A close under the 20-day average, after three days in the trade, is the trail sell. A 25% jump in 10 days is a climax warning, not the target.")
    if state["bars"] < 252:
        bits.append("Fewer than 252 sessions, so the 52-week and 12-month rules cannot pass, the same way the indicator has no value for those bars yet.")
    return " ".join(bits)


def _freshness(last_date, panel_date, bars, need):
    if last_date is None or panel_date is None:
        return "STALE"
    if pd.Timestamp(last_date).normalize() < pd.Timestamp(panel_date).normalize():
        return "STALE"
    if bars < need:
        return "PARTIAL"
    return "FRESH"


def _meta_row(universe, ticker):
    if universe is None or len(universe) == 0 or ticker not in set(universe["ticker"]):
        return {"company": "", "sector": "", "index_membership": ""}
    row = universe.loc[universe["ticker"] == ticker]
    if len(row) == 0:
        return {"company": "", "sector": "", "index_membership": ""}
    r = row.iloc[-1]
    return {
        "company": r.get("company") or "",
        "sector": r.get("sector") or "",
        "index_membership": r.get("index_membership") or "",
    }


def _bars(close, high, low, vol, ticker, spy):
    if ticker not in close.columns:
        return None
    frame = pd.DataFrame({
        "close": close[ticker],
        "high": high[ticker] if high is not None and ticker in high.columns else np.nan,
        "low": low[ticker] if low is not None and ticker in low.columns else np.nan,
        "volume": vol[ticker] if vol is not None and ticker in vol.columns else np.nan,
    })
    frame = frame.dropna(subset=["close", "high", "low"])
    if len(frame) == 0:
        return None
    spy_aligned = np.full(len(frame), np.nan)
    if spy is not None:
        spy_aligned = spy.reindex(frame.index).ffill().to_numpy(dtype=float)
    return frame, spy_aligned


def _panel_date(close):
    """Latest equity session. SPY's last close, not a later one-off bar such as VIX."""
    if close is None or len(close) == 0:
        return None
    if "SPY" in close.columns and close["SPY"].notna().any():
        return pd.Timestamp(close["SPY"].dropna().index.max())
    counts = close.notna().sum(axis=1)
    if len(counts) == 0 or counts.max() == 0:
        return None
    eligible = counts[counts >= max(1, counts.max() * 0.5)]
    return pd.Timestamp(eligible.index.max())


def scan_vcp(close, high, low, vol, universe):
    rows = []
    panel = _panel_date(close)
    spy = close["SPY"] if close is not None and "SPY" in close.columns else None
    names = list(universe["ticker"]) if universe is not None and len(universe) else []
    for ticker in names:
        got = _bars(close, high, low, vol, ticker, spy)
        if got is None:
            continue
        frame, spy_aligned = got
        state = vcp_last(
            frame["high"].to_numpy(), frame["low"].to_numpy(), frame["close"].to_numpy(),
            frame["volume"].to_numpy(), spy_aligned,
        )
        if state is None:
            continue
        status = _vcp_status(state)
        if status is None:
            continue
        stop, target, _, basis = _vcp_levels(state)
        meta = _meta_row(universe, ticker)
        last = frame.index[-1]
        strength = round(state["score"] / 8.0 * 80.0 + min(state["cnt"], 4) * 5.0, 1)
        note = VCP_NOTE
        if spy is None:
            note += " SPY was not in the price cache, so rule 8 cannot pass."
        row = {
            "ticker": ticker,
            "company": meta["company"],
            "sector": meta["sector"],
            "index_membership": meta["index_membership"],
            "status": status,
            "pivot": _round(state["pivot"]),
            "stop": _round(stop),
            "target": _round(target),
            "trail": _round(state["trail"]),
            "strength": strength,
            "reason": _vcp_reason(state, status, frame.index),
            "freshness": _freshness(last, panel, state["bars"], 252),
            "price": _round(state["close"]),
            "price_as_of": str(pd.Timestamp(last).date()),
            "trend_score": "%d of 8" % state["score"],
            "contractions": state["cnt"],
            "depths": "; ".join(str(d) for d in state["depths"]),
            "volume_ok": "yes" if state["big_vol"] else "no",
            "in_trade": "yes" if state["in_trade"] else "no",
            "stop_basis": basis,
            "data_status": "OK",
            "note": note,
        }
        for i, ok in enumerate(state["rules"], start=1):
            row["r%d" % i] = "PASS" if ok else "FAIL"
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    rank = {"BROKEN OUT today": 0, "READY": 1, "WATCHING": 2}
    out["_k"] = out["status"].map(rank)
    out = out.sort_values(["_k", "strength"], ascending=[True, False]).drop(columns="_k")
    return out


def _ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


def _ret(series, bars):
    if len(series) < bars + 1:
        return None
    a = _num(series.iloc[-1])
    b = _num(series.iloc[-1 - bars])
    if a is None or b is None or b == 0:
        return None
    return a / b - 1.0


def _market_one(series, name):
    c = series.dropna()
    if len(c) < 200:
        return None
    e21, e50, e200 = _ema(c, 21), _ema(c, 50), _ema(c, 200)
    last = float(c.iloc[-1])
    above50 = last > float(e50.iloc[-1])
    above200 = last > float(e200.iloc[-1])
    rising = float(e21.iloc[-1]) > float(e21.iloc[-5])
    if above50 and above200 and rising:
        label = "CONFIRMATION / constructive (above EMA50 and EMA200, EMA21 rising)"
    elif above200:
        label = "MIXED / still above EMA200 but weaker versus EMA50 or EMA21"
    else:
        label = "CORRECTION risk (below EMA200)"
    return {
        "name": name,
        "label": label,
        "last": last,
        "e21": float(e21.iloc[-1]),
        "e50": float(e50.iloc[-1]),
        "e200": float(e200.iloc[-1]),
        "above50": above50,
        "above200": above200,
        "rising": rising,
        "r63": _ret(c, 63),
        "r126": _ret(c, 126),
    }


def _combine_market(spy_m, qqq_m):
    """SPY is required. QQQ stays not verified when it was not already downloaded."""
    if spy_m is None:
        return {
            "label": NOT_VERIFIED,
            "spy": NOT_VERIFIED,
            "qqq": NOT_VERIFIED,
            "text": "SPY averages are not verified because SPY was not in the price cache.",
        }
    spy_txt = "SPY %s (price %s, EMA21 %s, EMA50 %s, EMA200 %s)" % (
        spy_m["label"], _round(spy_m["last"]), _round(spy_m["e21"]), _round(spy_m["e50"]), _round(spy_m["e200"]),
    )
    if qqq_m is None:
        return {
            "label": spy_m["label"],
            "spy": spy_m["label"],
            "qqq": NOT_VERIFIED,
            "text": spy_txt + ". QQQ versus its averages is not verified because QQQ is not in the price cache. No new download was made.",
        }
    qqq_txt = "QQQ %s (price %s, EMA21 %s, EMA50 %s, EMA200 %s)" % (
        qqq_m["label"], _round(qqq_m["last"]), _round(qqq_m["e21"]), _round(qqq_m["e50"]), _round(qqq_m["e200"]),
    )
    if (not spy_m["above200"]) or (not qqq_m["above200"]):
        label = "CORRECTION risk (below EMA200)"
    elif spy_m["label"].startswith("CONFIRMATION") and qqq_m["label"].startswith("CONFIRMATION"):
        label = "CONFIRMATION / constructive (above EMA50 and EMA200, EMA21 rising)"
    else:
        label = "MIXED / still above EMA200 but weaker versus EMA50 or EMA21"
    return {"label": label, "spy": spy_m["label"], "qqq": qqq_m["label"], "text": spy_txt + ". " + qqq_txt + "."}


def _frame_key(frame):
    text = str(frame)
    if len(text) == 6 and text.startswith("CY") and text[2:].isdigit():
        return int(text[2:]) * 10
    if len(text) == 8 and text.startswith("CY") and text[6] == "Q" and text[2:6].isdigit() and text[7] in "1234":
        return int(text[2:6]) * 10 + int(text[7])
    return None


def _yoy_eps(frame_df, ticker, quarterly):
    if frame_df is None or len(frame_df) == 0 or "eps" not in frame_df.columns:
        return None, None, None
    sub = frame_df[frame_df["ticker"] == ticker].copy()
    if len(sub) == 0:
        return None, None, None
    sub["k"] = sub["frame"].map(_frame_key)
    sub["eps_n"] = pd.to_numeric(sub["eps"], errors="coerce")
    sub = sub.dropna(subset=["k", "eps_n"])
    if quarterly:
        sub = sub[sub["frame"].astype(str).str.contains("Q")]
        gap = 10  # CY2024Q3 = year*10+3, year-ago is -10
    else:
        sub = sub[~sub["frame"].astype(str).str.contains("Q")]
        gap = 10
    if len(sub) == 0:
        return None, None, None
    sub = sub.sort_values("k")
    latest = sub.iloc[-1]
    prior = sub[sub["k"] == latest["k"] - gap]
    if len(prior) == 0:
        return None, None, None
    old = float(prior.iloc[-1]["eps_n"])
    now = float(latest["eps_n"])
    if old == 0:
        return None, None, None
    pct = (now - old) / abs(old) * 100.0
    return pct, now, old


def _holder_trend(holders, ticker):
    if holders is None or len(holders) == 0:
        return NOT_VERIFIED, ""
    sub = holders[holders["ticker"] == ticker]
    if len(sub) == 0:
        return NOT_VERIFIED, ""
    r = sub.iloc[-1]
    up = _num(r.get("inst_up"))
    down = _num(r.get("inst_down"))
    own = _num(r.get("ownership_pct"))
    if own is not None and own > 100:
        own_txt = " Reported holdings exceed shares outstanding, so the ownership percent is not used."
        own = None
    else:
        own_txt = " Ownership %s%%." % _round(own, 1) if own is not None else " Ownership percent is not verified."
    if up is None or down is None:
        level = ""
        if own is not None:
            level = " Ownership is %s%%, which is a level, not a trend." % _round(own, 1)
        elif "not used" in own_txt:
            level = own_txt
        return NOT_VERIFIED, "Institutional trend is not verified.%s" % level
    if up > down:
        trend = "up"
    elif up < down:
        trend = "down"
    else:
        trend = "flat"
    text = "Institutional shares increased %s versus decreased %s, so the trend is %s.%s" % (
        _round(up, 0), _round(down, 0), trend, own_txt)
    return trend, text


def _range_pct(close, win):
    if len(close) < win:
        return None
    seg = close.iloc[-win:]
    mean = float(seg.mean())
    if mean == 0:
        return None
    return (float(seg.max()) - float(seg.min())) / mean * 100.0


def scan_canslim(close, high, low, vol, universe, quarters, annual, holders):
    rows = []
    if close is None or len(close) == 0 or universe is None or len(universe) == 0:
        return pd.DataFrame(), {}
    panel = _panel_date(close)
    spy = close["SPY"].dropna() if "SPY" in close.columns else None
    qqq = close["QQQ"].dropna() if "QQQ" in close.columns else None
    spy_m = _market_one(spy, "SPY") if spy is not None else None
    qqq_m = _market_one(qqq, "QQQ") if qqq is not None else None
    market = _combine_market(spy_m, qqq_m)
    bench = spy if spy is not None else None
    bench_r63 = _ret(bench, NSE_RS_SHORT) if bench is not None else None
    bench_r126 = _ret(bench, NSE_RS_LONG) if bench is not None else None

    screened = []
    for ticker in list(universe["ticker"]):
        got = _bars(close, high, low, vol, ticker, bench)
        if got is None:
            continue
        frame, _spy_aligned = got
        c = frame["close"]
        if len(c) < 150 or bench is None or bench_r63 is None or bench_r126 is None:
            continue
        aligned = bench.reindex(c.index).ffill()
        common = c.index.intersection(aligned.dropna().index)
        c = c.loc[common]
        if len(c) < 150:
            continue
        r63 = _ret(c, NSE_RS_SHORT)
        r126 = _ret(c, NSE_RS_LONG)
        if r63 is None or r126 is None:
            continue
        e21, e50, e200 = _ema(c, 21), _ema(c, 50), _ema(c, 200)
        last = float(c.iloc[-1])
        e21v, e50v, e200v = float(e21.iloc[-1]), float(e50.iloc[-1]), float(e200.iloc[-1])
        adv = float(frame["volume"].reindex(c.index).iloc[-20:].mean()) if frame["volume"].notna().any() else None
        if adv is None or not np.isfinite(adv):
            continue
        liquid = adv >= NSE_ADV_MIN
        hi52 = float(c.iloc[-252:].max()) if len(c) >= 252 else float(c.max())
        pct_from_high = (last / hi52 - 1.0) * 100.0 if hi52 else None
        near = pct_from_high is not None and pct_from_high >= NSE_NEAR_HIGH
        r20, r40, r60 = _range_pct(c, 20), _range_pct(c, 40), _range_pct(c, 60)
        contracting = r20 is not None and r40 is not None and r60 is not None and r20 < r40 < r60
        mild = r20 is not None and r60 is not None and r20 < r60 * 0.75
        roll = c.rolling(10).min()
        higher_lows = False
        if len(roll.dropna()) > 40:
            a, b, d = float(roll.iloc[-35]), float(roll.iloc[-20]), float(roll.iloc[-5])
            higher_lows = d > b > a * 0.98
        trend = 0
        above200 = last > e200v
        above50 = last > e50v
        above21 = last > e21v
        rising = e21v > float(e21.iloc[-5])
        if above200:
            trend += 2
        if above50:
            trend += 2
        if above21:
            trend += 1
        if rising:
            trend += 1
        if e50v > e200v:
            trend += 1
        vcp_score = 0
        if contracting:
            vcp_score += 3
        elif mild:
            vcp_score += 2
        if higher_lows:
            vcp_score += 2
        if near:
            vcp_score += 1
        if r20 is not None and r20 < 8:
            vcp_score += 1
        prior = c.iloc[:-1]
        prior_hi = float(prior.iloc[-252:].max()) if len(prior) >= 252 else (float(prior.max()) if len(prior) else None)
        new_high = prior_hi is not None and last > prior_hi
        vol_s = frame["volume"].reindex(c.index)
        avg50 = vol_s.rolling(VOL_LEN, min_periods=VOL_LEN).mean()
        big_vol = bool(np.isfinite(vol_s.iloc[-1]) and np.isfinite(avg50.iloc[-1]) and float(vol_s.iloc[-1]) > float(avg50.iloc[-1]) * VOL_MULT)
        screened.append({
            "ticker": ticker, "last": last, "liquid": liquid, "adv": adv,
            "rs63": (r63 - bench_r63) * 100.0, "rs126": (r126 - bench_r126) * 100.0,
            "rs_rel": (0.6 * (r126 - bench_r126) + 0.4 * (r63 - bench_r63)) * 100.0,
            "pct_from_high": pct_from_high, "hi52": hi52, "near": near,
            "above50": above50, "above200": above200, "above21": above21, "rising": rising,
            "e21": e21v, "e50": e50v, "e200": e200v, "trend": trend,
            "r20": r20, "r40": r40, "r60": r60, "contracting": contracting, "mild": mild,
            "higher_lows": higher_lows, "vcp_score": vcp_score,
            "new_high": new_high, "big_vol": big_vol,
            "bars": len(c), "asof": c.index[-1], "short_history": len(c) < 252,
        })
    df = pd.DataFrame(screened)
    if len(df) == 0:
        return pd.DataFrame(), market
    liquid = df[df["liquid"]].copy()
    if len(liquid) == 0:
        return pd.DataFrame(), market
    liquid["rs_percentile"] = liquid["rs_rel"].rank(pct=True, method="average") * 100.0
    pct_map = liquid.set_index("ticker")["rs_percentile"]

    for rec in screened:
        if not rec["liquid"] or rec["ticker"] not in pct_map.index:
            continue
        rs_p = float(pct_map.loc[rec["ticker"]])
        strict = (
            rec["above50"] and rec["above200"] and rec["rising"]
            and rs_p >= NSE_RS_STRICT and (rec["vcp_score"] >= 2 or rec["near"])
        )
        soft = rec["above50"] and rs_p >= NSE_RS_SOFT and (rec["vcp_score"] >= 2 or rec["near"])
        if not soft and not strict:
            continue
        c_pct, c_now, c_old = _yoy_eps(quarters, rec["ticker"], True)
        a_pct, a_now, a_old = _yoy_eps(annual, rec["ticker"], False)
        i_trend, i_text = _holder_trend(holders, rec["ticker"])
        if strict and rec["new_high"] and rec["big_vol"]:
            status = "BROKEN OUT today"
        elif strict and rec["pct_from_high"] is not None and rec["pct_from_high"] >= -5:
            status = "READY"
        else:
            status = "WATCHING"
        strength = (
            rs_p * 0.45 + rec["trend"] * 8 + rec["vcp_score"] * 7
            + (5 if rec["near"] else 0)
            + max(0.0, 10 + (rec["pct_from_high"] or -10)) * 0.3
        )
        c_txt = NOT_VERIFIED if c_pct is None else "%.1f%% versus the year-ago quarter (%.2f vs %.2f)" % (c_pct, c_now, c_old)
        a_txt = NOT_VERIFIED if a_pct is None else "%.1f%% versus the prior year (%.2f vs %.2f)" % (a_pct, a_now, a_old)
        n_txt = (
            "%.1f%% from the 52-week closing high. Product or news catalyst is not verified."
            % rec["pct_from_high"]
        )
        s_txt = "20-day average volume %s shares. Float tightness is not verified." % _round(rec["adv"], 0)
        l_txt = "RS percentile %.0f in this liquid universe versus SPY. Industry group rank is not verified." % rs_p
        if rec["contracting"]:
            vcp_txt = "20/40/60 day ranges %.1f%% / %.1f%% / %.1f%%, contracting." % (rec["r20"], rec["r40"], rec["r60"])
        elif rec["mild"]:
            vcp_txt = "Mild range contraction, 20-day %.1f%% versus 60-day %.1f%%." % (rec["r20"], rec["r60"])
        else:
            vcp_txt = "20/40/60 day ranges %s / %s / %s." % (
                _round(rec["r20"], 1) if rec["r20"] is not None else NOT_VERIFIED,
                _round(rec["r40"], 1) if rec["r40"] is not None else NOT_VERIFIED,
                _round(rec["r60"], 1) if rec["r60"] is not None else NOT_VERIFIED,
            )
        if rec["higher_lows"]:
            vcp_txt += " Higher lows on the 10-day rolling low."
        qualify = "strict" if strict else "soft"
        reason = (
            "%s versus SPY. %s %s %s %s %s Market: %s "
            "Pivot is the 52-week closing high from the NSE method, not the VCP buy point. "
            "Stop: not verified. Target: not verified. That scan does not set either one. "
            "A close under EMA50 (%s) would fail its trend rule."
            % (
                "Strict qualify" if strict else "Soft watch, not a full qualify",
                "C %s." % c_txt, "A %s." % a_txt, "N %s" % n_txt, "S %s" % s_txt, "L %s" % l_txt,
                market["text"], _round(rec["e50"]),
            )
        )
        if status == "BROKEN OUT today":
            reason = "Closed at a new high on volume above 1.5 times the 50-day average. " + reason
        elif rec["new_high"] and not rec["big_vol"]:
            reason = "Closed at a new high, but volume was not above 1.5 times the 50-day average. " + reason
        meta = _meta_row(universe, rec["ticker"])
        gaps = []
        if c_pct is None:
            gaps.append("C not verified")
        if a_pct is None:
            gaps.append("A not verified")
        gaps.append("product catalyst not verified")
        gaps.append("float not verified")
        gaps.append("industry rank not verified")
        if i_trend == NOT_VERIFIED:
            gaps.append("I not verified")
        if market["qqq"] == NOT_VERIFIED:
            gaps.append("QQQ not verified")
        if market["spy"] == NOT_VERIFIED:
            gaps.append("SPY not verified")
        if rec["short_history"]:
            gaps.append("52-week window is shorter than 252 sessions")
        rows.append({
            "ticker": rec["ticker"],
            "company": meta["company"],
            "sector": meta["sector"],
            "index_membership": meta["index_membership"],
            "status": status,
            "pivot": _round(rec["hi52"]),
            "stop": "",
            "target": "",
            "strength": round(strength, 1),
            "reason": reason + " " + vcp_txt,
            "freshness": _freshness(rec["asof"], panel, rec["bars"], 252),
            "price": _round(last := rec["last"]),
            "price_as_of": str(pd.Timestamp(rec["asof"]).date()),
            "c_quarterly_eps": "" if c_pct is None else round(c_pct, 1),
            "c_status": c_txt,
            "a_annual_eps": "" if a_pct is None else round(a_pct, 1),
            "a_status": a_txt,
            "n_pct_from_high": round(rec["pct_from_high"], 1),
            "n_status": n_txt,
            "s_adv": _round(rec["adv"], 0),
            "s_status": s_txt,
            "l_rs_percentile": round(rs_p, 1),
            "l_status": l_txt,
            "i_trend": i_trend,
            "i_status": i_text,
            "m_market": market["label"],
            "m_spy": market["spy"],
            "m_qqq": market["qqq"],
            "m_status": market["text"],
            "qualify": qualify,
            "vcp_heuristic": rec["vcp_score"],
            "data_status": "OK",
            "note": "; ".join(gaps) + ".",
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out, market
    rank = {"BROKEN OUT today": 0, "READY": 1, "WATCHING": 2}
    out["_k"] = out["status"].map(rank)
    out = out.sort_values(["_k", "strength"], ascending=[True, False]).drop(columns="_k")
    return out, market


def _big_volume(volume):
    vol = np.asarray(volume, dtype=float)
    if len(vol) < VOL_LEN or not np.isfinite(vol[-1]):
        return False, None
    avg = pd.Series(vol).rolling(VOL_LEN, min_periods=VOL_LEN).mean().iloc[-1]
    if not np.isfinite(avg) or avg <= 0:
        return False, None
    return bool(vol[-1] > avg * VOL_MULT), float(vol[-1] / avg)


def scan_box(close, high, low, vol, universe):
    rows = []
    panel = _panel_date(close)
    names = list(universe["ticker"]) if universe is not None and len(universe) else []
    for ticker in names:
        got = _bars(close, high, low, vol, ticker, None)
        if got is None:
            continue
        frame, _ = got
        h = frame["high"].to_numpy(dtype=float)
        l = frame["low"].to_numpy(dtype=float)
        c = frame["close"].to_numpy(dtype=float)
        v = frame["volume"].to_numpy(dtype=float)
        n = len(c)
        if n < BOX_MIN_DAYS + 1:
            continue
        chosen = None
        for length in range(min(BOX_MAX_DAYS, n - 1), BOX_MIN_DAYS - 1, -1):
            seg_h = h[n - 1 - length:n - 1]
            seg_l = l[n - 1 - length:n - 1]
            seg_c = c[n - 1 - length:n - 1]
            if not np.isfinite(seg_h).all() or not np.isfinite(seg_l).all() or not np.isfinite(seg_c).all():
                continue
            rh = float(seg_h.max())
            rl = float(seg_l.min())
            mid = (rh + rl) / 2.0
            if mid <= 0 or seg_c[0] == 0:
                continue
            width = (rh - rl) / mid
            drift = abs(seg_c[-1] - seg_c[0]) / abs(seg_c[0])
            if width <= BOX_MAX_WIDTH and drift <= BOX_MAX_DRIFT:
                chosen = (length, rh, rl, width, drift)
                break
        if chosen is None:
            continue
        length, rh, rl, width, drift = chosen
        last = float(c[-1])
        big, ratio = _big_volume(v)
        if last > rh and big:
            status = "BROKEN OUT today"
        elif last > rh and not big:
            status = "WATCHING"
        elif last <= rh and last >= rh * (1.0 - BOX_NEAR):
            status = "READY"
        else:
            status = "WATCHING"
        height = rh - rl
        tight = max(0.0, 1.0 - width / BOX_MAX_WIDTH)
        length_score = (length - BOX_MIN_DAYS) / (BOX_MAX_DAYS - BOX_MIN_DAYS)
        vol_bonus = 0.15 if big else 0.0
        strength = round(min(100.0, 100.0 * (0.55 * tight + 0.30 * length_score + vol_bonus)), 1)
        if status == "BROKEN OUT today":
            lead = "Closed above the %d-day range high on volume %.1f times the 50-day average." % (length, ratio or 0)
        elif last > rh:
            lead = "Closed above the range high, but volume was not 1.5 times the 50-day average, so it is not marked broken out."
        elif status == "READY":
            lead = "Tight %d-day range and the close is within 2%% of the range high." % length
        else:
            lead = "Tight %d-day range. Price is still inside it, not yet at the high." % length
        meta = _meta_row(universe, ticker)
        rows.append({
            "ticker": ticker,
            "company": meta["company"],
            "sector": meta["sector"],
            "index_membership": meta["index_membership"],
            "status": status,
            "pivot": _round(rh),
            "stop": _round(rl),
            "target": _round(rh + height),
            "strength": strength,
            "reason": "%s Range is %.1f%% wide and the close drifted %.1f%%. Stop is the range low. Target is the range high plus the height of the range." % (
                lead, width * 100.0, drift * 100.0),
            "freshness": _freshness(frame.index[-1], panel, n, BOX_MIN_DAYS + VOL_LEN),
            "price": _round(last),
            "price_as_of": str(pd.Timestamp(frame.index[-1]).date()),
            "range_days": length,
            "range_width_pct": round(width * 100.0, 1),
            "volume_ratio": "" if ratio is None else round(ratio, 2),
            "data_status": "OK",
            "note": BOX_NOTE,
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    rank = {"BROKEN OUT today": 0, "READY": 1, "WATCHING": 2}
    out["_k"] = out["status"].map(rank)
    return out.sort_values(["_k", "strength"], ascending=[True, False]).drop(columns="_k")


def _volume_ratio(volume, mult):
    vol = np.asarray(volume, dtype=float)
    if len(vol) < VOL_LEN or not np.isfinite(vol[-1]):
        return False, None
    avg = pd.Series(vol).rolling(VOL_LEN, min_periods=VOL_LEN).mean().iloc[-1]
    if not np.isfinite(avg) or avg <= 0:
        return False, None
    ratio = float(vol[-1] / avg)
    return bool(ratio >= mult), ratio


def scan_breakdown(close, high, low, vol, universe):
    """Downside base break from cached bars. No network."""
    rows = []
    if close is None or len(close) == 0 or universe is None or len(universe) == 0:
        return pd.DataFrame(rows)
    panel = _panel_date(close)
    names = list(universe["ticker"]) if "ticker" in universe.columns else []
    for ticker in names:
        got = _bars(close, high, low, vol, ticker, None)
        if got is None:
            continue
        frame, _ = got
        h = frame["high"].to_numpy(dtype=float)
        l = frame["low"].to_numpy(dtype=float)
        c = frame["close"].to_numpy(dtype=float)
        v = frame["volume"].to_numpy(dtype=float)
        n = len(c)
        if n < 221:
            continue
        sma50 = _sma(c, 50)
        sma200 = _sma(c, 200)
        s50 = float(sma50[-1])
        s200 = float(sma200[-1])
        s200_ago = float(sma200[-21])
        last = float(c[-1])
        if not (np.isfinite(s50) and np.isfinite(s200) and np.isfinite(s200_ago)):
            continue
        if not (last < s50 < s200 and s200 <= s200_ago):
            continue
        chosen = None
        for length in range(min(BREAK_MAX_DAYS, n - 1), BREAK_MIN_DAYS - 1, -1):
            seg_h = h[n - 1 - length:n - 1]
            seg_l = l[n - 1 - length:n - 1]
            seg_c = c[n - 1 - length:n - 1]
            if not np.isfinite(seg_h).all() or not np.isfinite(seg_l).all() or not np.isfinite(seg_c).all():
                continue
            rh = float(seg_h.max())
            rl = float(seg_l.min())
            mid = (rh + rl) / 2.0
            if mid <= 0 or seg_c[0] == 0:
                continue
            width = (rh - rl) / mid
            drift = abs(seg_c[-1] - seg_c[0]) / abs(seg_c[0])
            half = length // 2
            if half < 1:
                continue
            first = float(seg_h[:half].max() - seg_l[:half].min())
            second = float(seg_h[half:].max() - seg_l[half:].min())
            if width <= BREAK_MAX_WIDTH and drift <= BREAK_MAX_DRIFT and second < first:
                chosen = (length, rh, rl, width, drift)
                break
        if chosen is None:
            continue
        length, rh, rl, width, drift = chosen
        big, ratio = _volume_ratio(v, BREAK_VOL_MULT)
        if last < rl and big:
            status = "BROKEN DOWN today"
        elif last < rl or (last <= rl * (1.0 + BREAK_NEAR) and last >= rl):
            status = "WATCHING"
        else:
            continue
        if status == "BROKEN DOWN today":
            entry = last
        elif last < rl:
            entry = last
        else:
            entry = rl
        risk = rh - entry
        if not np.isfinite(risk) or risk <= 0:
            continue
        target = entry - 2.0 * risk
        tight = max(0.0, 1.0 - width / BREAK_MAX_WIDTH)
        length_score = (length - BREAK_MIN_DAYS) / float(BREAK_MAX_DAYS - BREAK_MIN_DAYS)
        vol_bonus = 0.15 if big else 0.0
        strength = round(min(100.0, 100.0 * (0.55 * tight + 0.30 * length_score + vol_bonus)), 1)
        if status == "BROKEN DOWN today":
            lead = "Closed under the %d-day base low on volume %.1f times the 50-day average." % (length, ratio or 0)
        elif last < rl:
            lead = "Closed under the base low, but volume was under 1.4 times the 50-day average, so it is still watching."
        else:
            lead = "Tight %d-day base and the close is within 3%% of the base low." % length
        meta = _meta_row(universe, ticker)
        rows.append({
            "ticker": ticker,
            "company": meta["company"],
            "sector": meta["sector"],
            "index_membership": meta["index_membership"],
            "status": status,
            "pivot": _round(rl),
            "stop": _round(rh),
            "target": _round(target),
            "strength": strength,
            "reason": (
                "%s The base is %.1f%% wide and the close drifted %.1f%%. "
                "The second half of the base is tighter than the first. "
                "Price %.2f is under the 50-day at %.2f, and that is under the 200-day at %.2f, which is not rising. "
                "Stop is the base high. Target is the entry minus twice the risk up to that high."
            ) % (lead, width * 100.0, drift * 100.0, last, s50, s200),
            "freshness": _freshness(frame.index[-1], panel, n, 221),
            "price": _round(last),
            "price_as_of": str(pd.Timestamp(frame.index[-1]).date()),
            "range_days": length,
            "range_width_pct": round(width * 100.0, 1),
            "volume_ratio": "" if ratio is None else round(ratio, 2),
            "sma50": _round(s50),
            "sma200": _round(s200),
            "entry": _round(entry),
            "data_status": "OK",
            "note": BREAKDOWN_NOTE,
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    rank = {"BROKEN DOWN today": 0, "WATCHING": 1}
    out["_k"] = out["status"].map(rank)
    return out.sort_values(["_k", "strength"], ascending=[True, False]).drop(columns="_k")


def _prior_avg(v, i, n=HV_AVG_LEN):
    """Average volume of the n sessions before bar i. None when there is not enough history."""
    if i < n:
        return None
    seg = v[i - n:i]
    if not np.isfinite(seg).all():
        return None
    a = float(seg.mean())
    return a if a > 0 else None


def scan_volume(close, high, low, vol, universe):
    """High volume scanner from cached daily bars. No network.

    One row per name that is in at least one group:
    spike (volume >= 1.5x the prior 50-day average today), streak (3+ days in a row
    above that average), or quiet (10-day average volume under 0.6x the 50-day average
    while the close is within 5% of the 63-session high and above the 50-day average).
    """
    rows = []
    if close is None or len(close) == 0 or vol is None or len(vol) == 0 or universe is None or len(universe) == 0:
        return pd.DataFrame(rows)
    panel = _panel_date(close)
    names = list(universe["ticker"]) if "ticker" in universe.columns else []
    for ticker in names:
        got = _bars(close, high, low, vol, ticker, None)
        if got is None:
            continue
        frame, _ = got
        frame = frame.dropna(subset=["volume"])
        n = len(frame)
        if n < HV_AVG_LEN + 2:
            continue
        if panel is not None and pd.Timestamp(frame.index[-1]).normalize() < pd.Timestamp(panel).normalize():
            continue  # stale bar: today's volume is not on file
        c = frame["close"].to_numpy(dtype=float)
        h = frame["high"].to_numpy(dtype=float)
        v = frame["volume"].to_numpy(dtype=float)
        last = float(c[-1])
        prev = float(c[-2])
        today = float(v[-1])
        avg50 = _prior_avg(v, n - 1)
        if avg50 is None or not np.isfinite(today) or not np.isfinite(last) or not np.isfinite(prev) or prev <= 0:
            continue
        ratio = today / avg50
        change = (last / prev - 1.0) * 100.0
        streak = 0
        i = n - 1
        while i >= HV_AVG_LEN:
            a = _prior_avg(v, i)
            if a is None or not np.isfinite(v[i]) or v[i] <= a:
                break
            streak += 1
            i -= 1
        sma50 = float(np.mean(c[-50:])) if n >= 50 else float("nan")
        sma200 = float(np.mean(c[-200:])) if n >= 200 else float("nan")
        avg10 = float(np.mean(v[-HV_QUIET_LEN:]))
        avg50_now = float(np.mean(v[-HV_AVG_LEN:]))
        dry = avg10 / avg50_now if avg50_now > 0 else float("nan")
        hi = float(np.nanmax(h[-HV_HIGH_LEN:]))
        from_high = (last / hi - 1.0) * 100.0 if hi > 0 else float("nan")
        spike = ratio >= HV_LIST_MIN
        streaky = streak >= HV_STREAK_MIN
        quiet = (np.isfinite(dry) and dry < HV_QUIET_MAX and np.isfinite(sma50) and last > sma50
                 and np.isfinite(from_high) and from_high >= -HV_NEAR_HIGH * 100.0)
        if not (spike or streaky or quiet):
            continue
        if change > 0:
            direction = "BUYING"
        elif change < 0:
            direction = "SELLING"
        else:
            direction = "FLAT"
        above50 = "" if not np.isfinite(sma50) else ("above" if last > sma50 else "below")
        above200 = "" if not np.isfinite(sma200) else ("above" if last > sma200 else "below")
        bits = []
        if spike:
            word = {"BUYING": "closed up", "SELLING": "closed down", "FLAT": "closed flat"}[direction]
            bits.append("Traded %.1f times its usual volume today and %s %.1f%%." % (ratio, word, abs(change)))
        if streaky:
            bits.append("Volume has been above its 50-day average %d days in a row." % streak)
        if quiet:
            bits.append(
                "Volume has dried up to %.0f%% of normal over 10 days while the price sits %.1f%% from its 3-month high "
                "and above its 50-day average." % (dry * 100.0, abs(from_high)))
        meta = _meta_row(universe, ticker)
        rows.append({
            "ticker": ticker,
            "company": meta["company"],
            "sector": meta["sector"],
            "index_membership": meta["index_membership"],
            "price": _round(last),
            "change_pct": round(change, 2),
            "direction": direction,
            "volume": int(round(today)),
            "avg_volume_50": int(round(avg50)),
            "volume_ratio": round(ratio, 2),
            "spike": "yes" if spike else "no",
            "streak_days": streak,
            "streak": "yes" if streaky else "no",
            "avg_volume_10": int(round(avg10)),
            "dryup_ratio": round(dry, 2) if np.isfinite(dry) else "",
            "high_3m": _round(hi),
            "pct_from_high": round(from_high, 1) if np.isfinite(from_high) else "",
            "quiet": "yes" if quiet else "no",
            "sma50": _round(sma50) if np.isfinite(sma50) else "",
            "sma200": _round(sma200) if np.isfinite(sma200) else "",
            "vs_sma50": above50,
            "vs_sma200": above200,
            "reason": " ".join(bits),
            "freshness": _freshness(frame.index[-1], panel, n, 200),
            "price_as_of": str(pd.Timestamp(frame.index[-1]).date()),
            "data_status": "OK",
            "note": HIGH_VOLUME_NOTE,
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    return out.sort_values(["volume_ratio"], ascending=False).reset_index(drop=True)


def _flag_candidate(h, l, c, flag_len):
    n = len(c)
    # Flag occupies the bars after the pole and before today.
    j = n - 2 - flag_len
    if j < FLAG_POLE_MIN_BARS:
        return None
    start_min = max(0, j - FLAG_POLE_MAX_BARS)
    window = l[start_min:j]
    if len(window) < FLAG_POLE_MIN_BARS or not np.isfinite(window).all():
        return None
    start = start_min + int(np.argmin(window))
    bars = j - start
    if bars < FLAG_POLE_MIN_BARS or bars > FLAG_POLE_MAX_BARS:
        return None
    if not np.isfinite(h[start:j + 1]).all() or not np.isfinite(l[start:j + 1]).all():
        return None
    pole_low = float(l[start])
    pole_high = float(h[j])
    if pole_low <= 0 or pole_high < float(np.max(h[start:j + 1])):
        return None
    rise = (pole_high - pole_low) / pole_low
    if rise < FLAG_POLE_MIN:
        return None
    flag_h = h[j + 1:n - 1]
    flag_l = l[j + 1:n - 1]
    flag_c = c[j + 1:n - 1]
    if len(flag_h) != flag_len or not np.isfinite(flag_h).all() or not np.isfinite(flag_l).all():
        return None
    fh = float(flag_h.max())
    fl = float(flag_l.min())
    pole_height = pole_high - pole_low
    if pole_height <= 0 or fh > pole_high:
        return None
    retrace = (pole_high - fl) / pole_height
    if retrace >= FLAG_MAX_RETRACE:
        return None
    if float(flag_c[-1]) > float(flag_c[0]) * 1.01:
        return None
    return {
        "fh": fh, "fl": fl, "rise": rise, "retrace": retrace,
        "pole_height": pole_height, "flag_len": flag_len, "bars": bars,
    }


def scan_flag(close, high, low, vol, universe):
    rows = []
    panel = _panel_date(close)
    names = list(universe["ticker"]) if universe is not None and len(universe) else []
    for ticker in names:
        got = _bars(close, high, low, vol, ticker, None)
        if got is None:
            continue
        frame, _ = got
        h = frame["high"].to_numpy(dtype=float)
        l = frame["low"].to_numpy(dtype=float)
        c = frame["close"].to_numpy(dtype=float)
        v = frame["volume"].to_numpy(dtype=float)
        n = len(c)
        best = None
        for flag_len in range(FLAG_MIN_BARS, FLAG_MAX_BARS + 1):
            cand = _flag_candidate(h, l, c, flag_len)
            if cand is None:
                continue
            if best is None or cand["retrace"] < best["retrace"] - 1e-9 or (
                abs(cand["retrace"] - best["retrace"]) <= 1e-9 and cand["flag_len"] > best["flag_len"]
            ):
                best = cand
        if best is None:
            continue
        last = float(c[-1])
        big, ratio = _big_volume(v)
        fh, fl = best["fh"], best["fl"]
        if last > fh and big:
            status = "BROKEN OUT today"
        elif last > fh:
            status = "WATCHING"
        elif last <= fh and last >= fh * (1.0 - FLAG_NEAR):
            status = "READY"
        else:
            status = "WATCHING"
        pole_score = min((best["rise"] - FLAG_POLE_MIN) / 0.25, 1.0)
        shallow = max(0.0, 1.0 - best["retrace"] / FLAG_MAX_RETRACE)
        strength = round(min(100.0, 100.0 * (0.4 * pole_score + 0.4 * shallow + (0.2 if big else 0.0))), 1)
        if status == "BROKEN OUT today":
            lead = "Closed above the flag high on volume %.1f times the 50-day average." % (ratio or 0)
        elif last > fh:
            lead = "Closed above the flag high, but volume was not 1.5 times the 50-day average, so it is not marked broken out."
        elif status == "READY":
            lead = "Pole and flag are in place, and the close is within 2% of the flag high."
        else:
            lead = "Pole and a shallow flag are in place. Price is not yet at the flag high."
        meta = _meta_row(universe, ticker)
        rows.append({
            "ticker": ticker,
            "company": meta["company"],
            "sector": meta["sector"],
            "index_membership": meta["index_membership"],
            "status": status,
            "pivot": _round(fh),
            "stop": _round(fl),
            "target": _round(fh + best["pole_height"]),
            "strength": strength,
            "reason": "%s The pole rose %.1f%% in %d sessions. The flag is %d sessions and retraced %.0f%% of the pole. Stop is the flag low. Target is the flag high plus the pole height." % (
                lead, best["rise"] * 100.0, best["bars"], best["flag_len"], best["retrace"] * 100.0),
            "freshness": _freshness(frame.index[-1], panel, n, FLAG_POLE_MAX_BARS + FLAG_MAX_BARS + 1),
            "price": _round(last),
            "price_as_of": str(pd.Timestamp(frame.index[-1]).date()),
            "pole_pct": round(best["rise"] * 100.0, 1),
            "flag_bars": best["flag_len"],
            "retrace_pct": round(best["retrace"] * 100.0, 1),
            "volume_ratio": "" if ratio is None else round(ratio, 2),
            "data_status": "OK",
            "note": FLAG_NOTE,
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    rank = {"BROKEN OUT today": 0, "READY": 1, "WATCHING": 2}
    out["_k"] = out["status"].map(rank)
    return out.sort_values(["_k", "strength"], ascending=[True, False]).drop(columns="_k")


# ---------------------------------------------------------------- Qullamaggie and Marios breakouts
# Rules from Kristjan Kullamagi (Qullamaggie) and Marios Stamatoudis, from their own blog posts,
# FAQ, X posts, and interview notes. Daily bars only, so intraday entries are approximated:
# the trigger is the day's high crossing the base high, the fill is max(open, base high), and the
# stop is that day's low. Every rule has a switch and its numbers in config.json.
QM_DEFAULTS = {
    # Universe and leaders
    "price_filter": True, "min_price": 20.0,
    "adr_filter": True, "adr_days": 20, "adr_min_pct": 3.5, "adr_fast_pct": 5.0,
    "leader_gate": True, "leader_top_pct": 3.0, "leader_windows": [21, 63, 126],
    "traded_value_gate": False, "traded_value_days": 20, "min_traded_value_usd": 20000000.0,
    # Prior run
    "run_min_pct": 30.0, "run_lookback_max": 63, "run_lookback_min": 21,
    "run_leg_limit": True, "run_max_leg_days": 40,
    # Base
    "base_min_days": 10, "base_max_days": 40,
    # Desk rules, not the traders' own: a range cap on the base, and the base top near the run high.
    "base_range_cap": True, "base_max_range_pct": 25.0,
    "base_near_run_high": True, "base_top_near_run_high_pct": 10.0,
    # Desk rule: the base starts after the run, so its first bar sits in the upper part of the base range.
    "base_start_upper": True, "base_start_upper_share": 0.5,
    "tighten_check": True, "higher_lows": True,
    "ma_rule": True, "above_sma20_share": 0.7, "allow_all_above_sma50": True,
    "sma10_over_sma20": True, "mas_rising": True, "require_above_sma50": False,
    "volume_dry_up_gate": False, "dry_up_days": 5,
    # Entry
    "ready_within_adr": 1.0, "vol_mult": 1.5, "vol_len": 50,
    "stop_cap": True, "stop_cap_adr": 1.0, "aplus_adr": 0.5,
    # Exits and the trade record
    "track_trades": True, "display_cap_days": 60,
    "exits": True, "partial_day_min": 3, "partial_day_max": 5,
    "breakeven_after_partial": True, "trail_use_sma20": False, "trail_after_partial_only": True,
    # Context columns
    "market_light": True, "market_light_slope_days": 5,
    "earnings_flag": True, "earnings_within_sessions": 5,
    "sizing": True, "account_size": 1000000, "risk_per_trade_pct": 0.5, "max_position_pct": 25.0,
}
# Marios starts from the qullamaggie numbers. These keys are his own and always come from the marios block.
MARIOS_DEFAULTS = {
    "run_lookback_max": 126,
    "adr_min_pct": 2.5, "adr_preferred_pct": 3.5,
    "volume_dry_up_gate": True,
    "weak_close_flag": True, "weak_close_r": 0.5,
    "partial": True, "target_low_adr": 2.5, "target_high_adr": 3.0,
    "breakeven_after_partial": True,
    "trail_ladder": True, "trail_part_ma": 10, "trail_exit_ma": 20, "trail_after_partial_only": False,
    "display_cap_days": 60,
}
QM_NOTE = (
    "Qullamaggie's own rules: a top 1-3-6 month gainer, a 30%+ leg in the 1 to 3 months before a 2 week to 2 month base "
    "with higher lows that rides the rising 10 and 20-day averages, stop at the day's low no wider than 1 ADR, "
    "sell 1/3 to 1/2 after 3 to 5 days, stop to breakeven, then the first close under the 10-day. "
    "Daily-data stand-ins: the trigger is the day's high crossing the base high and the fill is the open or the base high."
)
MARIOS_NOTE = (
    "Marios's own rules: ADR% of 2.5 or more, a tight base with higher lows and drying volume, stop at the day's low, "
    "sell 1/4 to 1/3 at 2.5 to 3 ADRs, then stop to breakeven, sell 1/3 of the rest on a close under the 10-day "
    "and the rest on a close under the 20-day. Daily-data stand-ins: the trigger is the day's high crossing the base high "
    "and the fill is the open or the base high. ADR is used for the stop check instead of ATR."
)
QM_STATUS_RANK = {"BROKEN OUT today": 0, "IN TRADE": 1, "READY": 2, "CLOSED": 3, "WATCHING": 4}
# US market light: SPY and QQQ, the two broad-market series the desk already downloads in the same batch.
MARKET_LIGHT_TICKERS = (("SPY", "S&P 500 (SPY)"), ("QQQ", "Nasdaq-100 (QQQ)"))


def _clean_cfg(block):
    return {k: v for k, v in (block or {}).items() if not str(k).startswith("_")}


def _qm_cfg(cfg):
    out = dict(QM_DEFAULTS)
    out.update(_clean_cfg((cfg or {}).get("qullamaggie")))
    return out


def _marios_cfg(cfg):
    """Qullamaggie numbers for the shared rules, then Marios's own keys, then anything set in the marios block."""
    out = dict(QM_DEFAULTS)
    out.update({k: v for k, v in _clean_cfg((cfg or {}).get("qullamaggie")).items() if k not in MARIOS_DEFAULTS})
    out.update(MARIOS_DEFAULTS)
    out.update(_clean_cfg((cfg or {}).get("marios")))
    return out


def marios_adr_pct(high, low, days=20):
    """20-day average of high divided by low, minus 1, in percent. Qullamaggie's FAQ formula. None when short."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    if len(h) < days:
        return None
    hh, ll = h[-days:], l[-days:]
    if not (np.isfinite(hh).all() and np.isfinite(ll).all()) or (ll <= 0).any():
        return None
    return float(np.mean(hh / ll - 1.0) * 100.0)


def marios_targets(entry, adr_pct, low_mult=2.5, high_mult=3.0):
    """Partial profit zone in price: entry plus 2.5 and 3 ADRs, where one ADR is ADR% of the entry."""
    entry = _num(entry)
    adr_pct = _num(adr_pct)
    if entry is None or adr_pct is None:
        return None, None
    one = entry * adr_pct / 100.0
    return entry + low_mult * one, entry + high_mult * one


def _yes(flag):
    return "yes" if flag else "no"


def _adr_series(h, l, days):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where((l > 0) & np.isfinite(l) & np.isfinite(h), h / l - 1.0, np.nan)
    return pd.Series(r).rolling(days, min_periods=days).mean().to_numpy() * 100.0


def qm_leader_panels(close, tickers, windows):
    """Percentile rank (0 to 1, highest return = 1) of the return over each window, across the given tickers."""
    cols = [t for t in tickers if close is not None and t in close.columns]
    out = {}
    if not cols:
        return out
    sub = close[cols].astype(float)
    for w in windows:
        w = int(w)
        r = sub / sub.shift(w) - 1.0
        out[w] = r.rank(axis=1, pct=True)
    return out


def qm_market_light(close, p):
    """Green when every index has its 10-day above its 20-day and both rising, red when none do, yellow between."""
    cols = set(map(str, close.columns)) if close is not None else set()
    picks = list(MARKET_LIGHT_TICKERS)
    note = ""
    slope = int(p.get("market_light_slope_days", 5))
    parts, oks = [], []
    for tk, word in picks:
        if tk not in cols:
            parts.append("%s not in the cache" % word)
            continue
        s = close[tk].dropna().to_numpy(dtype=float)
        s10, s20 = _sma(s, 10), _sma(s, 20)
        if len(s) < 20 + slope + 1 or not np.isfinite(s20[-1 - slope]):
            parts.append("%s too short" % word)
            continue
        ok = bool(s10[-1] > s20[-1] and s10[-1] > s10[-1 - slope] and s20[-1] > s20[-1 - slope])
        oks.append(ok)
        parts.append("%s %s" % (word, "10-day over 20-day, both rising" if ok else "not 10 over 20 with both rising"))
    if not oks:
        light = ""
    elif all(oks):
        light = "green"
    elif any(oks):
        light = "yellow"
    else:
        light = "red"
    text = "Market light %s: %s.%s Not a gate." % (light or "not verified", "; ".join(parts), note)
    return light, text


def _earnings_map(scores):
    if scores is None or len(scores) == 0 or "ticker" not in scores.columns or "next_earnings" not in scores.columns:
        return {}
    out = {}
    for t, d in zip(scores["ticker"].astype(str), scores["next_earnings"]):
        ts = pd.to_datetime(d, errors="coerce")
        if pd.notna(ts):
            out[t] = pd.Timestamp(ts).tz_localize(None) if getattr(ts, "tzinfo", None) is not None else pd.Timestamp(ts)
    return out


def _qm_arrays(frame, p, ctx=None, ticker=None):
    h = frame["high"].to_numpy(dtype=float)
    l = frame["low"].to_numpy(dtype=float)
    c = frame["close"].to_numpy(dtype=float)
    v = frame["volume"].to_numpy(dtype=float)
    o = frame["open"].to_numpy(dtype=float) if "open" in frame.columns else np.full(len(c), np.nan)
    vol_len = int(p["vol_len"])
    va_prior = pd.Series(v).rolling(vol_len, min_periods=vol_len).mean().shift(1).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(np.isfinite(va_prior) & (va_prior > 0), v / va_prior, np.nan)
    tv_days = int(p["traded_value_days"])
    tv = pd.Series(c * v).rolling(tv_days, min_periods=tv_days).mean().to_numpy() / 1e6  # $ millions
    leaders = {}
    for w, panel in ((ctx or {}).get("leaders") or {}).items():
        if ticker in panel.columns:
            leaders[w] = panel[ticker].reindex(frame.index).to_numpy(dtype=float)
    return {
        "h": h, "l": l, "c": c, "v": v, "o": o, "ratio": ratio, "va": va_prior, "tv": tv,
        "adr": _adr_series(h, l, int(p["adr_days"])),
        "s10": _sma(c, 10), "s20": _sma(c, 20), "s50": _sma(c, 50),
        "leaders": leaders, "_run": {}, "_setup": {},
    }


def _qm_leader_at(a, e, p):
    """(passes, best percentile 0-100, window) for bar e."""
    best, best_w = None, None
    for w in p["leader_windows"]:
        arr = a["leaders"].get(int(w))
        if arr is None or e >= len(arr) or not np.isfinite(arr[e]):
            continue
        if best is None or arr[e] > best:
            best, best_w = float(arr[e]), int(w)
    if best is None:
        return (not p["leader_gate"]), None, None
    ok = best >= 1.0 - float(p["leader_top_pct"]) / 100.0
    return (ok or not p["leader_gate"]), best * 100.0, best_w


def _qm_run(a, s, p):
    """Biggest low-to-high leg whose low sits in the lookback before the base start s. Cached by s."""
    if s in a["_run"]:
        return a["_run"][s]
    h, l = a["h"], a["l"]
    r0 = max(0, s - int(p["run_lookback_max"]))
    out = None
    if s - r0 >= int(p["run_lookback_min"]):
        ll = l[r0:s]
        hh = h[r0:s + 1]
        leg = int(p["run_max_leg_days"]) if p["run_leg_limit"] else len(hh)
        pad = np.concatenate([hh, np.full(leg, -np.inf)])
        win = np.lib.stride_tricks.sliding_window_view(pad, leg + 1)[:len(ll)]
        with np.errstate(invalid="ignore"):
            peak_i = np.argmax(np.where(np.isfinite(win), win, -np.inf), axis=1)
        peak = win[np.arange(len(ll)), peak_i]
        with np.errstate(divide="ignore", invalid="ignore"):
            run = np.where((ll > 0) & np.isfinite(ll) & np.isfinite(peak), peak / ll - 1.0, -np.inf)
        if len(run) and np.isfinite(run).any():
            i = int(np.argmax(run))
            lo_i = r0 + i
            hi_i = lo_i + int(peak_i[i])
            out = {
                "run": float(run[i]), "lo_i": lo_i, "hi_i": hi_i, "run_low": float(l[lo_i]),
                "leg_days": hi_i - lo_i, "run_high": float(np.nanmax(h[lo_i:s + 1])),
            }
    a["_run"][s] = out
    return out


def _qm_base(a, t, length, p):
    """Base of `length` bars that ends the bar before t. None when a rule fails."""
    h, l, c, v = a["h"], a["l"], a["c"], a["v"]
    s = t - length
    if s - int(p["run_lookback_min"]) < 0:
        return None
    bh, bl, bc = h[s:t], l[s:t], c[s:t]
    if not (np.isfinite(bh).all() and np.isfinite(bl).all() and np.isfinite(bc).all()):
        return None
    pivot = float(bh.max())
    low = float(bl.min())
    if pivot <= 0:
        return None
    width = (pivot - low) / pivot
    if p["base_start_upper"] and pivot > low and bh[0] < low + float(p["base_start_upper_share"]) * (pivot - low):
        return None
    if p["base_range_cap"] and width > float(p["base_max_range_pct"]) / 100.0:
        return None
    half = length // 2
    first = float(bh[:half].max() - bl[:half].min())
    second = float(bh[half:].max() - bl[half:].min())
    if p["tighten_check"] and not second < first:
        return None
    higher = float(bl[half:].min()) >= float(bl[:half].min())
    if p["higher_lows"] and not higher:
        return None
    run = _qm_run(a, s, p)
    if run is None or run["run"] < float(p["run_min_pct"]) / 100.0:
        return None
    if p["base_near_run_high"] and pivot < run["run_high"] * (1.0 - float(p["base_top_near_run_high_pct"]) / 100.0):
        return None
    s10, s20, s50 = a["s10"], a["s20"], a["s50"]
    e = t - 1
    if not all(np.isfinite(x) for x in (s10[s], s20[s], s10[e], s20[e])):
        return None
    if p["mas_rising"] and not (s10[e] > s10[s] and s20[e] > s20[s]):
        return None
    if p["sma10_over_sma20"] and not s10[e] > s20[e]:
        return None
    if p["require_above_sma50"] and not (np.isfinite(s50[e]) and s10[e] > s50[e] and s20[e] > s50[e]):
        return None
    share20 = float(np.mean(bc > s20[s:t]))
    s50b = s50[s:t]
    all50 = bool(np.isfinite(s50b).all() and (bc > s50b).all())
    if p["ma_rule"] and not (share20 >= float(p["above_sma20_share"]) or (p["allow_all_above_sma50"] and all50)):
        return None
    dd = int(p["dry_up_days"])
    vl = int(p["vol_len"])
    dry = None
    if t - vl >= 0 and np.isfinite(v[t - vl:t]).all():
        dry = bool(np.mean(v[t - dd:t]) < np.mean(v[t - vl:t]))
    if p["volume_dry_up_gate"] and not dry:
        return None
    return {
        "pivot": pivot, "low": low, "width": width, "length": length, "start": s,
        "tighten": second / first if first > 0 else 1.0, "run": run["run"],
        "run_low": run["run_low"], "run_high": run["run_high"], "run_bars": run["leg_days"],
        "higher_lows": higher, "share20": share20, "all50": all50, "dry_up": dry,
    }


def _qm_setup(a, t, p):
    """Gates and the longest valid base for a trigger on bar t. Uses only bars up to t - 1. Cached by t."""
    if t in a["_setup"]:
        return a["_setup"][t]
    out = None
    e = t - 1
    c = a["c"]
    ok = e >= 1 and np.isfinite(c[e])
    adr = a["adr"][e] if ok else np.nan
    if ok and p["price_filter"] and not c[e] >= float(p["min_price"]):
        ok = False
    if ok and p["adr_filter"] and not (np.isfinite(adr) and adr >= float(p["adr_min_pct"])):
        ok = False
    tv = a["tv"][e] if ok else np.nan
    if ok and p["traded_value_gate"] and not (np.isfinite(tv) and tv * 1e6 >= float(p["min_traded_value_usd"])):
        ok = False
    lead_ok, lead_pct, lead_w = _qm_leader_at(a, e, p) if ok else (False, None, None)
    if ok and lead_ok:
        lo, hi = int(p["base_min_days"]), int(p["base_max_days"])
        for length in range(min(hi, t), lo - 1, -1):
            base = _qm_base(a, t, length, p)
            if base is not None:
                out = dict(base, adr=float(adr) if np.isfinite(adr) else None,
                           tv=float(tv) if np.isfinite(tv) else None, leader_pct=lead_pct, leader_w=lead_w)
                break
    a["_setup"][t] = out
    return out


def _qm_trigger(a, k, p):
    """Setup and fill when the day's high on bar k crossed above the base high and the prior day's high was at or under it."""
    h, l, o, c = a["h"], a["l"], a["o"], a["c"]
    lo = int(p["base_min_days"])
    if k < lo + 1 or k >= len(h) or not np.isfinite(h[k]):
        return None
    if not h[k] > np.nanmax(h[k - lo:k]):
        return None
    base = _qm_setup(a, k, p)
    if base is None:
        return None
    pivot = base["pivot"]
    if not (h[k] > pivot and h[k - 1] <= pivot):
        return None
    fill = max(float(o[k]), pivot) if np.isfinite(o[k]) else pivot
    stop = float(l[k])
    adr = base["adr"]
    adr_px = fill * adr / 100.0 if adr else None
    dist = max(fill - stop, 0.0)
    stop_adr = dist / adr_px if adr_px else None
    return dict(base, k=k, fill=fill, stop=stop, stop_adr=stop_adr,
                stop_check=_stop_check(stop_adr, p), confirmed=bool(c[k] > pivot),
                ratio=float(a["ratio"][k]) if np.isfinite(a["ratio"][k]) else None,
                open_known=bool(np.isfinite(o[k])))


def _stop_check(stop_adr, p):
    if stop_adr is None:
        return ""
    if p["stop_cap"] and stop_adr > float(p["stop_cap_adr"]):
        return "Too wide, skip"
    if stop_adr <= float(p["aplus_adr"]):
        return "A+"
    return "OK"


def _exit_px(a, j, stop):
    o = a["o"][j]
    return float(min(o, stop)) if np.isfinite(o) else float(stop)


def _qm_simulate(a, trig, p):
    """Qullamaggie ladder from the bar after the breakout to today."""
    c, l = a["c"], a["l"]
    k, fill = trig["k"], trig["fill"]
    stop = trig["stop"]
    sma = a["s20"] if p["trail_use_sma20"] else a["s10"]
    trail_word = "20-day" if p["trail_use_sma20"] else "10-day"
    partial_bar = None
    be = False
    n = len(c)
    for j in range(k + 1, n):
        if l[j] <= stop:
            return dict(status="CLOSED", exit_bar=j, exit_price=_exit_px(a, j, stop),
                        exit_reason="breakeven stop" if be else "stop at the breakout-day low",
                        partial_bar=partial_bar, stop_now=stop, trail_word=trail_word)
        if p["exits"]:
            active = partial_bar is not None or not p["trail_after_partial_only"]
            if active and np.isfinite(sma[j]) and c[j] < sma[j]:
                return dict(status="CLOSED", exit_bar=j, exit_price=float(c[j]),
                            exit_reason="first close under the %s average" % trail_word,
                            partial_bar=partial_bar, stop_now=stop, trail_word=trail_word)
            if partial_bar is None and j - k >= int(p["partial_day_min"]):
                partial_bar = j
                if p["breakeven_after_partial"]:
                    stop = max(stop, fill)
                    be = True
    return dict(status="IN TRADE", exit_bar=None, exit_price=None, exit_reason="",
                partial_bar=partial_bar, stop_now=stop, trail_word=trail_word)


def _marios_simulate(a, trig, p):
    """Marios ladder: partial at 2.5 ADRs, breakeven, a third of the rest under the 10-day, the rest under the 20-day."""
    c, h, l = a["c"], a["h"], a["l"]
    k, fill = trig["k"], trig["fill"]
    stop = trig["stop"]
    lo_t, hi_t = marios_targets(fill, trig["adr"], float(p["target_low_adr"]), float(p["target_high_adr"]))
    part_ma = a["s10"] if int(p["trail_part_ma"]) == 10 else _sma(c, int(p["trail_part_ma"]))
    exit_ma = a["s20"] if int(p["trail_exit_ma"]) == 20 else _sma(c, int(p["trail_exit_ma"]))
    partial_bar, third_bar = None, None
    be = False
    n = len(c)
    base = dict(target_low=lo_t, target_high=hi_t)
    for j in range(k + 1, n):
        if l[j] <= stop:
            return dict(base, status="CLOSED", exit_bar=j, exit_price=_exit_px(a, j, stop),
                        exit_reason="breakeven stop" if be else "stop at the breakout-day low",
                        partial_bar=partial_bar, third_bar=third_bar, stop_now=stop)
        if p["partial"] and partial_bar is None and lo_t is not None and h[j] >= lo_t:
            partial_bar = j
            if p["breakeven_after_partial"]:
                stop = max(stop, fill)
                be = True
        if p["trail_ladder"] and (partial_bar is not None or not p["trail_after_partial_only"]):
            if np.isfinite(exit_ma[j]) and c[j] < exit_ma[j]:
                return dict(base, status="CLOSED", exit_bar=j, exit_price=float(c[j]),
                            exit_reason="close under the %d-day average" % int(p["trail_exit_ma"]),
                            partial_bar=partial_bar, third_bar=third_bar, stop_now=stop)
            if third_bar is None and np.isfinite(part_ma[j]) and c[j] < part_ma[j]:
                third_bar = j
    return dict(base, status="IN TRADE", exit_bar=None, exit_price=None, exit_reason="",
                partial_bar=partial_bar, third_bar=third_bar, stop_now=stop)


def _qm_walk(a, p, marios):
    """Walk every bar in the display window. Returns (today's trigger, open or last closed trade)."""
    n = len(a["c"])
    t_last = n - 1
    start = max(int(p["base_min_days"]) + int(p["run_lookback_min"]) + 1, t_last - int(p["display_cap_days"]))
    today, trade = None, None
    k = start
    while k <= t_last:
        trig = _qm_trigger(a, k, p)
        if trig is None:
            k += 1
            continue
        if k == t_last:
            today = trig
            break
        if trig["stop_check"].startswith("Too wide") or not p["track_trades"]:
            k += 1
            continue
        sim = _marios_simulate(a, trig, p) if marios else _qm_simulate(a, trig, p)
        trade = dict(trig, **sim)
        if sim["status"] == "IN TRADE":
            break
        k = sim["exit_bar"] + 1
    return today, trade


def _sizing(entry, stop, p):
    entry, stop = _num(entry), _num(stop)
    if not p["sizing"] or entry is None or stop is None or entry <= 0 or stop >= entry:
        return {"shares": "", "position_value": "", "position_pct": ""}
    acct = float(p["account_size"])
    risk_amt = acct * float(p["risk_per_trade_pct"]) / 100.0
    shares = int(risk_amt // (entry - stop))
    cap = int((acct * float(p["max_position_pct"]) / 100.0) // entry)
    shares = max(0, min(shares, cap))
    value = shares * entry
    return {"shares": shares, "position_value": _round(value, 0), "position_pct": _round(value / acct * 100.0, 1)}


def _qm_strength(base, big, aplus, p):
    run = min(max(base["run"] - float(p["run_min_pct"]) / 100.0, 0.0) / 0.7, 1.0)
    tight = max(0.0, 1.0 - base["width"] / max(float(p["base_max_range_pct"]) / 100.0, 1e-9))
    squeeze = max(0.0, 1.0 - base["tighten"])
    lead = (base.get("leader_pct") or 0.0) / 100.0
    pts = 0.30 * run + 0.25 * tight + 0.10 * squeeze + 0.10 * lead + (0.15 if big else 0.0) + (0.10 if aplus else 0.0)
    return round(min(100.0, 100.0 * pts), 1)


def _fmt_mult(x):
    x = float(x)
    return ("%d" % x) if x == int(x) else ("%s" % round(x, 2))


def _date_at(frame, i):
    if i is None:
        return ""
    return str(pd.Timestamp(frame.index[int(i)]).date())


def _base_words(base):
    bits = [
        "The leg before the base rose %.0f%% in %d sessions." % (base["run"] * 100.0, base["run_bars"]),
        "The %d-day base is %.1f%% from high to low%s%s." % (
            base["length"], base["width"] * 100.0,
            ", its second half is tighter" if base["tighten"] < 1 else "",
            ", with higher lows" if base["higher_lows"] else ""),
        "Closes held above the 20-day %.0f%% of the time%s." % (
            base["share20"] * 100.0, " and above the 50-day every day" if base["all50"] else ""),
    ]
    if base.get("leader_pct") is not None:
        bits.append("It ranks in the top %.1f%% on its %d-day return." % (max(0.0, 100.0 - base["leader_pct"]), base["leader_w"]))
    return " ".join(bits)


def _qm_rows(close, high, low, vol, universe, cfg, marios=False, opn=None, scores=None):
    p = _marios_cfg(cfg) if marios else _qm_cfg(cfg)
    rows = []
    panel = _panel_date(close)
    names = list(universe["ticker"]) if universe is not None and len(universe) else []
    need = int(p["run_lookback_max"]) + int(p["base_max_days"]) + 1
    # Ranks are always worked out so the leader column shows even when the gate is off.
    ctx = {"leaders": qm_leader_panels(close, names, p["leader_windows"])}
    light, light_text = qm_market_light(close, p) if p["market_light"] else ("", "")
    earn = _earnings_map(scores) if p["earnings_flag"] else {}
    for ticker in names:
        if close is None or ticker not in close.columns:
            continue
        frame = pd.DataFrame({
            "close": close[ticker],
            "high": high[ticker] if high is not None and ticker in high.columns else np.nan,
            "low": low[ticker] if low is not None and ticker in low.columns else np.nan,
            "volume": vol[ticker] if vol is not None and ticker in vol.columns else np.nan,
            "open": opn[ticker] if opn is not None and ticker in getattr(opn, "columns", []) else np.nan,
        }).dropna(subset=["close", "high", "low"])
        n = len(frame)
        if n < int(p["base_min_days"]) + int(p["run_lookback_min"]) + 2 or n < 52:
            continue
        a = _qm_arrays(frame, p, ctx, ticker)
        today, trade = _qm_walk(a, p, marios)
        t = n - 1
        row = None
        if today is not None:
            row = _qm_row_breakout(a, frame, today, p, marios)
        elif trade is not None and trade["status"] == "IN TRADE":
            row = _qm_row_trade(a, frame, trade, p, marios)
        else:
            setup = _qm_setup(a, n, p)
            ready_row = _qm_row_setup(a, frame, setup, p, marios) if setup is not None else None
            if ready_row is not None and ready_row["status"] == "READY":
                row = ready_row
            elif trade is not None:
                row = _qm_row_trade(a, frame, trade, p, marios)
            else:
                row = ready_row
        if row is None:
            continue
        meta = _meta_row(universe, ticker)
        row.update({
            "ticker": ticker, "company": meta["company"], "sector": meta["sector"],
            "index_membership": meta["index_membership"],
            "freshness": _freshness(frame.index[-1], panel, n, need),
            "price": _round(a["c"][-1]), "price_as_of": str(pd.Timestamp(frame.index[-1]).date()),
            "data_status": "OK", "note": MARIOS_NOTE if marios else QM_NOTE,
            "adr_now": _round(a["adr"][t], 2),
            "traded_value_usd_m": _round(a["tv"][t], 1),
            "market_light": light,
            # Today's 10 and 20-day averages, drawn as lines on the row chart (US desk addition).
            "trail10": _round(a["s10"][t]), "trail20": _round(a["s20"][t]),
        })
        adr_now = a["adr"][t]
        if marios:
            row["adr_tag"] = ("preferred (%s%%+)" % _fmt_mult(p["adr_preferred_pct"])) if np.isfinite(adr_now) and adr_now >= float(p["adr_preferred_pct"]) else "below preferred"
        else:
            row["adr_tag"] = "fast" if np.isfinite(adr_now) and adr_now >= float(p["adr_fast_pct"]) else ""
        nxt = earn.get(ticker)
        if p["earnings_flag"] and nxt is not None and panel is not None:
            d0 = pd.Timestamp(panel).normalize()
            gap = int(np.busday_count(d0.date(), nxt.normalize().date())) if nxt.normalize() >= d0 else -1
            row["next_earnings"] = str(nxt.date())
            row["earnings_soon"] = _yes(0 <= gap <= int(p["earnings_within_sessions"]))
        else:
            row["next_earnings"] = ""
            row["earnings_soon"] = ""
        row.update(_sizing(row.get("entry"), row.get("stop") if row["status"] != "IN TRADE" else row.get("entry_stop"), p))
        extra = []
        if row["earnings_soon"] == "yes":
            extra.append("Results are due within %d sessions (%s), and both traders avoid new buys right before results." % (int(p["earnings_within_sessions"]), row["next_earnings"]))
        if light_text:
            extra.append(light_text)
        row["reason"] = (row["reason"] + " " + " ".join(extra)).strip()
        rows.append(row)
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    out["_k"] = out["status"].map(QM_STATUS_RANK)
    return out.sort_values(["_k", "strength"], ascending=[True, False]).drop(columns="_k").reset_index(drop=True)


def _qm_common(base, p):
    return {
        "pivot": _round(base["pivot"]),
        "run_pct": round(base["run"] * 100.0, 1), "run_days": base["run_bars"],
        "base_days": base["length"], "base_range_pct": round(base["width"] * 100.0, 1),
        "higher_lows": _yes(base["higher_lows"]), "sma20_share": round(base["share20"] * 100.0, 0),
        "dry_up": "" if base["dry_up"] is None else _yes(base["dry_up"]),
        "adr_pct": _round(base["adr"], 2),
        "leader_pct": _round(base["leader_pct"], 1), "leader_window": base["leader_w"] or "",
        "leader_top_pct": "" if base["leader_pct"] is None else round(max(0.0, 100.0 - base["leader_pct"]), 1),
    }


def _qm_blank_trade():
    return {"breakout_date": "", "days_in_trade": "", "exit_reason": "", "exit_date": "", "exit_price": "",
            "confirmed_close": "", "volume_flag": "", "volume_ratio": ""}


def _qm_row_breakout(a, frame, trig, p, marios):
    big = trig["ratio"] is not None and trig["ratio"] >= float(p["vol_mult"])
    row = _qm_common(trig, p)
    row.update(_qm_blank_trade())
    risk = (trig["fill"] - trig["stop"]) / trig["fill"] * 100.0 if trig["fill"] > trig["stop"] else None
    row.update({
        "status": "BROKEN OUT today", "entry": _round(trig["fill"]), "stop": _round(trig["stop"]),
        "stop_basis": "breakout-day low", "risk_pct": _round(risk, 1),
        "stop_adr": _round(trig["stop_adr"], 2), "stop_check": trig["stop_check"],
        "confirmed_close": _yes(trig["confirmed"]), "volume_flag": _yes(big),
        "volume_ratio": "" if trig["ratio"] is None else round(trig["ratio"], 2),
        "breakout_date": _date_at(frame, trig["k"]), "days_in_trade": 0,
        "strength": _qm_strength(trig, big, trig["stop_check"] == "A+", p),
    })
    bits = ["Today's high went above the %d-day base high of %s." % (trig["length"], _round(trig["pivot"]))]
    bits.append("Fill is %s, the %s." % (_round(trig["fill"]), "open, because it opened above the base high" if trig["open_known"] and a["o"][trig["k"]] > trig["pivot"] else ("base high, as a buy-stop" if trig["open_known"] else "base high (no open price in the cache)")))
    bits.append("Stop is today's low at %s, %.2f ADRs under the fill: %s." % (_round(trig["stop"]), trig["stop_adr"] or 0.0, trig["stop_check"] or "not verified"))
    bits.append("The close %s the base high." % ("held above" if trig["confirmed"] else "did not hold above"))
    bits.append("Volume was %s times the prior 50-day average%s." % (_fmt_mult(round(trig["ratio"] or 0, 2)), ", a big-volume breakout" if big else ""))
    bits.append(_base_words(trig))
    if marios:
        lo_t, hi_t = marios_targets(trig["fill"], trig["adr"], float(p["target_low_adr"]), float(p["target_high_adr"]))
        weak = None
        if p["weak_close_flag"]:
            c = a["c"][trig["k"]]
            weak = bool(c < trig["fill"] or c < trig["fill"] + float(p["weak_close_r"]) * (trig["fill"] - trig["stop"]))
        row.update({"target": _round(lo_t), "target_low": _round(lo_t), "target_high": _round(hi_t),
                    "partial_hit": "no", "partial_date": "", "weak_close": "" if weak is None else _yes(weak),
                    "trail_signal": "HOLD", "sold_third_date": "",
                    "trail10": _round(a["s10"][trig["k"]]), "trail20": _round(a["s20"][trig["k"]]),
                    "trade_stop": _round(trig["stop"])})
        bits.append("Sell 1/4 to 1/3 from %s (2.5 ADRs) to %s (3 ADRs)." % (_round(lo_t), _round(hi_t)))
        if weak:
            bits.append("Weak close for day 1: under the fill or less than half the risk above it. Marios often closes these.")
    else:
        row.update({"partial_flag": "not yet (day 3 to 5)", "trail_with": "20-day" if p["trail_use_sma20"] else "10-day",
                    "trail": _round((a["s20"] if p["trail_use_sma20"] else a["s10"])[trig["k"]]),
                    "trail_signal": "HOLD", "trade_stop": _round(trig["stop"])})
        bits.append("Plan: sell 1/3 to 1/2 after 3 to 5 days, move the stop to breakeven, then sell the rest on the first close under the %s average." % row["trail_with"])
    row["reason"] = " ".join(bits)
    return row


def _qm_row_trade(a, frame, tr, p, marios):
    t = len(a["c"]) - 1
    k = tr["k"]
    big = tr["ratio"] is not None and tr["ratio"] >= float(p["vol_mult"])
    row = _qm_common(tr, p)
    days = t - k
    closed = tr["status"] == "CLOSED"
    risk = (tr["fill"] - tr["stop"]) / tr["fill"] * 100.0 if tr["fill"] > tr["stop"] else None
    row.update({
        "status": tr["status"], "entry": _round(tr["fill"]), "stop": _round(tr["stop_now"]),
        "entry_stop": _round(tr["stop"]),
        "stop_basis": "breakeven" if tr["stop_now"] > tr["stop"] else "breakout-day low",
        "risk_pct": _round(risk, 1), "stop_adr": _round(tr["stop_adr"], 2), "stop_check": tr["stop_check"],
        "confirmed_close": _yes(tr["confirmed"]), "volume_flag": _yes(big),
        "volume_ratio": "" if tr["ratio"] is None else round(tr["ratio"], 2),
        "breakout_date": _date_at(frame, k), "days_in_trade": (tr["exit_bar"] - k) if closed else days,
        "exit_reason": tr["exit_reason"], "exit_date": _date_at(frame, tr["exit_bar"]),
        "exit_price": _round(tr["exit_price"]),
        "trade_stop": _round(tr["stop_now"]),
        "strength": _qm_strength(tr, big, tr["stop_check"] == "A+", p),
    })
    bits = ["Broke out on %s: the day's high crossed the base high of %s. Fill %s, stop %s (that day's low)." % (
        row["breakout_date"], _round(tr["pivot"]), _round(tr["fill"]), _round(tr["stop"]))]
    if marios:
        part_d = _date_at(frame, tr["partial_bar"])
        third_d = _date_at(frame, tr["third_bar"])
        weak = None
        if p["weak_close_flag"]:
            c = a["c"][k]
            weak = bool(c < tr["fill"] or c < tr["fill"] + float(p["weak_close_r"]) * (tr["fill"] - tr["stop"]))
        if closed:
            sig = "EXIT" if "average" in tr["exit_reason"] else "STOPPED"
        elif tr["third_bar"] == t:
            sig = "SELL 1/3"
        else:
            sig = "HOLD"
        row.update({"target": _round(tr["target_low"]), "target_low": _round(tr["target_low"]),
                    "target_high": _round(tr["target_high"]),
                    "partial_hit": _yes(tr["partial_bar"] is not None), "partial_date": part_d,
                    "weak_close": "" if weak is None else _yes(weak), "trail_signal": sig,
                    "sold_third_date": third_d,
                    "trail10": _round(a["s10"][t]), "trail20": _round(a["s20"][t])})
        bits.append("Partial zone %s to %s: %s." % (_round(tr["target_low"]), _round(tr["target_high"]),
                                                    ("reached on " + part_d + ", stop moved to breakeven") if part_d else "not reached yet"))
        if third_d:
            bits.append("Closed under the 10-day on %s, so 1/3 of the rest was sold." % third_d)
    else:
        trail_arr = a["s20"] if p["trail_use_sma20"] else a["s10"]
        if tr["partial_bar"] is None:
            pflag = "not yet (day 3 to 5)"
        elif closed or days > int(p["partial_day_max"]):
            pflag = "taken " + _date_at(frame, tr["partial_bar"])
        else:
            pflag = "Sell 1/3 to 1/2"
        row.update({"partial_flag": pflag, "trail_with": tr["trail_word"], "trail": _round(trail_arr[t]),
                    "trail_signal": ("EXIT" if "average" in tr["exit_reason"] else "STOPPED") if closed else "HOLD"})
        if tr["partial_bar"] is not None:
            bits.append("Day %d after the breakout (%s): sell 1/3 to 1/2 and move the stop to breakeven." % (
                int(p["partial_day_min"]), _date_at(frame, tr["partial_bar"])))
    if closed:
        bits.append("CLOSED on %s at %s: %s." % (row["exit_date"], row["exit_price"], tr["exit_reason"]))
    else:
        bits.append("IN TRADE for %d session%s. Stop now %s." % (days, "" if days == 1 else "s", _round(tr["stop_now"])))
    bits.append(_base_words(tr))
    row["reason"] = " ".join(bits)
    return row


def _qm_row_setup(a, frame, setup, p, marios):
    """READY or WATCHING for a trigger tomorrow. The base includes today's bar."""
    t = len(a["c"]) - 1
    last = float(a["c"][t])
    pivot = setup["pivot"]
    if last < setup["low"]:
        return None
    adr = setup["adr"]
    adr_px = last * adr / 100.0 if adr else None
    near = float(p["ready_within_adr"])
    status = "READY" if adr_px is not None and pivot - near * adr_px <= last <= pivot else "WATCHING"
    today_low = float(a["l"][t])
    cap_stop = pivot - float(p["stop_cap_adr"]) * pivot * adr / 100.0 if adr else None
    if cap_stop is not None and (not np.isfinite(today_low) or today_low < cap_stop):
        stop, basis = cap_stop, "1 ADR under the buy point (stop cap)"
    else:
        stop, basis = today_low, "today's low"
    stop_adr = (pivot - stop) / (pivot * adr / 100.0) if adr and stop < pivot else None
    risk = (pivot - stop) / pivot * 100.0 if stop < pivot else None
    row = _qm_common(setup, p)
    row.update(_qm_blank_trade())
    check = _stop_check(stop_adr, p)
    if check.startswith("Too wide"):
        check = "OK"
    row.update({
        "status": status, "entry": _round(pivot), "stop": _round(stop), "stop_basis": basis,
        "risk_pct": _round(risk, 1), "stop_adr": _round(stop_adr, 2), "stop_check": check,
        "trade_stop": "", "strength": _qm_strength(setup, False, check == "A+", p),
    })
    gap = (pivot - last) / adr_px if adr_px else None
    if status == "READY":
        lead = "READY: the close is %.2f ADRs under the %d-day base high of %s." % (gap or 0.0, setup["length"], _round(pivot))
    else:
        lead = "WATCHING: a valid %d-day base, but the close is more than %s ADR under the base high of %s." % (setup["length"], _fmt_mult(near), _round(pivot))
    bits = [lead, "A buy-stop at the base high is the daily stand-in for the opening range high. The real stop is the low of the breakout day, and the trade is skipped if that is more than %s ADR under the fill." % _fmt_mult(p["stop_cap_adr"])]
    bits.append("Stop shown is %s." % basis)
    bits.append(_base_words(setup))
    if setup["dry_up"]:
        bits.append("Volume dried up in the last %d base days." % int(p["dry_up_days"]))
    if marios:
        lo_t, hi_t = marios_targets(pivot, adr, float(p["target_low_adr"]), float(p["target_high_adr"]))
        row.update({"target": _round(lo_t), "target_low": _round(lo_t), "target_high": _round(hi_t),
                    "partial_hit": "", "partial_date": "", "weak_close": "", "trail_signal": "",
                    "sold_third_date": "", "trail10": _round(a["s10"][t]), "trail20": _round(a["s20"][t])})
        bits.append("If it triggers, sell 1/4 to 1/3 from %s to %s." % (_round(lo_t), _round(hi_t)))
    else:
        row.update({"partial_flag": "", "trail_with": "20-day" if p["trail_use_sma20"] else "10-day",
                    "trail": _round((a["s20"] if p["trail_use_sma20"] else a["s10"])[t]), "trail_signal": ""})
    row["reason"] = " ".join(bits)
    return row


def scan_qullamaggie(close, high, low, vol, universe, cfg=None, opn=None, scores=None):
    return _qm_rows(close, high, low, vol, universe, cfg, marios=False, opn=opn, scores=scores)


def scan_marios(close, high, low, vol, universe, cfg=None, opn=None, scores=None):
    return _qm_rows(close, high, low, vol, universe, cfg, marios=True, opn=opn, scores=scores)


def combine_leaders(vcp, canslim):
    """One row per ticker that is a VCP ready/breakout or a strict CANSLIM qualify."""
    v = vcp.copy() if vcp is not None and len(vcp) else pd.DataFrame()
    c = canslim.copy() if canslim is not None and len(canslim) else pd.DataFrame()
    if len(v):
        v = v[v["status"].isin(["READY", "BROKEN OUT today"])]
    if len(c):
        c = c[c["qualify"] == "strict"] if "qualify" in c.columns else c.iloc[0:0]
    names = []
    if len(v):
        names.extend(list(v["ticker"]))
    if len(c):
        names.extend(list(c["ticker"]))
    names = list(dict.fromkeys(names))
    rows = []
    rank = {"BROKEN OUT today": 0, "READY": 1, "WATCHING": 2}
    v_i = v.set_index("ticker") if len(v) else pd.DataFrame()
    c_i = c.set_index("ticker") if len(c) else pd.DataFrame()
    for ticker in names:
        vr = v_i.loc[ticker] if len(v_i) and ticker in v_i.index else None
        cr = c_i.loc[ticker] if len(c_i) and ticker in c_i.index else None
        if isinstance(vr, pd.DataFrame):
            vr = vr.iloc[-1]
        if isinstance(cr, pd.DataFrame):
            cr = cr.iloc[-1]
        statuses = []
        if vr is not None:
            statuses.append(vr["status"])
        if cr is not None:
            statuses.append(cr["status"])
        status = sorted(statuses, key=lambda s: rank.get(s, 9))[0]
        use_v = vr is not None and vr.get("pivot") not in ("", None)
        src = vr if use_v else cr
        v_strength = _num(vr["strength"]) if vr is not None else None
        c_rs = _num(cr["l_rs_percentile"]) if cr is not None else None
        if v_strength is not None and c_rs is not None:
            strength = round(0.5 * v_strength + 0.5 * min(c_rs, 100.0), 1)
        elif v_strength is not None:
            strength = round(v_strength, 1)
        elif c_rs is not None:
            strength = round(min(c_rs, 100.0), 1)
        else:
            strength = ""
        parts = []
        if vr is not None:
            parts.append("VCP %s, trend %s, buy point %s." % (vr["status"], vr.get("trend_score", ""), vr.get("pivot", "")))
        if cr is not None:
            parts.append("CANSLIM %s, RS percentile %s. C %s. A %s. I %s." % (
                cr["status"], cr.get("l_rs_percentile", ""), cr.get("c_status", NOT_VERIFIED),
                cr.get("a_status", NOT_VERIFIED), cr.get("i_trend", NOT_VERIFIED)))
        if use_v:
            parts.append("Stop and target come from the VCP buy rules.")
        else:
            parts.append("Stop: not verified. Target: not verified. This name is a CANSLIM leader without a VCP buy point.")
        base = src
        rows.append({
            "ticker": ticker,
            "company": base.get("company", ""),
            "sector": base.get("sector", ""),
            "index_membership": base.get("index_membership", ""),
            "status": status,
            "pivot": base.get("pivot", ""),
            "stop": base.get("stop", "") if use_v else "",
            "target": base.get("target", "") if use_v else "",
            "strength": strength,
            "reason": " ".join(parts),
            "freshness": base.get("freshness", ""),
            "price": base.get("price", ""),
            "price_as_of": base.get("price_as_of", ""),
            "vcp_status": "" if vr is None else vr["status"],
            "canslim_status": "" if cr is None else cr["status"],
            "vcp_strength": "" if v_strength is None else v_strength,
            "canslim_strength": "" if cr is None else cr.get("strength", ""),
            "on_vcp": "yes" if vr is not None else "no",
            "on_canslim": "yes" if cr is not None else "no",
            "data_status": "OK",
            "note": "Leaders is the overlap of a ready or just-broken VCP and a strict CANSLIM qualify. A name on only one of those still appears.",
        })
    return pd.DataFrame(rows)


def w52_note():
    """Plain-English rule, with the window and the volume multiple filled from the constants."""
    return (
        "52-week high and low are the highest high and lowest low of the last %d sessions, including today. "
        "A new high today means the close is at or above the highest high of the prior %d sessions. "
        "A new low today means the close is at or below the lowest low of the prior %d sessions. "
        "Near the high means the close is within %g%% of the 52-week high. "
        "High on volume means that new high and volume at least %g times the 50-day average. "
        "Research only. This does not place a trade."
    ) % (W52_BARS, W52_BARS, W52_BARS, W52_NEAR_PCT, W52_VOL_MULT)


def _w52_text(v):
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(v).strip()
    if text.lower() in ("nan", "none"):
        return ""
    return text


def _w52_sessions(frame):
    """Flags for one ticker. The arrays are that name's own sessions, with gaps removed."""
    h = frame["high"].to_numpy(dtype=float)
    l = frame["low"].to_numpy(dtype=float)
    c = frame["close"].to_numpy(dtype=float)
    v = frame["volume"].to_numpy(dtype=float)
    hs = pd.Series(h)
    ls = pd.Series(l)
    high_52 = hs.rolling(W52_BARS, min_periods=W52_BARS).max().to_numpy()
    low_52 = ls.rolling(W52_BARS, min_periods=W52_BARS).min().to_numpy()
    prior_high = hs.rolling(W52_BARS, min_periods=W52_BARS).max().shift(1).to_numpy()
    prior_low = ls.rolling(W52_BARS, min_periods=W52_BARS).min().shift(1).to_numpy()
    vol_avg = pd.Series(v).rolling(W52_VOL_LEN, min_periods=W52_VOL_LEN).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = v / vol_avg
        pct_from = (c / high_52 - 1.0) * 100.0
        pct_above = (c / low_52 - 1.0) * 100.0
        span = high_52 - low_52
        pos = (c - low_52) / span * 100.0
    flat = np.isfinite(high_52) & np.isfinite(c) & ~(span > 0) & (np.abs(c - high_52) <= 1e-9)
    pos = np.where(np.isfinite(span) & (span > 0), pos, np.where(flat, 100.0, np.nan))
    pos = np.where(np.isfinite(pos), np.clip(pos, 0.0, 100.0), np.nan)
    ready = np.isfinite(prior_high) & np.isfinite(prior_low) & np.isfinite(c)
    new_high = ready & (c >= prior_high)
    new_low = ready & (c <= prior_low)
    # Within 5% of the 52-week high. The tiny slack keeps an exact 5% close on the near side of float rounding.
    near = np.isfinite(pct_from) & (pct_from >= -W52_NEAR_PCT - 1e-6)
    big = np.isfinite(ratio) & np.isfinite(vol_avg) & (vol_avg > 0) & (ratio >= W52_VOL_MULT)
    return pd.DataFrame({
        "price": c,
        "high_52w": high_52,
        "low_52w": low_52,
        "pct_from_high": pct_from,
        "pct_above_low": pct_above,
        "range_position_pct": pos,
        "volume_ratio": np.where(np.isfinite(ratio) & np.isfinite(vol_avg) & (vol_avg > 0), ratio, np.nan),
        "ready": ready,
        "new_high": new_high,
        "new_low": new_low,
        "near": near,
        "high_on_volume": new_high & big,
    }, index=frame.index)


def _days_since_high(highs, i):
    """Sessions since the most recent bar that printed the 252-session high. Today is 0."""
    if i < W52_BARS - 1:
        return None
    window = np.asarray(highs[i - (W52_BARS - 1):i + 1], dtype=float)
    if window.shape[0] != W52_BARS or not np.isfinite(window).all():
        return None
    hits = np.flatnonzero(window == float(window.max()))
    if len(hits) == 0:
        return None
    return int(window.shape[0] - 1 - hits[-1])


def _w52_lookup(table, ticker, col):
    if table is None or ticker not in table.index or col not in table.columns:
        return None
    return table.at[ticker, col]


def scan_52w(close, high, low, vol, universe, scores=None):
    """One row per ticker, plus a daily highs/lows count backfilled from the same bars.

    No network. Names without a bar are skipped. A flag is yes only on the latest
    panel session, and only when 252 prior sessions exist. The history file keeps
    every such session, which is more than a year when the cache holds about five.
    """
    if close is None or len(getattr(close, "index", [])) == 0 or universe is None or len(universe) == 0:
        return pd.DataFrame(), pd.DataFrame()
    if "ticker" not in getattr(universe, "columns", []):
        return pd.DataFrame(), pd.DataFrame()
    names = []
    seen = set()
    for raw in universe["ticker"].tolist():
        ticker = str(raw).strip()
        if not ticker or ticker in seen or ticker not in close.columns:
            continue
        seen.add(ticker)
        names.append(ticker)
    if not names:
        return pd.DataFrame(), pd.DataFrame()
    panel = _panel_date(close)
    panel_ts = None if panel is None else pd.Timestamp(panel)
    if getattr(panel_ts, "tzinfo", None) is not None:
        panel_ts = panel_ts.tz_localize(None)
    if panel_ts is not None:
        panel_ts = panel_ts.normalize()
    score_idx = None
    if scores is not None and len(scores) and "ticker" in scores.columns:
        score_idx = scores.drop_duplicates("ticker", keep="last").set_index("ticker")
    hsrc = high if high is not None else close
    lsrc = low if low is not None else close
    note = w52_note()
    rows = []
    pieces = []
    for ticker in names:
        if ticker not in hsrc.columns or ticker not in lsrc.columns:
            continue
        if vol is not None and ticker in vol.columns:
            vol_s = vol[ticker]
        else:
            vol_s = np.nan
        frame = pd.DataFrame({
            "high": hsrc[ticker],
            "low": lsrc[ticker],
            "close": close[ticker],
            "volume": vol_s,
        })
        frame = frame.dropna(subset=["close", "high", "low"])
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        if panel_ts is not None and len(frame):
            frame = frame.loc[:panel_ts]
        if len(frame) == 0:
            continue
        stats = _w52_sessions(frame)
        ready = stats["ready"].to_numpy(dtype=bool)
        ranged_bars = np.isfinite(stats["high_52w"].to_numpy(dtype=float))
        keep = ready | ranged_bars
        if keep.any():
            piece = pd.DataFrame({
                "new_highs": np.where(ready, stats["new_high"].to_numpy(dtype=int), 0),
                "new_lows": np.where(ready, stats["new_low"].to_numpy(dtype=int), 0),
                "near_high_count": np.where(ranged_bars, stats["near"].to_numpy(dtype=int), 0),
            }, index=stats.index)
            piece = piece.loc[keep]
            piece.index.name = "date"
            pieces.append(piece)
        last = stats.iloc[-1]
        last_dt = pd.Timestamp(stats.index[-1])
        if getattr(last_dt, "tzinfo", None) is not None:
            last_dt = last_dt.tz_localize(None)
        on_panel = panel_ts is not None and last_dt.normalize() == panel_ts
        active = bool(on_panel and last["ready"])
        near_now = bool(on_panel and np.isfinite(last["high_52w"]) and last["near"])
        meta = _meta_row(universe, ticker)
        for col, key in (("company", "company"), ("sector", "sector"), ("index_membership", "index_membership")):
            if not meta.get(key):
                meta[key] = _w52_text(_w52_lookup(score_idx, ticker, col))
        score = _num(_w52_lookup(score_idx, ticker, "score"))
        verdict = _w52_text(_w52_lookup(score_idx, ticker, "verdict"))
        ranged = np.isfinite(last["high_52w"]) and np.isfinite(last["low_52w"])
        status = "OK" if active else "PARTIAL"
        rows.append({
            "ticker": ticker,
            "company": meta.get("company") or "",
            "sector": meta.get("sector") or "",
            "index_membership": meta.get("index_membership") or "",
            "price": _round(last["price"]),
            "price_as_of": last_dt.strftime("%Y-%m-%d"),
            "high_52w": _round(last["high_52w"]) if ranged else None,
            "low_52w": _round(last["low_52w"]) if ranged else None,
            "pct_from_high": _round(last["pct_from_high"]) if ranged else None,
            "pct_above_low": _round(last["pct_above_low"]) if ranged else None,
            "range_position_pct": _round(last["range_position_pct"]) if ranged else None,
            "new_high_today": "yes" if active and bool(last["new_high"]) else "no",
            "new_low_today": "yes" if active and bool(last["new_low"]) else "no",
            "near_high": "yes" if near_now else "no",
            "high_on_volume": "yes" if active and bool(last["high_on_volume"]) else "no",
            "volume_ratio": _round(last["volume_ratio"]) if _num(last["volume_ratio"]) is not None else None,
            "days_since_high": _days_since_high(frame["high"].to_numpy(dtype=float), len(frame) - 1) if ranged else None,
            "score": score,
            "verdict": verdict,
            "data_status": status,
            "note": note,
        })
    hist = _w52_history(pieces)
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out, hist
    out["_rp"] = pd.to_numeric(out["range_position_pct"], errors="coerce")
    out["_sc"] = pd.to_numeric(out["score"], errors="coerce")
    out = out.sort_values(["_rp", "_sc", "ticker"], ascending=[False, False, True], na_position="last")
    return out.drop(columns=["_rp", "_sc"]), hist


def _w52_history(pieces):
    if not pieces:
        return pd.DataFrame()
    cat = pd.concat(pieces)
    cat.index.name = "date"
    g = cat.groupby(level=0).sum()
    g = g.sort_index()
    g["net"] = g["new_highs"].astype(int) - g["new_lows"].astype(int)
    g["new_highs"] = g["new_highs"].astype(int)
    g["new_lows"] = g["new_lows"].astype(int)
    g["near_high_count"] = g["near_high_count"].astype(int)
    idx = pd.to_datetime(g.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    g = g.copy()
    g.insert(0, "date", idx.strftime("%Y-%m-%d"))
    g["data_status"] = "OK"
    g["note"] = (
        "Each session counts names with a full %d prior sessions. "
        "New highs and new lows use the close. Near high is within %g%% of the 252-session high. "
        "Net is new highs minus new lows. Built from the cached bars."
    ) % (W52_BARS, W52_NEAR_PCT)
    g = g.reset_index(drop=True)
    return g[["date", "new_highs", "new_lows", "near_high_count", "net", "data_status", "note"]]


def _ma_state(series):
    """Last close, 50-day average, and 200-day average. None when the window is short."""
    if series is None:
        return None
    s = pd.Series(series, dtype=float).dropna()
    if len(s) < 200:
        return None
    sma50 = float(s.rolling(50, min_periods=50).mean().iloc[-1])
    sma200 = float(s.rolling(200, min_periods=200).mean().iloc[-1])
    last = float(s.iloc[-1])
    if not (np.isfinite(sma50) and np.isfinite(sma200) and np.isfinite(last)):
        return None
    return last, sma50, sma200


def above_both_sma(series):
    """Close above the 50-day and the 200-day. A stock does not also need a golden cross."""
    state = _ma_state(series)
    if state is None:
        return False
    last, sma50, sma200 = state
    return bool(last > sma50 and last > sma200)


def uptrend(series):
    """Market uptrend: close above both averages, and the 50-day above the 200-day.

    Used for SPY, which decides the list, and for QQQ, which is display only.
    A series shorter than 200 sessions is not an uptrend.
    """
    state = _ma_state(series)
    if state is None:
        return False
    last, sma50, sma200 = state
    return bool(last > sma50 and last > sma200 and sma50 > sma200)


def buy_stop(entry, setup_stop):
    """Tighter of the 7% stop and the setup stop, when that stop is below the entry."""
    entry = _num(entry)
    if entry is None or entry <= 0:
        return None
    cap = entry * (1.0 - BUY_STOP_PCT / 100.0)
    own = _num(setup_stop)
    if own is not None and own < entry and own > cap:
        return own
    return cap


def buy_levels(entry, setup_stop, price, broken_out):
    """Stop, both targets, risk percent, and reward versus that risk.

    Target 1 is 20% above the entry. After a breakout it is 20% above the close.
    Target 2 is the entry plus three times the dollar risk.
    """
    entry = _num(entry)
    stop = buy_stop(entry, setup_stop)
    price = _num(price)
    if entry is None or stop is None or stop >= entry:
        return None
    risk = entry - stop
    risk_pct = risk / entry * 100.0
    if not (0 < risk_pct <= BUY_MAX_RISK_PCT):
        return None
    base = price if broken_out and price is not None else entry
    target1 = base * (1.0 + BUY_PART_PCT / 100.0)
    target2 = entry + BUY_TARGET2_R * risk
    reward = (target1 - entry) / risk
    return {
        "stop": stop,
        "target1": target1,
        "target2": target2,
        "risk_pct": risk_pct,
        "reward_risk": reward,
    }


def _yn_flag(flag):
    return "yes" if flag else "no"


def _setup_records(df, source):
    if df is None or len(getattr(df, "index", [])) == 0 or "ticker" not in getattr(df, "columns", []):
        return []
    rows = []
    for rec in df.to_dict("records"):
        status = str(rec.get("status") or "").strip()
        ticker = str(rec.get("ticker") or "").strip()
        if not ticker or status not in BUY_LIVE_STATUS:
            continue
        if str(rec.get("stop_check") or "").startswith("Too wide"):
            continue
        rows.append({
            "ticker": ticker,
            "source": source,
            "status": status,
            "pivot": _num(rec.get("pivot")),
            "stop": _num(rec.get("stop")),
            "strength": _num(rec.get("strength")),
            "company": _w52_text(rec.get("company")),
            "sector": _w52_text(rec.get("sector")),
            "index_membership": _w52_text(rec.get("index_membership")),
            "price": _num(rec.get("price")),
            "price_as_of": _w52_text(rec.get("price_as_of")),
        })
    return rows


def _buy_reason(sources, best, entry, broken_out):
    joined = " + ".join(sources)
    state = "broke out today" if broken_out else "is ready"
    if len(sources) > 1:
        state = "agree, and the strongest " + state
    base = "today's close" if broken_out else "the entry"
    return (
        "%s %s. Entry is the %s buy point at %s. Target 1 is 20%% above %s. "
        "The stop is shown because many breakouts fail."
    ) % (joined, state, best["source"], _round(entry), base)


def buy_rows_visible(df, market_filter):
    """Rows the page lists. The market switch hides them when SPY is not in an uptrend."""
    if df is None or len(df) == 0 or "ticker" not in df.columns:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    rows = df[df["ticker"].astype(str).str.strip() != ""].copy()
    if len(rows) == 0 or not market_filter:
        return rows
    ok = str(rows.iloc[0].get("market_ok") or "").strip().lower() == "yes"
    if ok:
        return rows
    return rows.iloc[0:0]


def _ep_buy_rows(ep):
    """Episodic Pivot rows with a buy_status: READY (EP TODAY - CONFIRMED and DAY 2-5 WATCH) or
    BROKEN OUT today (today's high crossed the EP-day high). Stop not too wide; faded and delayed rows stay out."""
    if ep is None or len(getattr(ep, "index", [])) == 0 or "buy_status" not in getattr(ep, "columns", []):
        return None
    rows = ep[ep["buy_status"].astype(str).isin(["READY", "BROKEN OUT today"])].copy()
    if len(rows) == 0:
        return None
    rows["status"] = rows["buy_status"].astype(str)
    rows["pivot"] = rows["entry"]
    return rows


def build_buy_setups(vcp, box, flag, canslim, scores, close=None, week=None, sma_ok=None, market=None,
                     qullamaggie=None, marios=None, ep=None):
    """Names that pass the stock rules. market_ok is SPY's uptrend, for the page filter.

    No network. Scanners, scores, the 52-week file, and the cached closes are the inputs.
    The market switch does not delete rows, so the page can show them greyed.
    """
    grouped = {}
    for source, frame in (("VCP", vcp), ("Box", box), ("Flag", flag), ("Qullamaggie", qullamaggie),
                          ("Marios", marios), ("EP", _ep_buy_rows(ep)), ("CANSLIM", canslim)):
        for rec in _setup_records(frame, source):
            grouped.setdefault(rec["ticker"], []).append(rec)
    score_idx = None
    if scores is not None and len(scores) and "ticker" in getattr(scores, "columns", []):
        score_idx = scores.drop_duplicates("ticker", keep="last").set_index("ticker")
    week_idx = None
    if week is not None and len(week) and "ticker" in getattr(week, "columns", []):
        week_idx = week.drop_duplicates("ticker", keep="last").set_index("ticker")
    if market is None:
        spy_ok = uptrend(close["SPY"]) if close is not None and "SPY" in getattr(close, "columns", []) else False
        qqq_ok = uptrend(close["QQQ"]) if close is not None and "QQQ" in getattr(close, "columns", []) else False
    else:
        spy_ok = bool(market.get("spy"))
        qqq_ok = bool(market.get("qqq"))
    market_ok = _yn_flag(spy_ok)
    qqq_flag = _yn_flag(qqq_ok)
    order = {name: i for i, name in enumerate(BUY_SETUP_ORDER)}
    rows = []
    for ticker, setups_for in grouped.items():
        verdict = _w52_text(_w52_lookup(score_idx, ticker, "verdict"))
        if verdict != "BUY":
            continue
        if sma_ok is not None:
            if not sma_ok.get(ticker):
                continue
            price = None
            price_as_of = ""
        else:
            price, price_as_of = _close_last(close, ticker)
            series = close[ticker] if close is not None and ticker in getattr(close, "columns", []) else None
            if price is None or not above_both_sma(series):
                continue
        usable = [rec for rec in setups_for if rec["pivot"] is not None and rec["pivot"] > 0]
        if not usable:
            continue
        usable.sort(key=lambda rec: (-(rec["strength"] if rec["strength"] is not None else -1), order[rec["source"]]))
        best = usable[0]
        if price is None:
            price = best["price"]
        if not price_as_of:
            price_as_of = best["price_as_of"]
        broken = best["status"] == "BROKEN OUT today"
        levels = buy_levels(best["pivot"], best["stop"], price, broken)
        if levels is None:
            continue
        sources = [
            name for name in BUY_SETUP_ORDER
            if any(rec["source"] == name and rec["pivot"] is not None and rec["pivot"] > 0 for rec in setups_for)
        ]
        meta_company = _w52_text(_w52_lookup(score_idx, ticker, "company")) or best["company"]
        meta_sector = _w52_text(_w52_lookup(score_idx, ticker, "sector")) or best["sector"]
        meta_index = _w52_text(_w52_lookup(score_idx, ticker, "index_membership")) or best["index_membership"]
        score = _num(_w52_lookup(score_idx, ticker, "score"))
        range_pos = _num(_w52_lookup(week_idx, ticker, "range_position_pct"))
        from_high = _num(_w52_lookup(week_idx, ticker, "pct_from_high"))
        dist = None if price is None else (price / best["pivot"] - 1.0) * 100.0
        dist_val = _round(dist)
        if dist_val == 0:
            dist_val = 0.0
        rows.append({
            "ticker": ticker,
            "company": meta_company,
            "sector": meta_sector,
            "index_membership": meta_index,
            "price": _round(price),
            "price_as_of": price_as_of,
            "setup_sources": " + ".join(sources),
            "sources_count": len(sources),
            "best_status": best["status"],
            "entry": _round(best["pivot"]),
            "stop": _round(levels["stop"]),
            "target1": _round(levels["target1"]),
            "target2": _round(levels["target2"]),
            "risk_pct": _round(levels["risk_pct"]),
            "reward_risk": _round(levels["reward_risk"]),
            "dist_to_entry_pct": dist_val,
            "score": score,
            "verdict": verdict,
            "range_position_52w": _round(range_pos) if range_pos is not None else None,
            "pct_from_high_52w": _round(from_high) if from_high is not None else None,
            "reason": _buy_reason(sources, best, best["pivot"], broken),
            "market_ok": market_ok,
            "spy_uptrend": market_ok,
            "qqq_uptrend": qqq_flag,
            "data_status": "OK",
            "note": "Research list, not a recommendation. This desk never places trades.",
        })
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return _buy_market_row(market_ok, qqq_flag)
    out["_status"] = out["best_status"].map(lambda s: 0 if s == "BROKEN OUT today" else 1)
    out["_dist"] = pd.to_numeric(out["dist_to_entry_pct"], errors="coerce").abs()
    out["_score"] = pd.to_numeric(out["score"], errors="coerce")
    out = out.sort_values(
        ["_status", "sources_count", "_dist", "_score", "ticker"],
        ascending=[True, False, True, False, True],
        na_position="last",
    )
    return out.drop(columns=["_status", "_dist", "_score"]).reset_index(drop=True)


def _close_last(close, ticker):
    if close is None or ticker not in getattr(close, "columns", []):
        return None, ""
    s = close[ticker].dropna()
    if len(s) == 0:
        return None, ""
    dt = pd.Timestamp(s.index[-1])
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_localize(None)
    return float(s.iloc[-1]), dt.strftime("%Y-%m-%d")


def _buy_market_row(market_ok, qqq_flag):
    """One row so the page can show SPY and QQQ when no stock passed."""
    return pd.DataFrame([{
        "ticker": "",
        "company": "",
        "sector": "",
        "index_membership": "",
        "price": None,
        "price_as_of": "",
        "setup_sources": "",
        "sources_count": None,
        "best_status": "",
        "entry": None,
        "stop": None,
        "target1": None,
        "target2": None,
        "risk_pct": None,
        "reward_risk": None,
        "dist_to_entry_pct": None,
        "score": None,
        "verdict": "",
        "range_position_52w": None,
        "pct_from_high_52w": None,
        "reason": "",
        "market_ok": market_ok,
        "spy_uptrend": market_ok,
        "qqq_uptrend": qqq_flag,
        "data_status": "OK",
        "note": "No names passed the buy-setup rules. Research list, not a recommendation. This desk never places trades.",
    }])


def build_setups(close, high, low, vol, universe, quarters, annual, holders, features, scores=None, cfg=None, opn=None):
    """Return the scanner frames. Each is empty when that switch is off."""
    features = features or {}
    want_v = features.get("scanner_vcp", True)
    want_c = features.get("scanner_canslim", True)
    want_b = features.get("scanner_box", True)
    want_f = features.get("scanner_flag", True)
    want_l = features.get("scanner_leaders", True)
    want_w = features.get("scanner_52w", True)
    want_bd = features.get("scanner_breakdown", True)
    want_hv = features.get("scanner_volume", True)
    want_q = features.get("scanner_qullamaggie", True)
    want_m = features.get("scanner_marios", True)
    vcp = scan_vcp(close, high, low, vol, universe) if (want_v or want_l) else pd.DataFrame()
    canslim, _market = scan_canslim(close, high, low, vol, universe, quarters, annual, holders) if (want_c or want_l) else (pd.DataFrame(), {})
    box = scan_box(close, high, low, vol, universe) if want_b else pd.DataFrame()
    breakdown = scan_breakdown(close, high, low, vol, universe) if want_bd else pd.DataFrame()
    flag = scan_flag(close, high, low, vol, universe) if want_f else pd.DataFrame()
    volume = scan_volume(close, high, low, vol, universe) if want_hv else pd.DataFrame()
    qull = scan_qullamaggie(close, high, low, vol, universe, cfg, opn=opn, scores=scores) if want_q else pd.DataFrame()
    mar = scan_marios(close, high, low, vol, universe, cfg, opn=opn, scores=scores) if want_m else pd.DataFrame()
    leaders = combine_leaders(vcp, canslim) if want_l else pd.DataFrame()
    if want_w:
        week, week_hist = scan_52w(close, high, low, vol, universe, scores)
    else:
        week, week_hist = pd.DataFrame(), pd.DataFrame()
    if not want_v:
        vcp = pd.DataFrame()
    if not want_c:
        canslim = pd.DataFrame()
    return {
        "scanner_vcp": vcp,
        "scanner_canslim": canslim,
        "scanner_box": box,
        "scanner_breakdown": breakdown,
        "scanner_flag": flag,
        "scanner_qullamaggie": qull,
        "scanner_marios": mar,
        "scanner_volume": volume,
        "scanner_leaders": leaders,
        "scanner_52w": week,
        "highs_lows_history": week_hist,
    }
