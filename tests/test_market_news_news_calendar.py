"""RSS parse + calendar parse (offline fixtures, no network)."""
import json
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news import calendar_fetch, news_fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "market_news", "fixtures")


def test_parse_fed_rss():
    xml = open(os.path.join(FIX, "sample_rss_fed.xml"), encoding="utf-8").read()
    rows = news_fetch.parse_rss(xml, "Federal Reserve", True)
    assert len(rows) == 2
    assert rows[0]["trusted"] is True
    assert "FOMC" in rows[0]["title"] or "Federal Reserve" in rows[0]["title"]


def test_calendar_from_fixture():
    cal = json.load(open(os.path.join(FIX, "calendar.json")))
    got = calendar_fetch.next_events(
        today=dt.date(2026, 11, 5),
        fixture_rows=cal["week"],
    )
    assert got["next"]["event"] == "Initial Jobless Claims"
    assert "Jobless" in got["text"]


def test_calendar_payload_parser():
    payload = {
        "data": {
            "rows": [
                {"country": "United States", "eventName": "CPI Urban Consumer", "time": "08:30",
                 "consensus": "0.2%", "previous": "0.1%"},
                {"country": "Germany", "eventName": "CPI", "time": "08:00"},
                {"country": "US", "eventName": "Something Minor", "time": "09:00"},
            ]
        }
    }
    rows = calendar_fetch.parse_day_payload(payload, dt.date(2026, 11, 10))
    assert len(rows) == 2
    assert rows[0]["country"] == "US"
    assert rows[1]["country"] == "Europe"
    assert rows[0]["event"].startswith("CPI")
    assert all("Minor" not in r["event"] for r in rows)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
