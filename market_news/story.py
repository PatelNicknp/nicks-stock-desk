"""Layout fields for the Today market-news card.

The bold line comes from desk numbers. A cause is named only when a free
headline and a desk number both support it. Otherwise the card says there
is no clear cause. No Yahoo. No single-stock tips.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple

_MONTHS = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MON = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_SHORT = {
    "Technology": "Tech",
    "Health Care": "Health",
    "Financials": "Financials",
    "Industrials": "Industrials",
    "Communication Services": "Comm. services",
    "Consumer Discretionary": "Discretionary",
    "Consumer Staples": "Staples",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real estate",
    "Materials": "Materials",
    "Semiconductors": "Chips",
}

# Words that let a footnote point at a headline for a sector chip or bullet.
_SECTOR_WORDS = {
    "Technology": ("tech", "chip", "semiconductor", "nasdaq", " ai "),
    "Semiconductors": ("chip", "semiconductor", "nasdaq"),
    "Energy": ("oil", "crude", "energy"),
    "Consumer Staples": ("staple",),
    "Health Care": ("health",),
    "Financials": ("bank", "financial", "rate"),
    "Industrials": ("industrial",),
    "Communication Services": ("communication",),
    "Consumer Discretionary": ("consumer", "retail"),
    "Utilities": ("utilit",),
    "Real Estate": ("real estate", "housing"),
    "Materials": ("material", "mining"),
}


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


def _pct_text(n: Optional[float]) -> Optional[str]:
    if n is None:
        return None
    s = ("%.2f" % abs(float(n))).rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s + "%"


def _sign(n: Optional[float]) -> str:
    if n is None or abs(n) < 0.05:
        return "flat"
    return "down" if n < 0 else "up"


def _direction(spy: Optional[float], qqq: Optional[float]) -> str:
    a = spy if spy is not None else qqq
    b = qqq if qqq is not None else spy
    if a is None and b is None:
        return "unknown"
    down = (a is not None and a < -0.3) or (b is not None and b < -0.3)
    up = (a is not None and a > 0.3) or (b is not None and b > 0.3)
    if down and not up:
        return "down"
    if up and not down:
        return "up"
    if down and up:
        # Mixed indexes: follow the S&P when we have it.
        if spy is not None and spy < -0.15:
            return "down"
        if spy is not None and spy > 0.15:
            return "up"
        return "flat"
    return "flat"


def _xl_rows(sectors: List[Dict[str, Any]]) -> List[Tuple[float, str, str]]:
    rows = []
    for row in sectors or []:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker.startswith("XL"):
            continue
        pct = _f(row.get("day_pct"))
        name = (row.get("name") or row.get("sector") or ticker).strip()
        if pct is None or not name:
            continue
        rows.append((pct, name, ticker))
    rows.sort(key=lambda r: r[0])
    return rows


def _by_ticker(sectors: List[Dict[str, Any]], ticker: str) -> Optional[Tuple[float, str, str]]:
    for row in sectors or []:
        if str(row.get("ticker") or "").upper() != ticker:
            continue
        pct = _f(row.get("day_pct"))
        name = (row.get("name") or ticker).strip()
        if pct is None:
            return None
        return pct, name, ticker
    return None


def _index_lead(spy: Optional[float], qqq: Optional[float], direction: str) -> str:
    if spy is None and qqq is None:
        return "The desk does not have an index move for today."
    if direction == "down":
        if spy is not None and qqq is not None and qqq <= spy - 0.5:
            return "The Nasdaq led stocks lower."
        if spy is not None and qqq is not None and spy <= qqq - 0.5:
            return "The S&P led stocks lower."
        return "Stocks fell."
    if direction == "up":
        if spy is not None and qqq is not None and qqq >= spy + 0.5:
            return "The Nasdaq led stocks higher."
        if spy is not None and qqq is not None and spy >= qqq + 0.5:
            return "The S&P led stocks higher."
        return "Stocks rose."
    if direction == "flat":
        return "The market was little changed."
    return "The desk does not have a clear index move for today."


def _blob(h: Dict[str, Any]) -> str:
    return " " + re.sub(r"\s+", " ", ((h.get("title") or "") + " " + (h.get("summary") or "")).lower()) + " "


def _mentions(h: Dict[str, Any], words: Tuple[str, ...]) -> bool:
    blob = _blob(h)
    return any(w in blob for w in words)


def _cause_matches_desk(
    cause: str,
    stats: Dict[str, Any],
    sectors: List[Dict[str, Any]],
    direction: str,
) -> bool:
    """True only when a desk number lines up with this cause. A headline alone is not enough."""
    spy = _f(stats.get("spy_day_pct"))
    qqq = _f(stats.get("qqq_day_pct"))
    xl = _xl_rows(sectors)
    tech = next((r for r in xl if r[2] == "XLK" or "Tech" in r[1]), None)
    energy = next((r for r in xl if r[2] == "XLE" or r[1] == "Energy"), None)
    financials = next((r for r in xl if r[2] == "XLF"), None)

    if cause == "ai_mood":
        if tech is not None and direction in ("down", "up") and _sign(tech[0]) == direction and abs(tech[0]) >= 1:
            return True
        if spy is not None and qqq is not None and direction == "down" and qqq <= spy - 0.5 and qqq < -0.3:
            return True
        if spy is not None and qqq is not None and direction == "up" and qqq >= spy + 0.5 and qqq > 0.3:
            return True
        return False
    if cause == "oil":
        # Energy has to be a real part of the day's move, not a small offset.
        return energy is not None and abs(energy[0]) >= 1.0 and (
            direction == "flat" or _sign(energy[0]) == direction or abs(energy[0]) >= 1.5
        )
    if cause == "rates":
        # A Fed headline plus a high VIX is not enough. Financials have to move with the day.
        return (
            financials is not None
            and direction in ("down", "up")
            and _sign(financials[0]) == direction
            and abs(financials[0]) >= 1.0
        )
    # Jobs, inflation, elections, war, and earnings season have no matching
    # number on this desk, so they are not treated as the cause of the move.
    return False


_CAUSE_WORDS = {
    "ai_mood": (
        "artificial intelligence", " ai ", "chip", "semiconductor", "nasdaq", "tech",
        "data center", "data-center", "ai regulat", "ai build", "ai trade",
    ),
    "oil": ("oil", "crude", "energy"),
    "rates": ("federal reserve", "fomc", "interest rate", " rate", "yield"),
    "jobs": ("jobs", "payroll", "jobless", "unemployment"),
    "inflation": ("inflation", "cpi", "ppi"),
    "election": ("election", "midterm", "tariff"),
    "war": ("war ", "ukraine", "ceasefire"),
}


def _pick_headline(headlines: List[Dict[str, Any]], cause: str) -> Optional[Dict[str, Any]]:
    """Use a headline only when its own words name the cause. A leftover tag is not enough."""
    if not headlines:
        return None
    words = _CAUSE_WORDS.get(cause) or ()

    def score(h: Dict[str, Any]) -> Tuple[int, int, float]:
        blob = _blob(h)
        hits = sum(1 for w in words if w in blob)
        specific = 1 if ("regulat" in blob or "data center" in blob or "data-center" in blob or "fear" in blob) else 0
        wrap = 1 if any(bit in blob for bit in (
            "fell", "fall", "drop", "slid", "slide", "crater", "plunge", "selloff",
            "sell-off", "worst day", "on fears", "correction", "wipes out", "rout",
        )) else 0
        rank = h.get("rank")
        try:
            rank_n = float(rank) if rank is not None else 0.0
        except (TypeError, ValueError):
            rank_n = 0.0
        return (hits, specific, wrap, rank_n)

    best = max(headlines, key=score)
    if words and score(best)[0] == 0:
        return None
    return best


def _finish_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def _long_date(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    return "%s %d, %d" % (_MONTHS[d.month], d.day, d.year)


def _short_date(published: str, session: str) -> str:
    raw = published or session or ""
    try:
        d = dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return ""
    return "%s %d" % (_MON[d.month], d.day)


def _news_item(h: Dict[str, Any], n: int, session: str) -> Dict[str, Any]:
    return {
        "n": n,
        "title": (h.get("title") or "").strip(),
        "source": (h.get("source") or "").strip(),
        "via": (h.get("via") or "").strip(),
        "url": h.get("url") or "",
        "published": h.get("published") or "",
        "published_at": h.get("published_at") or "",
        "date_label": h.get("published_pt") or _short_date(h.get("published") or "", session),
        "age_label": h.get("age_label") or "",
        "region": h.get("region") or "",
        "why": h.get("why") or "",
    }


def _same_story(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (a.get("url") and a.get("url") == b.get("url")) or (
        (a.get("title") or "").strip().lower() == (b.get("title") or "").strip().lower()
    )


def _sector_bullet(name: str, pct: float, role: str) -> Dict[str, Any]:
    short = _SHORT.get(name, name)
    if role == "hit":
        lead = "Technology took the biggest hit." if name == "Technology" else "%s took the biggest hit." % short
    elif role == "lead":
        lead = "%s led the gain." % short
    elif role == "held":
        lead = "%s held up." % short
    else:
        lead = "%s was soft." % short
    return {
        "lead": lead,
        "rest": "%s %s %s." % (
            short,
            "fell" if pct < 0 else "rose" if pct > 0 else "was flat at",
            _pct_text(pct),
        ),
        "sector": name,
        "ref": None,
    }


def _attach_refs(bullets: List[Dict[str, Any]], news: List[Dict[str, Any]], headlines: List[Dict[str, Any]]) -> None:
    by_title = {(h.get("title") or "").strip(): h for h in headlines}
    for b in bullets:
        sector = b.get("sector")
        words = _SECTOR_WORDS.get(sector or "", ())
        if not words:
            continue
        for item in news:
            raw = by_title.get(item.get("title") or "")
            if raw and _mentions(raw, words):
                b["ref"] = item["n"]
                break


def _indexes(stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    spy = _f(stats.get("spy_day_pct"))
    qqq = _f(stats.get("qqq_day_pct"))
    dow = _f(stats.get("dia_day_pct") or stats.get("dow_day_pct"))
    out = [
        {"name": "S&P 500", "pct": spy, "pct_text": _pct_text(spy), "arrow": _sign(spy), "source": "spy"},
        {"name": "Nasdaq", "pct": qqq, "pct_text": _pct_text(qqq), "arrow": _sign(qqq), "source": "qqq"},
    ]
    if dow is not None:
        out.append({
            "name": "Dow",
            "pct": dow,
            "pct_text": _pct_text(dow),
            "arrow": _sign(dow),
            "source": "dia",
        })
    return out


def _chips(xl: List[Tuple[float, str, str]], sectors: List[Dict[str, Any]], direction: str) -> Tuple[str, List[Dict[str, Any]]]:
    if direction == "up":
        label = "Where the buying was"
        movers = [r for r in reversed(xl) if r[0] > 0][:2]
    elif direction == "down":
        label = "Where the selling hit"
        movers = [r for r in xl if r[0] < 0][:2]
    else:
        label = "Where the move showed up"
        movers = (xl[:1] + xl[-1:]) if xl else []

    smh = _by_ticker(sectors, "SMH")
    show_chips = bool(smh and direction in ("up", "down") and _sign(smh[0]) == direction and abs(smh[0]) >= 1)
    # Two move chips, like the sample: the lead sector, plus chips when that industry ETF is on file.
    if show_chips:
        movers = movers[:1]

    chips = []
    seen = set()
    for pct, name, ticker in movers:
        if ticker in seen:
            continue
        seen.add(ticker)
        chips.append({
            "name": _SHORT.get(name, name),
            "pct": pct,
            "pct_text": _pct_text(pct),
            "arrow": _sign(pct),
            "kind": "move",
        })

    if show_chips:
        chips.append({
            "name": "Chips",
            "pct": smh[0],
            "pct_text": _pct_text(smh[0]),
            "arrow": _sign(smh[0]),
            "kind": "move",
        })

    n = len(xl)
    down_n = sum(1 for p, _n, _t in xl if p < -0.05)
    up_n = sum(1 for p, _n, _t in xl if p > 0.05)
    summary = None
    if n:
        if down_n == n and direction != "up":
            summary = "All %d sectors down" % n
        elif up_n == n and direction != "down":
            summary = "All %d sectors up" % n
        elif direction == "down":
            summary = "%d of %d sectors down" % (down_n, n)
        elif direction == "up":
            summary = "%d of %d sectors up" % (up_n, n)
        else:
            summary = "%d of %d sectors down" % (down_n, n)
    if summary:
        chips.append({"name": summary, "pct": None, "pct_text": None, "arrow": "flat", "kind": "summary"})

    moves = [c for c in chips if c["kind"] == "move" and c.get("pct") is not None]
    peak = max((abs(c["pct"]) for c in moves), default=0)
    for c in chips:
        if c["kind"] != "move" or not peak:
            c["bar"] = 0
        else:
            c["bar"] = int(round(100.0 * abs(c["pct"]) / peak))
    return label, chips


def _bullets(
    xl: List[Tuple[float, str, str]],
    stats: Dict[str, Any],
    direction: str,
) -> List[Dict[str, Any]]:
    bullets: List[Dict[str, Any]] = []
    if not xl:
        return bullets
    if direction == "up":
        pct, name, _t = xl[-1]
        bullets.append(_sector_bullet(name, pct, "lead"))
        held = None
    else:
        pct, name, _t = xl[0]
        bullets.append(_sector_bullet(name, pct, "hit"))
        held = xl[-1] if xl[-1][2] != xl[0][2] and xl[-1][0] > 0 else None

    adv = _i(stats.get("advancers"))
    dec = _i(stats.get("decliners"))
    if adv is not None and dec is not None:
        if dec > adv:
            bullets.append({
                "lead": "More stocks fell than rose.",
                "rest": "%d stocks fell and %d rose." % (dec, adv),
                "sector": None,
                "ref": None,
            })
        elif adv > dec:
            bullets.append({
                "lead": "More stocks rose than fell.",
                "rest": "%d stocks rose and %d fell." % (adv, dec),
                "sector": None,
                "ref": None,
            })
        else:
            bullets.append({
                "lead": "Gainers and losers were about even.",
                "rest": "%d stocks rose and %d fell." % (adv, dec),
                "sector": None,
                "ref": None,
            })

    if held is not None and len(bullets) < 3:
        bullets.append(_sector_bullet(held[1], held[0], "held"))
    return bullets[:3]


def _lead_from_headline(headline: Dict[str, Any], direction: str, cause: str) -> str:
    """A short reason line. Every word is backed by the headline or the day's direction."""
    blob = _blob(headline)
    if direction == "down" and ("data center" in blob or "data-center" in blob) and (
        " ai " in blob or "chip" in blob
    ):
        return "AI data-center fears sent stocks lower."
    if direction == "down" and " ai " in blob and (
        "regulat" in blob or "fear" in blob
    ):
        return "AI regulation fears sent stocks lower."
    if direction == "down" and ("chip" in blob or "semiconductor" in blob) and (
        "nasdaq" in blob or "tech" in blob or "stock" in blob
    ):
        return "Chip and tech shares led stocks lower."
    if direction == "down" and "ai trade" in blob:
        return "The AI trade led stocks lower."
    if direction == "up" and (" ai " in blob or "chip" in blob):
        return "The AI trade led stocks higher."
    if cause == "oil" and direction == "down":
        return "Oil was part of the drop."
    if cause == "oil" and direction == "up":
        return "Oil was part of the rise."
    if cause == "rates":
        return "Rates were part of the move."
    if cause == "ai_mood" and direction == "down":
        return "Tech led stocks lower."
    if cause == "ai_mood" and direction == "up":
        return "Tech led stocks higher."
    if direction == "down":
        return "Stocks fell."
    if direction == "up":
        return "Stocks rose."
    return "The market was little changed."


def build_story(
    stats: Dict[str, Any],
    sectors: List[Dict[str, Any]],
    headlines: List[Dict[str, Any]],
    causes: List[Dict[str, Any]],
    slot: str = "evening_close",
) -> Dict[str, Any]:
    spy = _f(stats.get("spy_day_pct"))
    qqq = _f(stats.get("qqq_day_pct"))
    direction = _direction(spy, qqq)
    xl = _xl_rows(sectors)
    session = str(stats.get("price_as_of") or "")

    linked = [
        c for c in (causes or [])
        if (c.get("headlines") or []) and _cause_matches_desk(c.get("cause") or "", stats, sectors, direction)
    ]
    support_h = _pick_headline(
        (linked[0].get("headlines") if linked else None) or [],
        (linked[0].get("cause") if linked else "") or "",
    )
    clear = support_h is not None

    if clear:
        lead = _lead_from_headline(support_h, direction, linked[0].get("cause") or "")
    else:
        lead = _index_lead(spy, qqq, direction)

    if clear:
        support = _finish_sentence(support_h.get("title") or "")
        cause = linked[0].get("cause")
    else:
        if headlines:
            support = "No clear cause in the free headlines. None of them line up with the desk numbers."
        else:
            support = "No clear cause. The free feeds had no big-picture headline, so this is the desk numbers only."
        cause = None

    # Cited headline first, then the other ranked headlines. The card shows five.
    # Anything past that stays in the brief for More details.
    ordered: List[Dict[str, Any]] = []
    if support_h:
        ordered.append(support_h)
    for h in headlines or []:
        if any(_same_story(h, have) for have in ordered):
            continue
        ordered.append(h)
        if len(ordered) >= 7:
            break
    ordered = ordered[:7]
    news = [_news_item(h, i + 1, session) for i, h in enumerate(ordered)]
    support_ref = 1 if clear and news else None

    bullets = _bullets(xl, stats, direction)
    _attach_refs(bullets, news, ordered)
    for b in bullets:
        b.pop("sector", None)

    label, chips = _chips(xl, sectors, direction)
    summary = "U.S. closing summary" if slot == "evening_close" else "U.S. morning summary"

    return {
        "direction": direction,
        "date_label": _long_date(session) if session else "",
        "summary": summary,
        "clear_cause": clear,
        "cause": cause,
        "lead": lead,
        "support": support,
        "support_ref": support_ref,
        "bullets": bullets,
        "sector_label": label,
        "chips": chips,
        "indexes": _indexes(stats),
        "news": news,
        "note": (
            "The plain line quotes a free headline that lines up with a desk number. "
            "It is a report, not proof of a single cause."
            if clear else
            "No headline was tied to the move. The bold line is the desk numbers only."
        ),
    }
