"""Episodic Pivot (EP) scanner for the US desk. Research only: it never places a trade.

Original Qullamaggie / Stockbee rules on the desk's cached daily bars, earnings dates, SEC quarters,
and Yahoo profiles. No new downloads. Nick's own filters are switches in the episodic_pivot block, all off.

Sources (see the research note): Qullamaggie's blog posts on EPs (gap of 10%+, big early volume,
opening-range-high entry, stop at the day's low no wider than 1 to 1.5 ADR, sell 1/3 to 1/2 after 3 to 5 days,
breakeven, trail with the 10 or 20-day) and Stockbee's EP posts (volume 3x average, 5-day time stop,
delayed-reaction EPs that build a tight range after the news).
"""
import numpy as np
import pandas as pd

import setups
from setups import _num, _round, _sma

EP_DEFAULTS = {
    # Detection
    "gap_trigger": True,
    "gap_min_pct": 10.0,
    "sb_close_change_pct": 0.0,
    "rvol_filter": True,
    "rvol_min": 3.0,
    "rvol_avg_len": 50,
    "early_volume_test": True,
    "early_volume_min_x": 1.0,
    "early_volume_until": "11:15",
    "volume_curve": {"10:15": 0.20, "11:15": 0.33, "12:15": 0.43, "13:15": 0.52, "14:15": 0.62, "15:15": 0.75, "16:00": 1.0},
    "min_price": 1.0,
    "min_dollar_volume_50d": 3000000.0,
    "close_upper_half_for_confirm": True,
    "confirm_close_above_open": True,
    "adr_days": 20,
    "stop_width_check": True,
    "max_stop_adr_mult": 1.5,
    # Ranking and catalyst
    "neglect_rank": True,
    "neglect_a_max_63d_pct": 10.0,
    "neglect_a_max_126d_pct": 20.0,
    "neglect_b_max_63d_pct": 30.0,
    "first_ep_lookback": 126,
    "catalyst_check": True,
    "surprise_min_pct": 10.0,
    "growth_min_pct": 25.0,
    "analyst_neglect_max": 5,
    "small_cap_tag_usd": 10000000000.0,
    # Watch windows
    "display_cap_days": 60,
    "watch_days": 5,
    "delayed_watch_days": 20,
    "delayed_range_days": 5,
    "delayed_range_adr_mult": 1.5,
    "closed_keep_days": 10,
    # Exits
    "partial_day_min": 3,
    "partial_day_max": 5,
    "breakeven_after_partial": True,
    "trail_fast_adr_pct": 5.0,
    "trail_fast_ma": 10,
    "trail_slow_ma": 20,
    "trail_after_partial_only": True,
    # Stockbee time stop: a flag only. The trade stays IN TRADE.
    "time_stop_flag": True,
    "time_stop_days": 5,
    "time_stop_adr_mult": 1.0,
    "feed_buy_setups": True,
    # Nick's own filters. Each is a switch, off by default, with its number ready.
    "nick_gap_filter": False, "nick_gap_min_pct": 10.0,
    "nick_rvol_filter": False, "nick_rvol_min": 3.0,
    "nick_price_floor": False, "nick_min_price": 5.0,
    "nick_min_mcap": False, "nick_min_mcap_usd": 500000000.0,
    "nick_min_avg_volume": False, "nick_avg_volume_days": 30, "nick_min_avg_volume_shares": 500000,
    "nick_max_perf_3m": False, "nick_max_perf_3m_pct": 30.0,
    "nick_require_earnings": False,
    "nick_require_catalyst": False, "nick_min_catalyst_score": 2,
    "nick_require_flat_base": False, "nick_flat_base_grade": "A",
}

EP_STATUS_RANK = {
    "EP TODAY - FORMING": 0, "EP TODAY - CONFIRMED": 1, "DAY 2-5 WATCH": 2, "IN TRADE": 3,
    "DELAYED EP WATCH": 4, "EP FADED": 5, "CLOSED": 6,
}
EP_BUY_STATUSES = ("EP TODAY - CONFIRMED", "DAY 2-5 WATCH")
EP_BROKE_OUT = "BROKEN OUT today"
EP_NOTE = (
    "Episodic Pivot: a gap up of 10% or more on news, with volume at least 3 times normal. "
    "Daily bars only: the desk cannot see the pre-market or the opening range high, so the next-day level is the EP-day high "
    "and the stop is the EP-day low. Research only. This desk never places trades."
)
MANUAL_CHECK = "Guidance raised? Revenue beat? Non-earnings news? Check the news link by hand."
NO_FOLLOW_TEXT = "No follow-through: not up 1 normal day's move after %d sessions (Stockbee's time stop)."


def ep_cfg(cfg):
    out = dict(EP_DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("episodic_pivot") or {}).items() if not str(k).startswith("_")})
    return out


# ---------------------------------------------------------------- time helpers (no clock: callers pass now_et)
def _as_et(ts):
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("America/New_York")
    return ts.tz_convert("America/New_York")


def volume_share(now_et, curve):
    """Expected share of a full day's volume by now_et (ET), from the config curve. 1.0 after the close."""
    t = _as_et(now_et)
    minutes = t.hour * 60 + t.minute
    pts = []
    for key, val in (curve or {}).items():
        hh, mm = str(key).split(":")
        pts.append((int(hh) * 60 + int(mm), float(val)))
    pts.sort()
    if not pts:
        return 1.0
    share = pts[0][1]
    for m, val in pts:
        if minutes >= m:
            share = val
    return share


def in_early_window(now_et, until):
    """True before `until` (ET, "HH:MM"): the first hourly run, where the early volume test applies."""
    if now_et is None:
        return False
    t = _as_et(now_et)
    hh, mm = str(until).split(":")
    return t.hour * 60 + t.minute < int(hh) * 60 + int(mm)


def bar_is_partial(last_date, now_et):
    """True when the last bar is today's session and the market has not closed yet (before 16:00 ET)."""
    if now_et is None or last_date is None:
        return False
    t = _as_et(now_et)
    if pd.Timestamp(last_date).date() != t.date():
        return False
    return (t.hour, t.minute) < (16, 0) and (t.hour, t.minute) >= (9, 30)


# ---------------------------------------------------------------- catalyst inputs
def earnings_by_ticker(earnings):
    out = {}
    if earnings is None or len(earnings) == 0 or "earnings_dt" not in getattr(earnings, "columns", []):
        return out
    df = earnings.copy()
    df["_dt"] = pd.to_datetime(df["earnings_dt"], errors="coerce", utc=True)
    df = df.dropna(subset=["_dt"])
    df["_dt"] = df["_dt"].dt.tz_convert("America/New_York")
    for t, g in df.groupby(df["ticker"].astype(str)):
        out[t] = g.sort_values("_dt")
    return out


def link_earnings(rows, ep_date, prev_date):
    """The earnings report that explains a gap on ep_date: after the close on the prior session or before the
    close on ep_date. Returns (row or None, timing words)."""
    if rows is None or len(rows) == 0:
        return None, ""
    d = pd.Timestamp(ep_date).date()
    p = pd.Timestamp(prev_date).date() if prev_date is not None else None
    best = None
    for _, r in rows.iterrows():
        dt = r["_dt"]
        day = dt.date()
        mins = dt.hour * 60 + dt.minute
        timing = None
        if mins == 0 and day in (d, p):
            timing = "time not given"
        elif day == d and mins < 9 * 60 + 30:
            timing = "before open"
        elif day == d and mins < 16 * 60:
            timing = "during session"
        elif p is not None and day == p and mins >= 16 * 60:
            timing = "after close the day before"
        elif p is not None and p < day < d:
            timing = "between sessions"
        if timing:
            best = (r, timing)
    return best if best else (None, "")


def quarter_growth(quarters, ticker, before):
    """Last filed quarter (filed before `before`): EPS YoY %, revenue YoY %, and whether revenue growth sped up."""
    out = {"eps_yoy": None, "rev_yoy": None, "rev_accel": None}
    if quarters is None or len(quarters) == 0 or "ticker" not in quarters.columns:
        return out
    q = quarters[quarters["ticker"].astype(str) == ticker]
    if len(q) == 0 or "end" not in q.columns:
        return out
    q = q.copy()
    q["_end"] = pd.to_datetime(q["end"], errors="coerce")
    q["_filed"] = pd.to_datetime(q.get("filed"), errors="coerce") if "filed" in q.columns else q["_end"]
    q = q[q["_filed"] < pd.Timestamp(before)].dropna(subset=["_end"]).sort_values("_end")
    if len(q) == 0:
        return out

    def yoy(row, col):
        cur = _num(row.get(col))
        if cur is None:
            return None
        prior = q[(q["_end"] - row["_end"]).abs().sub(pd.Timedelta(days=365)).abs() <= pd.Timedelta(days=20)]
        prior = prior[prior["_end"] < row["_end"]]
        if len(prior) == 0:
            return None
        old = _num(prior.iloc[-1].get(col))
        if old is None or old == 0:
            return None
        return (cur - old) / abs(old) * 100.0

    last = q.iloc[-1]
    out["eps_yoy"] = yoy(last, "eps")
    out["rev_yoy"] = yoy(last, "revenue")
    if len(q) >= 2 and out["rev_yoy"] is not None:
        prev = yoy(q.iloc[-2], "revenue")
        if prev is not None:
            out["rev_accel"] = bool(out["rev_yoy"] > prev)
    return out


def _info_map(info):
    if info is None or len(info) == 0 or "ticker" not in info.columns:
        return {}
    return info.drop_duplicates("ticker", keep="last").set_index("ticker").to_dict("index")


# ---------------------------------------------------------------- bar logic
def _arrays(frame, p):
    o = frame["open"].to_numpy(dtype=float)
    h = frame["high"].to_numpy(dtype=float)
    l = frame["low"].to_numpy(dtype=float)
    c = frame["close"].to_numpy(dtype=float)
    v = frame["volume"].to_numpy(dtype=float)
    n = int(p["rvol_avg_len"])
    avg = pd.Series(v).rolling(n, min_periods=n).mean().shift(1).to_numpy()
    nd = int(p["nick_avg_volume_days"])
    avg30 = pd.Series(v).rolling(nd, min_periods=nd).mean().shift(1).to_numpy()
    dvol = pd.Series(c * v).rolling(n, min_periods=n).mean().shift(1).to_numpy()
    return {
        "o": o, "h": h, "l": l, "c": c, "v": v, "avg": avg, "avg30": avg30, "dvol": dvol,
        "adr": setups._adr_series(h, l, int(p["adr_days"])),
        "s10": _sma(c, 10), "s20": _sma(c, 20),
        "s_fast": _sma(c, int(p["trail_fast_ma"])), "s_slow": _sma(c, int(p["trail_slow_ma"])),
    }


def _gap(a, i):
    pc = a["c"][i - 1]
    if not (np.isfinite(pc) and pc > 0 and np.isfinite(a["o"][i])):
        return None, None
    chg = (a["c"][i] / pc - 1.0) * 100.0 if np.isfinite(a["c"][i]) else None
    return (a["o"][i] / pc - 1.0) * 100.0, chg


def _is_event(a, i, p, partial=False, share=1.0, early_window=False):
    """Gap (or Stockbee close move) and volume tests on bar i. Returns a dict or None."""
    if i < 1 or i >= len(a["c"]):
        return None
    gap, chg = _gap(a, i)
    if gap is None:
        return None
    sb = float(p["sb_close_change_pct"] or 0)
    moved = (bool(p["gap_trigger"]) and gap >= float(p["gap_min_pct"])) or (sb > 0 and chg is not None and chg >= sb)
    if not moved:
        return None
    avg = a["avg"][i]
    if not (np.isfinite(avg) and avg > 0):
        return None
    rvol_full = a["v"][i] / avg
    if partial:
        pace = a["v"][i] / (avg * max(share, 1e-6))
        early = bool(p["early_volume_test"]) and early_window and a["v"][i] >= float(p["early_volume_min_x"]) * avg
        if p["rvol_filter"] and not (pace >= float(p["rvol_min"]) or early):
            return None
        rvol, basis = pace, "pace so far today (volume so far vs %.0f%% of a normal day)" % (share * 100.0)
    else:
        if p["rvol_filter"] and rvol_full < float(p["rvol_min"]):
            return None
        rvol, basis = rvol_full, "full day vs the %d-day average" % int(p["rvol_avg_len"])
    rng = a["h"][i] - a["l"][i]
    dcr = (a["c"][i] - a["l"][i]) / rng * 100.0 if rng > 0 else 100.0
    if partial and a["c"][i] <= a["o"][i]:
        return None
    return {"i": i, "gap": gap, "chg": chg, "rvol": rvol, "rvol_basis": basis, "dcr": dcr}


def _gates(a, i, p, mcap, erow, ev=None, cat=None):
    """Liquidity floor plus Nick's switches, judged on the day before the EP. (passes, reason if not).

    cat: a callable that returns the catalyst score, used only when nick_require_catalyst is on."""
    e = i - 1
    px = a["c"][e]
    if not (np.isfinite(px) and px >= float(p["min_price"])):
        return False, "price"
    dv = a["dvol"][i]
    if float(p["min_dollar_volume_50d"]) > 0 and not (np.isfinite(dv) and dv >= float(p["min_dollar_volume_50d"])):
        return False, "dollar volume"
    if p["nick_gap_filter"] and not (ev is not None and ev["gap"] is not None and ev["gap"] >= float(p["nick_gap_min_pct"])):
        return False, "Nick gap"
    if p["nick_rvol_filter"] and not (ev is not None and ev["rvol"] is not None and ev["rvol"] >= float(p["nick_rvol_min"])):
        return False, "Nick volume"
    if p["nick_price_floor"] and not px >= float(p["nick_min_price"]):
        return False, "Nick price"
    if p["nick_min_mcap"] and not (mcap is not None and mcap >= float(p["nick_min_mcap_usd"])):
        return False, "Nick market cap"
    if p["nick_min_avg_volume"] and not (np.isfinite(a["avg30"][i]) and a["avg30"][i] >= float(p["nick_min_avg_volume_shares"])):
        return False, "Nick average volume"
    if p["nick_max_perf_3m"]:
        r63 = _ret(a, e, 63)
        if r63 is None or r63 > float(p["nick_max_perf_3m_pct"]):
            return False, "Nick 3-month run"
    if p["nick_require_earnings"] and erow is None:
        return False, "Nick earnings only"
    if p["nick_require_catalyst"]:
        score = cat() if cat is not None else None
        if score is None or score < int(p["nick_min_catalyst_score"]):
            return False, "Nick catalyst score"
    if p["nick_require_flat_base"]:
        grade = _neglect(a, i, p)["neglect_grade"]
        if not (grade and grade <= str(p["nick_flat_base_grade"]).upper()):
            return False, "Nick flat base"
    return True, ""


def _ret(a, e, bars):
    if e - bars < 0:
        return None
    a0, a1 = a["c"][e - bars], a["c"][e]
    if not (np.isfinite(a0) and np.isfinite(a1) and a0 > 0):
        return None
    return (a1 / a0 - 1.0) * 100.0


def _neglect(a, i, p=None):
    e = i - 1
    r63, r126 = _ret(a, e, 63), _ret(a, e, 126)
    lo = max(0, i - 126)
    hh, ll = np.nanmax(a["h"][lo:i]), np.nanmin(a["l"][lo:i])
    base = (hh - ll) / ll * 100.0 if ll > 0 else None
    p = p or EP_DEFAULTS
    if r63 is not None and r126 is not None and r63 <= float(p["neglect_a_max_63d_pct"]) and r126 <= float(p["neglect_a_max_126d_pct"]):
        grade = "A"
    elif r63 is not None and r63 <= float(p["neglect_b_max_63d_pct"]):
        grade = "B"
    elif r63 is not None:
        grade = "C"
    else:
        grade = ""
    return {"ret_63d_prior": r63, "ret_126d_prior": r126, "base_range_pct": base, "neglect_grade": grade}


def _first_ep(a, i, p):
    lo = max(1, i - int(p["first_ep_lookback"]))
    for k in range(lo, i):
        gap, _ = _gap(a, k)
        avg = a["avg"][k]
        if gap is not None and gap >= float(p["gap_min_pct"]) and np.isfinite(avg) and avg > 0 and a["v"][k] / avg >= float(p["rvol_min"]):
            return False
    return True


def _confirmed(a, ev, p):
    i = ev["i"]
    ok_open = a["c"][i] >= a["o"][i] if p["confirm_close_above_open"] else True
    ok_half = ev["dcr"] >= 50.0 if p["close_upper_half_for_confirm"] else True
    return bool(ok_open and ok_half)


def _tight_range(a, j, e, p, adr_px):
    """Tight range of the `delayed_range_days` bars before j (all after the EP day). (high, low) or None."""
    d = int(p["delayed_range_days"])
    s = j - d
    if s <= e or adr_px is None:
        return None
    hh, ll = float(np.nanmax(a["h"][s:j])), float(np.nanmin(a["l"][s:j]))
    if hh - ll <= float(p["delayed_range_adr_mult"]) * adr_px:
        return hh, ll
    return None


def _simulate_trade(a, k, fill, stop, adr_pct, p):
    """Bar-by-bar from the bar after the trigger. Partial on day 3-5, breakeven, trail, and the Stockbee time stop flag.

    The time stop never closes the trade: after time_stop_days sessions, a best close still under
    fill x (1 + time_stop_adr_mult ADR) sets no_follow and the signal NO FOLLOW-THROUGH."""
    c, h, l = a["c"], a["h"], a["l"]
    fast = adr_pct is not None and adr_pct >= float(p["trail_fast_adr_pct"])
    n_ma = int(p["trail_fast_ma"]) if fast else int(p["trail_slow_ma"])
    sma = a["s_fast"] if fast else a["s_slow"]
    word = "%d-day" % n_ma
    partial, be = None, False
    best_close = float(c[k])
    for j in range(k + 1, len(c)):
        if l[j] <= stop:
            return dict(status="CLOSED", exit_bar=j, exit_price=float(min(a["o"][j], stop)) if np.isfinite(a["o"][j]) else float(stop),
                        exit_reason="breakeven stop" if be else "stop at the EP-day low", signal="SELL",
                        partial_bar=partial, stop_now=stop, trail_word=word, trail_arr=sma, no_follow=False)
        days = j - k
        active = partial is not None or not p["trail_after_partial_only"]
        if active and np.isfinite(sma[j]) and c[j] < sma[j]:
            return dict(status="CLOSED", exit_bar=j, exit_price=float(c[j]), exit_reason="first close under the %s average" % word,
                        signal="SELL", partial_bar=partial, stop_now=stop, trail_word=word, trail_arr=sma, no_follow=False)
        best_close = max(best_close, float(c[j]))
        if partial is None and days >= int(p["partial_day_min"]):
            partial = j
            if p["breakeven_after_partial"]:
                stop = max(stop, fill)
                be = True
    t = len(c) - 1
    days_t = t - k
    no_follow = False
    if p["time_stop_flag"] and days_t >= int(p["time_stop_days"]) and adr_pct:
        no_follow = bool(best_close < fill * (1.0 + float(p["time_stop_adr_mult"]) * adr_pct / 100.0))
    if partial is not None and int(p["partial_day_min"]) <= days_t <= int(p["partial_day_max"]):
        sig = "SELL PART"
    elif no_follow:
        sig = "NO FOLLOW-THROUGH"
    else:
        sig = "HOLD"
    return dict(status="IN TRADE", exit_bar=None, exit_price=None, exit_reason="", signal=sig,
                partial_bar=partial, stop_now=stop, trail_word=word, trail_arr=sma, no_follow=no_follow)


def _lifecycle(a, ev, p, confirmed):
    """What happened after a completed EP bar e, up to today. Returns a dict with status and levels."""
    e = ev["i"]
    t = len(a["c"]) - 1
    adr_pct = a["adr"][e - 1] if e >= 1 and np.isfinite(a["adr"][e - 1]) else None
    entry, stop = float(a["h"][e]), float(a["l"][e])
    out = {"entry": entry, "stop": stop, "entry_basis": "EP-day high", "stop_basis": "EP-day low", "adr_pct": adr_pct,
           "trigger_bar": None, "delayed": False}
    if e == t:
        out["status"] = "EP TODAY - CONFIRMED" if confirmed else "EP FADED"
        return out
    for j in range(e + 1, t + 1):
        d = j - e
        fresh_entry, fresh_stop, kind = None, None, None
        if confirmed and d <= int(p["watch_days"]):
            fresh_entry, fresh_stop, kind = entry, stop, "day 2-5"
        elif d <= int(p["delayed_watch_days"]):
            adr_px = a["c"][j - 1] * adr_pct / 100.0 if adr_pct else None
            rng = _tight_range(a, j, e, p, adr_px)
            if rng is not None:
                fresh_entry, fresh_stop, kind = rng[0], rng[1], "delayed"
        if fresh_entry is not None and a["h"][j] > fresh_entry:
            fill = max(float(a["o"][j]), fresh_entry) if np.isfinite(a["o"][j]) else fresh_entry
            sim = _simulate_trade(a, j, fill, fresh_stop, adr_pct, p)
            out.update(sim)
            out.update({"trigger_bar": j, "fill": fill, "entry": fresh_entry, "stop_entry": fresh_stop,
                        "delayed": kind == "delayed",
                        "entry_basis": "EP-day high" if kind == "day 2-5" else "tight-range high after the EP",
                        "stop_basis": "EP-day low" if kind == "day 2-5" else "tight-range low"})
            return out
        if a["c"][j] < stop:
            out.update({"status": "CLOSED", "exit_bar": j, "exit_price": float(a["c"][j]),
                        "exit_reason": "closed under the EP-day low before it triggered", "signal": ""})
            return out
        if d > int(p["delayed_watch_days"]):
            out.update({"status": "CLOSED", "exit_bar": j, "exit_price": None,
                        "exit_reason": "%d sessions without a trigger" % int(p["delayed_watch_days"]), "signal": ""})
            return out
    d = t - e
    if confirmed and d <= int(p["watch_days"]):
        out["status"] = "DAY 2-5 WATCH"
        return out
    adr_px = a["c"][t] * adr_pct / 100.0 if adr_pct else None
    rng = _tight_range(a, t + 1, e, p, adr_px)
    if rng is not None:
        out.update({"status": "DELAYED EP WATCH", "entry": rng[0], "stop": rng[1], "delayed": True,
                    "entry_basis": "tight-range high after the EP", "stop_basis": "tight-range low"})
    elif confirmed:
        out.update({"status": "DELAYED EP WATCH", "entry": None, "stop": stop, "delayed": True,
                    "entry_basis": "waiting for a tight range", "stop_basis": "EP-day low"})
    else:
        out["status"] = "EP FADED"
    return out


# ---------------------------------------------------------------- the scan
def scan_ep(close, high, low, vol, opn, universe, cfg=None, earnings=None, quarters=None, info=None, now_et=None):
    """One row per stock with a live or recent EP. now_et (ET timestamp) only decides whether the last bar is
    still forming; pass None after the close or in tests that use completed bars."""
    p = ep_cfg(cfg)
    names = list(universe["ticker"]) if universe is not None and len(universe) else []
    if close is None or len(close) == 0 or opn is None:
        return pd.DataFrame()
    panel = setups._panel_date(close)
    earn = earnings_by_ticker(earnings)
    imap = _info_map(info)
    share = volume_share(now_et, p["volume_curve"]) if now_et is not None else 1.0
    early_window = in_early_window(now_et, p["early_volume_until"])
    rows = []
    for ticker in names:
        if ticker not in close.columns or ticker not in getattr(opn, "columns", []):
            continue
        frame = pd.DataFrame({
            "open": opn[ticker],
            "close": close[ticker],
            "high": high[ticker] if ticker in high.columns else np.nan,
            "low": low[ticker] if ticker in low.columns else np.nan,
            "volume": vol[ticker] if ticker in vol.columns else np.nan,
        }).dropna(subset=["close", "high", "low"])
        n = len(frame)
        need = int(p["rvol_avg_len"]) + 2
        if n < need:
            continue
        a = _arrays(frame, p)
        t = n - 1
        partial = bar_is_partial(frame.index[-1], now_et)
        lo = max(1, t - int(p["display_cap_days"]))
        meta = imap.get(ticker, {})
        mcap = _num(meta.get("market_cap"))
        row = None
        for i in range(t, lo - 1, -1):
            is_today = i == t
            ev = _is_event(a, i, p, partial=partial and is_today, share=share, early_window=early_window)
            if ev is None:
                continue
            prev_date = frame.index[i - 1]
            if p["catalyst_check"]:
                erow, timing = link_earnings(earn.get(ticker), frame.index[i], prev_date)
            else:
                erow, timing = None, ""
            ep_day = frame.index[i]
            ok, _why = _gates(a, i, p, mcap, erow, ev,
                              cat=lambda erow=erow, ep_day=ep_day: catalyst_score(erow, quarter_growth(quarters, ticker, ep_day), p))
            if not ok:
                continue
            # The newest EP that passes decides the row. A CLOSED one older than closed_keep_days shows nothing.
            row = _build_row(a, frame, ev, p, partial and is_today, erow, timing, quarters, ticker, meta, mcap)
            break
        if row is None:
            continue
        um = setups._meta_row(universe, ticker)
        row.update({
            "ticker": ticker, "company": um["company"] or meta.get("company") or "", "sector": um["sector"],
            "index_membership": um["index_membership"],
            "freshness": setups._freshness(frame.index[-1], panel, n, need),
            "price": _round(a["c"][t]), "price_as_of": str(pd.Timestamp(frame.index[-1]).date()),
            "data_status": "OK", "note": EP_NOTE,
            "trail10": _round(a["s10"][t]), "trail20": _round(a["s20"][t]),
            "news_link": "https://finance.yahoo.com/quote/%s/news" % ticker,
        })
        rows.append(row)
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    out["_k"] = out["status"].map(EP_STATUS_RANK).fillna(9)
    out["_g"] = out["neglect_grade"].map({"A": 0, "B": 1, "C": 2}).fillna(3) if p["neglect_rank"] else 0
    out["_r"] = pd.to_numeric(out["rvol"], errors="coerce").fillna(0)
    return out.sort_values(["_k", "_g", "_r"], ascending=[True, True, False]).drop(columns=["_k", "_g", "_r"]).reset_index(drop=True)


def _build_row(a, frame, ev, p, forming, erow, timing, quarters, ticker, meta, mcap):
    i = ev["i"]
    t = len(a["c"]) - 1
    ep_date = pd.Timestamp(frame.index[i])
    neg = _neglect(a, i, p)
    adr_pre = a["adr"][i - 1] if np.isfinite(a["adr"][i - 1]) else None
    surprise = _num(erow.get("surprise_pct")) if erow is not None else None
    eps_a = _num(erow.get("eps_actual")) if erow is not None else None
    eps_e = _num(erow.get("eps_estimate")) if erow is not None else None
    if p["catalyst_check"]:
        growth = quarter_growth(quarters, ticker, ep_date)
        pts = catalyst_score(erow, growth, p)
    else:
        growth = {"eps_yoy": None, "rev_yoy": None, "rev_accel": None}
        pts = None
    analysts = _num(meta.get("analyst_count"))
    row = {
        "ep_date": str(ep_date.date()), "days_since_ep": t - i,
        "catalyst_tag": "Earnings EP" if erow is not None else "Non-earnings - check news",
        "report_timing": timing,
        "gap_pct": _round(ev["gap"], 1), "change_pct": _round(ev["chg"], 1),
        "volume": _round(a["v"][i], 0), "avg_volume_50": _round(a["avg"][i], 0),
        "rvol": _round(ev["rvol"], 2), "rvol_basis": ev["rvol_basis"], "dcr_pct": _round(ev["dcr"], 0),
        "first_ep_6m": "yes" if _first_ep(a, i, p) else "no",
        "ret_63d_prior": _round(neg["ret_63d_prior"], 1), "ret_126d_prior": _round(neg["ret_126d_prior"], 1),
        "base_range_pct": _round(neg["base_range_pct"], 1), "neglect_grade": neg["neglect_grade"],
        "eps_actual": _round(eps_a, 2), "eps_estimate": _round(eps_e, 2),
        "surprise_pct": _round(surprise, 1) if surprise is not None else ("Pending, fills after 6:30 PM ET" if erow is not None else ""),
        "eps_yoy_last_filed": _round(growth["eps_yoy"], 1), "rev_yoy_last_filed": _round(growth["rev_yoy"], 1),
        "rev_accel": "" if growth["rev_accel"] is None else ("yes" if growth["rev_accel"] else "no"),
        "analyst_count": _round(analysts, 0), "catalyst_score": "" if pts is None else pts, "manual_check": MANUAL_CHECK,
        "market_cap": _round(mcap, 0),
        "small_young_tag": ("under $%dB" % int(float(p["small_cap_tag_usd"]) / 1e9)) if mcap is not None and mcap < float(p["small_cap_tag_usd"]) else "",
        "adr_pct": _round(adr_pre, 2),
        "partial_window": "", "trail_with": "", "trail_level": "", "signal": "", "result_pct": "",
        "fill": "", "trigger_date": "", "days_in_trade": "", "exit_reason": "", "exit_date": "", "exit_price": "",
        "buy_status": "",
    }
    if forming:
        entry, stop = float(a["h"][t]), float(a["l"][t])
        row.update({"status": "EP TODAY - FORMING", "entry": entry, "stop": stop,
                    "entry_basis": "day high so far; read the opening range high on your chart",
                    "stop_basis": "today's low so far"})
        life = {"status": "EP TODAY - FORMING", "adr_pct": adr_pre}
    else:
        life = _lifecycle(a, ev, p, _confirmed(a, ev, p))
        row.update({"status": life["status"], "entry": life.get("entry"), "stop": life.get("stop"),
                    "entry_basis": life.get("entry_basis", ""), "stop_basis": life.get("stop_basis", "")})
    if row["status"] == "CLOSED":
        xb = life.get("exit_bar")
        if xb is not None and t - xb > int(p["closed_keep_days"]):
            return None
    entry, stop = _num(row["entry"]), _num(row["stop"])
    if life.get("trigger_bar") is not None:
        k = life["trigger_bar"]
        fill = life["fill"]
        stop0 = life["stop_entry"]
        row.update({"fill": _round(fill), "trigger_date": str(pd.Timestamp(frame.index[k]).date()),
                    "trail_with": life["trail_word"], "trail_level": _round(life["trail_arr"][t]),
                    "signal": life.get("signal", ""), "stop": _round(life["stop_now"]),
                    "stop_basis": "breakeven" if life["stop_now"] > stop0 else row["stop_basis"]})
        entry, stop = fill, stop0
        if life["status"] == "CLOSED":
            xb = life["exit_bar"]
            row.update({"days_in_trade": xb - k, "exit_reason": life["exit_reason"],
                        "exit_date": str(pd.Timestamp(frame.index[xb]).date()), "exit_price": _round(life["exit_price"]),
                        "result_pct": _round((life["exit_price"] / fill - 1.0) * 100.0, 1) if life["exit_price"] else ""})
        else:
            dk = t - k
            row["days_in_trade"] = dk
            row["partial_window"] = ("Sell 1/3 to 1/2, move the stop to breakeven" if int(p["partial_day_min"]) <= dk <= int(p["partial_day_max"])
                                     else ("taken" if life.get("partial_bar") is not None else "day 3 to 5"))
            row["result_pct"] = _round((a["c"][t] / fill - 1.0) * 100.0, 1)
    elif row["status"] == "CLOSED":
        xb = life.get("exit_bar")
        row.update({"exit_reason": life.get("exit_reason", ""), "exit_date": str(pd.Timestamp(frame.index[xb]).date()) if xb is not None else ""})
    risk = (entry - stop) / entry * 100.0 if entry and stop is not None and entry > stop else None
    rva = risk / adr_pre if risk is not None and adr_pre else None
    row.update({"entry": _round(row["entry"]), "stop": _round(row["stop"]),
                "pivot": _round(row["entry"]), "risk_pct": _round(risk, 1), "risk_vs_adr": _round(rva, 2)})
    too_wide = bool(p["stop_width_check"]) and rva is not None and rva > float(p["max_stop_adr_mult"])
    row["stop_check"] = "Too wide, skip" if too_wide else ("OK" if rva is not None else "")
    if p["feed_buy_setups"] and not too_wide and _num(row["entry"]) is not None:
        if row["status"] in EP_BUY_STATUSES:
            row["buy_status"] = "READY"
        elif (row["status"] == "IN TRADE" and life.get("trigger_bar") == t and not life.get("delayed")
              and life.get("entry_basis") == "EP-day high"):
            # Broke out today: today's high crossed the EP-day high (day 2 to 5). Delayed-range triggers stay out.
            row["buy_status"] = EP_BROKE_OUT
    row["strength"] = _strength(row, ev, p)
    row["reason"] = _reason(row, ev, p, forming, life)
    return row


def _strength(row, ev, p):
    pts = min(ev["rvol"] / 10.0, 1.0) * 30.0 + min(max(ev["gap"], 0) / 30.0, 1.0) * 20.0
    pts += {"A": 20.0, "B": 10.0}.get(row["neglect_grade"], 0.0)
    pts += (_num(row["catalyst_score"]) or 0) * 5.0
    pts += 10.0 if ev["dcr"] >= 50 else 0.0
    return round(min(pts, 100.0), 1)


def _reason(row, ev, p, forming, life):
    bits = []
    move = "Gapped up %.1f%%" % ev["gap"]
    if row["catalyst_tag"] == "Earnings EP":
        move += " after earnings (reported %s)" % row["report_timing"]
    else:
        move += " with no earnings report linked; check the news for the reason"
    bits.append(move + " on %s." % row["ep_date"])
    bits.append("Volume is %.1fx normal (%s)." % (ev["rvol"], row["rvol_basis"]))
    s = _num(row["surprise_pct"])
    if s is not None:
        bits.append("EPS %s the estimate by %.0f%%." % ("beat" if s >= 0 else "missed", abs(s)))
    elif row["catalyst_tag"] == "Earnings EP":
        bits.append("EPS result is pending; it fills after the 6:30 PM ET run.")
    grade = row["neglect_grade"]
    if grade:
        words = {"A": "flat or down for months (grade A)", "B": "up a little before the gap (grade B)", "C": "already ran more than 30% in 3 months (grade C)"}
        bits.append("Before the gap it was %s." % words[grade])
    ac = _num(row["analyst_count"])
    if ac is not None and ac <= float(p["analyst_neglect_max"]):
        bits.append("Only %d analysts follow it, a sign of neglect." % int(ac))
    st = row["status"]
    if st == "EP TODAY - FORMING":
        bits.append("Still forming today. Watch the opening range high on your chart. Stop is today's low so far at %s." % row["stop"])
    elif st == "EP TODAY - CONFIRMED":
        bits.append("Closed strong (%s). Next sessions: a move above the EP-day high %s; stop at the EP-day low %s." % (_confirm_words(p), row["entry"], row["stop"]))
    elif st == "EP FADED":
        bits.append("Faded: the close was %s. Not an entry. It is watched for a delayed EP for %d sessions." % (_fade_words(p), int(p["delayed_watch_days"])))
    elif st == "DAY 2-5 WATCH":
        bits.append("Day %d after the EP. Not yet above the EP-day high %s, and has not closed under the EP-day low %s." % (row["days_since_ep"] + 1, row["entry"], row["stop"]))
    elif st == "DELAYED EP WATCH":
        if _num(row["entry"]) is not None:
            bits.append("Delayed EP: held above the EP-day low and built a tight range. A move above %s is the trigger; stop at %s." % (row["entry"], row["stop"]))
        else:
            bits.append("Held above the EP-day low but has not built a tight range yet.")
    elif st == "IN TRADE":
        bits.append("Traded above %s on %s (fill %s). Day %s in the trade. Signal: %s." % (row["entry"], row["trigger_date"], row["fill"], row["days_in_trade"], row["signal"]))
        if row.get("buy_status") == EP_BROKE_OUT:
            bits.append("It broke out today above the EP-day high, so it is on Buy setups as broke out.")
        bits.append("Plan: sell 1/3 to 1/2 on day 3 to 5, move the stop to breakeven, then sell the rest on the first close under the %s average." % row["trail_with"])
        if life.get("no_follow"):
            bits.append(NO_FOLLOW_TEXT % int(p["time_stop_days"]))
    elif st == "CLOSED":
        bits.append("CLOSED%s: %s." % ((" on " + row["exit_date"]) if row["exit_date"] else "", row["exit_reason"]))
    if _num(row["risk_vs_adr"]) is not None:
        bits.append("Risk %.1f%% = %.1fx its normal daily range%s." % (_num(row["risk_pct"]), _num(row["risk_vs_adr"]),
                                                                       ", too wide (over %sx), so it stays off Buy setups" % _fmt(p["max_stop_adr_mult"]) if row["stop_check"].startswith("Too wide") else ""))
    bits.append(MANUAL_CHECK)
    return " ".join(bits)


def _confirm_words(p):
    parts = []
    if p["close_upper_half_for_confirm"]:
        parts.append("top half of the day")
    if p["confirm_close_above_open"]:
        parts.append("at or above the open")
    return ", ".join(parts) if parts else "no close test"


def _fade_words(p):
    parts = []
    if p["close_upper_half_for_confirm"]:
        parts.append("in the lower half of the day")
    if p["confirm_close_above_open"]:
        parts.append("under the open")
    return " or ".join(parts) if parts else "weak"


def catalyst_score(erow, growth, p):
    """0 to 4: earnings linked to the EP day, EPS beat by surprise_min_pct, strong growth, revenue speeding up."""
    pts = 0
    if erow is not None:
        pts += 1
        surprise = _num(erow.get("surprise_pct"))
        if surprise is not None and surprise >= float(p["surprise_min_pct"]):
            pts += 1
    gmin = float(p["growth_min_pct"])
    if (growth["eps_yoy"] is not None and growth["eps_yoy"] >= gmin) or (growth["rev_yoy"] is not None and growth["rev_yoy"] >= gmin):
        pts += 1
    if growth["rev_accel"]:
        pts += 1
    return pts


def _fmt(x):
    x = float(x)
    return ("%d" % x) if x == int(x) else str(x)


def ep_buy_frame(ep):
    """EP rows that feed Buy setups, renamed to the shape the builder reads.

    READY: EP TODAY - CONFIRMED and DAY 2-5 WATCH. BROKEN OUT today: today's high crossed the EP-day high.
    Entry (pivot) is the EP-day high either way. Too wide, faded and delayed rows never carry a buy_status."""
    if ep is None or len(ep) == 0 or "buy_status" not in ep.columns:
        return pd.DataFrame()
    rows = ep[ep["buy_status"].astype(str).isin(["READY", EP_BROKE_OUT])].copy()
    if len(rows) == 0:
        return pd.DataFrame()
    rows["status"] = rows["buy_status"].astype(str)
    rows["pivot"] = rows["entry"]
    return rows
