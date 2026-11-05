"""Cause ranking and headline tagging (overall market only — no tickers)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .schema import CAUSE_TAGS

# Keyword → cause. Order matters only for scoring boosts; a headline can match several.
CAUSE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "rates": (
        "fed ", "federal reserve", "fomc", "interest rate", "rate cut", "rate hike",
        "treasury yield", "bond yield", "powell", "dot plot", "quantitative",
    ),
    "jobs": (
        "payroll", "jobs report", "unemployment", "jobless", "nonfarm", "labor market",
        "hiring", "layoff",
    ),
    "oil": (
        "oil ", "crude", "opec", "brent", "wti", "gasoline", "energy prices",
    ),
    "election": (
        "election", "midterm", "ballot", "congress", "senate", "white house",
        "president", "voting", "electoral",
    ),
    "ai_mood": (
        "artificial intelligence", " ai ", "ai spending", "ai trade", "chip",
        "semiconductor", "nvidia", "tech selloff", "tech stocks", "big tech",
        "magnificent", "nasdaq", "megacap tech", "mega-cap tech",
    ),
    "war": (
        "war ", "missile", "invasion", "military", "gaza", "ukraine", "israel",
        "iran", "conflict", "geopolit", "airstrike", "ceasefire",
    ),
    "earnings_season": (
        "earnings season", "mega-cap earnings", "megacap earnings",
        "corporate earnings", "quarterly results wave",
    ),
    "inflation": (
        "inflation", "cpi", "ppi", "pce", "consumer price", "price index",
        "cost of living",
    ),
}

# Sector-day moves that reinforce a cause even without a matching headline.
SECTOR_CAUSE_HINTS: Tuple[Tuple[str, Tuple[str, ...], float], ...] = (
    # (cause, name/ticker fragments, min abs day_pct to count)
    ("ai_mood", ("Technology", "XLK", "Information Technology"), 2.0),
    ("oil", ("Energy", "XLE"), 1.0),
    ("rates", ("Financials", "XLF", "Utilities", "XLU", "Real Estate", "XLRE"), 1.5),
)


def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", (text or "").lower()) + " "


def tag_headline(title: str, summary: str = "") -> List[str]:
    blob = _norm(title) + _norm(summary)
    hits = []
    for cause, words in CAUSE_KEYWORDS.items():
        if any(w in blob for w in words):
            hits.append(cause)
    return hits


def score_causes(
    headlines: List[Dict[str, Any]],
    stats: Dict[str, Any],
    sectors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Rank 1–2 main causes; attach matching headlines under each label."""
    scores = {c: 0.0 for c in CAUSE_TAGS}
    buckets: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CAUSE_TAGS}

    for h in headlines:
        tags = h.get("causes") or tag_headline(h.get("title") or "", h.get("summary") or "")
        h = dict(h)
        h["causes"] = tags
        trust_bonus = 1.5 if h.get("trusted") else 1.0
        for t in tags:
            if t in scores:
                scores[t] += trust_bonus
                buckets[t].append(h)

    # Desk numbers reinforce causes.
    qqq = _f(stats.get("qqq_day_pct"))
    spy = _f(stats.get("spy_day_pct"))
    if qqq is not None and spy is not None and qqq <= spy - 1.5 and qqq <= -2:
        scores["ai_mood"] += 3.0
    if spy is not None and spy <= -2 and qqq is not None and qqq <= -3:
        scores["ai_mood"] += 1.5

    for cause, fragments, thresh in SECTOR_CAUSE_HINTS:
        for row in sectors or []:
            label = " ".join(
                str(row.get(k) or "") for k in ("name", "sector", "ticker", "group_name")
            )
            pct = _f(row.get("day_pct"))
            if pct is None:
                continue
            if any(frag.lower() in label.lower() for frag in fragments) and abs(pct) >= thresh:
                scores[cause] += 1.0 + min(abs(pct) / 3.0, 2.0)

    vix = _f(stats.get("vix"))
    if vix is not None and vix >= 22 and scores["ai_mood"] >= 2:
        scores["ai_mood"] += 0.5

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [(c, s) for c, s in ranked if s > 0][:2]
    if not top:
        # Fallback: strongest sector move names a cause.
        if qqq is not None and abs(qqq) >= abs(spy or 0):
            top = [("ai_mood", 1.0)]
        else:
            top = [("rates", 0.5)]

    out = []
    for cause, score in top:
        label = _pretty(cause)
        out.append({
            "cause": cause,
            "label": label,
            "score": round(score, 2),
            "headlines": buckets.get(cause) or [],
        })
    return out


def _pretty(cause: str) -> str:
    return {
        "rates": "Rates / Fed",
        "jobs": "Jobs",
        "oil": "Oil / Energy",
        "election": "Election",
        "ai_mood": "AI / Tech mood",
        "war": "War / Geopolitics",
        "earnings_season": "Earnings season",
        "inflation": "Inflation",
    }.get(cause, cause.replace("_", " ").title())


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick_headlines(
    raw: List[Dict[str, Any]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Keep 3–5 big-picture headlines; prefer trusted; drop duplicates and single-stock noise."""
    seen = set()
    kept: List[Dict[str, Any]] = []
    # Trusted first, then others.
    ordered = sorted(raw, key=lambda h: (0 if h.get("trusted") else 1, h.get("published") or ""), reverse=False)
    ordered = sorted(raw, key=lambda h: (0 if h.get("trusted") else 1))

    for h in ordered:
        title = (h.get("title") or "").strip()
        if not title or _looks_single_stock(title):
            continue
        key = re.sub(r"[^a-z0-9]+", "", title.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        tags = h.get("causes") or tag_headline(title, h.get("summary") or "")
        # Prefer headlines that map to a locked cause; allow 1 untagged trusted wire.
        if not tags and not h.get("trusted"):
            continue
        item = {
            "title": title,
            "source": h.get("source") or "",
            "url": h.get("url") or "",
            "published": h.get("published") or "",
            "trusted": bool(h.get("trusted")),
            "causes": tags,
        }
        kept.append(item)
        if len(kept) >= limit:
            break

    if len(kept) < 3:
        # Fill with any remaining non-single-stock titles.
        for h in ordered:
            if len(kept) >= max(3, limit):
                break
            title = (h.get("title") or "").strip()
            if not title or _looks_single_stock(title):
                continue
            key = re.sub(r"[^a-z0-9]+", "", title.lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            kept.append({
                "title": title,
                "source": h.get("source") or "",
                "url": h.get("url") or "",
                "published": h.get("published") or "",
                "trusted": bool(h.get("trusted")),
                "causes": h.get("causes") or tag_headline(title, h.get("summary") or ""),
            })
    return kept[:limit]


_TICKER_NOISE = re.compile(
    r"\b(NVDA|AAPL|MSFT|AMZN|META|TSLA|GOOGL|GOOG|AMD|INTC|NFLX|CRM|ORCL)\b"
)
_SINGLE_STOCK = re.compile(
    r"\b(stock plummeted|shares (surge|soar|plunge|jump|fall|rise)|earnings beat|earnings miss)\b",
    re.I,
)


def _looks_single_stock(title: str) -> bool:
    """Drop obvious one-name stories; keep broad AI/tech mood lines even if a ticker appears."""
    t = title or ""
    broad = any(
        w in t.lower()
        for w in (
            "market", "stocks", "nasdaq", "s&p", "dow ", "wall street", "tech stocks",
            "semiconductor", "ai spending", "ai trade", "futures", "investors",
            "election", "fed ", "inflation", "oil", "treasury",
        )
    )
    if broad:
        return False
    if _TICKER_NOISE.search(t) and _SINGLE_STOCK.search(t):
        return True
    if _TICKER_NOISE.search(t) and not broad:
        # A title that is mostly one ticker with no market framing.
        return True
    return False
