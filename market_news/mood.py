"""Mood chip, regime, breadth-vs-price, and why-the-market-moved lines.

All from desk numbers only. No Yahoo. No broker.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


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


def _sector_rows(sectors: list) -> List[Tuple[float, str, str]]:
    """Rank SPDR sector ETFs (XL*) by day_pct. Falls back to all rows if no XL*."""
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
        ranked.append((pct, name, str(row.get("ticker") or "").upper()))
    ranked.sort(key=lambda x: x[0])
    return ranked


def _dow_pct(stats: Dict[str, Any], ranked: List[Tuple[float, str, str]]) -> Tuple[Optional[float], str]:
    """Real DIA/Dow day % when the desk has it; else XLF+XLI average (Dow-heavy groups)."""
    for key in ("dia_day_pct", "dow_day_pct"):
        n = _f(stats.get(key))
        if n is not None:
            return n, "dia"
    bits = [p for p, _n, t in ranked if t in ("XLF", "XLI")]
    if len(bits) >= 2:
        return sum(bits) / len(bits), "proxy"
    if len(bits) == 1:
        return bits[0], "proxy"
    return None, "missing"


def why_moved_short(stats: Dict[str, Any], sectors: list) -> str:
    """v1 one-sentence why line (kept for the compact switch and prior-brief compare)."""
    spy = _f(stats.get("spy_day_pct"))
    qqq = _f(stats.get("qqq_day_pct"))
    vix = _f(stats.get("vix"))
    adv = _i(stats.get("advancers"))
    dec = _i(stats.get("decliners"))
    ranked = _sector_rows(sectors)

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
    return sentence[0].upper() + sentence[1:]


def why_moved(
    stats: Dict[str, Any],
    sectors: list,
    causes: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """2–3 plain sentences: biggest driver, leaders/laggards, how broad the move was.

    Built only from desk numbers + optional top cause tags. No single-stock names.
    """
    spy = _f(stats.get("spy_day_pct"))
    qqq = _f(stats.get("qqq_day_pct"))
    vix = _f(stats.get("vix"))
    adv = _i(stats.get("advancers"))
    dec = _i(stats.get("decliners"))
    ranked = _sector_rows(sectors)
    dow, dow_kind = _dow_pct(stats, ranked)

    # Sentence 1 — indexes
    s1_bits = []
    if spy is not None and qqq is not None:
        if spy < -0.3 or qqq < -0.3:
            s1_bits.append(
                "The market fell: S&P %.1f%%, Nasdaq %.1f%%"
                % (spy, qqq)
            )
        elif spy > 0.3 or qqq > 0.3:
            s1_bits.append(
                "The market rose: S&P %.1f%%, Nasdaq %.1f%%"
                % (spy, qqq)
            )
        else:
            s1_bits.append(
                "The market was quiet: S&P %.1f%%, Nasdaq %.1f%%"
                % (spy, qqq)
            )
    elif spy is not None:
        s1_bits.append("The S&P moved %.1f%%" % spy)
    else:
        s1_bits.append("Desk index numbers are thin today")

    if dow is not None:
        if dow_kind == "dia":
            s1_bits.append("Dow %.1f%%" % dow)
        else:
            s1_bits.append("Dow-heavy groups (Financials/Industrials) about %.1f%%" % dow)

    s1 = s1_bits[0]
    if len(s1_bits) > 1:
        s1 = s1_bits[0] + ", " + ", ".join(s1_bits[1:])
    if not s1.endswith("."):
        s1 += "."

    # Sentence 2 — biggest driver + leading / lagging sectors
    lag = ranked[:2] if ranked else []
    lead = list(reversed(ranked[-2:])) if ranked else []
    driver = None
    if causes:
        driver = (causes[0].get("label") or causes[0].get("cause") or "").strip() or None

    # Infer driver from tape when no cause tag yet
    if not driver and qqq is not None and spy is not None and abs(qqq - spy) >= 1.0:
        driver = "AI / Tech mood" if abs(qqq) >= abs(spy) else None
    if not driver and lag and abs(lag[0][0]) >= 1.5:
        # Use the worst sector name as a soft driver hint only for tech/energy
        name = lag[0][1]
        if "Tech" in name:
            driver = "AI / Tech mood"
        elif "Energy" in name:
            driver = "Oil / Energy"

    s2_parts = []
    if driver:
        s2_parts.append("Biggest driver: %s" % driver)
    if lag:
        s2_parts.append(
            "lagging sectors were "
            + " and ".join("%s (%.1f%%)" % (n, p) for p, n, _ in lag)
        )
    if lead and (not lag or lead[0][2] != lag[0][2]):
        # Avoid repeating the same names if the whole tape is one-sided
        lead_clean = [r for r in lead if not lag or r[2] not in {x[2] for x in lag}]
        if not lead_clean and lead:
            lead_clean = lead
        if lead_clean:
            verb = "held up" if lead_clean[0][0] >= 0 else "were the least weak"
            s2_parts.append(
                "leading sectors "
                + " and ".join("%s (%.1f%%)" % (n, p) for p, n, _ in lead_clean)
                + " " + verb
            )
    if s2_parts:
        s2 = s2_parts[0]
        for p in s2_parts[1:]:
            if p.startswith("lagging") or p.startswith("leading"):
                s2 += "; " + p
            else:
                s2 += ". " + p[0].upper() + p[1:]
        if not s2.endswith("."):
            s2 += "."
        s2 = s2[0].upper() + s2[1:]
    else:
        s2 = "Sector moves were mixed."

    # Sentence 3 — breadth + VIX
    s3_bits = []
    if adv is not None and dec is not None and (adv + dec) > 0:
        share_down = dec / float(adv + dec)
        share_up = adv / float(adv + dec)
        if dec > adv * 1.15:
            how = "broad" if share_down >= 0.6 else "fairly broad"
            s3_bits.append(
                "The move was %s: %d stocks fell and %d rose"
                % (how, dec, adv)
            )
        elif adv > dec * 1.15:
            how = "broad" if share_up >= 0.6 else "fairly broad"
            s3_bits.append(
                "The move was %s: %d stocks rose and %d fell"
                % (how, adv, dec)
            )
        else:
            s3_bits.append(
                "Breadth was mixed (%d up, %d down)" % (adv, dec)
            )
    if vix is not None:
        if vix >= 25:
            s3_bits.append("VIX is elevated at %.1f" % vix)
        elif vix >= 20:
            s3_bits.append("VIX is firm at %.1f" % vix)
        elif vix < 16:
            s3_bits.append("VIX is calm at %.1f" % vix)

    if s3_bits:
        s3 = s3_bits[0]
        for bit in s3_bits[1:]:
            # Keep acronyms like VIX intact — only lower a leading lowercase word.
            s3 += "; " + bit
        if not s3.endswith("."):
            s3 += "."
        s3 = s3[0].upper() + s3[1:]
    else:
        s3 = ""

    parts = [s1, s2] + ([s3] if s3 else [])
    return " ".join(parts)


# Back-compat alias used by older call sites that expect one string.
def why_moved_legacy(stats: Dict[str, Any], sectors: list) -> str:
    return why_moved_short(stats, sectors)
