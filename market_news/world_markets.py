"""Major equity-market snapshots for the Today news card.

A percent is shown only when two prices in the same payload agree with it,
or when it is the desk's existing SPY/QQQ day change. An ETF is never labeled
as the index. A failed or unverified feed stays unknown. No OHLC candles.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import ssl
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from .news_fetch import safe_url

# Official index identifiers. The Boerse Frankfurt public price feed is a
# vendor snapshot (mic ARIVA), not the home exchange's official close.
INDEXES = (
    {
        "id": "spx",
        "name": "S&P 500",
        "region": "US",
        "tz": "America/New_York",
        "open_min": 9 * 60 + 30,
        "close_min": 16 * 60,
        "words": ("s&p 500", "s&p500"),
    },
    {
        "id": "sxxp",
        "name": "STOXX Europe 600",
        "region": "Europe",
        "tz": "Europe/Berlin",
        "open_min": 9 * 60,
        "close_min": 17 * 60 + 30,
        "isin": "EU0009658202",
        "words": ("stoxx", "europe 600"),
    },
    {
        "id": "dax",
        "name": "DAX",
        "region": "Europe",
        "tz": "Europe/Berlin",
        "open_min": 9 * 60,
        "close_min": 17 * 60 + 30,
        "isin": "DE0008469008",
        "words": ("dax",),
    },
    {
        "id": "ukx",
        "name": "FTSE 100",
        "region": "UK",
        "tz": "Europe/London",
        "open_min": 8 * 60,
        "close_min": 16 * 60 + 30,
        "isin": "GB0001383545",
        "words": ("ftse 100", "ftse"),
    },
    {
        "id": "n225",
        "name": "Nikkei 225",
        "region": "Japan",
        "tz": "Asia/Tokyo",
        "open_min": 9 * 60,
        "close_min": 15 * 60,
        "words": ("nikkei",),
        "blocked": (
            "The publisher's daily file says not to circulate the values, "
            "so this desk does not republish a Nikkei close."
        ),
    },
    {
        "id": "ssec",
        "name": "Shanghai Composite",
        "region": "China",
        "tz": "Asia/Shanghai",
        "open_min": 9 * 60 + 30,
        "close_min": 15 * 60,
        "words": ("shanghai composite", "shanghai"),
    },
    {
        "id": "hsi",
        "name": "Hang Seng",
        "region": "Hong Kong",
        "tz": "Asia/Hong_Kong",
        "open_min": 9 * 60 + 30,
        "close_min": 16 * 60,
        "words": ("hang seng",),
    },
    {
        "id": "nifty",
        "name": "Nifty 50",
        "region": "India",
        "tz": "Asia/Kolkata",
        "open_min": 9 * 60 + 15,
        "close_min": 15 * 60 + 30,
        "words": ("nifty 50", "nifty"),
    },
)

PROXIES = (
    {
        "id": "spy",
        "name": "SPY",
        "region": "US",
        "tz": "America/New_York",
        "open_min": 9 * 60 + 30,
        "close_min": 16 * 60,
        "field": "spy_day_pct",
        "stands_for": "S&P 500",
        "words": ("s&p 500", "s&p500"),
    },
    {
        "id": "qqq",
        "name": "QQQ",
        "region": "US",
        "tz": "America/New_York",
        "open_min": 9 * 60 + 30,
        "close_min": 16 * 60,
        "field": "qqq_day_pct",
        "stands_for": "Nasdaq-100",
        "words": ("nasdaq-100", "nasdaq 100"),
    },
)

REGION_ORDER = ("US", "Europe", "UK", "Japan", "China", "Hong Kong", "India")
BOERSE = "https://api.boerse-frankfurt.de/v1/data/price_information?isin="
NSE_URL = "https://www.nseindia.com/api/allIndices"
NSE_PAGE = "https://www.nseindia.com/market-data/live-equity-market"
PCT_TOLERANCE = 0.08
STALE_DAYS = 4
DELAY_MINUTES = 15


def _zone(name: str):
    if ZoneInfo is None:
        return dt.timezone.utc
    return ZoneInfo(name)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value or "")[:10]
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def verified_change(last: Any, prev: Any, reported: Any) -> Optional[float]:
    """Return the percent only when last and previous close reproduce it.

    A reported percent with no second price, or one that disagrees, is dropped.
    """
    last_n = _num(last)
    prev_n = _num(prev)
    reported_n = _num(reported)
    if last_n is None or prev_n in (None, 0) or last_n == prev_n:
        return None
    calc = (last_n / prev_n - 1.0) * 100.0
    if reported_n is None:
        return round(calc, 2)
    if abs(calc - reported_n) <= PCT_TOLERANCE:
        return round(reported_n, 2)
    return None


def session_status(
    session_date: Optional[dt.date],
    quote_at: Optional[dt.datetime],
    now: dt.datetime,
    tz_name: str,
    open_min: int,
    close_min: int,
) -> str:
    """Label the quote against the market's own clock.

    ``session_date`` is the quote's trading date. The time the feed was
    retrieved is not a session date.
    """
    if session_date is None or now is None:
        return "unknown"
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    local_now = now.astimezone(_zone(tz_name))
    age = (local_now.date() - session_date).days
    if age < 0:
        return "unknown"
    if age > STALE_DAYS:
        return "stale"
    if age >= 1:
        return "prior_local_close"
    if local_now.weekday() >= 5:
        return "unknown"
    if quote_at is None:
        mins = local_now.hour * 60 + local_now.minute
        if mins >= close_min:
            return "closed"
        if mins < open_min:
            return "prior_local_close"
        return "intraday"
    if quote_at.tzinfo is None:
        quote_at = quote_at.replace(tzinfo=_zone(tz_name))
    quote_local = quote_at.astimezone(_zone(tz_name))
    if quote_local.date() != session_date:
        return "prior_local_close"
    quote_min = quote_local.hour * 60 + quote_local.minute
    now_min = local_now.hour * 60 + local_now.minute
    if now_min >= close_min or quote_min >= close_min:
        return "closed"
    lag = (local_now - quote_local).total_seconds() / 60.0
    if lag >= DELAY_MINUTES:
        return "delayed"
    return "intraday"


def _blank(spec: Dict[str, Any], note: str, kind: str = "index") -> Dict[str, Any]:
    return {
        "id": spec["id"],
        "name": spec["name"],
        "region": spec["region"],
        "kind": kind,
        "pct": None,
        "verified": False,
        "session_date": "",
        "quote_at": "",
        "status": "unknown",
        "source": "",
        "source_url": "",
        "note": note,
        "cause": "",
        "cause_source": "",
        "cause_url": "",
    }


_DOWN = ("dip", "fall", "fell", "drop", "drops", "slide", "slides", "tumble", "tumbles", "lower", "selloff", "sell-off", "plunge", "down")
_UP = ("rise", "rises", "rose", "higher", "gain", "gains", "rally", "rallies", "climb", "climbs", "up")


def _word(blob: str, word: str) -> bool:
    return (" " + word + " ") in (" " + blob + " ")


def _conflicts(blob: str, pct: float) -> bool:
    down = any(_word(blob, w) for w in _DOWN)
    up = any(_word(blob, w) for w in _UP)
    if pct > 0 and down and not up:
        return True
    if pct < 0 and up and not down:
        return True
    return False


def _cause_for(spec: Dict[str, Any], headlines: List[Dict[str, Any]], pct: Optional[float]) -> Dict[str, str]:
    empty = {"cause": "", "cause_source": "", "cause_url": ""}
    if pct is None:
        return empty
    words = spec.get("words") or ()
    for h in headlines or []:
        blob = ((h.get("title") or "") + " " + (h.get("summary") or "")).lower()
        if not any(w in blob for w in words):
            continue
        if _conflicts(blob, pct):
            continue
        url = safe_url(h.get("url") or "")
        if not url:
            continue
        title = (h.get("title") or "").strip()
        source = (h.get("source") or "Source").strip()
        return {
            "cause": "Possible context from %s: %s. Not proof this caused the percent." % (source, title),
            "cause_source": source,
            "cause_url": url,
        }
    return empty


def _with_cause(row: Dict[str, Any], spec: Dict[str, Any], headlines: List[Dict[str, Any]]) -> Dict[str, Any]:
    row.update(_cause_for(spec, headlines, row.get("pct")))
    return row


def parse_boerse_payload(text: str) -> Optional[Dict[str, Any]]:
    """First ``data:`` object from the Boerse Frankfurt event stream."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw.startswith("{"):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None
    return None


def row_from_boerse(
    spec: Dict[str, Any],
    payload: Optional[Dict[str, Any]],
    now: dt.datetime,
    headlines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not payload or payload.get("error"):
        note = "No verified close from the public quote feed."
        if payload and payload.get("error"):
            note = "Quote feed failed. No number is filled in."
        return _with_cause(_blank(spec, note), spec, headlines or [])
    if payload.get("isin") and payload.get("isin") != spec.get("isin"):
        return _with_cause(_blank(spec, "Quote was for a different instrument."), spec, headlines or [])
    pct = verified_change(
        payload.get("lastPrice"),
        payload.get("closingPricePrevTradingDay"),
        payload.get("changeToPrevDayInPercent"),
    )
    stamp = payload.get("timestampLastPrice") or ""
    quote_at = None
    try:
        quote_at = dt.datetime.fromisoformat(str(stamp))
    except ValueError:
        quote_at = None
    session = quote_at.astimezone(_zone(spec["tz"])).date() if quote_at else None
    status = session_status(session, quote_at, now, spec["tz"], spec["open_min"], spec["close_min"])
    if pct is None:
        row = _blank(
            spec,
            "The feed's last price and previous-close field do not support a percent, so none is shown.",
        )
        row["session_date"] = session.isoformat() if session else ""
        row["quote_at"] = stamp
        row["status"] = "unknown" if status == "unknown" else status
        row["source"] = "Boerse Frankfurt"
        return _with_cause(row, spec, headlines or [])
    row = {
        "id": spec["id"],
        "name": spec["name"],
        "region": spec["region"],
        "kind": "index",
        "pct": pct,
        "verified": True,
        "session_date": session.isoformat() if session else "",
        "quote_at": stamp,
        "status": status,
        "source": "Boerse Frankfurt",
        "source_url": safe_url(BOERSE + spec["isin"]),
        "note": "Vendor snapshot from the public price feed. Not an official home-exchange close. Percent checked against the two prices in that payload.",
        "cause": "",
        "cause_source": "",
        "cause_url": "",
    }
    return _with_cause(row, spec, headlines or [])


def row_from_nse(
    payload: Optional[Dict[str, Any]],
    now: dt.datetime,
    headlines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    spec = next(s for s in INDEXES if s["id"] == "nifty")
    if not payload or payload.get("error"):
        return _with_cause(_blank(spec, "NSE public indices feed failed. No number is filled in."), spec, headlines or [])
    hit = None
    for item in payload.get("data") or []:
        if item.get("index") == "NIFTY 50":
            hit = item
            break
    if not hit:
        return _with_cause(_blank(spec, "NSE response had no Nifty 50 row."), spec, headlines or [])
    pct = verified_change(hit.get("last"), hit.get("previousClose"), hit.get("percentChange"))
    stamp = str(payload.get("timestamp") or "")
    quote_at = None
    for fmt in ("%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            quote_at = dt.datetime.strptime(stamp, fmt).replace(tzinfo=_zone(spec["tz"]))
            break
        except ValueError:
            continue
    session = quote_at.date() if quote_at else None
    status = session_status(session, quote_at, now, spec["tz"], spec["open_min"], spec["close_min"])
    if pct is None:
        row = _blank(spec, "NSE last and previous close do not support the reported percent.")
        row["status"] = status if status != "unknown" else "unknown"
        row["session_date"] = session.isoformat() if session else ""
        return _with_cause(row, spec, headlines or [])
    row = {
        "id": "nifty",
        "name": "Nifty 50",
        "region": "India",
        "kind": "index",
        "pct": pct,
        "verified": True,
        "session_date": session.isoformat() if session else "",
        "quote_at": quote_at.isoformat() if quote_at else "",
        "status": status,
        "source": "NSE India",
        "source_url": safe_url(NSE_PAGE),
        "note": "One Nifty 50 snapshot from the NSE public indices response. Not a history and not Sensex.",
        "cause": "",
        "cause_source": "",
        "cause_url": "",
    }
    return _with_cause(row, spec, headlines or [])


def _desk_clock(text: str) -> Optional[dt.datetime]:
    """Desk stamps look like '2026-11-06 07:30 PT'. The zone is Pacific, not the bar date alone."""
    raw = (text or "").strip()
    if len(raw) < 16:
        return None
    try:
        day = dt.date.fromisoformat(raw[:10])
        hour = int(raw[11:13])
        minute = int(raw[14:16])
    except ValueError:
        return None
    if "PT" not in raw.upper():
        return None
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=_zone("America/Los_Angeles"))


def row_from_desk_proxy(
    spec: Dict[str, Any],
    stats: Dict[str, Any],
    now: dt.datetime,
    headlines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    pct = _num(stats.get(spec["field"]))
    session = _date(stats.get("price_as_of"))
    if pct is None or session is None:
        row = _blank(
            spec,
            "No %s day change on the desk file." % spec["name"],
            kind="etf_proxy",
        )
        row["name"] = spec["name"]
        return _with_cause(row, spec, headlines or [])
    stamp = _desk_clock(str(stats.get("updated_pt") or ""))
    status = session_status(session, None, now, spec["tz"], spec["open_min"], spec["close_min"])
    note = "%s is an ETF proxy for %s, not the index. Day change already stored by the desk. No new price request." % (
        spec["name"], spec["stands_for"],
    )
    quote_at = ""
    if stamp is not None:
        quote_at = stamp.isoformat()
        local = stamp.astimezone(_zone(spec["tz"]))
        if local.date() == session and (local.hour * 60 + local.minute) < spec["close_min"]:
            status = "open_print"
            note += " The desk stamp is before that market's close, so this percent is not a closing return."
    row = {
        "id": spec["id"],
        "name": spec["name"],
        "region": spec["region"],
        "kind": "etf_proxy",
        "pct": round(pct, 2),
        "verified": True,
        "session_date": session.isoformat(),
        "quote_at": quote_at,
        "status": status,
        "source": "Desk price file",
        "source_url": "",
        "note": note,
        "cause": "",
        "cause_source": "",
        "cause_url": "",
    }
    return _with_cause(row, spec, headlines or [])


def _strip_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One verified row per region. An index outranks an ETF proxy."""
    chosen: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row.get("pct") is None or not row.get("verified"):
            continue
        region = row["region"]
        have = chosen.get(region)
        if have is None or (have.get("kind") != "index" and row.get("kind") == "index"):
            chosen[region] = row
    return [chosen[name] for name in REGION_ORDER if name in chosen]


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    indexes = [r for r in rows if r.get("kind") == "index" and r.get("verified") and r.get("pct") is not None]
    regions = []
    for name in REGION_ORDER:
        if any(r["region"] == name for r in indexes):
            regions.append(name)
    dates = sorted({r.get("session_date") or "" for r in indexes if r.get("session_date")})
    mixed = len(dates) > 1
    if len(regions) < 3:
        breadth = "unknown"
        text = "Not enough verified index closes to call a worldwide move."
    else:
        signs = set()
        for r in indexes:
            pct = r["pct"]
            signs.add(0 if pct == 0 else (1 if pct > 0 else -1))
        if signs == {1}:
            breadth = "higher"
            text = "Verified indexes on file finished higher. Blank markets are not part of that."
        elif signs == {-1}:
            breadth = "lower"
            text = "Verified indexes on file finished lower. Blank markets are not part of that."
        else:
            breadth = "mixed"
            text = "Verified indexes on file did not all move the same way."
    if mixed:
        text += " Session dates are each market's own date, not one global day."
    missing = [r["name"] for r in rows if r.get("kind") == "index" and r.get("pct") is None]
    return {
        "breadth": breadth,
        "text": text,
        "missing": missing,
        "strip_ids": [r["id"] for r in _strip_rows(rows)],
    }


def build_world_moves(
    stats: Optional[Dict[str, Any]] = None,
    quotes: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
    headlines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pure assembly. ``quotes`` keys are ISINs plus ``nse``."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    stats = stats or {}
    quotes = quotes or {}
    headlines = headlines or []
    rows: List[Dict[str, Any]] = []
    for spec in INDEXES:
        if spec.get("blocked"):
            rows.append(_with_cause(_blank(spec, spec["blocked"]), spec, headlines))
            continue
        if spec["id"] == "nifty":
            rows.append(row_from_nse(quotes.get("nse"), now, headlines))
            continue
        if spec.get("isin"):
            rows.append(row_from_boerse(spec, quotes.get(spec["isin"]), now, headlines))
            continue
        rows.append(_with_cause(
            _blank(spec, "No permitted index snapshot for %s." % spec["name"]),
            spec,
            headlines,
        ))
    for spec in PROXIES:
        rows.append(row_from_desk_proxy(spec, stats, now, headlines))
    summary = summarize(rows)
    return {
        "retrieved_at": now.astimezone(dt.timezone.utc).isoformat(),
        "summary": summary["text"],
        "breadth": summary["breadth"],
        "missing": summary["missing"],
        "strip": _strip_rows(rows),
        "rows": rows,
    }


def _read_stream(host: str, path: str, limit: int = 4000) -> str:
    """Read the start of an HTTP response and stop. Used for the event stream."""
    req = (
        "GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: NicksStockDesk/1.0\r\n"
        "Accept: */*\r\nConnection: close\r\n\r\n" % (path, host)
    ).encode()
    ctx = ssl.create_default_context()
    raw = b""
    with socket.create_connection((host, 443), timeout=12) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as wrapped:
            wrapped.settimeout(8)
            wrapped.sendall(req)
            while len(raw) < limit:
                try:
                    chunk = wrapped.recv(1500)
                except socket.timeout:
                    break
                if not chunk:
                    break
                raw += chunk
    return raw.decode("utf-8", "replace")


def fetch_quotes(
    cache_dir: Optional[str] = None,
    now: Optional[dt.datetime] = None,
    max_age_hours: float = 6,
    opener: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """One cached pass over the public quote feeds. Failures stay empty."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    path = os.path.join(cache_dir or "cache", "world_markets.json")
    cached = _read_cache(path, now, max_age_hours)
    if cached is not None:
        return cached
    quotes: Dict[str, Any] = {}
    for spec in INDEXES:
        isin = spec.get("isin")
        if not isin:
            continue
        try:
            body = _read_stream("api.boerse-frankfurt.de", "/v1/data/price_information?isin=" + isin)
            parsed = parse_boerse_payload(body)
            quotes[isin] = parsed or {"error": "empty"}
        except Exception as exc:
            quotes[isin] = {"error": str(exc)[:160]}
    try:
        quotes["nse"] = _read_nse(opener)
    except Exception as exc:
        quotes["nse"] = {"error": str(exc)[:160]}
    _write_cache(path, now, quotes)
    return quotes


def _read_nse(opener: Optional[Callable[..., Any]]) -> Dict[str, Any]:
    req = Request(NSE_URL, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    })
    open_fn = opener or urlopen
    with open_fn(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    kept = None
    for item in payload.get("data") or []:
        if item.get("index") == "NIFTY 50":
            kept = {
                "index": "NIFTY 50",
                "last": item.get("last"),
                "previousClose": item.get("previousClose"),
                "percentChange": item.get("percentChange"),
            }
            break
    return {"timestamp": payload.get("timestamp"), "data": [kept] if kept else []}


def _read_cache(path: str, now: dt.datetime, max_age_hours: float) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
        stamp = dt.datetime.fromisoformat(saved.get("retrieved_at"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        age = (now - stamp).total_seconds() / 3600.0
        if age <= max_age_hours:
            return saved.get("quotes") or {}
    except (OSError, ValueError, TypeError):
        return None
    return None


def _write_cache(path: str, now: dt.datetime, quotes: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"retrieved_at": now.isoformat(), "quotes": quotes}, handle)
    except OSError:
        return
