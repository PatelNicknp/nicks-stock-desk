"""World-market snapshots: session labels, verified percents, and blank feeds."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_news.world_markets import (
    build_world_moves,
    row_from_boerse,
    session_status,
    verified_change,
)
from market_news.brief import publish
import json
import shutil
import tempfile

UTC = dt.timezone.utc
# Saturday 7 Nov 2026, noon UTC. US cash is closed. India is Saturday evening.
SAT = dt.datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
# Friday 6 Nov 2026, 16:00 UTC = 11:00 New York (EST, UTC-5).
FRI_OPEN = dt.datetime(2026, 11, 6, 16, 0, tzinfo=UTC)


def _idx(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_session_labels_use_the_market_clock_not_retrieval_time():
    friday = dt.date(2026, 11, 6)
    assert session_status(friday, None, SAT, "America/New_York", 9 * 60 + 30, 16 * 60) == "prior_local_close"
    closed_now = dt.datetime(2026, 11, 6, 22, 0, tzinfo=UTC)  # 17:00 New York
    assert session_status(friday, None, closed_now, "America/New_York", 9 * 60 + 30, 16 * 60) == "closed"
    quote = dt.datetime(2026, 11, 6, 15, 50, tzinfo=UTC)  # 10:50 New York
    assert session_status(friday, quote, FRI_OPEN, "America/New_York", 9 * 60 + 30, 16 * 60) == "intraday"
    late = dt.datetime(2026, 11, 6, 15, 20, tzinfo=UTC)  # 10:20 New York, 40 minutes behind
    assert session_status(friday, late, FRI_OPEN, "America/New_York", 9 * 60 + 30, 16 * 60) == "delayed"
    assert session_status(dt.date(2026, 10, 20), None, SAT, "America/New_York", 9 * 60 + 30, 16 * 60) == "stale"
    # 01:00 UTC Saturday is still Friday evening in New York and Saturday morning in Tokyo.
    instant = dt.datetime(2026, 11, 7, 1, 0, tzinfo=UTC)
    assert session_status(dt.date(2026, 11, 6), None, instant, "America/New_York", 9 * 60 + 30, 16 * 60) == "closed"
    assert session_status(dt.date(2026, 11, 6), None, instant, "Asia/Tokyo", 9 * 60, 15 * 60) == "prior_local_close"
    assert session_status(dt.date(2026, 11, 7), None, instant, "Asia/Tokyo", 9 * 60, 15 * 60) == "unknown"


def test_percent_needs_two_prices_that_agree():
    assert verified_change(25030.35, 24536.6, 2.01) == 2.01
    assert verified_change(110, 100, None) == 10.0
    assert verified_change(25683.872, 25683.872, -1.96) is None
    assert verified_change(110, 100, 5.0) is None
    assert verified_change(None, None, 1.2) is None


def test_proxy_does_not_fill_the_index_and_breadth_stays_unknown():
    moves = build_world_moves(
        stats={"spy_day_pct": 1.02, "qqq_day_pct": 2.03, "price_as_of": "2026-11-06"},
        quotes={},
        now=SAT,
        headlines=[{
            "title": "Nifty 50 rises as banks lead",
            "source": "Reuters",
            "url": "javascript:alert(1)",
        }, {
            "title": "S&P 500 futures dip as tech sells off",
            "source": "CNBC",
            "url": "https://example.com/dip",
        }, {
            "title": "S&P 500 ends higher after a quiet session",
            "source": "Reuters",
            "url": "https://example.com/spx",
        }],
    )
    spx = _idx(moves["rows"], "S&P 500")
    spy = _idx(moves["rows"], "SPY")
    assert spx["pct"] is None and spx["kind"] == "index" and spx["cause"] == ""
    assert spy["pct"] == 1.02 and spy["kind"] == "etf_proxy"
    assert spy["status"] == "prior_local_close"
    assert spy["session_date"] == "2026-11-06"
    assert "ETF proxy" in spy["note"]
    assert spy["cause_url"] == "https://example.com/spx"
    assert "Not proof" in spy["cause"]
    nifty = _idx(moves["rows"], "Nifty 50")
    assert nifty["cause_url"] == ""
    assert moves["breadth"] == "unknown"
    assert "worldwide" in moves["summary"].lower()
    assert "rally" not in moves["summary"].lower()
    assert all(r["id"] != "spy" or r in moves["strip"] for r in moves["strip"])
    assert moves["strip"][0]["name"] == "SPY"


def test_verified_nifty_and_failed_vendor_percent():
    spec = {
        "id": "dax", "name": "DAX", "region": "Europe", "tz": "Europe/Berlin",
        "open_min": 9 * 60, "close_min": 17 * 60 + 30, "isin": "DE0008469008",
        "words": ("dax",),
    }
    blank = row_from_boerse(spec, {
        "isin": "DE0008469008",
        "lastPrice": 25683.872,
        "closingPricePrevTradingDay": 25683.872,
        "changeToPrevDayInPercent": -1.96,
        "timestampLastPrice": "2026-11-06T22:00:25+01:00",
    }, SAT)
    assert blank["pct"] is None
    assert blank["session_date"] == "2026-11-06"
    assert "2026-11-07" not in blank["session_date"]

    moves = build_world_moves(
        stats={"price_as_of": "2026-11-06"},
        quotes={"nse": {
            "timestamp": "06-Nov-2026 15:30",
            "data": [{"index": "NIFTY 50", "last": 25030.35, "previousClose": 24536.6, "percentChange": 2.01}],
        }, "DE0008469008": {"error": "down"}},
        now=SAT,
    )
    nifty = _idx(moves["rows"], "Nifty 50")
    assert nifty["pct"] == 2.01
    assert nifty["verified"] is True
    assert nifty["kind"] == "index"
    assert nifty["status"] == "prior_local_close"
    assert nifty["session_date"] == "2026-11-06"
    assert nifty["source"] == "NSE India"
    dax = _idx(moves["rows"], "DAX")
    assert dax["pct"] is None
    nikkei = _idx(moves["rows"], "Nikkei 225")
    assert nikkei["pct"] is None and "does not republish" in nikkei["note"]
    assert moves["breadth"] == "unknown"


def test_three_verified_indexes_can_agree_without_calling_it_global():
    now = dt.datetime(2026, 11, 6, 21, 0, tzinfo=UTC)
    quotes = {
        "EU0009658202": {
            "isin": "EU0009658202",
            "lastPrice": 110,
            "closingPricePrevTradingDay": 100,
            "changeToPrevDayInPercent": 10,
            "timestampLastPrice": "2026-11-06T17:30:00+01:00",
        },
        "GB0001383545": {
            "isin": "GB0001383545",
            "lastPrice": 110,
            "closingPricePrevTradingDay": 100,
            "changeToPrevDayInPercent": 10,
            "timestampLastPrice": "2026-11-06T16:35:00+00:00",
        },
        "nse": {
            "timestamp": "06-Nov-2026 15:30",
            "data": [{"index": "NIFTY 50", "last": 110, "previousClose": 100, "percentChange": 10}],
        },
    }
    moves = build_world_moves(stats={}, quotes=quotes, now=now)
    assert moves["breadth"] == "higher"
    assert "Blank markets" in moves["summary"]
    assert "global rally" not in moves["summary"].lower()
    names = [r["name"] for r in moves["strip"]]
    assert names == ["STOXX Europe 600", "FTSE 100", "Nifty 50"]
    assert _idx(moves["rows"], "S&P 500")["pct"] is None


def test_offline_publish_does_not_invent_a_world_percent():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fix = os.path.join(root, "market_news", "fixtures")
    tmp = tempfile.mkdtemp(prefix="mnw-")
    try:
        shutil.copy(os.path.join(fix, "market_today.csv"), os.path.join(tmp, "market_today.csv"))
        shutil.copy(os.path.join(fix, "sectors.csv"), os.path.join(tmp, "sectors.csv"))
        headlines = json.load(open(os.path.join(fix, "headlines.json")))
        calendar = json.load(open(os.path.join(fix, "calendar.json")))
        brief = publish(
            data_dir=tmp,
            mode="offline",
            now_et=dt.datetime(2026, 11, 5, 10, 15),
            offline_headlines=headlines,
            offline_calendar=calendar,
        )
    finally:
        shutil.rmtree(tmp)
    world = brief["world_moves"]
    assert _idx(world["rows"], "SPY")["pct"] == -2.73
    assert _idx(world["rows"], "S&P 500")["pct"] is None
    assert _idx(world["rows"], "Nikkei 225")["pct"] is None
    assert world["breadth"] == "unknown"
