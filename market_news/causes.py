"""Cause ranking and headline tagging (overall market only — no tickers)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple

from .schema import CAUSE_TAGS

# Keyword → cause. Order matters only for scoring boosts; a headline can match several.
CAUSE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "rates": (
        "fed ", "federal reserve", "fomc", "interest rate", "rate cut", "rate hike",
        "treasury yield", "bond yield", "yields", "powell", "dot plot", "quantitative",
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
        "president", "voting", "electoral", "capitol hill", "tariff",
    ),
    "ai_mood": (
        "artificial intelligence", " ai ", "ai spending", "ai trade", "ai regulat",
        "ai build", "data center", "data-center", "chip",
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

SECTOR_CAUSE_HINTS: Tuple[Tuple[str, Tuple[str, ...], float], ...] = (
    ("ai_mood", ("Technology", "XLK", "Information Technology"), 2.0),
    ("oil", ("Energy", "XLE"), 1.0),
    ("rates", ("Financials", "XLF", "Utilities", "XLU", "Real Estate", "XLRE"), 1.5),
)

# Big-picture importance keywords (overall market only).
_IMPORTANCE = (
    ("federal reserve", 4.0),
    ("fomc", 4.0),
    ("interest rate", 3.5),
    ("cpi", 3.5),
    ("inflation", 3.0),
    ("payroll", 3.0),
    ("jobs report", 3.0),
    ("election", 3.0),
    ("midterm", 3.0),
    ("war ", 3.0),
    ("ukraine", 2.5),
    ("oil ", 2.5),
    ("opec", 2.5),
    ("ai spending", 2.5),
    ("tech selloff", 2.5),
    ("nasdaq", 2.0),
    ("s&p", 2.0),
    ("wall street", 1.5),
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


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())[:80]


def _token_set(title: str) -> set:
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "as", "at", "by", "with"}
    toks = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {t for t in toks if len(t) > 2 and t not in stop}


def _same_tape(a: str, b: str) -> bool:
    """Same chip-led Nasdaq selloff told twice. A regulation headline is a different story."""
    def tape(s: str) -> bool:
        t = " " + (s or "").lower() + " "
        tech = "nasdaq" in t or " tech " in t or "tech stock" in t
        chips = " chip" in t or "semiconductor" in t
        return tech and chips
    return tape(a) and tape(b)


def _near_duplicate(a: str, b: str, thresh: float = 0.72) -> bool:
    """Token Jaccard — catch the same story from two wires."""
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return union > 0 and (inter / union) >= thresh


def _importance_score(title: str, summary: str = "") -> float:
    blob = _norm(title) + _norm(summary)
    score = 0.0
    for word, pts in _IMPORTANCE:
        if word in blob:
            score += pts
    return score


def _rank_key(h: Dict[str, Any]) -> Tuple:
    """Higher is better: trusted, importance, has causes, then title for stability."""
    title = h.get("title") or ""
    tags = h.get("causes") or []
    return (
        1 if h.get("trusted") else 0,
        _importance_score(title, h.get("summary") or ""),
        len(tags),
        title.lower(),
    )


# Market-wrap language ranks above a generic macro headline.
_WRAP_BITS = (
    "stocks fell", "stocks fall", "stocks drop", "stocks crater", "stocks slide",
    "stocks tumble", "stock market", "sell-off", "selloff", "market rout",
    "worst day", "correction territory", "wall street", "on fears",
    "as investors", "investors dump", "investors fret", "investors exit",
    "nasdaq drop", "nasdaq dive", "nasdaq slide", "nasdaq post", "nasdaq enter",
    "nasdaq lag", "s&p 500", "dow jones", "dow plunge", "tech stocks",
    "wipes out", "biggest daily drop", "biggest drop", "led lower", "led stocks",
    "tech stock plunge", "ai trade",
)
# A headline can explain the move without saying "stocks fell".
_DRIVER_BITS = (
    " ai ", "chip", "semiconductor", "data center", "data-center", "ai regulat",
    "ai build", "federal reserve", "fomc", "interest rate", "treasury yield",
    "yields", "jobs report", "payroll", "jobless", "inflation", "cpi", "oil ",
    "crude", "tariff", "election", "midterm",
)
_MARKET_BITS = (
    "stock", "nasdaq", "s&p", "dow", "wall street", "market", "tech",
    "chip", "semiconductor", "futures", "investor",
)
_OFF_TOPIC = (
    "first lady", "measles", "tax bracket", "standard deduction", "gift tax",
    "earnings call transcript", "what you should know", "stock moves",
    "just fell", "enforcement action", "enforcement actions", "gasoline",
    "capital gains", "estate and gift",
)


def market_wrap_score(title: str, summary: str = "") -> float:
    blob = _norm(title) + _norm(summary)
    score = 0.0
    for bit in _WRAP_BITS:
        if bit in blob:
            score += 5.0
    if "because" in blob and any(w in blob for w in ("stock", "market", "nasdaq")):
        score += 4.0
    if "data center" in blob or "data-center" in blob or "moratorium" in blob:
        score += 8.0
    if "ai regulat" in blob or "fears of ai" in blob:
        score += 4.0
    return score


def _parsed_day(published: str):
    raw = (published or "").strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        got = parsedate_to_datetime(raw)
        if got is not None:
            return got.date()
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def _near_session(published: str, session: str) -> bool:
    """Keep the session day, the day before, and the next UTC date (after-close wraps)."""
    if not session:
        return True
    day = _parsed_day(published)
    if day is None:
        return True
    try:
        anchor = dt.date.fromisoformat(str(session)[:10])
    except ValueError:
        return True
    return (anchor - dt.timedelta(days=1)) <= day <= (anchor + dt.timedelta(days=1))


def explains_the_move(title: str, summary: str = "") -> bool:
    """True for a market wrap or a headline about why the market moved. Not a side story."""
    if _looks_single_stock(title):
        return False
    blob = _norm(title) + _norm(summary)
    if any(bit in blob for bit in _OFF_TOPIC):
        return False
    if market_wrap_score(title, summary) > 0:
        return True
    driver = any(bit in blob for bit in _DRIVER_BITS)
    market = any(bit in blob for bit in _MARKET_BITS)
    return driver and market


def pick_headlines(
    raw: List[Dict[str, Any]],
    limit: int = 7,
    session: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Keep 5–7 big-picture headlines about why the market moved.

    Market-wrap and "stocks fell because" stories rank first. Side stories
    (one stock, old wires, politics with no market) are dropped.
    """
    limit = max(3, min(int(limit or 7), 7))
    target = limit

    prepared: List[Dict[str, Any]] = []
    for h in raw or []:
        title = (h.get("title") or "").strip()
        summary = h.get("summary") or ""
        if not title or not explains_the_move(title, summary):
            continue
        if session and not _near_session(h.get("published") or "", session):
            continue
        tags = h.get("causes") or tag_headline(title, summary)
        item = {
            "title": title,
            "source": h.get("source") or "",
            "url": h.get("url") or "",
            "published": h.get("published") or "",
            "summary": summary,
            "trusted": bool(h.get("trusted")),
            "causes": tags,
            "via": h.get("via") or "",
            "wrap": market_wrap_score(title, summary),
        }
        prepared.append(item)

    def rank_key(h: Dict[str, Any]) -> Tuple:
        on_day = 1 if session and _parsed_day(h.get("published") or "") and str(_parsed_day(h.get("published") or "")) == str(session)[:10] else 0
        return (
            h.get("wrap") or 0.0,
            on_day,
            _importance_score(h["title"], h.get("summary") or ""),
            len(h.get("causes") or []),
            1 if h.get("trusted") else 0,
            h["title"].lower(),
        )

    prepared.sort(key=rank_key, reverse=True)

    seen_keys = set()
    kept: List[Dict[str, Any]] = []
    for h in prepared:
        key = _title_key(h["title"])
        if key in seen_keys:
            continue
        if any(_near_duplicate(h["title"], k["title"]) or _same_tape(h["title"], k["title"]) for k in kept):
            continue
        seen_keys.add(key)
        # Drop summary from the published brief payload (UI uses title/source/url).
        kept.append({
            "title": h["title"],
            "source": h["source"],
            "url": h["url"],
            "published": h["published"],
            "trusted": h["trusted"],
            "causes": h["causes"],
            "via": h.get("via") or "",
            "rank": round(
                (h.get("wrap") or 0.0)
                + _importance_score(h["title"], h.get("summary") or "")
                + 0.5 * len(h["causes"] or []),
                2,
            ),
        })
        if len(kept) >= target:
            break

    # If we asked for 5–7 but only got a few, try a looser fill (still no single-stock).
    if len(kept) < min(5, target):
        for h in prepared:
            if len(kept) >= target:
                break
            key = _title_key(h["title"])
            if key in seen_keys:
                continue
            if any(_near_duplicate(h["title"], k["title"]) or _same_tape(h["title"], k["title"]) for k in kept):
                continue
            seen_keys.add(key)
            kept.append({
                "title": h["title"],
                "source": h["source"],
                "url": h["url"],
                "published": h["published"],
                "trusted": h["trusted"],
                "causes": h["causes"],
                "via": h.get("via") or "",
                "rank": 0.0,
            })
    return kept[:target]


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
        return True
    return False
