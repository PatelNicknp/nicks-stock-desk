"""Cboe delayed option quotes and the Treasury 3-month yield.

One request per ticker. Raw chains are not what we keep: the cache stores
only the expiries and strikes a debit spread can use. A failed request
returns None so the caller can keep the previous cache. This module never
places an order.
"""
import datetime as dt
import json
import os
import re
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/%s.json"
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/%d/all?type=daily_treasury_yield_curve&field_tdr_date_value=%d&page&_format=csv"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"
OCC = re.compile(r"^(?P<root>[A-Z\.]+?)(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<cp>[CP])(?P<k>\d{8})$")
# A little wider than the 30 to 75 day fallback so a saved chain is still useful the next morning.
CACHE_DTE = (25, 80)
CACHE_SPOT = (0.50, 1.60)


def fetch_text(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json,text/csv,*/*",
        "Accept-Language": "en-US",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def cboe_symbol(ticker):
    return str(ticker or "").upper().replace(".", "")


def fetch_cboe(ticker, fetch=None):
    """Return parsed JSON or None. Tries the symbol, then the symbol without a dot."""
    fetch = fetch or fetch_text
    sym = str(ticker or "").upper()
    urls = [CBOE_URL % cboe_symbol(sym)]
    if "." in sym and cboe_symbol(sym) != sym:
        urls.insert(0, CBOE_URL % sym)
    for url in urls:
        try:
            return json.loads(fetch(url))
        except Exception:
            continue
    return None


def parse_chain(payload, today, spot):
    """Compact quote list. None when the payload is not a chain."""
    if not payload or not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    options = data.get("options") if isinstance(data, dict) else None
    if not isinstance(options, list):
        return None
    try:
        spot_n = float(spot) if spot else float(data.get("current_price") or 0)
    except (TypeError, ValueError):
        spot_n = 0.0
    lo = spot_n * CACHE_SPOT[0] if spot_n else 0.0
    hi = spot_n * CACHE_SPOT[1] if spot_n else 0.0
    quotes = []
    for opt in options:
        if not isinstance(opt, dict):
            continue
        m = OCC.match(str(opt.get("option") or ""))
        if not m:
            continue
        exp = dt.date(2000 + int(m["y"]), int(m["m"]), int(m["d"]))
        dte = (exp - today).days
        if dte < CACHE_DTE[0] or dte > CACHE_DTE[1]:
            continue
        strike = int(m["k"]) / 1000.0
        if lo and (strike < lo or strike > hi):
            continue
        try:
            bid = float(opt.get("bid") or 0)
            ask = float(opt.get("ask") or 0)
            oi = int(float(opt.get("open_interest") or 0))
        except (TypeError, ValueError):
            continue
        quotes.append({
            "exp": exp.isoformat(),
            "kind": "call" if m["cp"] == "C" else "put",
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "oi": oi,
        })
    as_of = ""
    if isinstance(data, dict):
        as_of = str(data.get("last_trade_time") or data.get("timestamp") or "")
    if not as_of:
        as_of = str(payload.get("timestamp") or "")
    return {
        "as_of": as_of,
        "spot_cboe": data.get("current_price") if isinstance(data, dict) else None,
        "quotes": quotes,
    }


def chain_path(cache_dir, ticker):
    safe = cboe_symbol(ticker).replace("/", "")
    return os.path.join(cache_dir, "options_chains", safe + ".json")


def load_cached(cache_dir, ticker):
    path = chain_path(cache_dir, ticker)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("quotes"), list):
        return None
    return data


def save_cached(cache_dir, ticker, chain):
    path = chain_path(cache_dir, ticker)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(chain, fh, separators=(",", ":"))


def _treasury_from_csv(text):
    if not text or not text.startswith("Date"):
        return None
    lines = text.strip().splitlines()
    hdr = [h.strip('"') for h in lines[0].split(",")]
    if "3 Mo" not in hdr:
        return None
    i = hdr.index("3 Mo")
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) > i and parts[i].strip():
            try:
                return float(parts[i]) / 100.0, parts[0].strip().strip('"')
            except ValueError:
                continue
    return None


def _fred_from_csv(text):
    if not text or "DGS3MO" not in text:
        return None
    lines = text.strip().splitlines()[1:]
    for ln in reversed(lines):
        if "," not in ln:
            continue
        day, val = ln.split(",", 1)
        val = val.strip()
        if val in ("", "."):
            continue
        try:
            return float(val) / 100.0, day.strip()
        except ValueError:
            continue
    return None


def risk_free(cache_dir, fallback=0.04, fetch=None, today=None):
    """(rate, source, as_of). Keeps the last good reading when the sites fail."""
    fetch = fetch or fetch_text
    today = today or dt.date.today()
    path = os.path.join(cache_dir, "treasury_3m.json")
    got = None
    for year in (today.year, today.year - 1):
        try:
            text = fetch(TREASURY_URL % (year, year))
        except Exception:
            text = None
        got = _treasury_from_csv(text) if text else None
        if got:
            rate, as_of = got
            payload = {"rate": rate, "source": "US Treasury yield curve (3-month)", "as_of": as_of}
            try:
                os.makedirs(cache_dir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
            except OSError:
                pass
            return rate, payload["source"], as_of
    try:
        text = fetch(FRED_URL)
    except Exception:
        text = None
    got = _fred_from_csv(text) if text else None
    if got:
        rate, as_of = got
        payload = {"rate": rate, "source": "FRED DGS3MO", "as_of": as_of}
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except OSError:
            pass
        return rate, payload["source"], as_of
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
            return float(old["rate"]), str(old.get("source") or "saved Treasury rate"), str(old.get("as_of") or "")
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return float(fallback), "4% fallback", ""
