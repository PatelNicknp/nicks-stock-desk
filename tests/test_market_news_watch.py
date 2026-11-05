"""Offline tests for the next-session watch line and the Friday week note."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news.brief import build_brief, load_sectors, load_stats
from market_news import news_fetch
from market_news.watch import format_pt, watch_next_line, weekly_recap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "market_news", "fixtures")


def _calendar():
    return json.load(open(os.path.join(FIX, "calendar.json"), encoding="utf-8"))


def test_et_morning_print_is_pacific():
    assert format_pt("08:30") == "5:30 AM PT"
    assert format_pt("14:00") == "11:00 AM PT"
    assert format_pt("2:00 PM") == "11:00 AM PT"


def test_cpi_tomorrow_expects_a_jumpy_open():
    cal = {"week": [{"date": "2026-11-06", "time": "08:30", "event": "CPI"}]}
    assert watch_next_line("2026-11-05", cal) == "CPI tomorrow 5:30 AM PT — expect a jumpy open"


def test_jobless_claims_on_the_fixture_calendar():
    # Thursday Nov 5 brief. Next session is Friday, and claims print at 8:30 ET.
    assert watch_next_line("2026-11-05", _calendar()) == (
        "Jobless claims tomorrow 5:30 AM PT — expect a jumpy open"
    )


def test_afternoon_release_does_not_promise_a_jumpy_open():
    cal = {"next": {"date": "2026-11-06", "time": "14:00", "event": "FOMC Statement"}}
    assert watch_next_line("2026-11-05", cal) == "Fed decision tomorrow 11:00 AM PT"


def test_omit_when_nothing_notable_is_on_the_next_session():
    # CPI is Monday, not Friday. Thursday's next session has nothing scheduled.
    cal = {"week": [{"date": "2026-11-09", "time": "08:30", "event": "CPI"}]}
    assert watch_next_line("2026-11-05", cal) is None
    assert watch_next_line("2026-11-05", {"next": None, "week": []}) is None
    assert watch_next_line("2026-11-05", {}) is None


def test_friday_close_looks_ahead_to_monday():
    cal = {"week": [
        {"date": "2026-11-07", "time": "10:00", "event": "University of Michigan Sentiment"},
        {"date": "2026-11-09", "time": "08:30", "event": "Consumer Price Index"},
    ]}
    assert watch_next_line("2026-11-06", cal) == "CPI Monday 5:30 AM PT — expect a jumpy open"


def _week():
    return [
        {"date": "2026-11-02", "slot": "evening_close", "mood": "Calm", "causes": ["election"]},
        {"date": "2026-11-03", "slot": "evening_close", "mood": "Mixed", "causes": ["ai_mood", "election"]},
        {"date": "2026-11-04", "slot": "evening_close", "mood": "Mixed", "causes": ["ai_mood"]},
        {"date": "2026-11-05", "slot": "evening_close", "mood": "Fear", "causes": ["ai_mood"]},
        {"date": "2026-11-06", "slot": "evening_close", "mood": "Fear", "causes": ["oil", "ai_mood"]},
        # Outside this week. Must not lead the note.
        {"date": "2026-10-30", "slot": "evening_close", "mood": "Calm", "causes": ["war"]},
    ]


def test_friday_close_recap_names_the_week_and_a_worsening_mood():
    got = weekly_recap("2026-11-06", "evening_close", _week())
    assert got["causes"] == ["ai_mood", "election"]
    assert got["mood"] == "worsening"
    assert got["text"] == (
        "This week was driven by AI / Tech mood and Election. Mood is worsening."
    )
    assert "war" not in got["text"].lower()


def test_recap_improving_and_only_on_the_friday_close():
    rows = [
        {"date": "2026-11-02", "slot": "evening_close", "mood": "Fear", "causes": ["war"]},
        {"date": "2026-11-06", "slot": "evening_close", "mood": "Calm", "causes": ["war"]},
    ]
    got = weekly_recap("2026-11-06", "evening_close", rows)
    assert got["mood"] == "improving"
    assert got["text"] == "This week was driven by War / Geopolitics. Mood is improving."
    assert weekly_recap("2026-11-06", "morning_open", rows) is None
    assert weekly_recap("2026-11-05", "evening_close", rows) is None


def test_recap_steady_when_the_mood_does_not_change():
    rows = [
        {"date": "2026-11-02", "slot": "morning_open", "mood": "Mixed", "causes": ["rates"]},
        {"date": "2026-11-06", "slot": "evening_close", "mood": "Mixed", "causes": ["rates"]},
    ]
    got = weekly_recap("2026-11-06", "evening_close", rows)
    assert got["mood"] == "steady"
    assert "Mood is steady." in got["text"]


def test_thursday_brief_has_the_watch_line_and_no_week_note():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    headlines = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    brief = build_brief(
        stats=stats, sectors=sectors, headlines_raw=headlines, calendar=_calendar(),
        slot="morning_open", now_et_hour=10, history_rows=_week(),
    )
    assert brief["session"] == "2026-11-05"
    assert dt.date.fromisoformat(brief["session"]).weekday() == 3  # Thursday
    assert brief["watch_next"] == "Jobless claims tomorrow 5:30 AM PT — expect a jumpy open"
    assert brief["weekly_recap"] is None


def test_friday_close_brief_includes_that_days_mood():
    stats = load_stats(market_today_path=os.path.join(FIX, "market_today.csv"))
    stats["price_as_of"] = "2026-11-06"
    sectors = load_sectors(sectors_path=os.path.join(FIX, "sectors.csv"))
    headlines = news_fetch.headlines_from_fixture(json.load(open(os.path.join(FIX, "headlines.json"))))
    # History stops Thursday. The Friday close stub is this brief (Fear).
    history = [r for r in _week() if r["date"] < "2026-11-06"]
    brief = build_brief(
        stats=stats, sectors=sectors, headlines_raw=headlines, calendar=_calendar(),
        slot="evening_close", now_et_hour=18, history_rows=history,
    )
    assert brief["weekly_recap"]["mood"] == "worsening"
    assert "Mood is worsening." in brief["weekly_recap"]["text"]
    assert brief["weekly_recap"]["causes"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
