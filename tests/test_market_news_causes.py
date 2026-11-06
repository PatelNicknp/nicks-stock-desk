"""Cause tagging, ranking, and headline filtering."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news.brief import load_sectors, load_stats
from market_news.causes import pick_headlines, score_causes, tag_headline
from market_news import news_fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "market_news", "fixtures")


def test_tag_ai_and_oil():
    assert "ai_mood" in tag_headline("Nasdaq slides as AI and chip stocks sell off")
    assert "oil" in tag_headline("Oil prices firm on OPEC talk")
    assert "election" in tag_headline("Markets digest US midterm results")
    assert "rates" in tag_headline("Federal Reserve signals patience on interest rates")


def test_drops_single_stock_noise():
    raw = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    kept = pick_headlines(raw, limit=7)
    titles = " | ".join(h["title"] for h in kept)
    assert "Thomson Reuters Stock Plummeted" not in titles
    assert "NVDA shares surge" not in titles
    assert any("Nasdaq" in h["title"] for h in kept)
    assert 5 <= len(kept) <= 7


def test_cause_ranking_prefers_ai_on_down_tech_day():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    raw = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    headlines = pick_headlines(raw, limit=7)
    causes = score_causes(headlines, stats, sectors)
    assert len(causes) <= 2
    assert causes[0]["cause"] == "ai_mood"
    assert causes[0]["label"] == "AI / Tech mood"


def test_dedup_near_duplicate_ai_story():
    raw = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    kept = pick_headlines(raw, limit=7)
    titles = [h["title"] for h in kept]
    # CNBC near-dupe of Reuters AI/Nasdaq story should be dropped
    assert sum("AI" in t or "ai" in t.lower() or "Nasdaq" in t for t in titles if "chip" in t.lower() or "AI" in t or "ai trade" in t.lower()) <= 2
    assert not any("AI trade wobbles" in t for t in titles)


def test_wraps_outrank_side_stories():
    raw = [
        {"title": "First Lady Melania Trump Unites Russia and Ukraine at the White House",
         "source": "White House", "trusted": True, "published": "2026-11-05"},
        {"title": "Does the blue wave mean lower gasoline prices soon?",
         "source": "NPR", "trusted": True, "published": "2026-11-05"},
        {"title": "Federal Reserve issues FOMC statement",
         "source": "Federal Reserve", "trusted": True, "published": "2026-10-28"},
        {"title": "Why IonQ stock just fell 10% today",
         "source": "Yahoo Finance", "trusted": True, "published": "2026-11-05"},
        {"title": "Nasdaq posts biggest daily drop in 19 months on fears of AI regulations",
         "source": "Reuters", "trusted": True, "published": "2026-11-05"},
        {"title": "Top Democrats call to rein in AI buildout after midterms: National data center moratorium now",
         "source": "CNBC", "trusted": True, "published": "2026-11-05"},
    ]
    kept = pick_headlines(raw, limit=7, session="2026-11-05")
    titles = [h["title"] for h in kept]
    assert titles[0].startswith("Nasdaq posts biggest daily drop")
    blob = " | ".join(titles)
    assert "Melania" not in blob
    assert "gasoline" not in blob.lower()
    assert "FOMC statement" not in blob
    assert "IonQ" not in blob
    assert any("data center" in t.lower() for t in titles)


def test_ranking_prefers_trusted_fed():
    raw = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    kept = pick_headlines(raw, limit=7)
    sources = [h["source"] for h in kept]
    assert "Federal Reserve" in sources or "Reuters" in sources
    assert all(h.get("rank") is not None for h in kept)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
