"""Next big US macro event this week — free Nasdaq economic calendar (no login).

Same family of public JSON the desk already uses in load_econ().
This pack only asks for *future* dates for the watch strip; it does not
re-download Yahoo prices.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen

UA = (
    "Mozilla/5.0 (compatible; NicksStockDesk/1.0; +https://github.com/PatelNicknp/nicks-stock-desk) "
    "research-only"
)

NASDAQ_ECON = "https://api.nasdaq.com/api/calendar/economicevents?date=%s"

# Events that move the whole market. Matched case-insensitively as substrings.
WATCH_NAMES = (
    "FOMC",
    "Fed Interest Rate",
    "Federal Funds",
    "CPI",
    "Consumer Price",
    "PCE",
    "Nonfarm",
    "Non-Farm",
    "Employment Situation",
    "Unemployment Rate",
    "Jobless Claims",
    "GDP",
    "Retail Sales",
    "ISM Manufacturing",
    "ISM Services",
    "PPI",
    "Producer Price",
    "JOLTS",
    "Consumer Confidence",
    "Michigan Sentiment",
)


def fetch_text(url: str, timeout: int = 20) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Language": "en-US",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _is_watch(event_name: str) -> bool:
    e = event_name or ""
    return any(w.lower() in e.lower() for w in WATCH_NAMES)


# Major economies whose prints can move global stock markets. Not every country on the feed.
WATCH_COUNTRIES = {
    "United States": "US",
    "US": "US",
    "USA": "US",
    "Euro Area": "Europe",
    "Eurozone": "Europe",
    "European Union": "Europe",
    "EU": "Europe",
    "Germany": "Europe",
    "France": "Europe",
    "United Kingdom": "UK",
    "UK": "UK",
    "China": "China",
    "Japan": "Japan",
    "India": "India",
}


def parse_day_payload(payload: Dict[str, Any], day: dt.date) -> List[Dict[str, Any]]:
    rows = ((payload or {}).get("data") or {}).get("rows") or []
    out = []
    for item in rows:
        country = (item.get("country") or "").strip()
        label = WATCH_COUNTRIES.get(country)
        if not label:
            continue
        name = (item.get("eventName") or "").strip()
        if not name or not _is_watch(name):
            continue
        out.append({
            "date": day.isoformat(),
            "time": (item.get("time") or "").strip(),
            "event": name,
            "forecast": item.get("consensus"),
            "previous": item.get("previous"),
            "country": label,
        })
    return out


def next_events(
    today: Optional[dt.date] = None,
    days: int = 7,
    fetch: Optional[Callable[[str], str]] = None,
    fixture_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return the next watch event plus the week's list.

    Offline: pass fixture_rows (already filtered) and fetch is unused.
    """
    today = today or dt.date.today()
    if fixture_rows is not None:
        upcoming = [
            r for r in fixture_rows
            if (r.get("date") or "") >= today.isoformat()
        ]
        upcoming.sort(key=lambda r: (r.get("date") or "", r.get("time") or "", r.get("event") or ""))
        nxt = upcoming[0] if upcoming else None
        return {
            "as_of": today.isoformat(),
            "next": nxt,
            "week": upcoming[:8],
            "source": "fixture",
            "text": _text(nxt),
        }

    fetch = fetch or fetch_text
    found: List[Dict[str, Any]] = []
    for i in range(0, days + 1):
        day = today + dt.timedelta(days=i)
        if day.weekday() >= 5:
            continue
        url = NASDAQ_ECON % day.isoformat()
        try:
            payload = json.loads(fetch(url))
            found.extend(parse_day_payload(payload, day))
        except Exception:
            continue
    found.sort(key=lambda r: (r.get("date") or "", r.get("time") or ""))
    nxt = found[0] if found else None
    return {
        "as_of": today.isoformat(),
        "next": nxt,
        "week": found[:8],
        "source": "nasdaq_economicevents",
        "text": _text(nxt),
    }


def _text(nxt: Optional[Dict[str, Any]]) -> str:
    if not nxt:
        return "No major macro print on the free calendar for the next few sessions."
    when = nxt.get("date") or ""
    time = nxt.get("time") or ""
    event = nxt.get("event") or "Macro release"
    place = nxt.get("country") or ""
    if place and place not in event:
        event = "%s %s" % (place, event)
    bit = when + ((" " + time) if time else "")
    return "Next up: %s (%s)." % (event, bit.strip())
