"""Learning stub helpers."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news import learning


def test_backfill_and_stats():
    history = [
        {"date": "2026-11-03", "causes": ["election"], "sources": ["Reuters"],
         "next_day_spy_pct": None, "next_day_direction": None},
        {"date": "2026-11-04", "causes": ["ai_mood"], "sources": ["Reuters", "AP"],
         "next_day_spy_pct": None, "next_day_direction": None},
    ]
    out = learning.backfill_next_day(history, "2026-11-05", -2.73)
    assert out[-1]["next_day_direction"] == "down"
    assert out[-1]["next_day_spy_pct"] == -2.73
    # Older unfinished row left alone on this pass (only latest prior filled)
    assert out[0]["next_day_direction"] is None
    stats = learning.cause_source_stats(out)
    assert stats["n_labeled"] == 1
    assert stats["by_cause"]["ai_mood"]["down"] == 1


if __name__ == "__main__":
    test_backfill_and_stats()
    print("ok test_backfill_and_stats")
