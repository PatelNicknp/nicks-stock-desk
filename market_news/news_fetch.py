"""Fetch free market-wide headlines (RSS / public XML). No API keys. No Yahoo."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen

from .schema import TRUSTED_SOURCES

UA = (
    "Mozilla/5.0 (compatible; NicksStockDesk/1.0; +https://github.com/PatelNicknp/nicks-stock-desk) "
    "research-only"
)

# Market-wrap feeds only. A feed that blocks or moves is skipped.
# Reuters and AP often refuse a direct RSS; Investing.com carries their wires
# in <author>, and parse_rss keeps that name.
FEEDS = (
    {"url": "https://www.cnbc.com/id/10000664/device/rss/rss.html", "source": "CNBC", "trusted": True},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "source": "CNBC", "trusted": True},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories/", "source": "MarketWatch", "trusted": True},
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US", "source": "Yahoo Finance", "trusted": True},
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EIXIC&region=US&lang=en-US", "source": "Yahoo Finance", "trusted": True},
    {"url": "https://www.investing.com/rss/news_25.rss", "source": "Investing.com", "trusted": True},
    {"url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets", "source": "Nasdaq", "trusted": True},
    {"url": "https://www.reuters.com/rssFeed/businessNews", "source": "Reuters", "trusted": True},
    {"url": "https://apnews.com/hub/business?output=rss", "source": "AP", "trusted": True},
)


def fetch_text(url: str, timeout: int = 20) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "en-US",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def parse_rss(xml_text: str, source: str, trusted: bool) -> List[Dict[str, Any]]:
    """Parse RSS or Atom into a list of headline dicts."""
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items: List[Dict[str, Any]] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = ""
        link = ""
        summary = ""
        published = ""
        author = ""
        for child in list(node):
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "title":
                title = text
            elif name in ("link",):
                href = child.attrib.get("href") if child.attrib else None
                link = href or text or link
            elif name in ("description", "summary", "content"):
                summary = re.sub(r"<[^>]+>", " ", text)
                summary = re.sub(r"\s+", " ", summary).strip()
            elif name in ("pubDate", "published", "updated", "date"):
                published = text
            elif name in ("author", "creator"):
                author = text
        if not title:
            continue
        wire, via = _wire_credit(source, author)
        items.append({
            "title": title,
            "url": link,
            "summary": summary[:280],
            "published": _iso_day(published),
            "source": wire,
            "via": via,
            "trusted": trusted or _is_trusted(wire),
        })
    return items


def _iso_day(published: str) -> str:
    raw = (published or "").strip()
    if not raw:
        return ""
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        return raw[:10]
    try:
        from email.utils import parsedate_to_datetime
        got = parsedate_to_datetime(raw)
        if got is not None:
            return got.date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return raw
    return raw


def _wire_credit(feed_source: str, author: str) -> tuple:
    """Investing.com and similar feeds name Reuters or AP in the author field."""
    who = (author or "").strip()
    low = who.lower()
    feed = feed_source or ""
    if "reuters" in low:
        via = "" if "reuters" in feed.lower() else feed
        return "Reuters", via
    if low in ("ap", "associated press") or "associated press" in low:
        via = "" if feed.lower() in ("ap", "associated press") else feed
        return "AP", via
    return feed, ""


def _is_trusted(source: str) -> bool:
    s = (source or "").lower()
    return any(t.lower() in s for t in TRUSTED_SOURCES)


def fetch_headlines(
    fetch: Optional[Callable[[str], str]] = None,
    feeds: Optional[tuple] = None,
    limit_per_feed: int = 10,
) -> List[Dict[str, Any]]:
    """Live fetch. On any feed error, skip that feed (caller keeps prior brief headlines)."""
    fetch = fetch or fetch_text
    out: List[Dict[str, Any]] = []
    for feed in feeds or FEEDS:
        try:
            xml_text = fetch(feed["url"])
            rows = parse_rss(xml_text, feed["source"], bool(feed.get("trusted")))
            out.extend(rows[:limit_per_feed])
        except Exception:
            continue
    return out


def headlines_from_fixture(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize fixture rows for offline builds/tests."""
    out = []
    for r in rows or []:
        source = r.get("source") or ""
        out.append({
            "title": (r.get("title") or "").strip(),
            "url": r.get("url") or "",
            "summary": r.get("summary") or "",
            "published": r.get("published") or "",
            "source": source,
            "via": r.get("via") or "",
            "trusted": bool(r.get("trusted")) if "trusted" in r else _is_trusted(source),
        })
    return [h for h in out if h["title"]]
