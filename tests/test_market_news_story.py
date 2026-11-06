"""The Today card only names a cause when a headline and a desk number agree."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news.brief import build_brief, load_sectors, load_stats
from market_news import news_fetch
from market_news.story import build_story

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "market_news", "fixtures")


def _parts():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    headlines = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    calendar = json.load(open(os.path.join(FIX, "calendar.json")))
    prior = json.load(open(os.path.join(FIX, "prior_brief.json")))
    history = json.load(open(os.path.join(FIX, "history_seed.json")))["rows"]
    brief = build_brief(
        stats=stats, sectors=sectors, headlines_raw=headlines, calendar=calendar,
        prior_brief=prior, slot="morning_open", now_et_hour=10, history_rows=history,
    )
    return stats, sectors, brief


def test_fixture_story_uses_the_ai_headline_and_desk_numbers():
    _stats, _sectors, brief = _parts()
    story = brief["story"]
    assert story["clear_cause"] is True
    assert story["cause"] == "ai_mood"
    assert story["lead"] == "Chip and tech shares led stocks lower."
    assert "AI and chip stocks sell off" in story["support"]
    assert story["support_ref"] == 1
    assert story["news"][0]["title"] in story["support"]
    assert story["news"][0]["source"] == "Reuters"
    assert 2 <= len(story["bullets"]) <= 3
    assert story["bullets"][0]["lead"] == "Technology took the biggest hit."
    assert "6.2%" in story["bullets"][0]["rest"]
    # The tech bullet may cite the chip headline. It must not cite a random one.
    assert story["bullets"][0]["ref"] == 1
    titles = [n["title"] for n in story["news"]]
    for b in story["bullets"]:
        if b["ref"] is not None:
            assert 1 <= b["ref"] <= len(titles)
    assert story["sector_label"] == "Where the selling hit"
    names = [c["name"] for c in story["chips"]]
    assert "Tech" in names
    assert any(c["kind"] == "summary" and c["name"] != "All 11 sectors down" for c in story["chips"])
    assert all(i["name"] != "Dow" for i in story["indexes"])
    spy = [i for i in story["indexes"] if i["name"] == "S&P 500"][0]
    assert spy["pct_text"] == "2.73%" and spy["arrow"] == "down"
    blob = json.dumps(story).lower()
    assert "data center" not in blob
    assert "nvda" not in blob
    assert "tighter rules" not in blob


def test_no_headline_means_no_invented_cause():
    stats = {
        "spy_day_pct": -2.7, "qqq_day_pct": -5.0, "vix": 22,
        "advancers": 200, "decliners": 300, "price_as_of": "2026-11-05",
    }
    sectors = [
        {"ticker": "XLK", "name": "Technology", "day_pct": -6.2},
        {"ticker": "XLP", "name": "Consumer Staples", "day_pct": 0.9},
    ]
    story = build_story(stats, sectors, [], [], slot="evening_close")
    assert story["clear_cause"] is False
    assert story["cause"] is None
    assert story["support_ref"] is None
    assert "No clear cause" in story["support"]
    assert story["lead"] == "The Nasdaq led stocks lower."
    assert "AI" not in story["lead"]


def test_headline_without_a_desk_link_is_not_the_cause():
    stats = {
        "spy_day_pct": -0.2, "qqq_day_pct": -0.1, "vix": 14,
        "advancers": 250, "decliners": 250, "price_as_of": "2026-11-05",
    }
    sectors = [
        {"ticker": "XLK", "name": "Technology", "day_pct": -0.1},
        {"ticker": "XLE", "name": "Energy", "day_pct": 0.1},
    ]
    headlines = [{
        "title": "Election results keep Washington in the headlines",
        "source": "Reuters",
        "url": "https://www.reuters.com/example/election",
        "published": "2026-11-05T12:00:00Z",
        "trusted": True,
        "causes": ["election"],
    }]
    causes = [{"cause": "election", "label": "Election", "score": 3, "headlines": headlines}]
    story = build_story(stats, sectors, headlines, causes, slot="morning_open")
    assert story["clear_cause"] is False
    assert "Election" not in story["lead"]
    assert "No clear cause" in story["support"]
    assert story["summary"] == "U.S. morning summary"


def test_ai_regulation_wrap_is_the_cause_when_chips_led():
    stats = {
        "spy_day_pct": -2.73, "qqq_day_pct": -4.98, "vix": 22,
        "advancers": 222, "decliners": 299, "price_as_of": "2026-11-05",
    }
    sectors = [
        {"ticker": "XLK", "name": "Technology", "day_pct": -6.2},
        {"ticker": "SMH", "name": "Semiconductors", "day_pct": -8.91},
        {"ticker": "XLF", "name": "Financials", "day_pct": -0.79},
        {"ticker": "XLP", "name": "Consumer Staples", "day_pct": 1.09},
    ]
    headlines = [
        {
            "title": "Nasdaq posts biggest daily drop in 19 months on fears of AI regulations",
            "source": "Reuters", "via": "Investing.com",
            "url": "https://www.investing.com/news/stock-market-news/example",
            "published": "2026-11-05", "trusted": True, "causes": ["ai_mood"], "rank": 20,
        },
        {
            "title": "Federal Reserve issues FOMC statement",
            "source": "Federal Reserve",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm",
            "published": "2026-10-28", "trusted": True, "causes": ["rates"], "rank": 5,
        },
    ]
    causes = [
        {"cause": "ai_mood", "label": "AI / Tech mood", "score": 8, "headlines": [headlines[0]]},
        {"cause": "rates", "label": "Rates / Fed", "score": 4, "headlines": [headlines[1]]},
    ]
    story = build_story(stats, sectors, headlines, causes, slot="evening_close")
    assert story["clear_cause"] is True
    assert story["cause"] == "ai_mood"
    assert story["lead"] == "AI regulation fears sent stocks lower."
    assert "AI regulations" in story["support"]
    assert story["news"][0]["source"] == "Reuters"
    assert story["news"][0]["via"] == "Investing.com"
    assert all(i["name"] != "Dow" for i in story["indexes"])


def test_fed_headline_and_a_high_vix_are_not_a_rates_cause():
    stats = {
        "spy_day_pct": -2.73, "qqq_day_pct": -4.98, "vix": 22,
        "advancers": 222, "decliners": 299, "price_as_of": "2026-11-05",
    }
    sectors = [
        {"ticker": "XLK", "name": "Technology", "day_pct": -6.2},
        {"ticker": "XLF", "name": "Financials", "day_pct": -0.79},
        {"ticker": "XLP", "name": "Consumer Staples", "day_pct": 1.09},
    ]
    headlines = [{
        "title": "Federal Reserve issues FOMC statement",
        "source": "Federal Reserve",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm",
        "published": "2026-10-28T18:00:00Z",
        "trusted": True,
        "causes": ["rates"],
    }]
    causes = [{"cause": "rates", "label": "Rates / Fed", "score": 4, "headlines": headlines}]
    story = build_story(stats, sectors, headlines, causes, slot="morning_open")
    assert story["clear_cause"] is False
    assert story["lead"] == "The Nasdaq led stocks lower."
    assert "Rates were part" not in story["lead"]
    assert "No clear cause" in story["support"]


def test_dow_prints_when_the_desk_has_one():
    stats = {"spy_day_pct": 0.4, "qqq_day_pct": 0.5, "dia_day_pct": 0.22, "price_as_of": "2026-11-05"}
    story = build_story(stats, [], [], [], slot="evening_close")
    dow = [i for i in story["indexes"] if i["name"] == "Dow"][0]
    assert dow["pct"] == 0.22 and dow["arrow"] == "up"
    assert story["sector_label"] == "Where the buying was"


def test_all_sectors_down_chip():
    sectors = [
        {"ticker": "XL%s" % i, "name": "Sector %s" % i, "day_pct": -1.0 - i}
        for i in range(11)
    ]
    # Give them real SPDR tickers so they count.
    tickers = ["XLK", "XLV", "XLF", "XLI", "XLC", "XLY", "XLP", "XLE", "XLU", "XLRE", "XLB"]
    sectors = [{"ticker": t, "name": t, "day_pct": -1.5} for t in tickers]
    stats = {"spy_day_pct": -2.0, "qqq_day_pct": -2.2, "price_as_of": "2026-11-05"}
    story = build_story(stats, sectors, [], [], slot="evening_close")
    assert any(c["name"] == "All 11 sectors down" for c in story["chips"])


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
