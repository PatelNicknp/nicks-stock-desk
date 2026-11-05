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
    kept = pick_headlines(raw, limit=5)
    titles = " | ".join(h["title"] for h in kept)
    assert "Thomson Reuters Stock Plummeted" not in titles
    assert "NVDA shares surge" not in titles
    assert any("Nasdaq" in h["title"] for h in kept)
    assert 3 <= len(kept) <= 5


def test_cause_ranking_prefers_ai_on_down_tech_day():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    raw = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    headlines = pick_headlines(raw, limit=5)
    causes = score_causes(headlines, stats, sectors)
    assert len(causes) <= 2
    assert causes[0]["cause"] == "ai_mood"
    assert causes[0]["label"] == "AI / Tech mood"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
