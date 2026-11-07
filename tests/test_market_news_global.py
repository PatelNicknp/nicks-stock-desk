"""Global macro headlines stay in the market brief. Company stories and bad links do not."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news import news_fetch
from market_news.causes import pick_headlines, region_of


def test_macro_abroad_is_kept_and_a_company_story_is_not():
    raw = [
        {"title": "Nasdaq posts biggest daily drop in 19 months on fears of AI regulations",
         "source": "Reuters", "trusted": True, "published": "2026-11-05", "url": "https://www.reuters.com/markets/us/ai"},
        {"title": "ECB holds rates as euro-area inflation cools",
         "source": "European Central Bank", "trusted": True, "published": "2026-11-05",
         "url": "https://www.ecb.europa.eu/press/pr/date/2026/html/example.en.html"},
        {"title": "Bank of Japan signals a further rate hike and the yen jumps",
         "source": "Reuters", "trusted": True, "published": "2026-11-05",
         "url": "https://www.reuters.com/markets/asia/boj"},
        {"title": "Oil jumps after a Gulf shipping threat",
         "source": "Reuters", "trusted": True, "published": "2026-11-05",
         "url": "https://www.reuters.com/markets/commodities/oil"},
        {"title": "Apple earnings beat estimates",
         "source": "CNBC", "trusted": True, "published": "2026-11-05",
         "url": "https://www.cnbc.com/apple-earnings"},
        {"title": "Diwali festival draws crowds in Mumbai",
         "source": "BBC", "trusted": True, "published": "2026-11-05",
         "url": "https://www.bbc.com/news/festival"},
        {"title": "NVDA shares surge after a rumor",
         "source": "Yahoo Finance", "trusted": True, "published": "2026-11-05",
         "url": "https://finance.yahoo.com/quote/NVDA"},
    ]
    kept = pick_headlines(raw, limit=7, session="2026-11-05")
    titles = [h["title"] for h in kept]
    blob = " | ".join(titles)
    assert any(t.startswith("Nasdaq posts") for t in titles)
    assert any("ECB" in t for t in titles)
    assert any("Bank of Japan" in t for t in titles)
    assert any(t.startswith("Oil jumps") for t in titles)
    assert "Apple" not in blob
    assert "Diwali" not in blob
    assert "NVDA" not in blob
    ecb = [h for h in kept if "ECB" in h["title"]][0]
    assert ecb["region"] == "Europe"
    assert "not proof" in ecb["why"]
    assert "Possible transmission" in ecb["why"]
    assert region_of("Reserve Bank of India holds rates, rupee firms") == "India"


def test_dedup_and_stale_and_bad_url():
    raw = [
        {"title": "China tariffs rattle global stock markets",
         "source": "Reuters", "trusted": True, "published": "2026-11-05",
         "url": "https://www.reuters.com/world/china/tariffs"},
        {"title": "China tariffs rattle global stock markets today",
         "source": "AP", "trusted": True, "published": "2026-11-05",
         "url": "https://apnews.com/article/china-tariffs"},
        {"title": "Federal Reserve issues FOMC statement on interest rates",
         "source": "Federal Reserve", "trusted": True, "published": "2026-10-01",
         "url": "javascript:alert(1)"},
        {"title": "Bank of England holds rates and gilt yields fall",
         "source": "Bank of England", "trusted": True, "published": "2026-11-05",
         "url": "https://www.bankofengland.co.uk/news/example"},
    ]
    kept = pick_headlines(raw, limit=7, session="2026-11-05")
    titles = [h["title"] for h in kept]
    assert sum("China tariffs" in t for t in titles) == 1
    assert not any("FOMC" in t for t in titles)
    assert all(not (h.get("url") or "").lower().startswith("javascript:") for h in kept)
    assert any(h["region"] == "UK" for h in kept)


def test_rss_keeps_event_time_and_a_dead_feed_is_skipped():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>ECB press conference on interest rates</title>
        <link>https://www.ecb.europa.eu/press/example</link>
        <pubDate>Thu, 05 Nov 2026 18:30:00 GMT</pubDate>
        <description>The Governing Council left rates unchanged.</description>
      </item>
    </channel></rss>"""
    rows = news_fetch.parse_rss(xml, "European Central Bank", True)
    assert rows[0]["published"]
    assert rows[0]["published_at"]
    assert "PT" in rows[0]["published_pt"]
    assert rows[0]["url"].startswith("https://")

    def boom(url):
        raise OSError("feed down")

    assert news_fetch.fetch_headlines(fetch=boom, feeds=({"url": "https://example.invalid/rss", "source": "BBC", "trusted": True},)) == []


def test_one_region_does_not_crowd_out_another_material_story():
    raw = []
    for i in range(4):
        raw.append({
            "title": "Federal Reserve officials discuss interest rate path number %d" % i,
            "source": "Reuters", "trusted": True, "published": "2026-11-05",
            "url": "https://www.reuters.com/fed/%d" % i,
        })
    raw.append({
        "title": "People's Bank of China cuts rates and Asian stocks rise",
        "source": "Reuters", "trusted": True, "published": "2026-11-05",
        "url": "https://www.reuters.com/world/china/pboc",
    })
    kept = pick_headlines(raw, limit=5, session="2026-11-05")
    assert any(h.get("region") == "China" for h in kept)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("global news ok")
