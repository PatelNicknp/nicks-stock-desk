"""Mood chip, regime, and breadth-vs-price checks from desk numbers only."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> Optional[int]:
    n = _f(v)
    return None if n is None else int(round(n))


def mood_chip(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Calm / Fear / Mixed from VIX + put/call zone + breadth.

    Rules (plain English, locked for this pack):
      Fear  — VIX >= 25, OR VIX >= 20 and decliners clearly beat advancers,
              OR put/call zone is Fear.
      Calm  — VIX < 16, put/call not Fear, and advancers >= decliners.
      Mixed — everything else.
    """
    vix = _f(stats.get("vix"))
    zone = str(stats.get("put_call_zone") or "").strip().title()
    adv = _i(stats.get("advancers"))
    dec = _i(stats.get("decliners"))
    breadth_weak = adv is not None and dec is not None and dec > adv * 1.15
    breadth_strong = adv is not None and dec is not None and adv >= dec

    reasons = []
    if vix is not None:
        reasons.append("VIX %.1f" % vix)
    if zone:
        reasons.append("put/call %s" % zone)
    if adv is not None and dec is not None:
        reasons.append("%d up / %d down" % (adv, dec))

    label = "Mixed"
    if zone == "Fear" or (vix is not None and vix >= 25) or (
        vix is not None and vix >= 20 and breadth_weak
    ):
        label = "Fear"
    elif (vix is None or vix < 16) and zone != "Fear" and breadth_strong:
        label = "Calm"

    return {
        "label": label,
        "vix": vix,
        "put_call_zone": zone or None,
        "put_call": _f(stats.get("put_call")),
        "advancers": adv,
        "decliners": dec,
        "why": ", ".join(reasons) if reasons else "not enough desk numbers",
    }


def regime_note(stats: Dict[str, Any]) -> Dict[str, Any]:
    """uptrend / chop / selloff from % above 50-day and 200-day."""
    b50 = _f(stats.get("breadth_sma50"))
    b200 = _f(stats.get("breadth_sma200"))
    if b50 is None and b200 is None:
        return {"label": "unknown", "pct_above_50day": None, "pct_above_200day": None,
                "text": "Regime unclear — breadth averages missing."}

    # Thresholds: strong majority above = uptrend; weak minority = selloff; else chop.
    above50 = b50 is not None and b50 >= 55
    below50 = b50 is not None and b50 < 40
    above200 = b200 is not None and b200 >= 55
    below200 = b200 is not None and b200 < 40

    if above50 and (b200 is None or above200 or (b200 is not None and b200 >= 50)):
        label = "uptrend"
        text = "More than half the desk is still above the 50-day%s." % (
            " and 200-day" if above200 else ""
        )
    elif below50 and (b200 is None or below200 or (b200 is not None and b200 < 50)):
        label = "selloff"
        text = "Under 40% of the desk is above the 50-day — a weak tape."
    else:
        label = "chop"
        text = "Breadth is split — not a clean uptrend or selloff."

    return {
        "label": label,
        "pct_above_50day": b50,
        "pct_above_200day": b200,
        "text": text,
    }


def breadth_vs_price(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Flag when the index and most stocks disagree."""
    spy = _f(stats.get("spy_day_pct"))
    adv = _i(stats.get("advancers"))
    dec = _i(stats.get("decliners"))
    if spy is None or adv is None or dec is None or (adv + dec) == 0:
        return {
            "aligned": None,
            "flag": None,
            "text": "Breadth check skipped — need SPY day % and advancers/decliners.",
        }

    index_up = spy > 0.15
    index_down = spy < -0.15
    most_up = adv > dec * 1.1
    most_down = dec > adv * 1.1

    if index_up and most_down:
        return {
            "aligned": False,
            "flag": "index_up_stocks_down",
            "text": "SPY is up, but more stocks fell than rose — a narrow advance.",
        }
    if index_down and most_up:
        return {
            "aligned": False,
            "flag": "index_down_stocks_up",
            "text": "SPY is down, but more stocks rose than fell — a narrow decline.",
        }
    if index_down and most_down:
        return {
            "aligned": True,
            "flag": "broad_decline",
            "text": "Index and breadth agree: a broad down day.",
        }
    if index_up and most_up:
        return {
            "aligned": True,
            "flag": "broad_advance",
            "text": "Index and breadth agree: a broad up day.",
        }
    return {
        "aligned": True,
        "flag": "flat_or_mixed",
        "text": "Index and breadth are roughly in line.",
    }


def why_moved(stats: Dict[str, Any], sectors: list) -> str:
    """One short plain-English sentence from desk numbers."""
    spy = _f(stats.get("spy_day_pct"))
    qqq = _f(stats.get("qqq_day_pct"))
    vix = _f(stats.get("vix"))
    adv = _i(stats.get("advancers"))
    dec = _i(stats.get("decliners"))

    # Rank sectors by day_pct. Prefer the 11 SPDR sector ETFs (ticker XL*).
    # data/sectors.csv also lists industry ETFs (SMH, ITA, …); a bad industry
    # print must not lead the sentence when the sector ETFs are present.
    rows = list(sectors or [])
    xl = [row for row in rows if str(row.get("ticker") or "").upper().startswith("XL")]
    if xl:
        rows = xl
    ranked = []
    for row in rows:
        pct = _f(row.get("day_pct"))
        name = (row.get("name") or row.get("sector") or row.get("ticker") or "").strip()
        if pct is None or not name:
            continue
        ranked.append((pct, name, str(row.get("ticker") or "")))
    ranked.sort(key=lambda x: x[0])

    weak = [r for r in ranked if r[0] <= -1.0][:2]
    strong = [r for r in ranked if r[0] >= 0.4][-2:]
    strong.reverse()

    parts = []
    if spy is not None and qqq is not None:
        if spy < -1 and qqq <= spy - 0.5:
            parts.append(
                "Stocks fell, with Nasdaq (%.1f%%) leading the S&P (%.1f%%) lower"
                % (qqq, spy)
            )
        elif spy > 1 and qqq >= spy + 0.5:
            parts.append(
                "Stocks rose, with Nasdaq (%.1f%%) leading the S&P (%.1f%%) higher"
                % (qqq, spy)
            )
        elif spy < -0.3:
            parts.append("The S&P slipped %.1f%% (Nasdaq %.1f%%)" % (spy, qqq))
        elif spy > 0.3:
            parts.append("The S&P gained %.1f%% (Nasdaq %.1f%%)" % (spy, qqq))
        else:
            parts.append("The S&P was little changed (%.1f%%; Nasdaq %.1f%%)" % (spy, qqq))
    elif spy is not None:
        parts.append("The S&P moved %.1f%%" % spy)
    else:
        parts.append("Desk numbers are thin today")

    if weak:
        parts.append(
            "dragged by " + " and ".join("%s (%.1f%%)" % (n, p) for p, n, _ in weak)
        )
    if strong:
        parts.append(
            "while " + " and ".join("%s (%.1f%%)" % (n, p) for p, n, _ in strong) + " held up"
        )

    if adv is not None and dec is not None:
        parts.append("(%d stocks up, %d down)" % (adv, dec))
    if vix is not None and vix >= 20:
        parts.append("VIX at %.1f" % vix)

    sentence = parts[0]
    for p in parts[1:]:
        if p.startswith("("):
            sentence += " " + p
        elif p.startswith("VIX "):
            sentence += "; " + p
        elif p.startswith("while ") or p.startswith("dragged "):
            sentence += ", " + p
        else:
            sentence += " " + p
    if not sentence.endswith("."):
        sentence += "."
    # Capitalize first letter only if needed
    return sentence[0].upper() + sentence[1:]
