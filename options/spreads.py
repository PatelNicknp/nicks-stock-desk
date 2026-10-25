"""Call and put debit spreads.

Expiry is 45 to 60 days, and 30 to 75 only when that window is empty.
The long leg is the strike whose absolute delta is inside 0.55 to 0.65
and closest to 0.60. The short leg is about 0.30 delta, or the listed
strike nearest the setup target when that target is closer to the spot
than the 0.30-delta strike is.

The debit must be at most 40% of the width. When it is wider, the long
strike walks toward the short strike, widest pair first, the same way
the mentor narrows a credit spread that does not fit. The first pair
that is at most 40% wide and passes the quote rules is the idea.
"""
import datetime as dt

from options.bs import delta as bs_delta
from options.bs import implied_vol

DTE_PRIMARY = (45, 60)
DTE_FALLBACK = (30, 75)
DTE_TARGET = 52
LONG_DELTA = 0.60
LONG_LO = 0.55
LONG_HI = 0.65
SHORT_DELTA = 0.30
MAX_DEBIT_RATIO = 0.40
MIN_OI = 500
MIN_PRICE = 10.0
MIN_AVG_VOLUME = 1_000_000.0
MAX_IV_RV = 1.3
# A quote under $1 is judged on the dollar width. At or above $1 it is a percent of the mid.
SPREAD_PCT = 0.10
SPREAD_DOLLAR = 0.10
GRADE_B_OI = 1500
GRADE_B_PCT = 0.06
GRADE_B_DOLLAR = 0.08
GRADE_A_OI = 5000
GRADE_A_PCT = 0.03
GRADE_A_DOLLAR = 0.05
BREAK_VOL_MULT = 1.4


def pick_expiry(dates, today):
    """dates are datetime.date. Returns (date, dte) or None."""
    def best(lo, hi):
        chosen = None
        for exp in dates:
            dte = (exp - today).days
            if lo <= dte <= hi and (chosen is None or abs(dte - DTE_TARGET) < abs(chosen[1] - DTE_TARGET)):
                chosen = (exp, dte)
        return chosen
    return best(*DTE_PRIMARY) or best(*DTE_FALLBACK)


def mid_of(bid, ask):
    """Return (mid, spread_pct, two_sided). A one-sided quote is not usable."""
    try:
        b = float(bid or 0)
        a = float(ask or 0)
    except (TypeError, ValueError):
        return None, None, False
    if b > 0 and a >= b:
        mid = (a + b) / 2.0
        if mid <= 0:
            return None, None, False
        return mid, (a - b) / mid, True
    return None, None, False


def quote_ok(bid, ask, mid, pct, dollars):
    if mid is None or mid <= 0:
        return False
    try:
        b = float(bid or 0)
        a = float(ask or 0)
    except (TypeError, ValueError):
        return False
    if b <= 0 or a < b:
        return False
    gap = a - b
    if mid < 1.0:
        return gap <= dollars + 1e-9
    return gap / mid <= pct + 1e-9


def liquidity_reason(long_leg, short_leg):
    """One plain reason, or '' when both legs pass."""
    if int(long_leg.get("oi") or 0) < MIN_OI or int(short_leg.get("oi") or 0) < MIN_OI:
        return "open interest under 500"
    for leg in (long_leg, short_leg):
        if not quote_ok(leg.get("bid"), leg.get("ask"), leg.get("mid"), SPREAD_PCT, SPREAD_DOLLAR):
            return "bid-ask is wide"
    return ""


def _grade_leg(leg):
    oi = int(leg.get("oi") or 0)
    if oi >= GRADE_A_OI and quote_ok(leg.get("bid"), leg.get("ask"), leg.get("mid"), GRADE_A_PCT, GRADE_A_DOLLAR):
        return "A"
    if oi >= GRADE_B_OI and quote_ok(leg.get("bid"), leg.get("ask"), leg.get("mid"), GRADE_B_PCT, GRADE_B_DOLLAR):
        return "B"
    return "C"


def liquidity_grade(long_leg, short_leg):
    """Worst leg wins. A is tighter than B, and B is tighter than C."""
    return max(_grade_leg(long_leg), _grade_leg(short_leg))


def spread_math(kind, long_strike, short_strike, debit, spot):
    """Per-contract dollars, plus the percent move from spot to breakeven."""
    width = abs(float(short_strike) - float(long_strike))
    debit = float(debit)
    if kind == "call":
        breakeven = float(long_strike) + debit
        move = (breakeven - spot) / spot * 100.0 if spot else None
    else:
        breakeven = float(long_strike) - debit
        move = (spot - breakeven) / spot * 100.0 if spot else None
    return {
        "width": width,
        "debit": debit,
        "ratio": (debit / width) if width else None,
        "cost": debit * 100.0,
        "max_profit": (width - debit) * 100.0,
        "max_loss": debit * 100.0,
        "breakeven": breakeven,
        "move_pct": move,
    }


def sizing_text(cost):
    """Contracts at 2% and at 5% of a $2k, $5k, and $10k account."""
    cost = float(cost or 0)
    bits = []
    for acct, label in ((2000, "$2k"), (5000, "$5k"), (10000, "$10k")):
        if cost <= 0:
            lo = hi = 0
        else:
            lo = int(acct * 0.02 // cost)
            hi = int(acct * 0.05 // cost)
        bits.append("%s: %d to %d" % (label, lo, hi))
    return "; ".join(bits)


def exit_text(kind, short_strike, stop, sma50):
    take = "Take profit at +100%% of the debit, or when the stock reaches the short strike at %s." % _num(short_strike)
    close = "Close the spread by 21 days to expiry."
    if kind == "call":
        stop_bit = "Stop if the close is below the setup stop at %s" % _num(stop)
        if sma50:
            stop_bit += " or below the 50-day average at %s" % _num(sma50)
        stop_bit += "."
    else:
        stop_bit = "Stop if the close is back above the breakdown level at %s." % _num(stop)
    return " ".join((take, stop_bit, close))


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return ("%.2f" % x).rstrip("0").rstrip(".")


def _decorate(quotes, kind, S, T, r):
    out = []
    for q in quotes:
        if q.get("kind") != kind:
            continue
        mid, sp, ok = mid_of(q.get("bid"), q.get("ask"))
        if not ok or mid is None:
            continue
        iv = implied_vol(mid, S, float(q["strike"]), T, r, kind)
        if iv is None or iv <= 0:
            continue
        d = abs(bs_delta(S, float(q["strike"]), T, r, iv, kind))
        out.append({
            "strike": float(q["strike"]),
            "bid": float(q.get("bid") or 0),
            "ask": float(q.get("ask") or 0),
            "mid": mid,
            "spread_pct": sp,
            "oi": int(q.get("oi") or 0),
            "iv": iv,
            "delta": d,
            "kind": kind,
        })
    return out


def _closest(rows, key, target):
    if not rows:
        return None
    return min(rows, key=lambda row: (abs(key(row) - target), row["strike"]))


def build_debit(quotes, kind, S, T, r, target_px, atm):
    """Return (spread dict, skip reason). skip reason is '' on a pass.

    quotes are one expiry and may include both calls and puts. Only `kind` is used.
    """
    _ = atm
    usable = _decorate(quotes, kind, S, T, r)
    if not usable:
        return None, "bid-ask is wide"
    # Prefer a listed strike inside 0.55 to 0.65. "About" that band still
    # accepts the nearest strike when the grid falls just outside it.
    longs = [q for q in usable if LONG_LO - 1e-9 <= q["delta"] <= LONG_HI + 1e-9]
    if not longs:
        nearest = _closest(usable, lambda q: q["delta"], LONG_DELTA)
        if nearest is None or abs(nearest["delta"] - LONG_DELTA) > 0.08:
            return None, "no long strike near 0.60 delta"
        longs = [nearest]
    initial = _closest(longs, lambda q: q["delta"], LONG_DELTA)
    if kind == "call":
        shorts = [q for q in usable if q["strike"] > initial["strike"] + 1e-9]
    else:
        shorts = [q for q in usable if q["strike"] < initial["strike"] - 1e-9]
    if not shorts:
        return None, "no short strike"
    d30 = _closest(shorts, lambda q: q["delta"], SHORT_DELTA)
    short = d30
    try:
        target = float(target_px)
    except (TypeError, ValueError):
        target = None
    if target is not None and target > 0:
        tgt = _closest(shorts, lambda q: q["strike"], target)
        if abs(target - S) < abs(d30["strike"] - S) - 1e-9:
            short = tgt
    if kind == "call":
        alts = [q for q in usable if initial["strike"] - 1e-9 <= q["strike"] < short["strike"] - 1e-9]
        alts.sort(key=lambda q: q["strike"])
    else:
        alts = [q for q in usable if short["strike"] + 1e-9 < q["strike"] <= initial["strike"] + 1e-9]
        alts.sort(key=lambda q: -q["strike"])
    saw_debit = False
    liq_fail = ""
    for leg in alts:
        debit = leg["mid"] - short["mid"]
        width = abs(short["strike"] - leg["strike"])
        if width <= 0 or debit <= 0:
            continue
        saw_debit = True
        math_ = spread_math(kind, leg["strike"], short["strike"], debit, S)
        reason = liquidity_reason(leg, short)
        if math_["ratio"] <= MAX_DEBIT_RATIO + 1e-9 and not reason:
            return {
                "kind": kind,
                "long": leg,
                "short": short,
                "narrowed": leg["strike"] != initial["strike"],
                "debit": debit,
                "width": width,
                "ratio": math_["ratio"],
                "math": math_,
                "grade": liquidity_grade(leg, short),
                "liq": "",
            }, ""
        if math_["ratio"] <= MAX_DEBIT_RATIO + 1e-9 and reason and not liq_fail:
            liq_fail = reason
    if liq_fail:
        return None, liq_fail
    if saw_debit:
        return None, "debit is more than 40% of the width"
    return None, "no debit spread"


def expiry_dates(quotes):
    out = []
    seen = set()
    for q in quotes:
        raw = q.get("exp")
        if raw in seen or not raw:
            continue
        seen.add(raw)
        if isinstance(raw, dt.date):
            out.append(raw)
            continue
        try:
            out.append(dt.date.fromisoformat(str(raw)[:10]))
        except ValueError:
            continue
    return out
