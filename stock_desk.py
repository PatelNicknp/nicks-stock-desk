"""Nick's Stock Desk.

Research screen for stocks. It never places a trade and it never calls a broker.

    python stock_desk.py --full      # prices plus the once-a-day fundamentals
    python stock_desk.py --hourly    # prices only; slow sources stay on today's cache
    python stock_desk.py --offline   # cache only, for tests

Slow sources (SEC filings, analyst data, 13F, insiders, option chains) are fetched
at most once per US session. If a source fails, the previous cache is kept and the
updates log says CACHED.
"""
import os, sys, io, json, time, html, re, datetime as dt
import numpy as np
import pandas as pd
import requests

import netutil
import fundamentals as fund
import scoring
import tables
import setups

ROOT = None  # set in main so tests can point DESK_ROOT at a temp folder
PT = "America/Los_Angeles"
ET = "America/New_York"
DISCLAIMER = tables.DISCLAIMER
LOG = []
STAMPS = {}

SECTOR_ETF_BY_NAME = {
    "Information Technology": "XLK", "Technology": "XLK",
    "Health Care": "XLV", "Healthcare": "XLV",
    "Financials": "XLF", "Financial Services": "XLF",
    "Industrials": "XLI",
    "Communication Services": "XLC", "Telecommunications": "XLC",
    "Consumer Discretionary": "XLY", "Consumer Cyclical": "XLY",
    "Consumer Staples": "XLP", "Consumer Defensive": "XLP",
    "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE",
    "Materials": "XLB", "Basic Materials": "XLB",
}

ECON_SPECS = [
    ("Growth", "GDP", ["GDP"], 1),
    ("Growth", "ISM manufacturing", ["ISM Manufacturing PMI"], 1),
    ("Growth", "Retail sales", ["Retail Sales"], 1),
    ("Inflation", "CPI", ["CPI"], 1),
    ("Inflation", "Fed funds rate", ["Fed Interest Rate Decision"], 1),
    ("Jobs", "Nonfarm payrolls", ["Nonfarm Payrolls"], 1),
    ("Jobs", "Unemployment rate", ["Unemployment Rate"], -1),
    ("Jobs", "Jobless claims", ["Initial Jobless Claims"], -1),
]


def root():
    return ROOT


def log(source, status, latest="", note=""):
    now = pd.Timestamp.now(tz=PT).strftime("%Y-%m-%d %H:%M PT")
    LOG.append({"source": source, "status": status, "latest": str(latest), "note": note, "checked_pt": now})
    print("[%s] %s %s %s" % (status, source, latest, note))


def paths():
    r = root()
    data, cache, inp = (os.path.join(r, d) for d in ("data", "cache", "input"))
    for d in (data, cache, os.path.join(cache, "pcr"), os.path.join(cache, "econ")):
        os.makedirs(d, exist_ok=True)
    return data, cache, inp


def load_cfg():
    with open(os.path.join(root(), "config.json")) as f:
        return json.load(f)


def load_stamps(cache):
    f = os.path.join(cache, "stamps.json")
    if os.path.exists(f):
        with open(f) as fh:
            STAMPS.update(json.load(fh))


def save_stamps(cache):
    with open(os.path.join(cache, "stamps.json"), "w") as f:
        json.dump(STAMPS, f, indent=1)


def rl(cfg):
    return cfg["rate_limit"]


def session_headers(cfg, sec=False):
    if sec:
        return {"User-Agent": rl(cfg)["sec_user_agent"], "Accept": "application/json", "Accept-Encoding": "gzip, deflate"}
    return {"User-Agent": "Mozilla/5.0 (compatible; NickStockDesk/1.0; research)", "Accept": "application/json,text/html,*/*"}


def today_et():
    return pd.Timestamp.now(tz=ET).strftime("%Y-%m-%d")


def progress_load(cache, name):
    """Tickers already fetched today. A crashed run can continue instead of starting over."""
    f = os.path.join(cache, "progress_%s.json" % name)
    if not os.path.exists(f):
        return set()
    try:
        data = json.load(open(f))
    except Exception:
        return set()
    if data.get("date") != today_et():
        return set()
    return set(data.get("tickers") or [])


def progress_save(cache, name, done):
    f = os.path.join(cache, "progress_%s.json" % name)
    json.dump({"date": today_et(), "tickers": sorted(done)}, open(f, "w"))


def read_csv(path, **kw):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame()
    return pd.read_csv(path, **kw)


def write_out(df, name, data_dir):
    cols = tables.COLS[name]
    if df is None:
        df = pd.DataFrame(columns=cols)
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan if c not in ("data_status", "note", "disclaimer") else ""
    out = out[cols]
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(4)
    out.to_csv(os.path.join(data_dir, name + ".csv"), index=False, na_rep="")


def gated(df, name, feature_on, missing_note):
    if not feature_on:
        return pd.DataFrame(columns=tables.COLS[name])
    return tables.ensure(df, tables.COLS[name], "MISSING", missing_note)


# ---------------------------------------------------------------- prices
def frames_from_download(df):
    if df is None or len(getattr(df, "index", [])) == 0 or not isinstance(df.columns, pd.MultiIndex):
        return None
    levels = [set(map(str, df.columns.get_level_values(i))) for i in range(df.columns.nlevels)]

    def grab(field):
        if field in levels[0]:
            sub = df.xs(field, axis=1, level=0)
        elif field in levels[1]:
            sub = df.xs(field, axis=1, level=1)
        else:
            return None
        if isinstance(sub, pd.Series):
            sub = sub.to_frame()
        return sub

    return grab("Close"), grab("High"), grab("Low"), grab("Volume")


def _normalize_index(df):
    if df is None:
        return None
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df = df.copy()
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def download_prices(tickers, cfg):
    import yfinance as yf
    batch = int(rl(cfg)["yahoo_batch_size"])
    pause = float(rl(cfg)["yahoo_batch_pause_seconds"])
    parts = []

    def pull(chunk):
        def once():
            df = yf.download(chunk, period="5y", interval="1d", auto_adjust=True, progress=False,
                             group_by="ticker", threads=True)
            got = frames_from_download(df)
            if got is None or got[0] is None or got[0].dropna(how="all").empty:
                raise netutil.RetryableError("empty price batch (%d names)" % len(chunk))
            return got
        try:
            return netutil.call_with_retry(once, max_tries=rl(cfg)["max_retries"], delays=tuple(rl(cfg)["backoff_seconds"]))
        except Exception:
            if len(chunk) == 1:
                return None
            mid = len(chunk) // 2
            return ("split", chunk[:mid], chunk[mid:])

    queue = [tickers[i:i + batch] for i in range(0, len(tickers), batch)]
    while queue:
        chunk = queue.pop(0)
        got = pull(chunk)
        if isinstance(got, tuple) and got and isinstance(got[0], str) and got[0] == "split":
            queue = [got[1], got[2]] + queue
            continue
        if isinstance(got, tuple) and got and not isinstance(got[0], str):
            parts.append(tuple(_normalize_index(x) for x in got))
        if queue:
            time.sleep(pause)
    if not parts:
        raise RuntimeError("no prices downloaded")
    def cat(i):
        frames = [p[i] for p in parts if p[i] is not None]
        out = pd.concat(frames, axis=1)
        out = out.loc[:, ~out.columns.duplicated()]
        return out.sort_index()
    return cat(0), cat(1), cat(2), cat(3)


def ohlcv_long(close, high, low, vol):
    def melt(df, name):
        x = df.copy()
        x.index.name = "date"
        m = x.reset_index().melt(id_vars="date", var_name="ticker", value_name=name)
        return m
    m = melt(close, "close")
    if high is not None:
        m = m.merge(melt(high, "high"), on=["date", "ticker"], how="left")
    if low is not None:
        m = m.merge(melt(low, "low"), on=["date", "ticker"], how="left")
    if vol is not None:
        m = m.merge(melt(vol, "volume"), on=["date", "ticker"], how="left")
    m = m.dropna(subset=["close"])
    m["date"] = pd.to_datetime(m["date"]).dt.strftime("%Y-%m-%d")
    return m


def wide_from_long(df, col):
    if df is None or len(df) == 0 or col not in df.columns:
        return pd.DataFrame()
    x = df.copy()
    x["date"] = pd.to_datetime(x["date"])
    w = x.pivot_table(index="date", columns="ticker", values=col, aggfunc="last").sort_index()
    return w


def load_prices(tickers, cfg, cache, mode):
    path = os.path.join(cache, "ohlcv.csv.gz")
    cached = read_csv(path) if os.path.exists(path) else pd.DataFrame()
    if mode == "offline":
        if len(cached):
            log("Prices (Yahoo Finance)", "OK", cached["date"].max() if "date" in cached else "", "offline mode, used cache")
            return cached
        log("Prices (Yahoo Finance)", "MISSING", "", "offline and no price cache")
        return pd.DataFrame()
    try:
        c, h, l, v = download_prices(tickers, cfg)
        long = ohlcv_long(c, h, l, v)
        long.to_csv(path, index=False, compression="gzip")
        last = str(pd.to_datetime(long["date"]).max().date())
        log("Prices (Yahoo Finance)", "OK", last, "%d rows, batched" % len(long))
        return long
    except Exception as exc:
        if len(cached):
            log("Prices (Yahoo Finance)", "CACHED", cached["date"].max(), str(exc)[:160])
            return cached
        log("Prices (Yahoo Finance)", "MISSING", "", str(exc)[:160])
        return pd.DataFrame()


# ---------------------------------------------------------------- universe
# One row per stock. A name in more than one list keeps every flag, so Looker can filter.
FLAGS = ("in_sp500", "in_ndx100", "in_growth")
INDEX_SOURCES = {
    "sp500": {
        "flag": "in_sp500",
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "cache": "sp500.csv",
        "legacy": "universe.csv",
        "log": "Universe (Wikipedia S&P 500)",
        "stamp": "universe_sp500",
    },
    "ndx100": {
        "flag": "in_ndx100",
        "url": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
        "cache": "ndx100.csv",
        "legacy": None,
        "log": "Universe (Wikipedia Nasdaq-100)",
        "stamp": "universe_ndx100",
    },
}
# Nasdaq-100's Wikipedia table uses ICB names. Map them onto the same sectors as the S&P list.
ICB_TO_GICS = {
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Health Care": "Health Care",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Industrials": "Industrials",
    "Utilities": "Utilities",
    "Financials": "Financials",
    "Real Estate": "Real Estate",
    "Energy": "Energy",
    "Basic Materials": "Materials",
    "Materials": "Materials",
}


def index_switches(cfg):
    raw = cfg.get("indexes") or {}
    return {
        "sp500": bool(raw.get("sp500", True)),
        "ndx100": bool(raw.get("ndx100", True)),
        "growth": bool(raw.get("growth", True)),
    }


def membership_label(in_sp500, in_ndx100, in_growth):
    """Stable tag: SP500 / NDX100 / Growth. A holding outside those lists is Focus."""
    parts = []
    if in_sp500 == "yes":
        parts.append("SP500")
    if in_ndx100 == "yes":
        parts.append("NDX100")
    if in_growth == "yes":
        parts.append("Growth")
    return " / ".join(parts) if parts else "Focus"


def wiki_constituents(tables, flag):
    """Pick the constituents table. Accepts Symbol (S&P 500) or Ticker (Nasdaq-100)."""
    for table in tables:
        t = table.copy()
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = [" ".join(str(x) for x in col if str(x) != "nan").strip() for col in t.columns]
        lookup = {str(c).lower().strip(): c for c in t.columns}
        sym_key = next((k for k in lookup if k == "symbol" or k.startswith("symbol") or k == "ticker" or k.startswith("ticker")), None)
        if not sym_key or len(t) < 20:
            continue
        sec = next((lookup[k] for k in lookup if "gics sector" in k or k == "sector" or "icb industry" in k), None)
        name = next((lookup[k] for k in lookup if k.startswith("security") or k == "company" or k.startswith("company")), None)
        tickers = (
            t[lookup[sym_key]].astype(str)
            .str.replace(r"\[.*?\]", "", regex=True)
            .str.replace(".", "-", regex=False)
            .str.upper()
            .str.strip()
        )
        df = pd.DataFrame({
            "ticker": tickers,
            "company": t[name].astype(str).str.replace(r"\[.*?\]", "", regex=True).str.strip() if name else "",
            "sector": t[sec].astype(str).str.replace(r"\[.*?\]", "", regex=True).str.strip() if sec else "",
        })
        df = df[df["ticker"].str.fullmatch(r"[A-Z0-9-]{1,10}")]
        df["sector"] = df["sector"].map(lambda s: ICB_TO_GICS.get(s, s))
        df = df.drop_duplicates("ticker")
        for f in FLAGS:
            df[f] = "yes" if f == flag else "no"
        return df.reset_index(drop=True)
    raise RuntimeError("no symbol table on the Wikipedia page")


def _read_index_cache(cache, spec):
    path = os.path.join(cache, spec["cache"])
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return read_csv(path), path
    legacy = spec.get("legacy")
    if legacy:
        old = os.path.join(cache, legacy)
        if os.path.exists(old) and os.path.getsize(old) > 0:
            return read_csv(old), path
    return pd.DataFrame(), path


def load_index(key, cfg, cache, mode):
    """One index list. Hourly and offline never call Wikipedia. A failed fetch keeps the cache."""
    spec = INDEX_SOURCES[key]
    cached, path = _read_index_cache(cache, spec)
    label = spec["log"]

    def finish(df, status, note, latest=""):
        log(label, status, latest, note)
        return _blank_flags(df, spec["flag"]) if len(df) else df

    switches = index_switches(cfg)
    switch_on = switches["sp500"] if key == "sp500" else switches["ndx100"]
    if not switch_on and len(cached):
        return finish(cached, "OK", "switch is off, used the saved list for tags only", len(cached))
    if not switch_on:
        return finish(pd.DataFrame(), "OK", "switch is off and there is no saved list")
    if mode in ("offline", "hourly"):
        if len(cached):
            note = "offline mode, used cache" if mode == "offline" else "reused cache (refreshes once a day)"
            return finish(cached, "OK", note, len(cached))
        return finish(pd.DataFrame(), "MISSING", "no cache and this run does not call Wikipedia")
    stamp = STAMPS.get(spec["stamp"]) or (STAMPS.get("universe") if key == "sp500" else None)
    if stamp == today_et() and len(cached) and "--force-slow" not in sys.argv:
        return finish(cached, "OK", "already fetched today", len(cached))
    try:
        r = netutil.http_get(requests, spec["url"], session_headers(cfg), 40, max_tries=rl(cfg)["max_retries"])
        df = wiki_constituents(pd.read_html(io.StringIO(r.text)), spec["flag"])
        df.to_csv(path, index=False)
        STAMPS[spec["stamp"]] = today_et()
        return finish(df, "OK", "%d names" % len(df), len(df))
    except Exception as exc:
        if len(cached):
            return finish(cached, "CACHED", str(exc)[:160], len(cached))
        return finish(pd.DataFrame(), "MISSING", str(exc)[:160])


def _blank_flags(df, yes_flag=None):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["ticker", "company", "sector", *FLAGS])
    out = df.copy()
    for col in ("ticker", "company", "sector"):
        if col not in out.columns:
            out[col] = ""
    out["ticker"] = out["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False)
    for f in FLAGS:
        if f not in out.columns:
            out[f] = "no"
        out[f] = out[f].fillna("no").astype(str).str.lower().map(lambda v: "yes" if v == "yes" else "no")
    if yes_flag:
        out[yes_flag] = "yes"
    return out


def growth_frame(cfg):
    rows = []
    for t in cfg.get("growth_names", []):
        rows.append({
            "ticker": str(t).upper().replace(".", "-"), "company": "", "sector": "",
            "in_sp500": "no", "in_ndx100": "no", "in_growth": "yes",
        })
    return pd.DataFrame(rows)


def combine_indexes(parts, holdings, watch, switches):
    """Dedupe by ticker. Score a name if any enabled index contains it, or it is a holding or a watchlist name."""
    frames = []
    for df in parts:
        if df is not None and len(df):
            frames.append(_blank_flags(df))
    always = {str(t).upper() for t in list(holdings) + list(watch)}
    if always:
        frames.append(pd.DataFrame([{
            "ticker": t, "company": "", "sector": "",
            "in_sp500": "no", "in_ndx100": "no", "in_growth": "no",
        } for t in always]))
    cols = ["ticker", "company", "sector", *FLAGS, "index_membership"]
    if not frames:
        return pd.DataFrame(columns=cols)
    df = pd.concat(frames, ignore_index=True)
    df = df.groupby("ticker", as_index=False).agg({
        "company": lambda s: next((x for x in s if isinstance(x, str) and str(x).strip() and str(x).lower() != "nan"), ""),
        "sector": lambda s: next((x for x in s if isinstance(x, str) and str(x).strip() and str(x).lower() != "nan"), ""),
        "in_sp500": lambda s: "yes" if (s == "yes").any() else "no",
        "in_ndx100": lambda s: "yes" if (s == "yes").any() else "no",
        "in_growth": lambda s: "yes" if (s == "yes").any() else "no",
    })
    df["index_membership"] = [
        membership_label(a, b, c) for a, b, c in zip(df["in_sp500"], df["in_ndx100"], df["in_growth"])
    ]

    def keep(row):
        if row["ticker"] in always:
            return True
        if switches.get("sp500", True) and row["in_sp500"] == "yes":
            return True
        if switches.get("ndx100", True) and row["in_ndx100"] == "yes":
            return True
        if switches.get("growth", True) and row["in_growth"] == "yes":
            return True
        return False

    return df[df.apply(keep, axis=1)].reset_index(drop=True)


# ---------------------------------------------------------------- slow SEC / yahoo / nasdaq
def cik_map(cfg, cache, mode):
    path = os.path.join(cache, "company_tickers.json")
    raw = None
    if os.path.exists(path):
        with open(path) as f:
            raw = json.load(f)
    allow = mode == "full" and (STAMPS.get("cik_map") != today_et() or raw is None or "--force-slow" in sys.argv)
    if allow:
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            lim = netutil.RateLimiter(rl(cfg)["sec_requests_per_second"])
            r = netutil.http_get(requests, url, session_headers(cfg, sec=True), 40, limiter=lim, max_tries=rl(cfg)["max_retries"])
            raw = r.json()
            with open(path, "w") as f:
                json.dump(raw, f)
            STAMPS["cik_map"] = today_et()
            log("SEC company tickers", "OK", today_et(), "%d companies" % len(raw))
        except Exception as exc:
            if raw is not None:
                log("SEC company tickers", "CACHED", "", str(exc)[:160])
            else:
                log("SEC company tickers", "MISSING", "", str(exc)[:160])
                return {}
    elif raw is not None:
        log("SEC company tickers", "OK", STAMPS.get("cik_map", ""), "reused cache")
    else:
        log("SEC company tickers", "MISSING", "", "no cache")
        return {}
    out = {}
    for row in raw.values():
        t = str(row.get("ticker", "")).upper().replace(".", "-")
        if t:
            out[t] = str(row.get("cik_str")).zfill(10)
    return out


def _need_fetch(name, cache_file, mode):
    exists = os.path.exists(cache_file) and os.path.getsize(cache_file) > 0
    return netutil.decide_slow(STAMPS.get(name), today_et(), exists, mode, force="--force-slow" in sys.argv)


def _missing_tickers(df, tickers):
    """Names in today's universe that are not in the saved file yet."""
    if df is None or len(df) == 0 or "ticker" not in getattr(df, "columns", []):
        return list(tickers)
    have = set(df["ticker"].astype(str))
    return [t for t in tickers if t not in have]


def load_sec(tickers, cik, cfg, cache, mode):
    annual_p = os.path.join(cache, "annual.csv")
    quarter_p = os.path.join(cache, "quarters.csv")
    annual, quarters = read_csv(annual_p), read_csv(quarter_p)
    decision = _need_fetch("sec_facts", annual_p, mode)
    gaps = None
    if decision == "reuse":
        gaps = _missing_tickers(annual, tickers) if mode == "full" else []
        gaps = [t for t in gaps if t in cik]
        if not gaps:
            log("Fundamentals (SEC EDGAR company facts)", "OK", STAMPS.get("sec_facts", ""), "reused cache (slow sources refresh at most once a day)")
            return annual, quarters
        print("SEC filling %d names added since the daily fetch" % len(gaps))
    if decision == "missing":
        log("Fundamentals (SEC EDGAR company facts)", "MISSING", "", "no cache and this run does not call the SEC")
        return annual, quarters
    lim = netutil.RateLimiter(rl(cfg)["sec_requests_per_second"])
    headers = session_headers(cfg, sec=True)
    # A new day refreshes everyone. A crash the same day continues where it stopped.
    done = progress_load(cache, "sec")
    new_a, new_q, fails = [], [], 0
    pool = gaps if gaps else [t for t in tickers if t in cik]
    todo = [t for t in pool if t not in done]
    if done:
        print("SEC skipping %d names already fetched today" % len(done))
    for i, t in enumerate(todo):
        url = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % cik[t]
        try:
            r = netutil.http_get(requests, url, headers, 60, limiter=lim, max_tries=rl(cfg)["max_retries"])
            a, q = fund.parse_companyfacts(r.json())
            if len(a):
                a = a.copy()
                a["ticker"] = t
                new_a.append(a)
            if len(q):
                q = q.copy()
                q["ticker"] = t
                new_q.append(q)
            done.add(t)
        except Exception as exc:
            fails += 1
            if i < 3:
                print("sec fail", t, str(exc)[:100])
        if (i + 1) % 40 == 0:
            print("SEC %d / %d" % (i + 1, len(todo)))
            annual, quarters = _flush_sec(annual, quarters, new_a, new_q, annual_p, quarter_p)
            progress_save(cache, "sec", done)
    annual, quarters = _flush_sec(annual, quarters, new_a, new_q, annual_p, quarter_p)
    progress_save(cache, "sec", done)
    fail_rate = fails / max(len(todo), 1)
    if fails == len(todo) and len(todo):
        status = "CACHED" if len(annual) else "MISSING"
        if status != "CACHED":
            STAMPS.pop("sec_facts", None)
        log("Fundamentals (SEC EDGAR company facts)", status, "", "all %d requests failed" % fails)
    elif fail_rate > 0.5:
        log("Fundamentals (SEC EDGAR company facts)", "CACHED", "", "%d of %d failed; will try again next full run" % (fails, len(todo)))
    else:
        STAMPS["sec_facts"] = today_et()
        note = "%d names" % annual["ticker"].nunique() if len(annual) else "0"
        if fails:
            note += ", %d failed and kept prior rows" % fails
        log("Fundamentals (SEC EDGAR company facts)", "OK", today_et(), note)
    return annual, quarters


def _flush_sec(annual, quarters, new_a, new_q, annual_p, quarter_p):
    if new_a:
        add = pd.concat(new_a, ignore_index=True)
        keep = annual[~annual["ticker"].isin(add["ticker"])] if len(annual) else annual
        annual = pd.concat([keep, add], ignore_index=True)
        annual.to_csv(annual_p, index=False)
        new_a.clear()
    if new_q:
        add = pd.concat(new_q, ignore_index=True)
        keep = quarters[~quarters["ticker"].isin(add["ticker"])] if len(quarters) else quarters
        quarters = pd.concat([keep, add], ignore_index=True)
        quarters.to_csv(quarter_p, index=False)
        new_q.clear()
    return annual, quarters


def load_yahoo(tickers, cfg, cache, mode):
    info_p = os.path.join(cache, "yahoo_info.csv")
    earn_p = os.path.join(cache, "earnings.csv")
    info, earn = read_csv(info_p), read_csv(earn_p)
    decision = _need_fetch("yahoo_slow", info_p, mode)
    gaps = None
    if decision == "reuse":
        gaps = _missing_tickers(info, tickers) if mode == "full" else []
        if not gaps:
            log("Analyst and profile (Yahoo Finance)", "OK", STAMPS.get("yahoo_slow", ""), "reused cache (slow sources refresh at most once a day)")
            log("Earnings dates (Yahoo Finance)", "OK", STAMPS.get("yahoo_slow", ""), "reused cache")
            return info, earn
        print("Yahoo profiles filling %d names added since the daily fetch" % len(gaps))
    if decision == "missing":
        log("Analyst and profile (Yahoo Finance)", "MISSING", "", "no cache and this run does not call Yahoo profiles")
        log("Earnings dates (Yahoo Finance)", "MISSING", "", "no cache")
        return info, earn
    import yfinance as yf
    lim = netutil.RateLimiter(rl(cfg)["yahoo_profile_per_second"])
    done = progress_load(cache, "yahoo")
    rows, erows, fails = [], [], 0
    old_info = info.set_index("ticker") if len(info) and "ticker" in info.columns else None
    if len(info) and done:
        rows.extend(info[info["ticker"].isin(done)].to_dict("records"))
        if len(earn):
            erows.extend(earn[earn["ticker"].isin(done)].to_dict("records"))
    pool = gaps if gaps else list(tickers)
    todo = [t for t in pool if t not in done]
    if done:
        print("Yahoo profiles skipping %d names already fetched today" % len(done))
    for i, t in enumerate(todo):
        lim.wait()
        try:
            tk = yf.Ticker(t)
            def once():
                inf = tk.info or {}
                if not inf or (inf.get("regularMarketPrice") is None and inf.get("forwardPE") is None and inf.get("shortName") is None):
                    raise netutil.RetryableError("empty profile " + t)
                return inf
            inf = netutil.call_with_retry(once, max_tries=rl(cfg)["max_retries"])
            rows.append({
                "ticker": t,
                "company": inf.get("shortName") or inf.get("longName") or "",
                "sector": inf.get("sector") or "",
                "industry": inf.get("industry") or "",
                "forward_pe": inf.get("forwardPE"),
                "analyst_mean": inf.get("recommendationMean"),
                "analyst_count": inf.get("numberOfAnalystOpinions"),
                "target_mean": inf.get("targetMeanPrice"),
                "target_median": inf.get("targetMedianPrice"),
                    "earnings_ts": inf.get("earningsTimestamp"),
            })
            done.add(t)
            try:
                ed = tk.earnings_dates
            except Exception:
                ed = None
            if ed is not None and len(ed):
                ed = ed.reset_index()
                for _, r in ed.iterrows():
                    erows.append({
                        "ticker": t,
                        "earnings_dt": str(r.iloc[0]),
                        "eps_estimate": r.get("EPS Estimate"),
                        "eps_actual": r.get("Reported EPS"),
                        "surprise_pct": r.get("Surprise(%)"),
                    })
        except Exception:
            fails += 1
            if old_info is not None and t in old_info.index:
                rows.append(old_info.loc[t].to_dict())
        if (i + 1) % 25 == 0:
            print("Yahoo profiles %d / %d" % (i + 1, len(todo)))
            if rows:
                pd.DataFrame(rows).drop_duplicates("ticker", keep="last").to_csv(info_p, index=False)
            if erows:
                pd.DataFrame(erows).to_csv(earn_p, index=False)
            progress_save(cache, "yahoo", done)
    if rows:
        info = pd.DataFrame(rows).drop_duplicates("ticker", keep="last")
        info.to_csv(info_p, index=False)
    if erows:
        earn = pd.DataFrame(erows)
        # keep prior earnings for tickers we failed, if we got nothing for them
        if fails and os.path.exists(earn_p):
            prev = read_csv(earn_p)
            if len(prev):
                got = set(earn["ticker"])
                earn = pd.concat([earn, prev[~prev["ticker"].isin(got)]], ignore_index=True)
        earn.to_csv(earn_p, index=False)
    progress_save(cache, "yahoo", done)
    fail_rate = fails / max(len(todo), 1)
    if fail_rate > 0.5:
        log("Analyst and profile (Yahoo Finance)", "CACHED" if len(info) else "MISSING", "", "%d of %d failed" % (fails, len(tickers)))
        log("Earnings dates (Yahoo Finance)", "CACHED" if len(earn) else "MISSING", "", "same pass as profiles")
    else:
        STAMPS["yahoo_slow"] = today_et()
        log("Analyst and profile (Yahoo Finance)", "OK", today_et(), "%d names, %d failed" % (len(info), fails))
        log("Earnings dates (Yahoo Finance)", "OK" if len(earn) else "MISSING", today_et(), "%d rows" % len(earn))
    return info, earn


def _parse_int(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace("%", "").strip()
    if s in ("", "N/A", "--", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_holders(tickers, cfg, cache, mode):
    path = os.path.join(cache, "holders.csv")
    detail_p = os.path.join(cache, "holder_rows.csv")
    summary, detail = read_csv(path), read_csv(detail_p)
    decision = _need_fetch("holders", path, mode)
    gaps = None
    if decision == "reuse":
        gaps = _missing_tickers(summary, tickers) if mode == "full" else []
        if not gaps:
            log("Institutional 13F and insider (Nasdaq)", "OK", STAMPS.get("holders", ""), "reused cache (slow sources refresh at most once a day)")
            return summary, detail
        print("Nasdaq filling %d names added since the daily fetch" % len(gaps))
    if decision == "missing":
        log("Institutional 13F and insider (Nasdaq)", "MISSING", "", "no cache and this run does not call Nasdaq")
        return summary, detail
    lim = netutil.RateLimiter(rl(cfg)["nasdaq_requests_per_second"])
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    done = progress_load(cache, "holders")
    sums, rows, fails = [], [], 0
    old = summary.set_index("ticker") if len(summary) and "ticker" in summary.columns else None
    if len(summary) and done:
        sums.extend(summary[summary["ticker"].isin(done)].to_dict("records"))
    if len(detail) and done and "ticker" in detail.columns:
        rows.extend(detail[detail["ticker"].isin(done)].to_dict("records"))
    pool = gaps if gaps else list(tickers)
    todo = [t for t in pool if t not in done]
    if done:
        print("Nasdaq skipping %d names already fetched today" % len(done))
    for i, t in enumerate(todo):
        try:
            hurl = "https://api.nasdaq.com/api/company/%s/institutional-holdings?limit=5" % t
            iurl = "https://api.nasdaq.com/api/company/%s/insider-trades?limit=5" % t
            hr = netutil.http_get(requests, hurl, headers, 30, limiter=lim, max_tries=rl(cfg)["max_retries"])
            ir = netutil.http_get(requests, iurl, headers, 30, limiter=lim, max_tries=rl(cfg)["max_retries"])
            hd, idata = hr.json().get("data") or {}, ir.json().get("data") or {}
            increased = decreased = holders = own = None
            as_of = ""
            for r in ((hd.get("activePositions") or {}).get("rows") or []):
                name = r.get("positions") or ""
                if "Increased" in name:
                    increased = _parse_int(r.get("shares"))
                elif "Decreased" in name:
                    decreased = _parse_int(r.get("shares"))
                elif "Total" in name:
                    holders = _parse_int(r.get("holders"))
            own_s = ((hd.get("ownershipSummary") or {}).get("SharesOutstandingPCT") or {}).get("value")
            own = _parse_int(own_s)
            table = ((hd.get("holdingsTransactions") or {}).get("table") or {})
            for r in (table.get("rows") or [])[:5]:
                if not as_of:
                    as_of = r.get("date") or ""
                rows.append({
                    "ticker": t, "owner": r.get("ownerName"), "shares": _parse_int(r.get("sharesHeld")),
                    "share_change": _parse_int(r.get("sharesChange")), "as_of": r.get("date") or "",
                })
            buys = sells = None
            for r in ((idata.get("numberOfTrades") or {}).get("rows") or []):
                name = r.get("insiderTrade") or ""
                if "Buy" in name:
                    buys = _parse_int(r.get("months3"))
                elif "Sell" in name:
                    sells = _parse_int(r.get("months3"))
            sums.append({
                "ticker": t, "inst_up": increased, "inst_down": decreased, "holders": holders,
                "ownership_pct": own,                 "as_of": as_of, "insider_buys": buys, "insider_sells": sells,
            })
            done.add(t)
        except Exception:
            fails += 1
            if old is not None and t in old.index:
                sums.append(old.loc[t].to_dict())
        if (i + 1) % 40 == 0:
            print("Nasdaq %d / %d" % (i + 1, len(todo)))
            if sums:
                pd.DataFrame(sums).drop_duplicates("ticker", keep="last").to_csv(path, index=False)
            if rows:
                pd.DataFrame(rows).to_csv(detail_p, index=False)
            progress_save(cache, "holders", done)
    if sums:
        summary = pd.DataFrame(sums).drop_duplicates("ticker", keep="last")
        summary.to_csv(path, index=False)
    if rows:
        detail = pd.DataFrame(rows)
        detail.to_csv(detail_p, index=False)
    progress_save(cache, "holders", done)
    fail_rate = fails / max(len(todo), 1)
    if fail_rate > 0.5:
        log("Institutional 13F and insider (Nasdaq)", "CACHED" if len(summary) else "MISSING", "", "%d of %d failed" % (fails, len(tickers)))
    else:
        STAMPS["holders"] = today_et()
        log("Institutional 13F and insider (Nasdaq)", "OK", today_et(), "%d names, %d failed" % (len(summary), fails))
    return summary, detail


def load_news(tickers, cfg, cache, mode):
    path = os.path.join(cache, "news.csv")
    cached = read_csv(path) if os.path.exists(path) else pd.DataFrame()
    decision = _need_fetch("news", path, mode)
    if decision != "fetch":
        status = "OK" if len(cached) else "MISSING"
        note = "reused cache" if len(cached) else "no cache and this run does not fetch headlines"
        if decision == "missing":
            status = "MISSING"
        log("News headlines (Yahoo Finance)", status, STAMPS.get("news", ""), note)
        return cached
    lim = netutil.RateLimiter(rl(cfg)["news_per_second"])
    headers = {"User-Agent": "Mozilla/5.0"}
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    rows, fails = [], 0
    for t in tickers:
        try:
            def once(ticker=t):
                lim.wait()
                resp = requests.get(url, params={"q": ticker, "newsCount": 4, "quotesCount": 0}, headers=headers, timeout=20)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise netutil.RetryableError("news HTTP %s" % resp.status_code)
                if resp.status_code in (403, 404):
                    raise netutil.PermanentError("news HTTP %s" % resp.status_code)
                resp.raise_for_status()
                return resp.json()
            payload = netutil.call_with_retry(once, max_tries=3)
            for item in (payload.get("news") or [])[:4]:
                when = item.get("providerPublishTime")
                try:
                    published = pd.to_datetime(int(when), unit="s", utc=True).tz_convert(PT).strftime("%Y-%m-%d %H:%M PT")
                except Exception:
                    published = ""
                rows.append({
                    "ticker": t, "headline": item.get("title") or "", "publisher": item.get("publisher") or "",
                    "link": item.get("link") or "", "published": published,
                })
        except Exception:
            fails += 1
    if rows:
        df = pd.DataFrame(rows)
        if fails and len(cached):
            got = set(df["ticker"])
            df = pd.concat([df, cached[~cached["ticker"].isin(got)]], ignore_index=True)
        df.to_csv(path, index=False)
        STAMPS["news"] = today_et()
        log("News headlines (Yahoo Finance)", "OK", today_et(), "%d headlines, %d names failed" % (len(rows), fails))
        return df
    if len(cached):
        log("News headlines (Yahoo Finance)", "CACHED", "", "%d names failed" % fails)
        return cached
    log("News headlines (Yahoo Finance)", "MISSING", "", "no headlines")
    return pd.DataFrame()


def load_walls(tickers, cfg, cache, mode):
    path = os.path.join(cache, "option_walls.csv")
    cached = read_csv(path) if os.path.exists(path) else pd.DataFrame()
    decision = _need_fetch("option_walls", path, mode)
    if decision != "fetch":
        log("Option walls (Yahoo option chain)", "OK" if len(cached) else "MISSING", STAMPS.get("option_walls", ""),
            "reused cache (option chains refresh at most once a day)" if len(cached) else "no cache and this run does not download chains")
        return cached
    import yfinance as yf
    lim = netutil.RateLimiter(rl(cfg)["option_chain_per_second"])
    rows, fails = [], 0
    for t in tickers:
        try:
            lim.wait()
            tk = yf.Ticker(t)
            exps = list(tk.options or [])[:3]
            for exp in exps:
                lim.wait()
                chain = tk.option_chain(exp)
                for side, frame in (("call", chain.calls), ("put", chain.puts)):
                    if frame is None or len(frame) == 0:
                        continue
                    use = frame[pd.to_numeric(frame.get("openInterest"), errors="coerce").fillna(0) > 0]
                    for _, r in use.iterrows():
                        rows.append({
                            "ticker": t, "expiry": exp, "side": side, "strike": r.get("strike"),
                            "open_interest": r.get("openInterest"), "volume": r.get("volume"),
                        })
        except Exception:
            fails += 1
    if rows:
        df = pd.DataFrame(rows)
        # mark the strike with the most open interest on each side
        df["is_wall"] = "no"
        for (t, exp, side), g in df.groupby(["ticker", "expiry", "side"]):
            idx = pd.to_numeric(g["open_interest"], errors="coerce").idxmax()
            df.at[idx, "is_wall"] = "yes"
        df.to_csv(path, index=False)
        STAMPS["option_walls"] = today_et()
        log("Option walls (Yahoo option chain)", "OK", today_et(), "%d rows, %d names failed" % (len(df), fails))
        return df
    if len(cached):
        log("Option walls (Yahoo option chain)", "CACHED", "", "%d names failed" % fails)
        return cached
    log("Option walls (Yahoo option chain)", "MISSING", "", "no chains")
    return pd.DataFrame()


def load_pcr(cfg, cache, mode):
    path = os.path.join(cache, "pcr.csv")
    cached = read_csv(path) if os.path.exists(path) else pd.DataFrame()
    decision = _need_fetch("pcr", path, mode)
    if decision != "fetch":
        log("Put/call (CBOE)", "OK" if len(cached) else "MISSING", STAMPS.get("pcr", ""),
            "reused cache" if len(cached) else "no cache")
        return cached
    lim = netutil.RateLimiter(5)
    headers = session_headers(cfg)
    days = 160 if len(cached) < 40 else 6
    rows = []
    if len(cached):
        rows.extend(cached.to_dict("records"))
    have = set(str(r.get("date")) + "|" + str(r.get("name")) for r in rows)
    start = dt.date.today()
    got_new = 0
    for i in range(days):
        day = start - dt.timedelta(days=i)
        if day.weekday() >= 5:
            continue
        f = os.path.join(cache, "pcr", "%s.json" % day)
        payload = None
        if os.path.exists(f) and i > 4:
            try:
                payload = json.load(open(f))
            except Exception:
                payload = None
        if payload is None:
            url = "https://cdn.cboe.com/data/us/options/market_statistics/daily/%s_daily_options" % day
            try:
                r = netutil.http_get(requests, url, headers, 20, limiter=lim, max_tries=2)
                payload = r.json()
                with open(f, "w") as fh:
                    json.dump(payload, fh)
                got_new += 1
            except Exception:
                continue
        for item in payload.get("ratios") or []:
            key = "%s|%s" % (day, item.get("name"))
            if key in have:
                continue
            try:
                val = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            rows.append({"date": str(day), "name": item.get("name"), "value": val})
            have.add(key)
    df = pd.DataFrame(rows)
    if len(df):
        df = df.drop_duplicates(["date", "name"]).sort_values(["name", "date"])
        df.to_csv(path, index=False)
        STAMPS["pcr"] = today_et()
        log("Put/call (CBOE)", "OK", df["date"].max(), "%d days refreshed" % got_new)
        return df
    log("Put/call (CBOE)", "MISSING", "", "no files")
    return df


def load_fred(cfg, cache, mode):
    """FRED is often blocked from GitHub runners. Failure must not stop the job."""
    out = {}
    if mode == "offline":
        for sid in ("DGS10", "T10Y2Y"):
            f = os.path.join(cache, "fred_%s.csv" % sid)
            if os.path.exists(f):
                s = pd.read_csv(f)
                s.columns = ["date", "v"][:len(s.columns)]
                v = pd.to_numeric(s.iloc[:, 1], errors="coerce").dropna()
                if len(v):
                    out[sid] = float(v.iloc[-1])
        log("FRED", "OK" if out else "MISSING", "", "offline mode")
        return out
    headers = session_headers(cfg)
    ok = False
    err = ""
    for sid in ("DGS10", "T10Y2Y"):
        f = os.path.join(cache, "fred_%s.csv" % sid)
        try:
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + sid
            r = netutil.http_get(requests, url, headers, 12, max_tries=2, delays=(1.5, 3.0))
            open(f, "w").write(r.text)
            ok = True
        except Exception as exc:
            err = str(exc)[:120]
        if os.path.exists(f):
            try:
                s = pd.read_csv(f)
                v = pd.to_numeric(s.iloc[:, 1], errors="coerce").dropna()
                if len(v):
                    out[sid] = float(v.iloc[-1])
            except Exception:
                pass
    if ok:
        log("FRED", "OK", today_et(), "10-year yield and 10y-2y")
    elif out:
        log("FRED", "CACHED", "", err or "request failed, used the saved file")
    else:
        log("FRED", "MISSING", "", err or "no data and no cache. GitHub runners often block FRED.")
    return out


def _num_text(v):
    if v is None:
        return None
    v = html.unescape(str(v)).replace("\xa0", " ").replace(",", "").strip()
    if v in ("", "-", "—", "N/A"):
        return None
    m = re.match(r"^([-+]?\d*\.?\d+)\s*([%KMBT]?)", v)
    if not m:
        return None
    x = float(m.group(1))
    return x * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(m.group(2), 1)


def load_econ(cfg, cache, mode):
    path = os.path.join(cache, "econ.csv")
    cached = read_csv(path) if os.path.exists(path) else pd.DataFrame()
    decision = _need_fetch("econ", path, mode)
    if decision != "fetch":
        log("Economic calendar (Nasdaq)", "OK" if len(cached) else "MISSING", STAMPS.get("econ", ""),
            "reused cache" if len(cached) else "no cache")
        return cached
    lim = netutil.RateLimiter(rl(cfg)["nasdaq_requests_per_second"])
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    days = 120 if len(cached) < 20 else 12
    rows = []
    start = dt.date.today()
    for i in range(days):
        day = start - dt.timedelta(days=i)
        if day.weekday() >= 5:
            continue
        f = os.path.join(cache, "econ", "%s.json" % day)
        payload = None
        if os.path.exists(f) and i > 3:
            try:
                payload = json.load(open(f))
            except Exception:
                payload = None
        if payload is None:
            url = "https://api.nasdaq.com/api/calendar/economicevents?date=%s" % day
            try:
                r = netutil.http_get(requests, url, headers, 25, limiter=lim, max_tries=2)
                payload = r.json()
                with open(f, "w") as fh:
                    json.dump(payload, fh)
            except Exception:
                continue
        for item in ((payload.get("data") or {}).get("rows") or []):
            if item.get("country") not in ("United States", "US"):
                continue
            event = (item.get("eventName") or "").strip()
            actual = _num_text(item.get("actual"))
            forecast = _num_text(item.get("consensus"))
            for cat, label, names, good in ECON_SPECS:
                if event not in names:
                    continue
                surprise = None if actual is None or forecast is None else actual - forecast
                signal = None if surprise is None else (1 if surprise > 0 else -1 if surprise < 0 else 0) * good
                rows.append({
                    "country": "US", "category": cat, "indicator": label, "date": str(day),
                    "actual": item.get("actual"), "forecast": item.get("consensus"),
                    "surprise": surprise, "signal": signal,
                })
    df = pd.DataFrame(rows)
    if len(df):
        df = df.drop_duplicates(["indicator", "date"], keep="last")
        df.to_csv(path, index=False)
        STAMPS["econ"] = today_et()
        log("Economic calendar (Nasdaq)", "OK", df["date"].max(), "%d matched releases" % len(df))
        return df
    if len(cached):
        log("Economic calendar (Nasdaq)", "CACHED", "", "no fresh rows")
        return cached
    log("Economic calendar (Nasdaq)", "MISSING", "", "no matched releases")
    return df


# ---------------------------------------------------------------- score
def _rsi_series(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def _last(series, n=None):
    s = series.dropna()
    if n is not None and len(s) < n:
        return None
    if not len(s):
        return None
    return float(s.iloc[-1])


def market_features(close, high, low, vol, ticker, spy):
    if ticker not in close.columns:
        return None
    c = close[ticker].dropna()
    if len(c) < 30:
        return None
    h = high[ticker] if high is not None and ticker in high.columns else c
    l = low[ticker] if low is not None and ticker in low.columns else c
    v = vol[ticker] if vol is not None and ticker in vol.columns else None
    sma = lambda n: float(c.rolling(n).mean().iloc[-1]) if len(c) >= n else None
    rsi = _rsi_series(c)
    rsi_now = float(rsi.dropna().iloc[-1]) if rsi.dropna().shape[0] else None
    rsi_prev = float(rsi.dropna().iloc[-6]) if rsi.dropna().shape[0] > 6 else None
    prev_c = c.shift(1)
    tr = pd.concat([(h.reindex(c.index) - l.reindex(c.index)), (h.reindex(c.index) - prev_c).abs(), (l.reindex(c.index) - prev_c).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1]) if tr.dropna().shape[0] >= 14 else float(c.diff().abs().rolling(14).mean().iloc[-1])
    price = float(c.iloc[-1])
    high252 = float(h.reindex(c.index).tail(252).max())
    low252 = float(l.reindex(c.index).tail(252).min())
    def ret(n):
        if len(c) > n and c.iloc[-1 - n] > 0:
            return float(c.iloc[-1] / c.iloc[-1 - n] - 1)
        return None
    rs = None
    if spy is not None:
        sp = spy.reindex(c.index).dropna()
        both = c.reindex(sp.index).dropna()
        if len(both) > 63 and len(sp) > 63:
            rs = float(both.iloc[-1] / both.iloc[-64] - 1) - float(sp.iloc[-1] / sp.iloc[-64] - 1)
    vol_ratio = dollar = None
    if v is not None:
        vv = v.reindex(c.index).dropna()
        if len(vv) > 20 and vv.tail(20).mean():
            vol_ratio = float(vv.iloc[-1] / vv.tail(20).mean())
            dollar = float(price * vv.tail(20).mean())
    ytd = None
    year = c.index[-1].year
    sub = c[c.index.year == year]
    if len(sub) > 1 and sub.iloc[0] > 0:
        ytd = float(sub.iloc[-1] / sub.iloc[0] - 1)
    return {
        "price": price,
        "sma20": sma(20), "sma50": sma(50), "sma100": sma(100), "sma200": sma(200),
        "rsi": rsi_now, "rsi_prev": rsi_prev, "atr": atr,
        "high252": high252, "low252": low252,
        "day_pct": ret(1), "ret_1w": ret(5), "ret_1m": ret(21), "ret_3m": ret(63), "ret_ytd": ytd,
        "rs_spy": rs, "vol_ratio": vol_ratio, "dollar_volume": dollar,
        "dist_52w": (price / high252 - 1) if high252 else None,
        "near_low": bool(low252 and price <= low252 * 1.01),
        "asof": str(c.index[-1].date()),
    }


def build_scores(universe, close, high, low, vol, annual, quarters, info, holders, earnings, cfg):
    scfg = cfg["scoring"]
    info_i = info.set_index("ticker") if len(info) else pd.DataFrame()
    hold_i = holders.set_index("ticker") if len(holders) else pd.DataFrame()
    prepared = {}
    q_by = {}
    if len(quarters):
        q = quarters.copy()
        for t, g in q.groupby("ticker"):
            q_by[t] = g
    spy = close["SPY"] if "SPY" in close.columns else None
    etf_ret = {}
    if spy is not None:
        for etf in SECTOR_ETF_BY_NAME.values():
            if etf in close.columns and len(close[etf].dropna()) > 63:
                e = close[etf].dropna()
                s = spy.reindex(e.index).dropna()
                if len(s) > 63:
                    etf_ret[etf] = float(e.iloc[-1] / e.iloc[-64] - 1) - float(s.iloc[-1] / s.iloc[-64] - 1)
    rows = []
    group_etf = {}
    for etf in cfg.get("sector_etfs", []):
        group_etf.setdefault(etf.get("group"), etf["ticker"])
    for _, u in universe.iterrows():
        t = u["ticker"]
        mkt = market_features(close, high, low, vol, t, spy)
        if not mkt:
            continue
        if t not in prepared:
            sub = annual[annual["ticker"] == t] if len(annual) and "ticker" in annual.columns else pd.DataFrame()
            prepared[t] = fund.prepare_annual(sub, close[t].dropna()) if t in close.columns and len(sub) else pd.DataFrame()
        fin = fund.metrics_asof(prepared[t], mkt["asof"], mkt["price"], q_by.get(t))
        inf = info_i.loc[t].to_dict() if len(info_i) and t in info_i.index else {}
        if isinstance(info_i.loc[t], pd.DataFrame) if len(info_i) and t in info_i.index else False:
            inf = info_i.loc[t].iloc[-1].to_dict()
        hol = hold_i.loc[t].to_dict() if len(hold_i) and t in hold_i.index else {}
        if len(hold_i) and t in hold_i.index and isinstance(hold_i.loc[t], pd.DataFrame):
            hol = hold_i.loc[t].iloc[-1].to_dict()
        eps_flag = rev_flag = None
        if len(earnings) and "ticker" in earnings.columns:
            sube = earnings[earnings["ticker"] == t].copy()
            if len(sube):
                sube["earnings_dt"] = pd.to_datetime(sube["earnings_dt"], utc=True, errors="coerce")
                past = sube[pd.to_numeric(sube["eps_actual"], errors="coerce").notna()].sort_values("earnings_dt")
                if len(past):
                    last = past.iloc[-1]
                    eps_flag = scoring.beat_flag(scoring._f(last["eps_actual"]), scoring._f(last["eps_estimate"]))
        sector = u.get("sector") or inf.get("sector") or ""
        etf = SECTOR_ETF_BY_NAME.get(sector) or group_etf.get(sector)
        extra = {
            "forward_pe": scoring._f(inf.get("forward_pe")),
            "analyst_mean": scoring._f(inf.get("analyst_mean")),
            "analyst_n": scoring._f(inf.get("analyst_count")),
            "target_mean": scoring._f(inf.get("target_mean")),
            "target_median": scoring._f(inf.get("target_median")),
            "inst_up": scoring._f(hol.get("inst_up")),
            "inst_down": scoring._f(hol.get("inst_down")),
            "insider_buys": scoring._f(hol.get("insider_buys")),
            "insider_sells": scoring._f(hol.get("insider_sells")),
            "eps_flag": eps_flag, "rev_flag": rev_flag,
            "sector_excess": etf_ret.get(etf),
        }
        rec = scoring.score_components(fin, mkt, extra, scfg)
        # display percents
        for key in ("rev_growth", "rev_growth_avg", "eps_growth", "eps_growth_avg", "roe", "roe_avg",
                    "div_yield", "div_yield_avg", "day_pct", "ret_1w", "ret_1m", "ret_3m", "ret_ytd", "rs_spy", "dist_52w"):
            val = rec.get(key, mkt.get(key) if key in ("day_pct", "ret_1w", "ret_1m", "ret_3m", "ret_ytd") else None)
        rec["day_pct"] = _pct(mkt["day_pct"])
        rec["ret_1w"] = _pct(mkt["ret_1w"])
        rec["ret_1m"] = _pct(mkt["ret_1m"])
        rec["ret_3m"] = _pct(mkt["ret_3m"])
        rec["ret_ytd"] = _pct(mkt["ret_ytd"])
        rec["rs_spy_3m"] = _pct(mkt["rs_spy"])
        rec["dist_52w_high_pct"] = _pct(mkt["dist_52w"])
        for key in ("rev_growth", "eps_growth", "roe", "div_yield"):
            rec[key] = _pct(rec.get(key))
            rec[key + "_avg"] = _pct(rec.get(key + "_avg"))
        rec.update({
            "ticker": t,
            "company": u.get("company") or inf.get("company") or "",
            "sector": sector,
            "industry": inf.get("industry") or "",
            "index_membership": u.get("index_membership") or membership_label(u.get("in_sp500"), u.get("in_ndx100"), u.get("in_growth")),
            "universe": u.get("index_membership") or membership_label(u.get("in_sp500"), u.get("in_ndx100"), u.get("in_growth")),
            "price": round(mkt["price"], 2),
            "price_as_of": mkt["asof"],
            "rsi14": None if mkt["rsi"] is None else round(mkt["rsi"], 1),
            "volume_ratio": None if mkt["vol_ratio"] is None else round(mkt["vol_ratio"], 2),
            "dollar_volume": mkt["dollar_volume"],
            "above_sma20": _above(mkt["price"], mkt["sma20"]),
            "above_sma50": _above(mkt["price"], mkt["sma50"]),
            "above_sma100": _above(mkt["price"], mkt["sma100"]),
            "above_sma200": _above(mkt["price"], mkt["sma200"]),
            "near_low": mkt["near_low"],
            "analyst_mean": extra["analyst_mean"],
            "analyst_count": extra["analyst_n"],
            "fundamentals_basis": fin.get("basis") or "",
            "fundamentals_filed": fin.get("filed") or "",
            "fin_avg_years": fin.get("avg_years") or 0,
            "inst_up": extra["inst_up"], "inst_down": extra["inst_down"],
            "insider_buys_3m": extra["insider_buys"], "insider_sells_3m": extra["insider_sells"],
            "holders_asof": hol.get("as_of") or "",
            "ownership_pct": hol.get("ownership_pct"),
            "holders_n": hol.get("holders"),
            "dps": fin.get("dps"),
            "prepared": prepared[t],
        })
        # next earnings
        nxt = ""
        if len(earnings) and "ticker" in earnings.columns:
            sube = earnings[earnings["ticker"] == t]
            if len(sube):
                dts = pd.to_datetime(sube["earnings_dt"], utc=True, errors="coerce")
                future = dts[dts > pd.Timestamp.now(tz="UTC")]
                if len(future):
                    nxt = str(future.min().date())
        if not nxt and inf.get("earnings_ts"):
            try:
                nxt = str(pd.to_datetime(float(inf["earnings_ts"]), unit="s").date())
            except Exception:
                nxt = ""
        rec["next_earnings"] = nxt
        miss = tables.missing_fields(rec)
        rec["missing_fields"] = ";".join(miss)
        rec["missing_count"] = len(miss)
        for k in ("entry_low", "entry_high", "stop", "trade_target", "target_analyst", "target_pfcf", "target_peg", "target_blended"):
            if rec.get(k) is not None and np.isfinite(rec[k]):
                rec[k] = round(float(rec[k]), 2)
            elif rec.get(k) is not None and not np.isfinite(rec.get(k) or np.nan):
                rec[k] = None
        if rec.get("reward_risk") is not None and np.isfinite(rec["reward_risk"]):
            rec["reward_risk"] = round(float(rec["reward_risk"]), 2)
        rows.append(rec)
    df = pd.DataFrame(rows)
    if len(df):
        df = scoring.add_industry(df, scfg["flat_band_pct"])
        df = df.sort_values(["score", "ticker"], ascending=[False, True], na_position="last")
        df.insert(0, "rank", range(1, len(df) + 1))
    return df, prepared


def _pct(x):
    if x is None or not np.isfinite(x):
        return None
    return round(float(x) * 100, 2)


def _above(price, sma):
    if sma is None or not np.isfinite(sma):
        return ""
    return 1 if price > sma else 0


def apply_feature_blanks(df, features):
    if df is None or len(df) == 0:
        return df
    out = df.copy()
    if not features.get("score_breakdown", True):
        for c in out.columns:
            if c.startswith("pts_") or c in ("score", "confidence"):
                out[c] = np.nan
    if not features.get("verdicts", True):
        for c in ("verdict", "reason", "entry_low", "entry_high", "stop", "trade_target", "reward_risk"):
            if c in out.columns:
                out[c] = np.nan if c != "verdict" and c != "reason" else ""
    if not features.get("momentum_timing", True):
        for c in ("timing", "sma_alignment", "rs_spy_3m", "dist_52w_high_pct", "volume_ratio", "rsi14"):
            if c in out.columns:
                out[c] = np.nan if c != "timing" and c != "sma_alignment" else ""
    if not features.get("freshness_flags", True):
        for c in ("missing_fields", "missing_count", "price_status", "fundamentals_status", "analyst_status", "holders_status"):
            if c in out.columns:
                out[c] = ""
    return out


def holdings_table(cfg, inp):
    path = os.path.join(inp, "holdings.csv")
    if os.path.exists(path):
        df = read_csv(path)
        if len(df):
            return df
    rows = cfg.get("holdings") or []
    df = pd.DataFrame(rows)
    if len(df):
        os.makedirs(inp, exist_ok=True)
        df.to_csv(path, index=False)
    return df


def watch_table(cfg, inp):
    path = os.path.join(inp, "my_watchlist.csv")
    if os.path.exists(path):
        df = read_csv(path)
        if len(df):
            return df
    rows = [{"ticker": t, "note": ""} for t in cfg.get("watchlist", [])]
    df = pd.DataFrame(rows)
    if len(df):
        os.makedirs(inp, exist_ok=True)
        df.to_csv(path, index=False)
    return df


def build_portfolio(holds, scores, history):
    if holds is None or len(holds) == 0 or scores is None or len(scores) == 0:
        return pd.DataFrame(), pd.DataFrame()
    sc = scores.set_index("ticker")
    rows = []
    for _, h in holds.iterrows():
        t = str(h["ticker"]).upper()
        if t not in sc.index:
            continue
        r = sc.loc[t]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        shares = float(h["shares"])
        cost = float(h["avg_cost"])
        price = float(r["price"])
        value = shares * price
        basis = shares * cost
        week = _week_score(history, t)
        change = None if week is None or scoring._f(r.get("score")) is None else int(r["score"]) - int(week)
        status = "On track"
        if scoring._f(r.get("stop")) and price < float(r["stop"]):
            status = "Below stop"
        elif r.get("next_earnings"):
            try:
                days = (pd.Timestamp(r["next_earnings"]) - pd.Timestamp.now().normalize()).days
                if 0 <= days <= 7:
                    status = "Earnings soon"
            except Exception:
                pass
        if status == "On track" and change is not None and change <= -2:
            status = "Weakening"
        rows.append({
            "ticker": t, "company": r.get("company"), "shares": shares, "avg_cost": cost, "price": price,
            "day_pct": r.get("day_pct"), "value": round(value, 2), "cost": round(basis, 2),
            "gain": round(value - basis, 2), "gain_pct": round((price / cost - 1) * 100, 2) if cost else None,
            "score": r.get("score"), "score_week_ago": week, "score_week_change": change,
            "verdict": r.get("verdict"), "stop": r.get("stop"), "status": status,
            "example": h.get("example", ""),
        })
    port = pd.DataFrame(rows)
    if not len(port):
        return port, pd.DataFrame()
    total = port["value"].sum()
    port["weight_pct"] = (port["value"] / total * 100).round(1) if total else np.nan
    day = 0.0
    for _, r in port.iterrows():
        pct = scoring._f(r.get("day_pct"))
        if pct is not None:
            day += r["value"] - r["value"] / (1 + pct / 100.0)
    needs = int(port["status"].isin(["Below stop", "Weakening", "Earnings soon"]).sum())
    example = "yes" if (port["example"].astype(str).str.lower() == "yes").any() else "no"
    summary = pd.DataFrame([{
        "value": round(float(total), 2),
        "day_pnl": round(day, 2),
        "day_pnl_pct": round(day / (total - day) * 100, 2) if total != day else None,
        "total_gain": round(float(port["gain"].sum()), 2),
        "total_gain_pct": round(float(port["gain"].sum()) / float(port["cost"].sum()) * 100, 2) if port["cost"].sum() else None,
        "avg_score": round(float(pd.to_numeric(port["score"], errors="coerce").mean()), 2),
        "needs_attention": needs,
        "n_holdings": int(len(port)),
        "example_warning": "These holdings include example rows. Edit input/holdings.csv. This desk never places a trade." if example == "yes" else "",
    }])
    return port, summary


def _week_score(history, ticker):
    if history is None or len(history) == 0:
        return None
    sub = history[history["ticker"] == ticker].copy()
    if not len(sub):
        return None
    sub["date"] = pd.to_datetime(sub["date"])
    cut = pd.Timestamp.now().normalize() - pd.Timedelta(days=7)
    old = sub[sub["date"] <= cut]
    if not len(old):
        return None
    return scoring._f(old.sort_values("date").iloc[-1]["score"])


def build_watch(watch, scores):
    if watch is None or len(watch) == 0 or scores is None or len(scores) == 0:
        return pd.DataFrame()
    sc = scores.set_index("ticker")
    rows = []
    for _, w in watch.iterrows():
        t = str(w["ticker"]).upper()
        if t not in sc.index:
            continue
        r = sc.loc[t]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        price = scoring._f(r.get("price"))
        hi = scoring._f(r.get("entry_high"))
        dist = None
        if price and hi:
            dist = round((price / hi - 1) * 100, 2)
        rows.append({
            "ticker": t, "company": r.get("company"), "price": r.get("price"), "day_pct": r.get("day_pct"),
            "score": r.get("score"), "verdict": r.get("verdict"),
            "entry_low": r.get("entry_low"), "entry_high": r.get("entry_high"),
            "distance_to_entry_pct": dist, "timing": r.get("timing"), "note_input": w.get("note", ""),
        })
    return pd.DataFrame(rows)


def price_file(close, scores):
    if close is None or close.empty or scores is None or len(scores) == 0:
        return pd.DataFrame()
    names = [t for t in scores["ticker"] if t in close.columns]
    px = close[names].tail(126)
    sma20 = close[names].rolling(20).mean().reindex(px.index)
    sma50 = close[names].rolling(50).mean().reindex(px.index)
    levels = scores.set_index("ticker")
    rows = []
    for t in names:
        for d, val in px[t].dropna().items():
            rec = levels.loc[t]
            if isinstance(rec, pd.DataFrame):
                rec = rec.iloc[0]
            rows.append({
                "date": str(pd.Timestamp(d).date()), "ticker": t, "close": round(float(val), 2),
                "sma20": None if pd.isna(sma20.at[d, t]) else round(float(sma20.at[d, t]), 2),
                "sma50": None if pd.isna(sma50.at[d, t]) else round(float(sma50.at[d, t]), 2),
                "entry_low": rec.get("entry_low"), "entry_high": rec.get("entry_high"),
                "stop": rec.get("stop"), "trade_target": rec.get("trade_target"),
            })
    return pd.DataFrame(rows)


def news_rows(news, scores):
    rows = []
    if news is None or len(news) == 0:
        return pd.DataFrame()
    reasons = scores.set_index("ticker")["reason"].to_dict() if len(scores) else {}
    seen = set()
    for _, r in news.iterrows():
        tone, tone_note = scoring.headline_tone(r.get("headline"))
        rows.append({
            "ticker": r["ticker"], "kind": "headline", "headline": r.get("headline"),
            "summary": "%s Source: %s. %s" % (r.get("headline"), r.get("publisher") or "unknown", tone_note),
            "publisher": r.get("publisher"), "link": r.get("link"), "published": r.get("published"),
            "tone": tone, "tone_note": tone_note,
        })
        seen.add(r["ticker"])
    for t in seen:
        if t in reasons and reasons[t]:
            rows.append({
                "ticker": t, "kind": "desk_note", "headline": "Desk note",
                "summary": reasons[t], "publisher": "Desk research note", "link": "", "published": "",
                "tone": "", "tone_note": "This line is the desk's own score sentence, not a news article.",
            })
    return pd.DataFrame(rows)


def attach_status(scores, price_status, fin_status, an_status, hold_status):
    if scores is None or len(scores) == 0:
        return scores
    scores = scores.copy()
    scores["price_status"] = price_status
    scores["fundamentals_status"] = fin_status
    scores["analyst_status"] = an_status
    scores["holders_status"] = hold_status
    scores["data_status"] = "OK"
    scores["note"] = ""
    scores["disclaimer"] = DISCLAIMER
    return scores


def source_status(name):
    for row in LOG:
        if row["source"] == name:
            return row["status"]
    return ""


def main(argv=None):
    global ROOT
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = "full"
    if "--offline" in argv:
        mode = "offline"
    elif "--hourly" in argv:
        mode = "hourly"
    elif "--full" in argv:
        mode = "full"
    ROOT = os.environ.get("DESK_ROOT") or os.path.dirname(os.path.abspath(__file__))
    LOG.clear()
    STAMPS.clear()
    cfg = load_cfg()
    data, cache, inp = paths()
    load_stamps(cache)
    features = cfg["features"]
    holds = holdings_table(cfg, inp)
    watch = watch_table(cfg, inp)
    hold_tickers = [str(t).upper() for t in holds["ticker"]] if len(holds) else []
    watch_tickers = [str(t).upper() for t in watch["ticker"]] if len(watch) else []

    switches = index_switches(cfg)
    if features.get("universe", True):
        sp = load_index("sp500", cfg, cache, mode)
        ndx = load_index("ndx100", cfg, cache, mode)
        growth = growth_frame(cfg)
        universe = combine_indexes([sp, ndx, growth], hold_tickers, watch_tickers, switches)
    else:
        universe = combine_indexes([], hold_tickers, watch_tickers, switches)
        log("Universe feature", "OK", "", "feature off: scoring the holdings and watchlist only")
    etfs = [e["ticker"] for e in cfg.get("sector_etfs", [])]
    extras = etfs + ["SPY", "^VIX"]
    tickers = list(dict.fromkeys(list(universe["ticker"]) + extras))
    long = load_prices(tickers, cfg, cache, mode)
    close, high, low, vol = wide_from_long(long, "close"), wide_from_long(long, "high"), wide_from_long(long, "low"), wide_from_long(long, "volume")
    price_status = source_status("Prices (Yahoo Finance)")

    score_on = features.get("score_breakdown", True) or features.get("scorecard", True) or features.get("top_stocks", True)
    cik = cik_map(cfg, cache, mode) if score_on else {}
    sec_tickers = [t for t in universe["ticker"] if t in (cik or {})]
    if not score_on:
        annual, quarters = pd.DataFrame(), pd.DataFrame()
        info, earnings = pd.DataFrame(), pd.DataFrame()
        holders, holder_rows = pd.DataFrame(), pd.DataFrame()
    else:
        annual, quarters = load_sec(list(universe["ticker"]), cik, cfg, cache, mode) if cik else (pd.DataFrame(), pd.DataFrame())
        if not cik and score_on:
            log("Fundamentals (SEC EDGAR company facts)", "MISSING", "", "no CIK map")
        info, earnings = load_yahoo(list(universe["ticker"]), cfg, cache, mode)
        holders, holder_rows = load_holders(list(universe["ticker"]), cfg, cache, mode)
    # fill sector gaps from Yahoo
    if len(info) and len(universe):
        imap = info.set_index("ticker")
        for i, u in universe.iterrows():
            t = u["ticker"]
            if t in imap.index:
                row = imap.loc[t]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[-1]
                if not u.get("sector") and row.get("sector"):
                    universe.at[i, "sector"] = row.get("sector")
                if not u.get("company") and row.get("company"):
                    universe.at[i, "company"] = row.get("company")

    scores, prepared = build_scores(universe, close, high, low, vol, annual, quarters, info, holders, earnings, cfg) if len(close) else (pd.DataFrame(), {})
    scores = apply_feature_blanks(scores, features)
    fin_status = source_status("Fundamentals (SEC EDGAR company facts)")
    an_status = source_status("Analyst and profile (Yahoo Finance)")
    hold_status = source_status("Institutional 13F and insider (Nasdaq)")
    scores = attach_status(scores, price_status, fin_status, an_status, hold_status)
    if len(scores):
        scores["in_holdings"] = np.where(scores["ticker"].isin(hold_tickers), "yes", "no")

    # focus list for heavy sentiment feeds
    focus = list(dict.fromkeys(hold_tickers + watch_tickers))
    if len(scores):
        focus += list(scores["ticker"].head(25))
    focus = list(dict.fromkeys(focus))[:40]
    news = load_news(focus, cfg, cache, mode) if features.get("headline_sentiment", True) or features.get("news_earnings_summaries", True) else pd.DataFrame()
    walls = load_walls(focus, cfg, cache, mode) if features.get("option_walls", True) else pd.DataFrame()
    pcr = load_pcr(cfg, cache, mode) if features.get("put_call", True) else pd.DataFrame()
    pcr_df = tables.put_call_table(pcr, cfg["scoring"]["fear_line"], cfg["scoring"]["greed_line"]) if len(pcr) else pd.DataFrame()
    fred = load_fred(cfg, cache, mode)
    econ = load_econ(cfg, cache, mode) if features.get("macro_screener", True) else pd.DataFrame()

    # history and alerts
    hist_path = os.path.join(data, "score_history.csv")
    history = read_csv(hist_path) if os.path.exists(hist_path) else pd.DataFrame()
    prev_path = os.path.join(cache, "prev_scores.csv")
    prev = read_csv(prev_path) if os.path.exists(prev_path) else pd.DataFrame()
    alerts = pd.DataFrame(scoring.build_alerts(scores, prev, cfg["scoring"]["score_jump"], cfg["scoring"]["buy_at"], cfg["scoring"]["hold_at"])) if features.get("alerts", True) else pd.DataFrame()
    changes = pd.DataFrame()
    if features.get("alerts", True) and len(scores) and len(prev):
        p = prev.set_index("ticker")
        rows = []
        for _, r in scores.iterrows():
            if r["ticker"] not in p.index:
                continue
            old = p.loc[r["ticker"]]
            if isinstance(old, pd.DataFrame):
                old = old.iloc[-1]
            a, b = scoring._f(r.get("score")), scoring._f(old.get("score"))
            if a is None or b is None or a == b:
                continue
            rows.append({"ticker": r["ticker"], "company": r.get("company"), "price": r.get("price"), "day_pct": r.get("day_pct"),
                         "score": a, "score_prev": b, "score_change": a - b, "verdict": r.get("verdict")})
        changes = pd.DataFrame(rows)
        if len(changes):
            changes = changes.reindex(changes["score_change"].abs().sort_values(ascending=False).index)

    # backtest
    bt = {"summary": pd.DataFrame(), "buckets": pd.DataFrame(), "equity": pd.DataFrame(), "yearly": pd.DataFrame(), "notes": pd.DataFrame()}
    bt_path = os.path.join(data, "backtest_summary.csv")
    run_bt = features.get("backtest", True) and (mode in ("full", "offline") or "--backtest" in argv or not os.path.exists(bt_path))
    if features.get("backtest", True) and run_bt and len(close):
        sector_etf = {}
        for _, u in universe.iterrows():
            sector_etf[u["ticker"]] = SECTOR_ETF_BY_NAME.get(u.get("sector") or "")
        q_by = {t: g for t, g in quarters.groupby("ticker")} if len(quarters) else {}
        bt = scoring.run_backtest(close, prepared, q_by, sector_etf, close, "SPY", cfg["scoring"]["flat_band_pct"])
        if len(bt["summary"]):
            log("Backtest", "OK", bt["summary"]["end"].iloc[-1] if "end" in bt["summary"] else "", "monthly point-in-time test")
        else:
            log("Backtest", "MISSING", "", "not enough history or too few stocks with filings")
    elif features.get("backtest", True) and os.path.exists(bt_path):
        bt = {k: read_csv(os.path.join(data, "backtest_%s.csv" % k)) for k in ("summary", "buckets", "equity", "yearly", "notes")}
        log("Backtest", "OK", "", "reused the last test (it rebuilds on the after-close run)")
    elif not features.get("backtest", True):
        log("Backtest", "OK", "", "feature off")

    # assemble pages
    breadth = tables.breadth_history(close) if features.get("breadth", True) else pd.DataFrame()
    screener, sector_macro = tables.macro_tables(econ, cfg.get("sector_etfs", []))
    sectors = tables.etf_sectors(close, scores, cfg.get("sector_etfs", []), sector_macro) if features.get("top_sectors", True) else pd.DataFrame()
    # if macro feed empty, blank the macro columns and say so
    if features.get("top_sectors", True) and (econ is None or len(econ) == 0) and len(sectors):
        sectors["note"] = sectors.get("note", "")
        sectors["macro_note"] = "Macro surprises are missing, so those columns are blank."
    xratio = tables.xly_xlp_table(close) if features.get("xly_xlp", True) else pd.DataFrame()
    updated = pd.Timestamp.now(tz=PT).strftime("%Y-%m-%d %H:%M PT")
    asof = ""
    if len(close):
        asof = str(close.dropna(how="all").index.max().date())
    market = tables.market_row(close, breadth, pcr_df, fred, xratio, updated, asof, len(scores), scores)
    earn_pages, _hist = tables.earnings_pages(scores, earnings, close, hold_tickers) if len(scores) else ({}, pd.DataFrame())
    g, q, d, w = tables.scanners(scores, cfg["scoring"]) if len(scores) else (pd.DataFrame(),) * 4
    br, tr, pb, gl, heat = tables.technical_pages(scores) if len(scores) else (pd.DataFrame(),) * 5
    port, port_sum = build_portfolio(holds, scores, history) if features.get("watchlist_portfolio", True) else (pd.DataFrame(), pd.DataFrame())
    watch_out = build_watch(watch, scores) if features.get("watchlist_portfolio", True) else pd.DataFrame()
    prices = price_file(close, scores) if features.get("scorecard", True) else pd.DataFrame()
    news_out = news_rows(news, scores) if len(scores) else pd.DataFrame()
    headlines = news_out[news_out["kind"] == "headline"] if len(news_out) and "kind" in news_out.columns else pd.DataFrame()
    details = tables.score_details(scores) if len(scores) else pd.DataFrame()
    fins = tables.financials_long(scores) if len(scores) else pd.DataFrame()
    company = tables.company_rows(annual, close) if features.get("company_financials", True) else pd.DataFrame()
    hpe = tables.historical_pe(close, prepared) if features.get("historical_pe", True) else pd.DataFrame()
    if len(hpe):
        hpe["note"] = "desk_median_trailing_pe is the median of this desk's stocks. official_sp500_pe is MISSING: no free official series."
    fresh = tables.freshness_table(scores) if features.get("freshness_flags", True) else pd.DataFrame()
    # institutional long rows
    inst_rows = []
    if len(holders):
        for _, r in holders.iterrows():
            inst_rows.append({
                "ticker": r["ticker"], "row_type": "summary", "owner": "",
                "increased_shares": r.get("inst_up"), "decreased_shares": r.get("inst_down"),
                "holders": r.get("holders"), "ownership_pct": r.get("ownership_pct"),
                "shares": "", "share_change": "", "as_of": r.get("as_of"),
                "pts_institutional": scores.set_index("ticker")["pts_institutional"].get(r["ticker"]) if len(scores) else "",
            })
    if len(holder_rows):
        for _, r in holder_rows.iterrows():
            inst_rows.append({
                "ticker": r["ticker"], "row_type": "top_holder", "owner": r.get("owner"),
                "increased_shares": "", "decreased_shares": "", "holders": "", "ownership_pct": "",
                "shares": r.get("shares"), "share_change": r.get("share_change"), "as_of": r.get("as_of"),
                "pts_institutional": "",
            })
    inst = pd.DataFrame(inst_rows)
    if len(close) and len(universe):
        setup_frames = setups.build_setups(close, high, low, vol, universe, quarters, annual, holders, features)
    else:
        setup_frames = {k: pd.DataFrame() for k in ("scanner_vcp", "scanner_canslim", "scanner_box", "scanner_flag", "scanner_leaders")}
    def _n(frame):
        if frame is None or len(frame) == 0 or "ticker" not in getattr(frame, "columns", []):
            return 0
        return int((frame["ticker"].astype(str) != "").sum())
    log("Pattern scanners", "OK", asof, "VCP %d, CANSLIM %d, box %d, flag %d, leaders %d. No new downloads." % (
        _n(setup_frames["scanner_vcp"]), _n(setup_frames["scanner_canslim"]),
        _n(setup_frames["scanner_box"]), _n(setup_frames["scanner_flag"]), _n(setup_frames["scanner_leaders"]),
    ))

    insider = holders[["ticker", "insider_buys", "insider_sells"]].rename(columns={"insider_buys": "buys_3m", "insider_sells": "sells_3m"}) if len(holders) else pd.DataFrame()
    if len(insider) and len(scores):
        insider["pts_insider"] = insider["ticker"].map(scores.set_index("ticker")["pts_insider"])

    # walls note
    if len(walls):
        walls = walls.copy()
        walls["note"] = "Open interest only, for the focus list, once a day. Not an option pick."

    aaii_note = "AAII does not publish a free machine-readable survey. This page stays MISSING on purpose. The put/call page is the free mood gauge."

    files = {
        "scores": gated(scores, "scores", features.get("top_stocks", True) or features.get("scorecard", True), "No scores."),
        "score_details": gated(details, "score_details", features.get("scorecard", True), "No score breakdown."),
        "market_today": gated(market, "market_today", True, "No market snapshot."),
        "sectors": gated(sectors, "sectors", features.get("top_sectors", True), "No sector ETFs."),
        "breadth_history": gated(breadth, "breadth_history", features.get("breadth", True), "No breadth history."),
        "alerts": gated(alerts, "alerts", features.get("alerts", True), "No changes versus the last run."),
        "score_changes": gated(changes, "score_changes", features.get("alerts", True), "No score changes versus the last run."),
        "portfolio": gated(port, "portfolio", features.get("watchlist_portfolio", True), "No holdings."),
        "portfolio_summary": gated(port_sum, "portfolio_summary", features.get("watchlist_portfolio", True), "No holdings."),
        "watchlist": gated(watch_out, "watchlist", features.get("watchlist_portfolio", True), "Watchlist is empty."),
        "prices": gated(prices, "prices", features.get("scorecard", True), "No prices."),
        "news": gated(news_out, "news", features.get("news_earnings_summaries", True), "No headlines."),
        "scanner_growth": gated(g, "scanner_growth", features.get("scanner_growth", True), "Growth screen off or empty."),
        "scanner_quality": gated(q, "scanner_quality", features.get("scanner_quality", True), "Quality screen off or empty."),
        "scanner_dividend": gated(d, "scanner_dividend", features.get("scanner_dividend", True), "Dividend screen off or empty."),
        "scanner_wheel": gated(w, "scanner_wheel", features.get("scanner_wheel", True), "Wheel screen off or empty."),
        "scanner_vcp": gated(setup_frames["scanner_vcp"], "scanner_vcp", features.get("scanner_vcp", True), "No VCP setups. The scan used cached prices only."),
        "scanner_canslim": gated(setup_frames["scanner_canslim"], "scanner_canslim", features.get("scanner_canslim", True), "No CANSLIM setups. Missing letters stay not verified. No new downloads."),
        "scanner_box": gated(setup_frames["scanner_box"], "scanner_box", features.get("scanner_box", True), "No box setups in the cached prices."),
        "scanner_flag": gated(setup_frames["scanner_flag"], "scanner_flag", features.get("scanner_flag", True), "No flag setups in the cached prices."),
        "scanner_leaders": gated(setup_frames["scanner_leaders"], "scanner_leaders", features.get("scanner_leaders", True), "No leaders. A leader is a ready or just-broken VCP, a strict CANSLIM qualify, or both."),
        "earnings_calendar": gated(earn_pages.get("calendar"), "earnings_calendar", features.get("earnings_calendar", True), "No earnings dates."),
        "earnings_heatmap": gated(earn_pages.get("heatmap"), "earnings_heatmap", features.get("earnings_heatmap", True), "No earnings history. Revenue vs estimate is not in the free feed."),
        "earnings_cards": gated(earn_pages.get("cards"), "earnings_cards", features.get("earnings_cards", True), "No earnings history to grade."),
        "earnings_history": gated(earn_pages.get("history"), "earnings_history", features.get("earnings_tracker", True), "No earnings history."),
        "put_call": gated(pcr_df, "put_call", features.get("put_call", True), "CBOE put/call was not available."),
        "option_walls": gated(walls, "option_walls", features.get("option_walls", True), "Option chains were not downloaded. They refresh once a day for the focus list only."),
        "analyst_ratings": gated(scores, "analyst_ratings", features.get("analyst_ratings", True), "No analyst data."),
        "institutional_13f": gated(inst, "institutional_13f", features.get("institutional_13f", True), "No 13F summary. The full SEC 13F dump is too large for a fast page, so this file is a pre-aggregated summary."),
        "aaii_sentiment": gated(pd.DataFrame(), "aaii_sentiment", features.get("aaii_sentiment", True), aaii_note) if features.get("aaii_sentiment", True) else pd.DataFrame(columns=tables.COLS["aaii_sentiment"]),
        "insider_trading": gated(insider, "insider_trading", features.get("insider_trading", True), "No insider counts."),
        "headline_sentiment": gated(headlines, "headline_sentiment", features.get("headline_sentiment", True), "No headlines for the focus list."),
        "xly_xlp": gated(xratio, "xly_xlp", features.get("xly_xlp", True), "XLY or XLP price was missing."),
        "financials_summary": gated(fins, "financials_summary", features.get("financials_summary", True), "No financials."),
        "earnings_tracker": gated(earn_pages.get("history"), "earnings_tracker", features.get("earnings_tracker", True), "No earnings tracker."),
        "company_financials": gated(company, "company_financials", features.get("company_financials", True), "No company filings."),
        "dividend_scanner": gated(scores, "dividend_scanner", features.get("dividend_scanner", True), "No dividend rows."),
        "macro_screener": gated(screener, "macro_screener", features.get("macro_screener", True), "No actual-vs-forecast rows. The calendar did not return usable US releases."),
        "sector_macro": gated(sector_macro, "sector_macro", features.get("macro_screener", True), "No sector macro scores because the surprise feed is missing."),
        "historical_pe": gated(hpe, "historical_pe", features.get("historical_pe", True), "Not enough filings to build a median trailing P/E. Official S&P 500 P/E is MISSING."),
        "breakouts": gated(br, "breakouts", features.get("breakouts", True), "No names near a 52-week high."),
        "trends": gated(tr, "trends", features.get("trends", True), "No trend rows."),
        "pullbacks": gated(pb, "pullbacks", features.get("pullbacks", True), "No pullback rows."),
        "gainers_losers": gated(gl, "gainers_losers", features.get("gainers_losers", True), "No gainers."),
        "sector_performance": gated(tables.sector_perf(scores), "sector_performance", features.get("sector_performance", True), "No sector performance."),
        "heatmaps": gated(heat, "heatmaps", features.get("heatmaps", True), "No heatmap."),
        "freshness": gated(fresh, "freshness", features.get("freshness_flags", True), "Freshness flags are off."),
        "updates_log": pd.DataFrame(LOG),
        "help": pd.DataFrame(tables.help_rows(), columns=["topic", "plain_english"]),
        "settings": tables.settings_rows(cfg),
        "universe": gated(universe, "universe", True, "Universe is empty."),
        "backtest_summary": gated(bt.get("summary"), "backtest_summary", features.get("backtest", True), "Not enough point-in-time history to run the test."),
        "backtest_buckets": gated(bt.get("buckets"), "backtest_buckets", features.get("backtest", True), "No buckets."),
        "backtest_equity": gated(bt.get("equity"), "backtest_equity", features.get("backtest", True), "No equity curve."),
        "backtest_yearly": gated(bt.get("yearly"), "backtest_yearly", features.get("backtest", True), "No yearly rows."),
        "backtest_notes": gated(bt.get("notes"), "backtest_notes", features.get("backtest", True), "No notes."),
    }
    # AAII is intentionally a one-row MISSING file when the feature is on.
    if features.get("aaii_sentiment", True):
        files["aaii_sentiment"] = tables.ensure(pd.DataFrame(), tables.COLS["aaii_sentiment"], "MISSING", aaii_note)

    # alerts: if the builder returned nothing, say so plainly instead of looking broken
    if features.get("alerts", True) and (files["alerts"] is None or len(files["alerts"]) == 0 or (len(files["alerts"]) == 1 and files["alerts"].iloc[0].get("data_status") == "MISSING")):
        note = "No prior run to compare yet. Verdict changes show up on the next run." if not len(prev) else "No verdict changes or score crossings this run."
        files["alerts"] = tables.ensure(pd.DataFrame([{"ticker": "", "kind": "info", "text": note}]), tables.COLS["alerts"], "OK", note)

    for name, df in files.items():
        write_out(df if df is not None else pd.DataFrame(), name, data)

    # persist score history and previous snapshot for the next run
    if len(scores):
        today = pd.Timestamp.now(tz=ET).strftime("%Y-%m-%d")
        snap = scores[["ticker", "score", "verdict", "price", "timing", "stop", "insider_buys_3m"]].copy()
        snap["date"] = today
        hist = pd.concat([history, snap[["date", "ticker", "score"]]], ignore_index=True) if len(history) else snap[["date", "ticker", "score"]]
        hist = hist.drop_duplicates(["date", "ticker"], keep="last")
        hist.to_csv(hist_path, index=False)
        snap.to_csv(prev_path, index=False)
    save_stamps(cache)
    meta = {
        "updated_pt": updated,
        "price_as_of": asof,
        "mode": mode,
        "label": DISCLAIMER,
        "n_stocks": int(len(scores)),
        "tabs": sorted(files),
    }
    with open(os.path.join(data, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    # rewrite updates log now that backtest and the rest have logged
    write_out(pd.DataFrame(LOG), "updates_log", data)
    print("wrote %d files to %s" % (len(files), data))
    return files


if __name__ == "__main__":
    main()
