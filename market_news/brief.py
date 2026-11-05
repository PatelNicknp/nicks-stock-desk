"""Build and publish data/market_brief.json (+ history).

Reads desk CSVs already on disk. Fetches only free RSS + Nasdaq econ calendar.
Never touches Yahoo. Never places trades.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
from typing import Any, Callable, Dict, List, Optional

from . import calendar_fetch, learning, news_fetch
from .causes import pick_headlines, score_causes, tag_headline
from .mood import breadth_vs_price, mood_chip, regime_note, why_moved
from .schema import DISCLAIMER, FEATURE_FLAG, OUTPUT_FILES
from .watch import watch_next_line, weekly_recap

ET_LABEL = "America/Los_Angeles"  # desk UI shows PT; price_as_of is a New York calendar date


def read_csv_dicts(path: str) -> List[Dict[str, str]]:
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_json(path: str, default: Any = None) -> Any:
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _slot_for(now_et_hour: Optional[int] = None) -> str:
    """Morning open brief before 12:00 ET; evening close brief afterward."""
    if now_et_hour is None:
        # Approximate from local clock; desk hook should pass New York hour.
        now_et_hour = dt.datetime.now().hour
    return "morning_open" if now_et_hour < 12 else "evening_close"


def load_stats(
    market_today_row: Optional[Dict[str, Any]] = None,
    market_today_path: Optional[str] = None,
) -> Dict[str, Any]:
    if market_today_row:
        return dict(market_today_row)
    rows = read_csv_dicts(market_today_path) if market_today_path else []
    return dict(rows[0]) if rows else {}


def load_sectors(
    sectors_rows: Optional[List[Dict[str, Any]]] = None,
    sectors_path: Optional[str] = None,
    sector_perf_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if sectors_rows is not None:
        return list(sectors_rows)
    rows = read_csv_dicts(sectors_path) if sectors_path else []
    if rows:
        return rows
    return read_csv_dicts(sector_perf_path) if sector_perf_path else []


def compare_to_yesterday(
    mood_label: str,
    prior: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not prior:
        return {
            "prior_mood": None,
            "prior_session": None,
            "text": "No prior brief on file yet — check back tomorrow for the vs-yesterday line.",
            "flipped": False,
            "same_fear": False,
        }
    prior_mood = ((prior.get("mood") or {}).get("label")) or prior.get("mood_label")
    prior_session = prior.get("session") or prior.get("price_as_of")
    if not prior_mood:
        return {
            "prior_mood": None,
            "prior_session": prior_session,
            "text": "Prior brief had no mood chip.",
            "flipped": False,
            "same_fear": False,
        }
    if prior_mood == mood_label == "Fear":
        text = "Fear again — same mood chip as the last brief."
        return {"prior_mood": prior_mood, "prior_session": prior_session, "text": text,
                "flipped": False, "same_fear": True}
    if prior_mood == mood_label:
        text = "Mood steady versus last brief (%s)." % mood_label
        return {"prior_mood": prior_mood, "prior_session": prior_session, "text": text,
                "flipped": False, "same_fear": False}
    text = "Mood flipped: was %s, now %s." % (prior_mood, mood_label)
    return {"prior_mood": prior_mood, "prior_session": prior_session, "text": text,
            "flipped": True, "same_fear": False}


def build_brief(
    stats: Dict[str, Any],
    sectors: List[Dict[str, Any]],
    headlines_raw: List[Dict[str, Any]],
    calendar: Dict[str, Any],
    prior_brief: Optional[Dict[str, Any]] = None,
    slot: Optional[str] = None,
    now_et_hour: Optional[int] = None,
    history_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pure build — no I/O. Safe for unit tests."""
    session = str(stats.get("price_as_of") or dt.date.today().isoformat())
    slot = slot or _slot_for(now_et_hour)
    mood = mood_chip(stats)
    regime = regime_note(stats)
    breadth = breadth_vs_price(stats)
    why = why_moved(stats, sectors)

    # Tag then pick 3–5 big-picture headlines.
    tagged = []
    for h in headlines_raw:
        h = dict(h)
        h["causes"] = h.get("causes") or tag_headline(h.get("title") or "", h.get("summary") or "")
        tagged.append(h)
    headlines = pick_headlines(tagged, limit=5)
    causes = score_causes(headlines, stats, sectors)
    # Group: only headlines under the ranked causes (plus leftover top headlines list).
    vs = compare_to_yesterday(mood["label"], prior_brief)

    # Keep prior brief body for on-page compare (not just mood).
    prior_keep = None
    if prior_brief:
        prior_keep = {
            "session": prior_brief.get("session") or prior_brief.get("price_as_of"),
            "slot": prior_brief.get("slot"),
            "why_moved": prior_brief.get("why_moved"),
            "mood": (prior_brief.get("mood") or {}).get("label"),
            "causes": [c.get("label") or c.get("cause") for c in (prior_brief.get("causes") or [])],
        }

    brief = {
        "schema_version": 1,
        "feature": FEATURE_FLAG,
        "session": session,
        "slot": slot,
        "updated_pt": stats.get("updated_pt") or "",
        "price_as_of": session,
        "why_moved": why,
        "mood": mood,
        "headlines": headlines,
        "causes": causes,
        "vs_yesterday": vs,
        "breadth_check": breadth,
        "regime": regime,
        "calendar": {
            "next": (calendar or {}).get("next"),
            "week": (calendar or {}).get("week") or [],
            "text": (calendar or {}).get("text") or "",
            "source": (calendar or {}).get("source") or "",
        },
        "prior_brief": prior_keep,
        "stats": {
            "spy_price": _num(stats.get("spy_price")),
            "spy_day_pct": _num(stats.get("spy_day_pct")),
            "qqq_day_pct": _num(stats.get("qqq_day_pct")),
            "vix": _num(stats.get("vix")),
            "advancers": _int(stats.get("advancers")),
            "decliners": _int(stats.get("decliners")),
            "breadth_sma50": _num(stats.get("breadth_sma50")),
            "breadth_sma200": _num(stats.get("breadth_sma200")),
            "put_call": _num(stats.get("put_call")),
            "put_call_zone": stats.get("put_call_zone") or None,
            "fred_dgs10": _num(stats.get("fred_dgs10")),
        },
        "learning": None,  # filled below
        "disclaimer": DISCLAIMER,
        "data_status": stats.get("data_status") or "OK",
    }

    hist = list(history_rows or [])
    # Backfill next-day SPY onto prior stubs using today's spy_day_pct.
    hist = learning.backfill_next_day(hist, session, brief["stats"]["spy_day_pct"])
    stub = learning.stub_from_brief(brief)
    # Replace same session+slot stub if re-run; else append.
    hist = [
        r for r in hist
        if not (r.get("date") == stub["date"] and r.get("slot") == stub["slot"])
    ]
    hist.append(stub)
    # Cap history length so the file stays small.
    hist = hist[-120:]
    brief["learning"] = {
        "stub": stub,
        "stats": learning.cause_source_stats(hist),
    }
    # Next session's notable release (Pacific time). None when that day is quiet.
    brief["watch_next"] = watch_next_line(session, calendar)
    # Friday close only. Stays on the saved brief through the weekend.
    brief["weekly_recap"] = weekly_recap(session, slot, hist)
    brief["_history"] = hist  # publish() peels this off into the history file
    return brief


def publish(
    data_dir: str,
    cache_dir: Optional[str] = None,
    mode: str = "full",
    now_et: Optional[dt.datetime] = None,
    fetch_news: Optional[Callable[..., List[Dict[str, Any]]]] = None,
    fetch_calendar: Optional[Callable[..., Dict[str, Any]]] = None,
    offline_headlines: Optional[List[Dict[str, Any]]] = None,
    offline_calendar: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Read desk files under data_dir, write market_brief.json + history.

    mode: 'full' | 'hourly' | 'offline'
      - hourly/offline reuse on-disk brief headlines if a fresh fetch is not wanted;
        still rebuilds why/mood/regime from the latest market_today.csv.
    """
    data_dir = data_dir or "data"
    mt_path = os.path.join(data_dir, "market_today.csv")
    sectors_path = os.path.join(data_dir, "sectors.csv")
    sector_perf_path = os.path.join(data_dir, "sector_performance.csv")
    brief_path = os.path.join(data_dir, OUTPUT_FILES["brief"].split("/", 1)[-1])
    hist_path = os.path.join(data_dir, OUTPUT_FILES["history"].split("/", 1)[-1])

    stats = load_stats(market_today_path=mt_path)
    sectors = load_sectors(sectors_path=sectors_path, sector_perf_path=sector_perf_path)
    prior = read_json(brief_path, default=None)
    history = read_json(hist_path, default=[]) or []
    if isinstance(history, dict):
        history = history.get("rows") or []

    now_et = now_et or dt.datetime.now()
    slot = _slot_for(now_et.hour)

    # Headlines
    if offline_headlines is not None:
        headlines_raw = news_fetch.headlines_from_fixture(offline_headlines)
    elif mode in ("offline",) or fetch_news is None and mode == "hourly" and prior:
        # Hourly default: keep prior headlines unless a fetch function is injected.
        headlines_raw = list(prior.get("headlines") or []) if prior else []
        if not headlines_raw and fetch_news:
            headlines_raw = fetch_news()
    else:
        getter = fetch_news or news_fetch.fetch_headlines
        try:
            headlines_raw = getter()
        except Exception:
            headlines_raw = list((prior or {}).get("headlines") or [])

    # Calendar
    today = dt.date.fromisoformat(str(stats.get("price_as_of") or now_et.date()))
    if offline_calendar is not None:
        calendar = offline_calendar
    else:
        cal_fn = fetch_calendar or (lambda: calendar_fetch.next_events(today=today))
        try:
            calendar = cal_fn() if fetch_calendar else calendar_fetch.next_events(today=today)
        except Exception:
            calendar = (prior or {}).get("calendar") or {
                "next": None, "week": [], "text": "Calendar feed unavailable.", "source": "error",
            }

    brief = build_brief(
        stats=stats,
        sectors=sectors,
        headlines_raw=headlines_raw,
        calendar=calendar if isinstance(calendar, dict) else {},
        prior_brief=prior if isinstance(prior, dict) else None,
        slot=slot,
        now_et_hour=now_et.hour,
        history_rows=history,
    )
    hist = brief.pop("_history", history)
    write_json(brief_path, brief)
    write_json(hist_path, {"schema_version": 1, "rows": hist, "aggregates": brief.get("learning", {}).get("stats")})
    return brief


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return None if n is None else int(round(n))
