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

from . import calendar_fetch, learning, news_fetch, world_markets
from .causes import pick_headlines, score_causes, tag_headline
from .mood import breadth_vs_price, mood_chip, regime_note, why_moved, why_moved_short
from .schema import DISCLAIMER, FEATURE_FLAG, OUTPUT_FILES, SCHEMA_VERSION
from .story import build_story
from .tips import build_tips
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
    headline_limit: int = 7,
    now: Optional[dt.datetime] = None,
    world_moves: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure build — no I/O. Safe for unit tests.

    Always writes the full v2 payload. UI feature switches decide what to show:
      market_news_why_detail, market_news_more_headlines, market_news_card_layout,
      market_news_tips (all default on).
    """
    session = str(stats.get("price_as_of") or dt.date.today().isoformat())
    slot = slot or _slot_for(now_et_hour)
    mood = mood_chip(stats)
    regime = regime_note(stats)
    breadth = breadth_vs_price(stats)

    # Tag then pick 5–7 big-picture headlines (v2). Compact UI may show fewer.
    tagged = []
    for h in headlines_raw:
        h = dict(h)
        h["causes"] = h.get("causes") or tag_headline(h.get("title") or "", h.get("summary") or "")
        tagged.append(h)
    headlines = pick_headlines(tagged, limit=headline_limit, session=session, now=now)
    causes = score_causes(headlines, stats, sectors)

    why_short = why_moved_short(stats, sectors)
    why_detail = why_moved(stats, sectors, causes=causes)
    vs = compare_to_yesterday(mood["label"], prior_brief)
    tips = build_tips(mood, regime, breadth, stats)
    story = build_story(stats, sectors, headlines, causes, slot=slot)

    prior_keep = None
    if prior_brief:
        prior_keep = {
            "session": prior_brief.get("session") or prior_brief.get("price_as_of"),
            "slot": prior_brief.get("slot"),
            "why_moved": prior_brief.get("why_moved_short") or prior_brief.get("why_moved"),
            "mood": (prior_brief.get("mood") or {}).get("label"),
            "causes": [c.get("label") or c.get("cause") for c in (prior_brief.get("causes") or [])],
        }

    brief = {
        "schema_version": SCHEMA_VERSION,
        "feature": FEATURE_FLAG,
        "session": session,
        "slot": slot,
        "updated_pt": stats.get("updated_pt") or "",
        "price_as_of": session,
        # why_moved = detailed 2–3 sentences (v2 default). Short kept for compact mode.
        "why_moved": why_detail,
        "why_moved_short": why_short,
        "story": story,
        "mood": mood,
        "headlines": headlines,
        "causes": causes,
        "vs_yesterday": vs,
        "breadth_check": breadth,
        "regime": regime,
        "tips": tips,
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
            "dia_day_pct": _num(stats.get("dia_day_pct") or stats.get("dow_day_pct")),
            "vix": _num(stats.get("vix")),
            "advancers": _int(stats.get("advancers")),
            "decliners": _int(stats.get("decliners")),
            "breadth_sma50": _num(stats.get("breadth_sma50")),
            "breadth_sma200": _num(stats.get("breadth_sma200")),
            "put_call": _num(stats.get("put_call")),
            "put_call_zone": stats.get("put_call_zone") or None,
            "fred_dgs10": _num(stats.get("fred_dgs10")),
        },
        "learning": None,
        "disclaimer": DISCLAIMER,
        "data_status": stats.get("data_status") or "OK",
    }
    if world_moves is not None:
        brief["world_moves"] = world_moves

    hist = list(history_rows or [])
    hist = learning.backfill_next_day(hist, session, brief["stats"]["spy_day_pct"])
    stub = learning.stub_from_brief(brief)
    hist = [
        r for r in hist
        if not (r.get("date") == stub["date"] and r.get("slot") == stub["slot"])
    ]
    hist.append(stub)
    hist = hist[-120:]
    brief["learning"] = {
        "stub": stub,
        "stats": learning.cause_source_stats(hist),
    }
    brief["watch_next"] = watch_next_line(session, calendar)
    brief["weekly_recap"] = weekly_recap(session, slot, hist)
    brief["_history"] = hist
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
    headline_limit: int = 7,
    fetch_world: Optional[Callable[..., Dict[str, Any]]] = None,
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
    if _num(stats.get("dia_day_pct") or stats.get("dow_day_pct")) is None:
        dia = dia_day_pct_from_prices(cache_dir, stats.get("price_as_of"))
        if dia is not None:
            stats["dia_day_pct"] = dia
    sectors = load_sectors(sectors_path=sectors_path, sector_perf_path=sector_perf_path)
    prior = read_json(brief_path, default=None)
    history = read_json(hist_path, default=[]) or []
    if isinstance(history, dict):
        history = history.get("rows") or []

    now_et = now_et or dt.datetime.now()
    slot = _slot_for(now_et.hour)

    if offline_headlines is not None:
        headlines_raw = news_fetch.headlines_from_fixture(offline_headlines)
    elif mode in ("offline",) or fetch_news is None and mode == "hourly" and prior:
        headlines_raw = list(prior.get("headlines") or []) if prior else []
        if not headlines_raw and fetch_news:
            headlines_raw = fetch_news()
    else:
        getter = fetch_news or news_fetch.fetch_headlines
        try:
            headlines_raw = getter()
        except Exception:
            headlines_raw = list((prior or {}).get("headlines") or [])

    today = dt.date.fromisoformat(str(stats.get("price_as_of") or now_et.date()))
    if offline_calendar is not None:
        calendar = offline_calendar
    else:
        try:
            calendar = fetch_calendar() if fetch_calendar else calendar_fetch.next_events(today=today)
        except Exception:
            calendar = (prior or {}).get("calendar") or {
                "next": None, "week": [], "text": "Calendar feed unavailable.", "source": "error",
            }

    if mode == "offline":
        quotes = {}
    else:
        try:
            if fetch_world:
                quotes = fetch_world(cache_dir=cache_dir, now=now_et)
            else:
                quotes = world_markets.fetch_quotes(cache_dir=cache_dir, now=now_et)
        except Exception:
            quotes = {}
    world = world_markets.build_world_moves(
        stats=stats,
        quotes=quotes if isinstance(quotes, dict) else {},
        now=now_et,
        headlines=headlines_raw,
    )
    brief = build_brief(
        stats=stats,
        sectors=sectors,
        headlines_raw=headlines_raw,
        calendar=calendar if isinstance(calendar, dict) else {},
        prior_brief=prior if isinstance(prior, dict) else None,
        slot=slot,
        now_et_hour=now_et.hour,
        history_rows=history,
        headline_limit=headline_limit,
        now=now_et,
        world_moves=world,
    )
    hist = brief.pop("_history", history)
    write_json(brief_path, brief)
    write_json(hist_path, {"schema_version": SCHEMA_VERSION, "rows": hist, "aggregates": brief.get("learning", {}).get("stats")})
    return brief


def dia_day_pct_from_prices(cache_dir: Optional[str], session: Any) -> Optional[float]:
    """Dow day change from DIA bars already on disk. No Yahoo call.

    DOW the stock is not the index, so only the DIA ticker counts.
    """
    import gzip
    root = cache_dir or "cache"
    path = os.path.join(root, "ohlcv.csv.gz")
    if not os.path.exists(path):
        alt = os.path.join(os.path.dirname(root), "data", "ohlc", "DIA.csv")
        return _dia_from_csv(alt, session) if os.path.exists(alt) else None
    closes = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                parts = line.split(",")
                if len(parts) < 3 or parts[1] != "DIA":
                    continue
                closes.append((parts[0][:10], parts[2]))
    except OSError:
        return None
    return _pct_from_closes(closes, session)


def _dia_from_csv(path: str, session: Any) -> Optional[float]:
    closes = []
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                day = (row.get("date") or row.get("Date") or "")[:10]
                px = row.get("close") or row.get("Close") or ""
                if day and px:
                    closes.append((day, px))
    except OSError:
        return None
    return _pct_from_closes(closes, session)


def _pct_from_closes(closes, session: Any) -> Optional[float]:
    rows = []
    for day, px in closes:
        try:
            rows.append((day, float(px)))
        except (TypeError, ValueError):
            continue
    rows.sort()
    if session:
        cap = str(session)[:10]
        rows = [r for r in rows if r[0] <= cap]
    if len(rows) < 2 or rows[-2][1] == 0:
        return None
    return (rows[-1][1] / rows[-2][1] - 1.0) * 100.0


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
