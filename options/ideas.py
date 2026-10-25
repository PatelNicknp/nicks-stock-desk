"""Build the call and put debit-spread lists.

Call names are the first 15 rows of the buy-setup list, including names the
market filter would grey out. Put names are the first 15 breakdowns, with
BROKEN DOWN today ahead of WATCHING. Chains are requested only for those
names, and only on a full run or inside the 10:30 and 3:30 ET windows.
"""
import datetime as dt
import math

import pandas as pd

from options.check import price_check
from options.sources import fetch_cboe, load_cached, parse_chain, risk_free, save_cached
from options.spreads import (
    MAX_IV_RV,
    MIN_AVG_VOLUME,
    MIN_PRICE,
    build_debit,
    exit_text,
    expiry_dates,
    pick_expiry,
    sizing_text,
)

CALL_CAP = 15
PUT_CAP = 15
PAUSE_SECONDS = 1.5
EDUCATION = "Education, not financial advice."
WINDOW_MINUTES = 45


def slot_label(now):
    """'YYYY-MM-DD-am' or '-pm' inside 45 minutes of 10:30 or 15:30. Else None."""
    minutes = now.hour * 60 + now.minute
    day = now.strftime("%Y-%m-%d")
    if abs(minutes - (10 * 60 + 30)) <= WINDOW_MINUTES:
        return day + "-am"
    if abs(minutes - (15 * 60 + 30)) <= WINDOW_MINUTES:
        return day + "-pm"
    return None


def should_fetch(mode, now, stamp):
    if mode == "offline":
        return False
    if mode == "full":
        return True
    if mode != "hourly":
        return False
    slot = slot_label(now)
    if not slot:
        return False
    return str(stamp or "") != slot


def realized_vol(close, n):
    s = pd.Series(close, dtype=float).dropna()
    if len(s) < 2:
        return None
    r = (s / s.shift(1)).apply(lambda x: math.log(x) if x and x > 0 else float("nan")).dropna().tail(n)
    if len(r) < n * 0.8:
        return None
    return float(r.std() * math.sqrt(252))


def _last(series):
    if series is None:
        return None
    s = pd.Series(series, dtype=float).dropna()
    if len(s) == 0:
        return None
    return float(s.iloc[-1])


def _sma(series, n):
    s = pd.Series(series, dtype=float).dropna()
    if len(s) < n:
        return None
    return float(s.tail(n).mean())


def _avg_volume(series, n=50):
    s = pd.Series(series, dtype=float).dropna().tail(n)
    if len(s) < int(n * 0.8):
        return None
    return float(s.mean())


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def _ticker(v):
    t = str(v or "").strip().upper()
    if not t or t == "NAN":
        return ""
    return t


def call_names(buy, cap=CALL_CAP):
    if buy is None or len(buy) == 0 or "ticker" not in getattr(buy, "columns", []):
        return []
    rows = []
    for _, r in buy.iterrows():
        if str(r.get("data_status") or "") == "MISSING":
            continue
        t = _ticker(r.get("ticker"))
        if not t:
            continue
        rows.append(r)
        if len(rows) >= cap:
            break
    return rows


def put_names(breakdown, cap=PUT_CAP):
    if breakdown is None or len(breakdown) == 0 or "ticker" not in getattr(breakdown, "columns", []):
        return []
    frame = breakdown
    if "status" in frame.columns:
        rank = {"BROKEN DOWN today": 0, "WATCHING": 1}
        frame = frame.copy()
        frame["_k"] = frame["status"].map(lambda s: rank.get(s, 9))
        if "strength" in frame.columns:
            frame = frame.sort_values(["_k", "strength"], ascending=[True, False])
        else:
            frame = frame.sort_values(["_k"])
    rows = []
    for _, r in frame.iterrows():
        if str(r.get("data_status") or "") == "MISSING":
            continue
        if str(r.get("status") or "") not in ("BROKEN DOWN today", "WATCHING"):
            continue
        if not _ticker(r.get("ticker")):
            continue
        rows.append(r)
        if len(rows) >= cap:
            break
    return rows


def _earnings_map(earnings):
    out = {}
    if earnings is None or len(getattr(earnings, "index", [])) == 0 or "ticker" not in earnings.columns:
        return out
    for _, r in earnings.iterrows():
        t = _ticker(r.get("ticker"))
        raw = str(r.get("next_earnings") or "").strip()
        if not t or not raw or raw.lower() == "nan":
            continue
        try:
            out[t] = dt.date.fromisoformat(raw[:10])
        except ValueError:
            continue
    return out


def _col(frame, ticker):
    if frame is None or ticker not in getattr(frame, "columns", []):
        return None
    return frame[ticker]


def _atm_iv(quotes, exp, S, T, r):
    from options.bs import implied_vol
    from options.spreads import mid_of
    near = []
    for kind in ("call", "put"):
        rows = [q for q in quotes if q.get("exp") == exp and q.get("kind") == kind]
        rows.sort(key=lambda q: abs(float(q["strike"]) - S))
        for q in rows[:2]:
            mid, _, ok = mid_of(q.get("bid"), q.get("ask"))
            if not ok:
                continue
            iv = implied_vol(mid, S, float(q["strike"]), T, r, kind)
            if iv:
                near.append(iv)
    if not near:
        return None
    near.sort()
    n = len(near)
    return near[n // 2] if n % 2 else 0.5 * (near[n // 2 - 1] + near[n // 2])


def _round(v, nd=2):
    x = _num(v)
    if x is None:
        return ""
    return round(x, nd)


def _skip(ticker, company, side, reason, market_ok="n/a"):
    return {
        "ticker": ticker,
        "company": company,
        "side": side,
        "reason": reason,
        "market_ok": market_ok or "n/a",
        "data_status": "OK",
        "note": EDUCATION,
    }


def _consider_one(spec, chain, rate, today, earn_on):
    """spec is a dict of inputs. Returns (idea or None, skip or None)."""
    ticker = spec["ticker"]
    company = spec.get("company") or ""
    side = spec["side"]
    market_ok = spec.get("market_ok") or "n/a"
    kind = "call" if side == "call" else "put"
    spot = spec.get("spot")
    if spot is None or spot < MIN_PRICE:
        why = "price under $10" if spot is not None and spot < MIN_PRICE else "no price history"
        if spot is not None and spot < MIN_PRICE:
            why = "price under $10"
        elif spot is None:
            why = "no price history"
        return None, _skip(ticker, company, side, why, market_ok)
    avg = spec.get("avg_volume")
    if avg is None:
        return None, _skip(ticker, company, side, "not enough volume history", market_ok)
    if avg < MIN_AVG_VOLUME:
        return None, _skip(ticker, company, side, "average volume under 1 million", market_ok)
    if not chain or not chain.get("quotes"):
        return None, _skip(ticker, company, side, "no option quotes", market_ok)
    chosen = pick_expiry(expiry_dates(chain["quotes"]), today)
    if not chosen:
        return None, _skip(ticker, company, side, "no expiry in the 45 to 60 day window or the 30 to 75 day fallback", market_ok)
    exp, dte = chosen
    ed = earn_on.get(ticker)
    if ed is not None and today <= ed <= exp:
        return None, _skip(ticker, company, side, "earnings on %s fall before expiry" % ed.isoformat(), market_ok)
    T = dte / 365.0
    exp_s = exp.isoformat()
    scoped = [q for q in chain["quotes"] if str(q.get("exp"))[:10] == exp_s]
    rv20 = spec.get("rv20")
    rv60 = spec.get("rv60")
    atm = _atm_iv(scoped, exp_s, spot, T, rate)
    if atm is None:
        return None, _skip(ticker, company, side, "could not read implied vol", market_ok)
    if rv20 and atm / rv20 > MAX_IV_RV:
        return None, _skip(ticker, company, side, "implied vol is more than 1.3 times the 20-day realized vol", market_ok)
    built, why = build_debit(scoped, kind, spot, T, rate, spec.get("target"), atm)
    if why or not built:
        return None, _skip(ticker, company, side, why or "no debit spread", market_ok)
    long_leg = built["long"]
    short_leg = built["short"]
    check = price_check(
        [(+1, long_leg["strike"], kind, long_leg["iv"]), (-1, short_leg["strike"], kind, short_leg["iv"])],
        spot, T, rate, built["debit"], atm, rv20, rv60,
    ) or {}
    math_ = built["math"]
    stop = spec.get("stop")
    sma50 = spec.get("sma50")
    direction = "Bullish" if kind == "call" else "Bearish"
    as_of = str(chain.get("as_of") or "")
    idea = {
        "ticker": ticker,
        "company": company,
        "setup": spec.get("setup") or "",
        "direction": direction,
        "strikes": "%s/%s" % (_fmt_k(long_leg["strike"]), _fmt_k(short_leg["strike"])),
        "expiry": exp_s,
        "dte": dte,
        "cost": _round(math_["cost"], 2),
        "max_profit": _round(math_["max_profit"], 2),
        "max_loss": _round(math_["max_loss"], 2),
        "breakeven": _round(math_["breakeven"], 2),
        "move_pct": _round(math_["move_pct"], 2),
        "price_check": check.get("label") or "",
        "price_score": "" if check.get("score") is None else int(check["score"]),
        "liquidity": built["grade"],
        "exit_plan": exit_text(kind, short_leg["strike"], stop, sma50),
        "sizing": sizing_text(math_["cost"]),
        "education": EDUCATION,
        "side": side,
        "long_strike": _round(long_leg["strike"], 2),
        "short_strike": _round(short_leg["strike"], 2),
        "debit": _round(built["debit"], 4),
        "spot": _round(spot, 2),
        "stop": "" if stop is None else _round(stop, 2),
        "sma50": "" if sma50 is None else _round(sma50, 2),
        "target": "" if spec.get("target") is None else _round(spec.get("target"), 2),
        "market_ok": spec.get("market_ok") or "n/a",
        "narrowed": "yes" if built["narrowed"] else "no",
        "quote_as_of": as_of,
        "price_as_of": spec.get("price_as_of") or "",
        "data_status": "OK",
        "note": "Delayed Cboe quotes%s. %s This desk never places a trade." % (
            (" as of " + as_of) if as_of else "", EDUCATION),
    }
    check_row = {
        "ticker": ticker,
        "side": side,
        "direction": direction,
        "setup": spec.get("setup") or "",
        "spot": round(spot, 4),
        "long_strike": round(long_leg["strike"], 4),
        "short_strike": round(short_leg["strike"], 4),
        "long_delta": round(long_leg["delta"], 4),
        "short_delta": round(short_leg["delta"], 4),
        "long_iv": round(long_leg["iv"], 4),
        "short_iv": round(short_leg["iv"], 4),
        "expiry": exp_s,
        "dte": dte,
        "debit": round(built["debit"], 4),
        "width": round(built["width"], 4),
        "debit_over_width": round(built["ratio"], 4),
        "cost": round(math_["cost"], 2),
        "max_profit": round(math_["max_profit"], 2),
        "max_loss": round(math_["max_loss"], 2),
        "breakeven": round(math_["breakeven"], 4),
        "move_pct": None if math_["move_pct"] is None else round(math_["move_pct"], 4),
        "iv_atm": round(atm, 4),
        "rv20": None if rv20 is None else round(rv20, 4),
        "rv60": None if rv60 is None else round(rv60, 4),
        "blend": None if check.get("blend") is None else round(check["blend"], 4),
        "iv_over_rv20": None if not rv20 else round(atm / rv20, 4),
        "price_ratio": None if check.get("ratio") is None else round(check["ratio"], 4),
        "price_check": check.get("label") or "",
        "price_score": check.get("score"),
        "long_oi": int(long_leg["oi"]),
        "short_oi": int(short_leg["oi"]),
        "long_bid": round(long_leg["bid"], 4),
        "long_ask": round(long_leg["ask"], 4),
        "short_bid": round(short_leg["bid"], 4),
        "short_ask": round(short_leg["ask"], 4),
        "liquidity": built["grade"],
        "risk_free": round(rate, 6),
        "quote_as_of": as_of,
        "narrowed": "yes" if built["narrowed"] else "no",
        "target": spec.get("target"),
        "stop": stop,
        "education": EDUCATION,
    }
    return (idea, check_row), None


def _fmt_k(k):
    if abs(k - round(k)) < 1e-6:
        return str(int(round(k)))
    text = "%.2f" % k
    return text.rstrip("0").rstrip(".")


def _spec_from_buy(row, close, vol):
    t = _ticker(row.get("ticker"))
    c = _col(close, t)
    v = _col(vol, t)
    spot = _last(c)
    return {
        "ticker": t,
        "company": row.get("company") or "",
        "side": "call",
        "setup": " ".join(p for p in (str(row.get("setup_sources") or ""), str(row.get("best_status") or "")) if p and p != "nan").strip(),
        "spot": spot if spot is not None else _num(row.get("price")),
        "avg_volume": _avg_volume(v) if v is not None else None,
        "rv20": realized_vol(c, 20) if c is not None else None,
        "rv60": realized_vol(c, 60) if c is not None else None,
        "sma50": _sma(c, 50) if c is not None else None,
        "target": _num(row.get("target1")),
        "stop": _num(row.get("stop")),
        "market_ok": str(row.get("market_ok") or "n/a"),
        "price_as_of": str(row.get("price_as_of") or ""),
    }


def _spec_from_break(row, close, vol):
    t = _ticker(row.get("ticker"))
    c = _col(close, t)
    v = _col(vol, t)
    spot = _last(c)
    if spot is None:
        spot = _num(row.get("price"))
    return {
        "ticker": t,
        "company": row.get("company") or "",
        "side": "put",
        "setup": str(row.get("status") or "Breakdown"),
        "spot": spot,
        "avg_volume": _avg_volume(v) if v is not None else None,
        "rv20": realized_vol(c, 20) if c is not None else None,
        "rv60": realized_vol(c, 60) if c is not None else None,
        "sma50": _sma(c, 50) if c is not None else None,
        "target": _num(row.get("target")),
        "stop": _num(row.get("pivot")),
        "market_ok": "n/a",
        "price_as_of": str(row.get("price_as_of") or ""),
    }


def _load_or_fetch(ticker, spot, today, cache_dir, do_fetch, fetch, sleep, pause, state):
    if not do_fetch:
        return load_cached(cache_dir, ticker), False
    if state["n"]:
        sleep(pause)
    state["n"] += 1
    raw = None
    try:
        raw = fetch(ticker)
    except Exception:
        raw = None
    parsed = parse_chain(raw, today, spot) if raw else None
    if parsed and parsed.get("quotes"):
        parsed["saved_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            save_cached(cache_dir, ticker, parsed)
        except OSError:
            pass
        state["fresh"].add(ticker)
        return parsed, True
    state["failed"].add(ticker)
    return load_cached(cache_dir, ticker), False


def publish(close, vol, buy, breakdown, earnings, cache_dir, mode, now, stamp,
            fetch=None, sleep=None, pause=PAUSE_SECONDS, today=None, rate=None):
    """Return ideas, skipped, check rows, and a log tuple (status, latest, note).

    Does not raise when a quote source fails. Offline never calls the network.
    """
    import time
    sleep = sleep or time.sleep
    fetch = fetch or fetch_cboe
    today = today or dt.datetime.now().date()
    now_naive = now
    do_fetch = should_fetch(mode, now_naive, stamp)
    if rate is None:
        if do_fetch:
            try:
                rate, rate_src, rate_asof = risk_free(cache_dir)
            except Exception:
                rate, rate_src, rate_asof = 0.04, "4% fallback", ""
        else:
            rate, rate_src, rate_asof = _rate_offline(cache_dir)
    else:
        rate = float(rate)
        rate_src, rate_asof = "given", ""

    calls = call_names(buy)
    puts = put_names(breakdown)
    specs = [_spec_from_buy(r, close, vol) for r in calls]
    seen = {s["ticker"] for s in specs}
    for r in puts:
        spec = _spec_from_break(r, close, vol)
        specs.append(spec)
        seen.add(spec["ticker"])
    earn_on = _earnings_map(earnings)
    state = {"n": 0, "fresh": set(), "failed": set()}
    chains = {}
    # One request per ticker, even when it is on both lists.
    order = []
    for spec in specs:
        if spec["ticker"] not in order:
            order.append(spec["ticker"])
    for ticker in order:
        spot = next(s["spot"] for s in specs if s["ticker"] == ticker)
        # A name that will be skipped for price or volume still should not
        # spend a request. Both sides are checked below.
        needs = [s for s in specs if s["ticker"] == ticker]
        if all(_pre_skip(s) for s in needs):
            chains[ticker] = None
            continue
        chain, fresh = _load_or_fetch(ticker, spot, today, cache_dir, do_fetch, fetch, sleep, pause, state)
        chains[ticker] = chain
    ideas = []
    checks = []
    skipped = []
    check_cols = [
        "ticker", "side", "direction", "setup", "spot", "long_strike", "short_strike",
        "long_delta", "short_delta", "long_iv", "short_iv", "expiry", "dte", "debit", "width",
        "debit_over_width", "cost", "max_profit", "max_loss", "breakeven", "move_pct",
        "iv_atm", "rv20", "rv60", "blend", "iv_over_rv20", "price_ratio", "price_check", "price_score",
        "long_oi", "short_oi", "long_bid", "long_ask", "short_bid", "short_ask", "liquidity",
        "risk_free", "quote_as_of", "narrowed", "target", "stop", "education",
    ]
    for spec in specs:
        try:
            got, skip = _consider_one(spec, chains.get(spec["ticker"]), rate, today, earn_on)
        except Exception as ex:
            got, skip = None, _skip(spec["ticker"], spec.get("company") or "", spec["side"], "no option quotes", spec.get("market_ok") or "n/a")
            _ = ex
        if skip:
            skipped.append(skip)
        elif got:
            idea, check_row = got
            ideas.append(idea)
            checks.append(check_row)
    note_bits = [
        "calls %d, puts %d, skipped %d" % (
            sum(1 for r in ideas if r["side"] == "call"),
            sum(1 for r in ideas if r["side"] == "put"),
            len(skipped),
        ),
        "rate %s" % rate_src,
    ]
    if mode == "offline":
        status = "OK"
        note_bits.append("offline, no new chain request")
    elif not do_fetch:
        status = "OK"
        note_bits.append("outside the 10:30 and 3:30 ET windows, used saved chains")
    elif state["failed"] and not state["fresh"]:
        status = "CACHED"
        note_bits.append("Cboe did not answer; kept the last good chains")
    elif state["failed"]:
        status = "CACHED"
        note_bits.append("kept the last good chain for %d names" % len(state["failed"]))
    else:
        status = "OK"
        note_bits.append("Cboe delayed quotes")
    if rate_asof:
        note_bits.append("Treasury as of %s" % rate_asof)
    note_bits.append(EDUCATION + " No broker.")
    new_stamp = stamp
    if do_fetch and state["fresh"]:
        new_stamp = slot_label(now_naive) or (today.isoformat() + "-full")
    latest = ""
    if ideas:
        latest = ideas[0].get("quote_as_of") or ""
    return (
        pd.DataFrame(ideas),
        pd.DataFrame(skipped),
        pd.DataFrame(checks, columns=check_cols if not checks else None),
        (status, latest, ". ".join(note_bits)),
        new_stamp,
    )


def _pre_skip(spec):
    spot = spec.get("spot")
    if spot is None or spot < MIN_PRICE:
        return True
    avg = spec.get("avg_volume")
    if avg is None or avg < MIN_AVG_VOLUME:
        return True
    return False


def _rate_offline(cache_dir):
    """Saved Treasury rate, or the 4% fallback. No network."""
    import os
    import json
    path = os.path.join(cache_dir, "treasury_3m.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
            return float(old["rate"]), str(old.get("source") or "saved Treasury rate"), str(old.get("as_of") or "")
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return 0.04, "4% fallback", ""
