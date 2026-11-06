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

# Public feeds — no login. Desk already uses Nasdaq + Cboe + Treasury similarly.
# v2 adds NPR, MarketWatch, Guardian, The Hill for broader big-picture coverage.
FEEDS = (
    {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "source": "Federal Reserve",
        "trusted": True,
    },
    {
        "url": "https://www.bls.gov/feed/bls_latest.rss",
        "source": "Bureau of Labor Statistics",
        "trusted": True,
    },
    {
        "url": "https://www.whitehouse.gov/news/feed/",
        "source": "White House",
        "trusted": True,
    },
    {
        "url": "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
        "source": "Reuters",
        "trusted": True,
    },
    {
        "url": "https://feeds.npr.org/1006/rss.xml",
        "source": "NPR",
        "trusted": True,
    },
    {
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "source": "BBC Business",
        "trusted": False,
    },
    {
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "source": "CNBC",
        "trusted": False,
    },
    {
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "source": "MarketWatch",
        "trusted": False,
    },
    {
        "url": "https://www.theguardian.com/us/business/rss",
        "source": "Guardian Business",
        "trusted": False,
    },
    {
        "url": "https://thehill.com/feed/",
        "source": "The Hill",
        "trusted": False,
    },
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
        if not title:
            continue
        items.append({
            "title": title,
            "url": link,
            "summary": summary[:280],
            "published": published,
            "source": source,
            "trusted": trusted or _is_trusted(source),
        })
    return items


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
            "trusted": bool(r.get("trusted")) if "trusted" in r else _is_trusted(source),
        })
    return [h for h in out if h["title"]]
