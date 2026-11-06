"""Offline tips box tests — research only, no single-stock advice."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news.tips import build_tips


def test_fear_broad_decline_uptrend_tips():
    tips = build_tips(
        mood={"label": "Fear", "vix": 22.0},
        regime={"label": "uptrend"},
        breadth={"flag": "broad_decline"},
        stats={"vix": 22.0},
    )
    assert tips["title"] == "What it means for me"
    assert 2 <= len(tips["lines"]) <= 3
    blob = " ".join(tips["lines"]).lower()
    assert "patient" in blob or "slow" in blob or "fear" in blob
    assert "up" in blob  # trend still up line
    assert "nvda" not in blob
    assert "buy aapl" not in blob
    assert "research" in tips["disclaimer"].lower()


def test_chop_calmish_tips():
    tips = build_tips(
        mood={"label": "Mixed", "vix": 18.0},
        regime={"label": "chop"},
        breadth={"flag": "flat_or_mixed"},
        stats={"vix": 18.0},
    )
    blob = " ".join(tips["lines"]).lower()
    assert "choppy" in blob or "patient" in blob
    assert "chop" in blob


def test_never_names_a_ticker():
    tips = build_tips(
        mood={"label": "Calm", "vix": 14.0},
        regime={"label": "uptrend"},
        breadth={"flag": "broad_advance"},
        stats={"vix": 14.0},
    )
    blob = " ".join(tips["lines"]).upper()
    for t in ("NVDA", "AAPL", "TSLA", "META", "AMZN"):
        assert t not in blob


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
