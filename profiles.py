"""Company profiles, SIC sectors, Nasdaq earnings dates, and optional Finnhub websites.

SEC submissions and company-facts zips are the main fill for the whole universe.
SIC-to-sector mapping is approximate GICS-style and is only used when Wikipedia
or Yahoo left sector or industry blank. It must never overwrite those values.

The Nasdaq earnings calendar is one request per day. A failed fetch keeps the
saved calendar. Finnhub websites run only when FINNHUB_API_KEY is already set.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd

# Official nightly archives. Updated around 3:00 a.m. ET.
COMPANYFACTS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"

# Approximate GICS-style sector from a 4-digit SIC. Not official GICS.
# More specific codes win over the two-digit major group.
_SIC_EXACT = {
    "1000": "Materials", "1040": "Materials", "1220": "Energy", "1221": "Energy",
    "1311": "Energy", "1381": "Energy", "1382": "Energy", "1389": "Energy",
    "1400": "Materials", "1623": "Industrials",
    "2082": "Consumer Staples", "2085": "Consumer Staples", "2086": "Consumer Staples",
    "2111": "Consumer Staples", "2833": "Health Care", "2834": "Health Care",
    "2835": "Health Care", "2836": "Health Care", "2844": "Consumer Staples",
    "2911": "Energy", "3571": "Information Technology", "3572": "Information Technology",
    "3575": "Information Technology", "3576": "Information Technology",
    "3577": "Information Technology", "3578": "Information Technology",
    "3661": "Information Technology", "3663": "Information Technology",
    "3669": "Information Technology", "3670": "Information Technology",
    "3672": "Information Technology", "3674": "Information Technology",
    "3678": "Information Technology", "3679": "Information Technology",
    "3711": "Consumer Discretionary", "3713": "Consumer Discretionary",
    "3714": "Consumer Discretionary", "3715": "Consumer Discretionary",
    "3841": "Health Care", "3842": "Health Care", "3844": "Health Care",
    "3845": "Health Care", "3851": "Health Care", "3861": "Information Technology",
    "4812": "Communication Services", "4813": "Communication Services",
    "4822": "Communication Services", "4832": "Communication Services",
    "4833": "Communication Services", "4841": "Communication Services",
    "4899": "Communication Services", "4911": "Utilities", "4922": "Utilities",
    "4923": "Utilities", "4924": "Utilities", "4931": "Utilities", "4932": "Utilities",
    "4941": "Utilities", "4953": "Industrials", "4955": "Industrials",
    "5411": "Consumer Staples", "5412": "Consumer Staples", "5812": "Consumer Discretionary",
    "5912": "Consumer Staples", "5961": "Consumer Discretionary",
    "6021": "Financials", "6022": "Financials", "6029": "Financials",
    "6035": "Financials", "6036": "Financials", "6099": "Financials",
    "6111": "Financials", "6141": "Financials", "6153": "Financials",
    "6159": "Financials", "6162": "Financials", "6163": "Financials",
    "6199": "Financials", "6200": "Financials", "6211": "Financials",
    "6282": "Financials", "6311": "Financials", "6321": "Health Care",
    "6324": "Health Care", "6331": "Financials", "6351": "Financials",
    "6361": "Financials", "6399": "Financials", "6411": "Financials",
    "6500": "Real Estate", "6510": "Real Estate", "6512": "Real Estate",
    "6519": "Real Estate", "6531": "Real Estate", "6532": "Real Estate",
    "6552": "Real Estate", "6798": "Real Estate", "7011": "Consumer Discretionary",
    "7310": "Communication Services", "7311": "Communication Services",
    "7370": "Information Technology", "7371": "Information Technology",
    "7372": "Information Technology", "7373": "Information Technology",
    "7374": "Information Technology", "7375": "Communication Services",
    "7378": "Information Technology", "7389": "Industrials",
    "7812": "Communication Services", "7819": "Communication Services",
    "7822": "Communication Services", "7830": "Communication Services",
    "7832": "Communication Services", "7841": "Communication Services",
    "7990": "Consumer Discretionary", "8011": "Health Care", "8050": "Health Care",
    "8051": "Health Care", "8060": "Health Care", "8062": "Health Care",
    "8071": "Health Care", "8082": "Health Care", "8090": "Health Care",
    "8093": "Health Care", "8111": "Industrials", "8200": "Consumer Discretionary",
    "8731": "Health Care", "8741": "Industrials", "8742": "Industrials",
}

# First two SIC digits (major group) when no exact code matches.
_SIC_MAJOR = {
    1: "Consumer Staples", 2: "Consumer Staples", 7: "Consumer Staples",
    8: "Consumer Staples", 9: "Consumer Staples",
    10: "Materials", 12: "Energy", 13: "Energy", 14: "Materials",
    15: "Industrials", 16: "Industrials", 17: "Industrials",
    20: "Consumer Staples", 21: "Consumer Staples", 22: "Consumer Discretionary",
    23: "Consumer Discretionary", 24: "Materials", 25: "Consumer Discretionary",
    26: "Materials", 27: "Communication Services", 28: "Materials", 29: "Energy",
    30: "Materials", 31: "Consumer Discretionary", 32: "Materials", 33: "Materials",
    34: "Industrials", 35: "Industrials", 36: "Industrials", 37: "Industrials",
    38: "Industrials", 39: "Consumer Discretionary",
    40: "Industrials", 41: "Industrials", 42: "Industrials", 44: "Industrials",
    45: "Industrials", 46: "Energy", 47: "Industrials", 48: "Communication Services",
    49: "Utilities",
    50: "Industrials", 51: "Consumer Staples", 52: "Consumer Discretionary",
    53: "Consumer Discretionary", 54: "Consumer Staples", 55: "Consumer Discretionary",
    56: "Consumer Discretionary", 57: "Consumer Discretionary", 58: "Consumer Discretionary",
    59: "Consumer Discretionary",
    60: "Financials", 61: "Financials", 62: "Financials", 63: "Financials",
    64: "Financials", 65: "Real Estate", 67: "Financials",
    70: "Consumer Discretionary", 72: "Consumer Discretionary", 73: "Industrials",
    75: "Consumer Discretionary", 76: "Industrials", 78: "Communication Services",
    79: "Consumer Discretionary", 80: "Health Care", 81: "Industrials",
    82: "Consumer Discretionary", 83: "Health Care", 87: "Industrials",
}

_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}

SECTOR_SOURCE_SIC = "sic_approx"
SECTOR_SOURCE_NOTE = (
    "SIC-derived sectors are an approximate GICS-style label from the SEC SIC code. "
    "They are not official GICS and are used only when Wikipedia or Yahoo left the sector blank."
)


def _norm_ticker(symbol):
    return str(symbol or "").upper().replace(".", "-").replace("$", "-").replace("/", "-").strip()


def _blank(value):
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in ("nan", "none", "null"):
        return ""
    return text


def sic_to_sector(sic):
    """Approximate GICS-style sector for an SIC code. Blank if the code is unusable.

    This is not official GICS. Callers must only use it to fill a blank sector.
    """
    digits = "".join(ch for ch in str(sic or "") if ch.isdigit())
    if not digits:
        return ""
    code = digits.zfill(4)[:4]
    if code in _SIC_EXACT:
        return _SIC_EXACT[code]
    try:
        major = int(code[:2])
    except ValueError:
        return ""
    return _SIC_MAJOR.get(major, "")


def country_from_submissions(payload):
    """Best available country from an SEC submissions JSON object."""
    payload = payload or {}
    addresses = payload.get("addresses") or {}
    for key in ("business", "mailing"):
        addr = addresses.get(key) or {}
        country = _blank(addr.get("country")) or _blank(addr.get("stateOrCountryDescription"))
        code = _blank(addr.get("countryCode")) or _blank(addr.get("stateOrCountry"))
        if addr.get("isForeignLocation") in (1, "1", True):
            if country and country.upper() not in _US_STATES:
                return country
            if code and code.upper() not in _US_STATES:
                return country or code
        if country and country.upper() not in _US_STATES and "," in country:
            return country
        if country and country.upper() not in _US_STATES and len(country) > 2:
            # "United Kingdom", "Canada", "Ontario, Canada"
            if code.upper() not in _US_STATES or addr.get("isForeignLocation") in (1, "1", True):
                return country
    inc = _blank(payload.get("stateOfIncorporationDescription")) or _blank(payload.get("stateOfIncorporation"))
    inc_code = _blank(payload.get("stateOfIncorporation"))
    if inc_code.upper() in _US_STATES or inc.upper() in _US_STATES:
        return "United States"
    if inc and inc.upper() not in _US_STATES:
        return inc
    return "United States" if inc_code else ""


def parse_submissions_profile(payload, ticker=""):
    """Pull name, country, exchange, SIC, and an approximate sector from submissions JSON."""
    payload = payload or {}
    tickers = payload.get("tickers") or []
    exchanges = payload.get("exchanges") or []
    chosen = _norm_ticker(ticker)
    exchange = ""
    if chosen and tickers:
        norms = [_norm_ticker(t) for t in tickers]
        if chosen in norms:
            idx = norms.index(chosen)
            if idx < len(exchanges):
                exchange = _blank(exchanges[idx])
    if not exchange and exchanges:
        exchange = _blank(exchanges[0])
    if not chosen and tickers:
        chosen = _norm_ticker(tickers[0])
    sic = _blank(payload.get("sic"))
    sic_description = _blank(payload.get("sicDescription"))
    return {
        "ticker": chosen,
        "company": _blank(payload.get("name")),
        "country": country_from_submissions(payload),
        "exchange": exchange,
        "sic": sic,
        "sic_description": sic_description,
        "industry": sic_description,
        "sector": sic_to_sector(sic),
        "sector_source": SECTOR_SOURCE_SIC if sic_to_sector(sic) else "",
        "website": _blank(payload.get("website") or payload.get("investorWebsite")),
    }


def apply_profiles_to_universe(universe, profiles):
    """Fill blank company, sector, country, and industry only. Never overwrite a filled sector or name."""
    if universe is None or len(universe) == 0 or profiles is None or len(profiles) == 0:
        return universe if universe is not None else pd.DataFrame()
    out = universe.copy()
    for col in ("country", "industry", "sector_source", "exchange", "website"):
        if col not in out.columns:
            out[col] = ""
    by = {}
    for _, row in profiles.iterrows():
        by[_norm_ticker(row.get("ticker"))] = row
    for i, u in out.iterrows():
        row = by.get(_norm_ticker(u.get("ticker")))
        if row is None:
            continue
        if not _blank(u.get("company")) and row.get("company"):
            out.at[i, "company"] = row.get("company") or ""
        if not _blank(u.get("sector")) and row.get("sector"):
            out.at[i, "sector"] = row.get("sector")
            out.at[i, "sector_source"] = SECTOR_SOURCE_SIC
        if not _blank(u.get("industry")) and row.get("industry"):
            out.at[i, "industry"] = row.get("industry")
        if not _blank(u.get("country")) and row.get("country"):
            out.at[i, "country"] = row.get("country")
        if not _blank(u.get("exchange")) and row.get("exchange"):
            out.at[i, "exchange"] = row.get("exchange")
        if not _blank(u.get("website")) and row.get("website"):
            out.at[i, "website"] = row.get("website")
    return out


def apply_profiles_to_info(info, profiles):
    """Add industry (and company) to Yahoo profile rows only where those fields are blank."""
    if profiles is None or len(profiles) == 0:
        return info if info is not None else pd.DataFrame()
    if info is None or len(info) == 0:
        keep = profiles[["ticker", "company", "industry", "sector", "country", "website"]].copy() if "ticker" in profiles.columns else pd.DataFrame()
        return keep
    out = info.copy()
    for col in ("industry", "company", "country", "website", "sector"):
        if col not in out.columns:
            out[col] = ""
    have = set(out["ticker"].astype(str).map(_norm_ticker)) if "ticker" in out.columns else set()
    by = {}
    for _, row in profiles.iterrows():
        by[_norm_ticker(row.get("ticker"))] = row
    for i, rec in out.iterrows():
        row = by.get(_norm_ticker(rec.get("ticker")))
        if row is None:
            continue
        if not _blank(rec.get("industry")) and row.get("industry"):
            out.at[i, "industry"] = row.get("industry")
        if not _blank(rec.get("company")) and row.get("company"):
            out.at[i, "company"] = row.get("company")
        if not _blank(rec.get("country")) and row.get("country"):
            out.at[i, "country"] = row.get("country")
        if not _blank(rec.get("website")) and row.get("website"):
            out.at[i, "website"] = row.get("website")
    extra = []
    for ticker, row in by.items():
        if ticker and ticker not in have:
            extra.append({
                "ticker": ticker,
                "company": row.get("company") or "",
                "industry": row.get("industry") or "",
                "sector": row.get("sector") or "",
                "country": row.get("country") or "",
                "website": row.get("website") or "",
            })
    if extra:
        out = pd.concat([out, pd.DataFrame(extra)], ignore_index=True)
    return out


def calendar_days(start, days_ahead=60, skip_weekends=True):
    """Dates to request from the Nasdaq earnings calendar, starting at `start`.

    `days_ahead` is calendar days. Weekends are skipped so a 60-day window
    is about 33 calls, not 45.
    """
    start = pd.Timestamp(start).normalize()
    out = []
    for i in range(max(0, int(days_ahead))):
        day = start + pd.Timedelta(days=i)
        if skip_weekends and day.weekday() >= 5:
            continue
        out.append(day.strftime("%Y-%m-%d"))
    return out


def parse_nasdaq_earnings_payload(payload, day):
    """Rows from one Nasdaq earnings-calendar response."""
    data = (payload or {}).get("data") or payload or {}
    rows = data.get("rows") or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _norm_ticker(row.get("symbol") or row.get("ticker"))
        if not ticker:
            continue
        out.append({
            "ticker": ticker,
            "earnings_dt": str(day),
            "when_hint": _blank(row.get("time") or row.get("timeOfDay")),
            "eps_estimate": row.get("epsForecast") or row.get("eps_estimate") or "",
            "eps_actual": row.get("eps") or row.get("eps_actual") or "",
            "surprise_pct": row.get("surprise") or row.get("surprise_pct") or "",
            "source": "nasdaq_calendar",
        })
    return out



def parse_earnings_dt(series):
    """Parse earnings dates that may mix tz-aware timestamps and YYYY-MM-DD.

    A column that already has '2027-02-04 16:00:00-05:00' will otherwise turn a
    date-only '2026-12-16' into NaT when both are parsed together.
    """
    text = series.fillna("").astype(str).str.strip()
    date_only = text.str.match(r"^\d{4}-\d{2}-\d{2}$")
    text = text.where(~date_only, text + " 00:00:00+00:00")
    return pd.to_datetime(text, utc=True, errors="coerce")


def merge_earnings_dates(existing, calendar, now=None):
    """Add calendar dates only where a future earnings date is still missing.

    Existing Yahoo (or earlier) rows are kept. A failed or empty calendar leaves
    `existing` unchanged.
    """
    if calendar is None or len(calendar) == 0:
        return existing if existing is not None else pd.DataFrame()
    if existing is None or len(existing) == 0:
        return calendar.copy()
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    out = existing.copy()
    if "ticker" not in out.columns:
        return out
    have_future = set()
    if "earnings_dt" in out.columns:
        dts = parse_earnings_dt(out["earnings_dt"])
        for ticker, ts in zip(out["ticker"].astype(str).map(_norm_ticker), dts):
            if ticker and pd.notna(ts) and ts > now:
                have_future.add(ticker)
    add = []
    for _, row in calendar.iterrows():
        ticker = _norm_ticker(row.get("ticker"))
        if not ticker or ticker in have_future:
            continue
        add.append(dict(row))
        have_future.add(ticker)
    if add:
        out = pd.concat([out, pd.DataFrame(add)], ignore_index=True)
    return out


def keep_calendar_on_failure(prior, fresh, failed=False):
    """Never replace a saved calendar with an empty failed fetch."""
    if failed or fresh is None or len(fresh) == 0:
        return prior if prior is not None else pd.DataFrame()
    if prior is None or len(prior) == 0:
        return fresh
    # New rows for a date replace prior rows for that date; other prior dates stay.
    if "earnings_dt" not in fresh.columns:
        return fresh
    days = set(pd.to_datetime(fresh["earnings_dt"], errors="coerce").dt.strftime("%Y-%m-%d").dropna())
    if "earnings_dt" in prior.columns:
        prior_days = pd.to_datetime(prior["earnings_dt"], errors="coerce").dt.strftime("%Y-%m-%d")
        keep = prior[~prior_days.isin(days)]
    else:
        keep = prior
    return pd.concat([keep, fresh], ignore_index=True)


def zip_member_for_cik(names, cik):
    """Find the zip member for a 10-digit CIK. Accepts a few layout variants."""
    cik = str(cik).zfill(10)
    exact = (
        "CIK%s.json" % cik,
        "CIK%s.json".lower() % cik,
        "%s.json" % cik,
        "submissions/CIK%s.json" % cik,
        "companyfacts/CIK%s.json" % cik,
    )
    name_set = set(names)
    for candidate in exact:
        if candidate in name_set:
            return candidate
    suffix = "CIK%s.json" % cik
    for name in names:
        if name.endswith(suffix) or name.endswith("%s.json" % cik):
            return name
    return ""


def parse_companyfacts_from_zip(zip_path, cik_by_ticker, parse_companyfacts):
    """Parse annual and quarterly statements for the given tickers out of companyfacts.zip."""
    annual_parts, quarter_parts = [], []
    found, missing = [], []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for ticker, cik in (cik_by_ticker or {}).items():
            member = zip_member_for_cik(names, cik)
            if not member:
                missing.append(ticker)
                continue
            try:
                payload = json.loads(zf.read(member))
                annual, quarters = parse_companyfacts(payload)
            except Exception:
                missing.append(ticker)
                continue
            if annual is not None and len(annual):
                annual = annual.copy()
                annual["ticker"] = ticker
                annual_parts.append(annual)
            if quarters is not None and len(quarters):
                quarters = quarters.copy()
                quarters["ticker"] = ticker
                quarter_parts.append(quarters)
            found.append(ticker)
    annual = pd.concat(annual_parts, ignore_index=True) if annual_parts else pd.DataFrame()
    quarters = pd.concat(quarter_parts, ignore_index=True) if quarter_parts else pd.DataFrame()
    return annual, quarters, found, missing


def parse_submissions_from_zip(zip_path, cik_by_ticker):
    """Profile rows for the given tickers out of submissions.zip."""
    rows = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for ticker, cik in (cik_by_ticker or {}).items():
            member = zip_member_for_cik(names, cik)
            if not member:
                continue
            try:
                payload = json.loads(zf.read(member))
            except Exception:
                continue
            row = parse_submissions_profile(payload, ticker=ticker)
            if row.get("ticker"):
                rows.append(row)
    return pd.DataFrame(rows)


def http_download(session, url, dest, headers, timeout=300, limiter=None, chunk=1024 * 1024):
    """Stream a large file to disk. Used for the official SEC zip archives."""
    if limiter is not None:
        limiter.wait()
    with session.get(url, headers=headers, timeout=timeout, stream=True) as response:
        if response.status_code == 429 or response.status_code >= 500:
            raise RuntimeError("HTTP %s for %s" % (response.status_code, url))
        if response.status_code in (403, 404):
            raise RuntimeError("HTTP %s for %s" % (response.status_code, url))
        response.raise_for_status()
        folder = os.path.dirname(dest)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = dest + ".part"
        with open(tmp, "wb") as fh:
            for block in response.iter_content(chunk_size=chunk):
                if block:
                    fh.write(block)
        os.replace(tmp, dest)
    return dest


def finnhub_api_key():
    """Return the Finnhub key only if the environment already has one. Never invent a key."""
    return (os.environ.get("FINNHUB_API_KEY") or "").strip()


def parse_finnhub_profile(payload, ticker):
    payload = payload or {}
    return {
        "ticker": _norm_ticker(ticker),
        "website": _blank(payload.get("weburl") or payload.get("website")),
        "country": _blank(payload.get("country")),
        "industry": _blank(payload.get("finnhubIndustry") or payload.get("industry")),
    }
