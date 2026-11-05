"""Next-session watch line and the Friday close week note.

Both are overall-market only. The watch line uses the calendar events
this pack already keeps. The week note uses saved brief history.
No new feeds. No Yahoo.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from .causes import _pretty

# Nasdaq prints times in Eastern. Pacific is always 3 hours earlier.
_ET_TO_PT = 3 * 60
_OPEN_ET = 9 * 60 + 30  # 9:30 AM ET cash open

# Longer phrases first so "consumer price" wins over a stray "cpi".
_SHORT_NAMES = (
    ("jobless", "Jobless claims"),
    ("non-farm", "Jobs report"),
    ("nonfarm", "Jobs report"),
    ("employment situation", "Jobs report"),
    ("unemployment rate", "Jobs report"),
    ("consumer price", "CPI"),
    ("cpi", "CPI"),
    ("pce", "PCE"),
    ("producer price", "PPI"),
    ("ppi", "PPI"),
    ("fomc", "Fed decision"),
    ("fed interest", "Fed decision"),
    ("federal funds", "Fed decision"),
    ("retail sales", "Retail sales"),
    ("ism manufacturing", "ISM manufacturing"),
    ("ism services", "ISM services"),
    ("jolts", "JOLTS"),
    ("michigan", "Michigan sentiment"),
    ("consumer confidence", "Consumer confidence"),
    ("gdp", "GDP"),
)

_MOOD_RANK = {"Fear": 0, "Mixed": 1, "Calm": 2}
_SLOT_ORDER = {"morning_open": 0, "evening_close": 1}


def short_event(name: str) -> str:
    n = (name or "").lower()
    for key, label in _SHORT_NAMES:
        if key in n:
            return label
    cleaned = (name or "").strip()
    return cleaned or "US release"


def next_session_date(session: dt.date) -> dt.date:
    """The next weekday session after this brief's session date. Friday rolls to Monday."""
    day = session + dt.timedelta(days=1)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def _et_minutes(time_str: str) -> Optional[int]:
    """Minutes from midnight Eastern. Accepts 08:30, 14:00, and 2:00 PM."""
    raw = (time_str or "").strip().lower().replace(".", "")
    if not raw:
        return None
    ampm = None
    if raw.endswith("am"):
        ampm = "am"
        raw = raw[:-2].strip()
    elif raw.endswith("pm"):
        ampm = "pm"
        raw = raw[:-2].strip()
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59 or hour < 0 or minute < 0:
        return None
    return hour * 60 + minute


def format_pt(time_str: str) -> Optional[str]:
    """Eastern clock time as a Pacific clock time, e.g. 08:30 -> 5:30 AM PT."""
    mins = _et_minutes(time_str)
    if mins is None:
        return None
    pt = mins - _ET_TO_PT
    if pt < 0:
        pt += 24 * 60
    hour, minute = divmod(pt, 60)
    suffix = "AM" if hour < 12 else "PM"
    h12 = hour % 12 or 12
    return "%d:%02d %s PT" % (h12, minute, suffix)


def _events(calendar: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    calendar = calendar or {}
    rows = list(calendar.get("week") or [])
    nxt = calendar.get("next")
    if isinstance(nxt, dict):
        rows.append(nxt)
    seen = set()
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("date") or "")[:10],
            (row.get("time") or "").strip(),
            (row.get("event") or "").strip(),
        )
        if not key[2] or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def watch_next_line(session: str, calendar: Optional[Dict[str, Any]]) -> Optional[str]:
    """One plain line for the next session, or None when that day has no notable release.

    Times are Pacific. A release before the 9:30 AM ET open adds "expect a jumpy open".
    """
    try:
        day = dt.date.fromisoformat(str(session)[:10])
    except (TypeError, ValueError):
        return None
    target = next_session_date(day)
    on_day = [e for e in _events(calendar) if str(e.get("date") or "")[:10] == target.isoformat()]
    if not on_day:
        return None
    on_day.sort(key=lambda e: (
        _et_minutes(e.get("time") or "") is None,
        _et_minutes(e.get("time") or "") if _et_minutes(e.get("time") or "") is not None else 0,
        short_event(e.get("event") or ""),
    ))
    event = on_day[0]
    label = short_event(event.get("event") or "")
    when = "tomorrow" if target == day + dt.timedelta(days=1) else target.strftime("%A")
    pt = format_pt(event.get("time") or "")
    mins = _et_minutes(event.get("time") or "")
    jumpy = mins is not None and mins < _OPEN_ET
    if pt and jumpy:
        return "%s %s %s — expect a jumpy open" % (label, when, pt)
    if pt:
        return "%s %s %s" % (label, when, pt)
    return "%s %s" % (label, when)


def weekly_recap(
    session: str,
    slot: str,
    history_rows: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Friday close only. Top causes that week, and whether mood improved or worsened.

    The saved Friday brief stays on Today through the weekend, until Monday's brief replaces it.
    """
    try:
        day = dt.date.fromisoformat(str(session)[:10])
    except (TypeError, ValueError):
        return None
    if day.weekday() != 4 or slot != "evening_close":
        return None
    monday = (day - dt.timedelta(days=4)).isoformat()
    friday = day.isoformat()
    rows = []
    for row in history_rows or []:
        if not isinstance(row, dict):
            continue
        stamp = str(row.get("date") or "")[:10]
        if stamp and monday <= stamp <= friday:
            rows.append(row)
    if not rows:
        return None
    rows.sort(key=lambda r: (str(r.get("date") or ""), _SLOT_ORDER.get(r.get("slot"), 9)))

    counts: Dict[str, int] = {}
    for row in rows:
        for cause in row.get("causes") or []:
            if cause:
                counts[str(cause)] = counts.get(str(cause), 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    names = [_pretty(cause) for cause, _n in top]
    if len(names) >= 2:
        drove = "This week was driven by %s and %s." % (names[0], names[1])
    elif names:
        drove = "This week was driven by %s." % names[0]
    else:
        drove = "No single cause stood out this week."

    moods = [r.get("mood") for r in rows if r.get("mood") in _MOOD_RANK]
    if len(moods) >= 2 and _MOOD_RANK[moods[-1]] > _MOOD_RANK[moods[0]]:
        direction = "improving"
        mood_bit = "Mood is improving."
    elif len(moods) >= 2 and _MOOD_RANK[moods[-1]] < _MOOD_RANK[moods[0]]:
        direction = "worsening"
        mood_bit = "Mood is worsening."
    else:
        direction = "steady"
        mood_bit = "Mood is steady."
    return {
        "text": drove + " " + mood_bit,
        "causes": [cause for cause, _n in top],
        "mood": direction,
    }
