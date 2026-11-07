"""End-to-end offline brief build + learning stubs."""
import csv
import json
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news.brief import build_brief, load_sectors, load_stats, publish, read_json
from market_news import news_fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "market_news", "fixtures")


def _build():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    headlines = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    calendar = json.load(open(os.path.join(FIX, "calendar.json")))
    prior = json.load(open(os.path.join(FIX, "prior_brief.json")))
    history = json.load(open(os.path.join(FIX, "history_seed.json")))["rows"]
    return build_brief(
        stats=stats, sectors=sectors, headlines_raw=headlines, calendar=calendar,
        prior_brief=prior, slot="morning_open", now_et_hour=10, history_rows=history,
    )


def test_sample_brief_shape():
    brief = _build()
    hist = brief.pop("_history")
    assert brief["schema_version"] == 2
    assert brief["feature"] == "market_news"
    assert brief["session"] == "2026-11-05"
    assert brief["slot"] == "morning_open"
    assert brief["mood"]["label"] == "Fear"
    assert "Nasdaq" in brief["why_moved"]
    assert 5 <= len(brief["headlines"]) <= 7
    assert len(brief["causes"]) <= 2
    assert brief["causes"][0]["cause"] == "ai_mood"
    assert brief["vs_yesterday"]["flipped"] is True
    assert brief["breadth_check"]["flag"] == "broad_decline"
    assert brief["regime"]["label"] == "uptrend"
    assert brief["calendar"]["next"]["event"]
    assert brief["prior_brief"]["mood"] == "Mixed"
    assert "never places trades" in brief["disclaimer"].lower()
    # No single-stock chips
    blob = json.dumps(brief)
    assert "NVDA shares surge" not in blob
    assert "Thomson Reuters Stock Plummeted" not in blob
    # Learning backfilled Nov 4 from today's SPY move
    labeled = [r for r in hist if r.get("next_day_direction")]
    assert labeled
    assert labeled[-1]["date"] == "2026-11-04"
    assert labeled[-1]["next_day_direction"] == "down"
    assert brief["learning"]["stats"]["n_labeled"] >= 1


def test_publish_offline_roundtrip():
    tmp = tempfile.mkdtemp(prefix="mnp-")
    try:
        shutil.copy(os.path.join(FIX, "market_today.csv"), os.path.join(tmp, "market_today.csv"))
        shutil.copy(os.path.join(FIX, "sectors.csv"), os.path.join(tmp, "sectors.csv"))
        headlines = json.load(open(os.path.join(FIX, "headlines.json")))
        calendar = json.load(open(os.path.join(FIX, "calendar.json")))
        # Seed prior brief + history
        shutil.copy(os.path.join(FIX, "prior_brief.json"), os.path.join(tmp, "market_brief.json"))
        with open(os.path.join(tmp, "market_brief_history.json"), "w") as f:
            json.dump(json.load(open(os.path.join(FIX, "history_seed.json"))), f)

        brief = publish(
            data_dir=tmp,
            mode="offline",
            now_et=__import__("datetime").datetime(2026, 11, 5, 10, 15, 0),
            offline_headlines=headlines,
            offline_calendar=calendar,
        )
        assert os.path.exists(os.path.join(tmp, "market_brief.json"))
        assert os.path.exists(os.path.join(tmp, "market_brief_history.json"))
        saved = read_json(os.path.join(tmp, "market_brief.json"))
        assert saved["mood"]["label"] == brief["mood"]["label"] == "Fear"
        assert saved["why_moved"]
        hist = read_json(os.path.join(tmp, "market_brief_history.json"))
        assert hist["rows"]
    finally:
        shutil.rmtree(tmp)


def test_pack_sample_file_matches_narrative():
    """Down-tech-day narrative is built from the fixture as-of, not the live brief.

    The desk overwrites data/market_brief.json. This check uses market_today.csv
    in the fixture, whose price_as_of is 2026-11-05, and the same headlines.
    """
    with open(os.path.join(FIX, "market_today.csv"), newline="", encoding="utf-8") as handle:
        as_of = next(csv.DictReader(handle))
    sample = _build()
    sample.pop("_history", None)
    assert as_of["price_as_of"] == "2026-11-05"
    assert sample["session"] == as_of["price_as_of"]
    assert sample["schema_version"] == 2
    assert sample["mood"]["label"] == "Fear"
    assert "Technology" in sample["why_moved"]
    assert sample["why_moved_short"]
    assert sample["tips"] and len(sample["tips"]["lines"]) >= 2
    assert 5 <= len(sample["headlines"]) <= 7
    assert sample["stats"]["qqq_day_pct"] == float(as_of["qqq_day_pct"]) == -4.98
    assert sample["stats"]["spy_day_pct"] == float(as_of["spy_day_pct"]) == -2.73


def test_published_brief_tracks_the_desk_as_of():
    """The committed brief follows the desk file. It is not the fixture narrative."""
    live = json.load(open(os.path.join(ROOT, "data/market_brief.json")))
    with open(os.path.join(ROOT, "data/market_today.csv"), newline="", encoding="utf-8") as handle:
        desk = next(csv.DictReader(handle))
    assert live["session"] == desk["price_as_of"]
    assert live["price_as_of"] == desk["price_as_of"]
    assert live["stats"]["spy_day_pct"] == float(desk["spy_day_pct"])
    assert live["stats"]["qqq_day_pct"] == float(desk["qqq_day_pct"])
    assert "25030.35" not in json.dumps(live)

def test_v2_why_detail_and_tips_shape():
    brief = _build()
    brief.pop("_history", None)
    # 2–3 sentences
    assert brief["why_moved"].count(".") >= 2
    assert "Biggest driver" in brief["why_moved"] or "AI / Tech" in brief["why_moved"]
    assert "broad" in brief["why_moved"].lower() or "222" in brief["why_moved"]
    assert brief["why_moved_short"]
    assert brief["why_moved"] != brief["why_moved_short"]
    tips = brief["tips"]
    assert tips["title"] == "What it means for me"
    assert 2 <= len(tips["lines"]) <= 3
    blob = " ".join(tips["lines"]).lower()
    assert "nvda" not in blob and "aapl" not in blob
    assert "research" in tips["disclaimer"].lower()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
