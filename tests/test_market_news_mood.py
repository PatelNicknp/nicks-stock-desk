"""Offline mood / regime / breadth / why-moved tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news.brief import load_sectors, load_stats
from market_news.mood import breadth_vs_price, mood_chip, regime_note, why_moved

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "market_news", "fixtures")


def test_fear_on_down_tech_day():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    mood = mood_chip(stats)
    assert mood["label"] == "Fear"
    assert mood["vix"] == 21.98
    assert "VIX" in mood["why"]


def test_calm_when_quiet():
    mood = mood_chip({
        "vix": 14.0, "put_call_zone": "Greed", "advancers": 300, "decliners": 200,
    })
    assert mood["label"] == "Calm"


def test_mixed_mid():
    mood = mood_chip({
        "vix": 18.0, "put_call_zone": "Greed", "advancers": 250, "decliners": 250,
    })
    assert mood["label"] == "Mixed"


def test_regime_uptrend_from_fixture():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    reg = regime_note(stats)
    assert reg["label"] == "uptrend"
    assert reg["pct_above_50day"] == 66.9


def test_regime_selloff():
    reg = regime_note({"breadth_sma50": 30, "breadth_sma200": 35})
    assert reg["label"] == "selloff"


def test_breadth_aligned_decline():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    b = breadth_vs_price(stats)
    assert b["aligned"] is True
    assert b["flag"] == "broad_decline"


def test_breadth_divergence():
    b = breadth_vs_price({"spy_day_pct": 1.2, "advancers": 100, "decliners": 400})
    assert b["aligned"] is False
    assert b["flag"] == "index_up_stocks_down"


def test_why_moved_mentions_tech_and_staples():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    text = why_moved(stats, sectors)
    assert "Nasdaq" in text and "S&P" in text
    assert "Technology" in text
    assert "Consumer Staples" in text or "Health Care" in text
    assert "222" in text and "299" in text
    assert "VIX" in text
    assert "(222 stocks up, 299 down)" in text
    assert "held up(" not in text  # spacing regression guard


def test_why_moved_prefers_spdr_over_industry_etf():
    # The live sectors file includes industry ETFs. A wild industry print
    # must not replace the 11 SPDR sector ETFs in the sentence.
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    sectors = list(sectors) + [{
        "ticker": "ITA", "name": "Aerospace and Defense", "day_pct": "-67.36",
    }]
    text = why_moved(stats, sectors)
    assert "Aerospace" not in text
    assert "Technology" in text


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
