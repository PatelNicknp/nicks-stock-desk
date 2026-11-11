"""Nick's Stock Desk.

Research screen for stocks. It never places a trade and it never calls a broker.

    python stock_desk.py --full      # prices plus the once-a-day fundamentals
    python stock_desk.py --hourly    # prices only; slow sources stay on today's cache
    python stock_desk.py --offline   # cache only, for tests
    python stock_desk.py --backfill  # five-year history for names that have none yet

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
import profiles
import scoring
import tables
import setups
import episodic_pivot
import gap_up
import sector_rotation
import trading_floor
import trading_floor_paper

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
    """Directory that holds config.json.

    main() sets ROOT, including from DESK_ROOT, so tests can point at a temp
    folder. The backfill workflow's follow-up process imports this module and
    never calls main(), which used to leave ROOT as None and crash before the
    new price cache could be committed.
    """
    if ROOT:
        return ROOT
    env = os.environ.get("DESK_ROOT")
    if env:
        return env
    return os.path.dirname(os.path.abspath(__file__))


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

    # Open is already in this Yahoo batch. Keeping it does not add a request.
    return grab("Close"), grab("High"), grab("Low"), grab("Volume"), grab("Open")


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


PRICE_COLS = ["date", "ticker", "close", "high", "low", "volume", "open"]
# Same bar count market_features requires before a name can be scored.
MIN_HISTORY_BARS = 30
GAP_UNAVAILABLE_DAYS = 14
GAP_SHORT_DAYS = 7


def incremental_price_settings(cfg):
    """Knobs for the incremental price download. Missing keys keep these defaults."""
    raw = cfg.get("incremental_prices") or {}
    mode = str(raw.get("refresh_mode") or "weekly").strip().lower()
    if mode not in ("weekly", "slice"):
        mode = "weekly"
    try:
        concurrency = int(raw.get("chart_concurrency", 2))
    except (TypeError, ValueError):
        concurrency = 2
    try:
        overlap = int(raw.get("overlap_days", 5))
    except (TypeError, ValueError):
        overlap = 5
    try:
        below = int(raw.get("repair_below_bars", 126))
    except (TypeError, ValueError):
        below = 126
    try:
        every = int(raw.get("refresh_every_days", 7))
    except (TypeError, ValueError):
        every = 7
    try:
        slices = int(raw.get("refresh_slices", 8))
    except (TypeError, ValueError):
        slices = 8
    try:
        pct = float(raw.get("adjust_tolerance_pct", 0.05))
    except (TypeError, ValueError):
        pct = 0.05
    try:
        dollars = float(raw.get("adjust_tolerance_dollars", 0.02))
    except (TypeError, ValueError):
        dollars = 0.02
    period = str(raw.get("history_period") or "5y").strip() or "5y"
    return {
        "repair": bool(raw.get("repair", True)),
        "refresh": bool(raw.get("refresh", True)),
        "refresh_mode": mode,
        "refresh_every_days": max(1, every),
        "refresh_slices": max(1, slices),
        "overlap_days": max(1, overlap),
        "adjust_tolerance_pct": max(0.0, pct),
        "adjust_tolerance_dollars": max(0.0, dollars),
        "chart_concurrency": min(8, max(1, concurrency)),
        "repair_below_bars": max(1, below),
        "history_period": period,
        "backfill_per_run": _cfg_int(raw, "backfill_per_run", 40, 0, 2500),
        # Catch-up only (stock_desk.py --backfill). Regular runs keep backfill_per_run.
        "fast_backfill_per_run": _cfg_int(raw, "fast_backfill_per_run", 600, 0, 2500),
        "fast_backfill_max_runs": _cfg_int(raw, "fast_backfill_max_runs", 4, 1, 8),
    }


def _cfg_int(raw, key, default, lo, hi):
    try:
        n = int(raw.get(key, default))
    except (TypeError, ValueError):
        n = default
    return min(hi, max(lo, n))


def incremental_prices_on(cfg):
    return bool((cfg.get("features") or {}).get("incremental_prices", True))


def fast_history_backfill_on(cfg):
    """Catch-up switch. On, the manual backfill workflow uses the higher cap."""
    return bool((cfg.get("features") or {}).get("fast_history_backfill", True))


def price_settings_for(cfg, mode):
    """Regular runs stay on backfill_per_run. The catch-up workflow uses the fast cap.

    chart_concurrency is the same either way (two chart calls at a time).
    """
    settings = incremental_price_settings(cfg)
    if mode == "backfill" and fast_history_backfill_on(cfg) and incremental_prices_on(cfg):
        settings["backfill_per_run"] = settings["fast_backfill_per_run"]
    return settings


def backfill_symbols(plan):
    """Names this catch-up chunk should download, and names still left for a later chunk.

    Only a brand-new symbol (no saved bars). An incremental update, a repair, and
    the weekly refresh are the regular run's job, not this one-time history fill.
    """
    new, waiting = [], []
    for symbol, item in (plan or {}).items():
        if item.get("kind") == "full" and item.get("reason") == "new":
            new.append(symbol)
        elif item.get("reason") == "waiting":
            waiting.append(symbol)
    return sorted(new), sorted(waiting)


def backfill_should_chain(status, run_index, max_runs):
    """True when another bounded chunk should start.

    A clean chunk chains only when it saved histories and names are still waiting.
    A transient failure may chain until max_runs, including a chunk that saved
    nothing, so a short outage can resume. Auth and an unavailable-only chunk
    do not chain. run_index is 0 for the run started by hand.
    """
    if not status or not int(status.get("enabled") or 0):
        return False
    try:
        waiting = int(status.get("waiting") or 0)
        fetched = int(status.get("fetched") or 0)
        index = int(run_index or 0)
        limit = int(max_runs)
        outcome = int(status.get("outcome") or 0)
    except (TypeError, ValueError):
        return False
    if limit < 1 or index + 1 >= limit:
        return False
    if outcome == 2 or outcome == 3:
        return False
    if outcome == 1:
        return True
    if waiting <= 0 or fetched <= 0:
        return False
    return True


def emit_backfill_status(status):
    """One machine line the workflow reads. Values are integers."""
    keys = ("enabled", "fetched", "waiting", "cap", "concurrency", "universe", "outcome", "unavailable", "incomplete", "transient")
    parts = ["%s=%d" % (key, int(status.get(key) or 0)) for key in keys]
    print("BACKFILL " + " ".join(parts), flush=True)


def backfill_status_from_log(text):
    """Parse the last BACKFILL line. Missing keys stay absent."""
    line = ""
    for raw in (text or "").splitlines():
        if raw.startswith("BACKFILL "):
            line = raw.strip()
    status = {}
    for key, value in re.findall(r"([a-z]+)=(-?\d+)", line):
        status[key] = int(value)
    return status


def write_backfill_followup(log_path, run_index, output_path=None):
    """Decide whether the catch-up workflow should start another chunk.

    This is the process that runs after stock_desk.py --backfill. It only
    reads the log and config.json. It does not download prices and it does
    not rewrite the price cache.
    """
    with open(log_path, encoding="utf-8") as handle:
        status = backfill_status_from_log(handle.read())
    if "enabled" not in status:
        raise SystemExit("no BACKFILL line")
    settings = incremental_price_settings(load_cfg())
    chain = backfill_should_chain(status, run_index, settings["fast_backfill_max_runs"])
    outcome = int(status.get("outcome") or 0)
    degraded = outcome in (1, 2)
    cooldown = 60 if outcome == 1 and int(status.get("fetched") or 0) == 0 else 0
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write("chain=%s\n" % ("true" if chain else "false"))
            handle.write("degraded=%s\n" % ("true" if degraded else "false"))
            handle.write("cooldown=%s\n" % cooldown)
            handle.write("waiting=%s\n" % status.get("waiting", 0))
            handle.write("fetched=%s\n" % status.get("fetched", 0))
    return chain, status


def _price_frame(df):
    """One row per date and ticker, dates as YYYY-MM-DD. Drops a row with no close."""
    cols = PRICE_COLS
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=cols)
    out = df.copy()
    if "date" not in out.columns or "ticker" not in out.columns:
        return pd.DataFrame(columns=cols)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"])
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out["ticker"] = out["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False)
    # ^VIX is uppercased to ^VIX. A class share stored as BF.B becomes BF-B, matching the universe.
    for col in ("close", "high", "low", "volume", "open"):
        if col not in out.columns:
            out[col] = np.nan
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["close"])
    out = out.drop_duplicates(["date", "ticker"], keep="last")
    return out[cols]


def close_mismatch(old, new, pct, dollars):
    """True when the close moved by more than the wider of a cent band and a percent band."""
    try:
        old_n = float(old)
        new_n = float(new)
    except (TypeError, ValueError):
        return False
    if old_n != old_n or new_n != new_n:
        return False
    band = max(float(dollars), abs(old_n) * float(pct) / 100.0)
    return abs(new_n - old_n) > band


def weekly_refresh_due(stamp, today, every_days):
    """True when a recorded full refresh is at least every_days old.

    A missing stamp is not due. The file on disk is already a full history, and
    the caller records today so the clock starts without a second full download.
    """
    if not stamp or not today:
        return False
    try:
        age = (pd.Timestamp(str(today)[:10]) - pd.Timestamp(str(stamp)[:10])).days
    except (TypeError, ValueError):
        return False
    return age >= int(every_days)


def refresh_slice_index(today, slices):
    """Which slice a calendar day refreshes. The same day always picks the same slice."""
    n = max(1, int(slices))
    return int(pd.Timestamp(str(today)[:10]).dayofyear) % n


def ticker_in_slice(ticker, slices, index):
    n = max(1, int(slices))
    return sum(ord(c) for c in str(ticker)) % n == int(index) % n


def _cached_price_stats(cached):
    frame = _price_frame(cached)
    if len(frame) == 0:
        return {}, {}
    grouped = frame.groupby("ticker")["date"]
    return grouped.size().to_dict(), grouped.max().to_dict()


def _repair_already_done(repairs, ticker, bars):
    """A one-time full fetch already ran and the cache still has at least that many bars."""
    row = (repairs or {}).get(ticker) or (repairs or {}).get(str(ticker))
    if not isinstance(row, dict):
        return False
    try:
        recorded = int(row.get("bars", 0))
    except (TypeError, ValueError):
        return False
    return bars >= recorded


def load_price_gaps(cache):
    path = os.path.join(cache, "price_gaps.json")
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_price_gaps(cache, gaps):
    path = os.path.join(cache, "price_gaps.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(gaps or {}, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)


def gap_is_open(row, today):
    """True while a recorded gap should not be requested again."""
    if not row:
        return False
    return str(row.get("recheck_after") or "") > str(today)[:10]


def remember_price_gap(gaps, symbol, kind, detail, today, days):
    """Record why a symbol has no usable history, and when it may be tried again."""
    prior = (gaps or {}).get(symbol) or {}
    try:
        attempts = int(prior.get("attempts") or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    day = pd.Timestamp(str(today)[:10])
    gaps[symbol] = {
        "kind": kind,
        "reason": detail[:180],
        "checked": str(day.date()),
        "recheck_after": str((day + pd.Timedelta(days=int(days))).date()),
        "attempts": attempts,
    }
    return gaps


def classify_price_fetches(tickers, cached, settings, enabled, refresh_all=False, slice_index=None, repairs=None, gaps=None, today=None):
    """How to fetch each symbol. No clock and no network.

    enabled False: every symbol is a full download (the old run).
    Otherwise a symbol is full when it has no saved bars, its history is a short
    stub that has not already been repaired, the weekly refresh is due, or it
    falls in today's slice. Everyone else is incremental, starting overlap_days
    before the last saved bar.
    """
    settings = settings or {}
    counts, last = _cached_price_stats(cached)
    today_s = str(today or today_et())[:10]
    plan = {}
    for ticker in tickers:
        symbol = str(ticker).upper().replace(".", "-")
        if not enabled:
            plan[symbol] = {"kind": "full", "start": None, "reason": "switched_off"}
            continue
        bars = int(counts.get(symbol, 0))
        gap = (gaps or {}).get(symbol) or {}
        if bars <= 0 and gap_is_open(gap, today_s) and gap.get("kind") == "unavailable":
            plan[symbol] = {"kind": "skip", "start": None, "reason": "unavailable"}
            continue
        if bars <= 0:
            plan[symbol] = {"kind": "full", "start": None, "reason": "new"}
            continue
        short = settings.get("repair") and bars < int(settings.get("repair_below_bars", 126))
        if short and not _repair_already_done(repairs, symbol, bars):
            plan[symbol] = {"kind": "full", "start": None, "reason": "repair"}
            continue
        if refresh_all:
            plan[symbol] = {"kind": "full", "start": None, "reason": "refresh"}
            continue
        if slice_index is not None and settings.get("refresh") and settings.get("refresh_mode") == "slice":
            if ticker_in_slice(symbol, settings.get("refresh_slices", 8), slice_index):
                plan[symbol] = {"kind": "full", "start": None, "reason": "refresh"}
                continue
        last_day = pd.Timestamp(last[symbol])
        start = (last_day - pd.Timedelta(days=int(settings.get("overlap_days", 5)))).strftime("%Y-%m-%d")
        plan[symbol] = {"kind": "incremental", "start": start, "reason": "update"}
    # A brand-new name needs five years once. Regular runs pass a small cap so one
    # morning does not download a thousand full histories. The catch-up workflow
    # passes a higher cap and chains until the waiting list is empty.
    cap = settings.get("backfill_per_run", 40)
    if enabled and cap is not None:
        waiting = sorted(s for s, item in plan.items() if item["reason"] == "new")
        for symbol in waiting[int(cap):]:
            plan[symbol] = {"kind": "skip", "start": None, "reason": "waiting"}
    return plan


def overlap_mismatches(cached, fresh, settings):
    """Symbols whose completed overlap closes moved enough to suggest a split or adjustment.

    The newest downloaded bar is left out. During the session that bar is still
    forming, so a different close there is the hourly update, not a split.
    """
    old = _price_frame(cached)
    new = _price_frame(fresh)
    if len(old) == 0 or len(new) == 0:
        return []
    newest = new.groupby("ticker")["date"].max()
    both = old.merge(new, on=["date", "ticker"], suffixes=("_old", "_new"))
    if len(both) == 0:
        return []
    both = both[both["date"] < both["ticker"].map(newest)]
    if len(both) == 0:
        return []
    pct = settings.get("adjust_tolerance_pct", 0.05)
    dollars = settings.get("adjust_tolerance_dollars", 0.02)
    bad = pd.Series(
        [close_mismatch(a, b, pct, dollars) for a, b in zip(both["close_old"], both["close_new"])],
        index=both.index,
    )
    return sorted(set(both.loc[bad, "ticker"].astype(str)))


def merge_price_rows(cached, fresh, settings, hold_back=None):
    """Keep every saved bar. Replace a date the download also returned, and append new dates.

    Symbols in hold_back are left untouched, so a mismatched overlap is not mixed
    into the old adjustment basis while a full refetch is still to come.
    Returns (merged, mismatch_symbols).
    """
    old = _price_frame(cached)
    new = _price_frame(fresh)
    mismatches = overlap_mismatches(old, new, settings) if hold_back is None else []
    skip = set(hold_back or []) | set(mismatches)
    if skip and len(new):
        new = new[~new["ticker"].isin(skip)]
    if len(old) == 0:
        return new.reset_index(drop=True), mismatches
    if len(new) == 0:
        return old.reset_index(drop=True), mismatches
    keys = new[["date", "ticker"]].drop_duplicates()
    keys["_hit"] = 1
    marked = old.merge(keys, on=["date", "ticker"], how="left")
    kept = marked[marked["_hit"].isna()].drop(columns="_hit")
    out = pd.concat([kept[PRICE_COLS], new[PRICE_COLS]], ignore_index=True)
    out = out.drop_duplicates(["date", "ticker"], keep="last")
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    return out, mismatches


def combine_downloaded_prices(cached, fresh, merge, settings):
    """Switch off replaces the file with the download. Switch on merges and never shrinks."""
    if not merge:
        return _price_frame(fresh), []
    merged, mismatches = merge_price_rows(cached, fresh, settings)
    return merged, mismatches


def load_price_repairs(cache):
    path = os.path.join(cache, "price_repairs.json")
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_price_repairs(cache, repairs):
    with open(os.path.join(cache, "price_repairs.json"), "w") as f:
        json.dump(repairs, f, indent=1, sort_keys=True)


def note_price_repairs(repairs, merged, fresh, tickers, min_bars):
    """Remember a full fetch so a still-short history (a new listing) is not fetched again every hour.

    A one-bar answer is not remembered. That is the truncated file we are trying
    to repair, and the next run should ask for the full history again.
    """
    got = _price_frame(fresh)
    if len(got) == 0 or merged is None or len(merged) == 0:
        return repairs
    counts = merged.groupby(merged["ticker"].astype(str)).size()
    out = dict(repairs or {})
    for ticker in tickers:
        symbol = str(ticker)
        sub = got[got["ticker"] == symbol]
        if len(sub) < 2 or symbol not in counts.index:
            continue
        span_days = (pd.Timestamp(sub["date"].max()) - pd.Timestamp(sub["date"].min())).days
        if len(sub) < int(min_bars) and span_days < 10:
            continue
        out[symbol] = {"bars": int(counts[symbol])}
    return out


def failure_kind(exc):
    """Split a download error into unavailable, auth, or transient.

    Unavailable is only a positive no-bars answer. Rate limits, timeouts, and
    auth problems stay transient or auth so they are not stored as missing data.
    """
    if isinstance(exc, netutil.PermanentError):
        return "unavailable"
    msg = str(exc).lower()
    if any(s in msg for s in ("429", "rate limit", "too many requests", "timeout", "timed out", "connection reset", "connection aborted", "temporarily")):
        return "transient"
    if any(s in msg for s in ("401", "403", "unauthorized", "forbidden", "invalid crumb", "permission")):
        return "auth"
    if netutil.is_permanent_message(exc):
        return "unavailable"
    return "transient"


def _whole_chunk_failure(kind, exc):
    """True when retrying each symbol would just repeat the same block."""
    if kind == "auth":
        return True
    msg = str(exc).lower()
    return kind == "transient" and any(s in msg for s in ("429", "rate limit", "too many requests", "timeout", "timed out"))


def download_prices(tickers, cfg, start=None, threads=True, period=None, outcomes=None):
    import yfinance as yf
    batch = int(rl(cfg)["yahoo_batch_size"])
    pause = float(rl(cfg)["yahoo_batch_pause_seconds"])
    parts = []

    def pull(chunk):
        def once():
            # period="5y" is the full history. A start date asks only for the overlap and the new days.
            common = dict(interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=threads)
            if start:
                df = yf.download(chunk, start=start, **common)
            elif period and period != "5y":
                df = yf.download(chunk, period=period, **common)
            else:
                df = yf.download(chunk, period="5y", **common)
            got = frames_from_download(df)
            if got is None or got[0] is None or got[0].dropna(how="all").empty:
                if len(chunk) == 1:
                    raise netutil.PermanentError("no daily bars returned")
                raise netutil.RetryableError("empty price batch (%d names)" % len(chunk))
            return got
        try:
            return netutil.call_with_retry(once, max_tries=rl(cfg)["max_retries"], delays=tuple(rl(cfg)["backoff_seconds"]))
        except Exception as exc:
            kind = failure_kind(exc)
            if outcomes is not None and (len(chunk) == 1 or _whole_chunk_failure(kind, exc)):
                targets = list(chunk) if len(chunk) > 1 else [chunk[0]]
                recorded = "unavailable" if kind == "unavailable" else kind
                for symbol in targets:
                    outcomes.append({"symbol": str(symbol), "kind": recorded, "detail": str(exc)[:180]})
                return None
            if len(chunk) == 1:
                return None
            mid = len(chunk) // 2
            return ("split", chunk[:mid], chunk[mid:])

    queue = [list(tickers)[i:i + batch] for i in range(0, len(tickers), batch)]
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
        frames = [p[i] for p in parts if len(p) > i and p[i] is not None]
        if not frames:
            return None
        out = pd.concat(frames, axis=1)
        out = out.loc[:, ~out.columns.duplicated()]
        return out.sort_index()
    return cat(0), cat(1), cat(2), cat(3), cat(4)


def ohlcv_long(close, high, low, vol, opn=None):
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
    if opn is not None:
        m = m.merge(melt(opn, "open"), on=["date", "ticker"], how="left")
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


def _download_long(tickers, cfg, start, threads, period, outcomes=None):
    if not tickers:
        return pd.DataFrame(columns=PRICE_COLS)
    frames = download_prices(tickers, cfg, start=start, threads=threads, period=period, outcomes=outcomes)
    return _price_frame(ohlcv_long(*frames))


def _save_prices(path, frame):
    """Replace the price cache in one step so a crash cannot leave a half-written file."""
    out = _price_frame(frame)
    tmp = path + ".tmp"
    out.to_csv(tmp, index=False, compression="gzip")
    os.replace(tmp, path)
    return out


def load_prices(tickers, cfg, cache, mode):
    path = os.path.join(cache, "ohlcv.csv.gz")
    cached = read_csv(path) if os.path.exists(path) else pd.DataFrame()
    if mode == "offline":
        if len(cached):
            log("Prices (Yahoo Finance)", "OK", cached["date"].max() if "date" in cached else "", "offline mode, used cache")
            return cached
        log("Prices (Yahoo Finance)", "MISSING", "", "offline and no price cache")
        return pd.DataFrame()
    settings = price_settings_for(cfg, mode)
    use_merge = incremental_prices_on(cfg) and len(cached) > 0
    if not use_merge:
        try:
            # Switch off is the old download: five years, yfinance's own parallel threads, and the file is replaced.
            # Switch on with an empty cache still uses the configured length and the slower chart concurrency.
            if incremental_prices_on(cfg):
                full_period, full_threads = settings["history_period"], settings["chart_concurrency"]
            else:
                full_period, full_threads = None, True
            long = _download_long(tickers, cfg, None, full_threads, full_period)
            long = _save_prices(path, long)
            last = str(pd.to_datetime(long["date"]).max().date()) if len(long) else ""
            note = "%d rows, batched" % len(long)
            if not incremental_prices_on(cfg):
                note += ", incremental prices off"
            log("Prices (Yahoo Finance)", "OK", last, note)
            return long
        except Exception as exc:
            if len(cached):
                log("Prices (Yahoo Finance)", "CACHED", cached["date"].max(), str(exc)[:160])
                return cached
            log("Prices (Yahoo Finance)", "MISSING", "", str(exc)[:160])
            return pd.DataFrame()
    try:
        today = today_et()
        repairs = load_price_repairs(cache)
        refresh_all = False
        slice_index = None
        if settings["refresh"] and mode == "full":
            if settings["refresh_mode"] == "slice":
                slice_index = refresh_slice_index(today, settings["refresh_slices"])
            elif weekly_refresh_due(STAMPS.get("prices_full_refresh"), today, settings["refresh_every_days"]):
                refresh_all = True
            elif not STAMPS.get("prices_full_refresh"):
                # The cache is already a full history. Start the weekly clock without downloading it again.
                STAMPS["prices_full_refresh"] = today
        plan = classify_price_fetches(
            tickers, cached, settings, True,
            refresh_all=refresh_all, slice_index=slice_index, repairs=repairs,
        )
        groups = {}
        for symbol, item in plan.items():
            groups.setdefault((item["kind"], item["start"]), []).append(symbol)
        fresh_parts = []
        failed_groups = 0
        threads = settings["chart_concurrency"]
        for (kind, start), group in sorted(groups.items(), key=lambda kv: (kv[0][0] != "full", kv[0][1] or "")):
            if kind == "skip":
                continue
            try:
                part = _download_long(group, cfg, start, threads, settings["history_period"])
                if len(part):
                    fresh_parts.append(part)
            except Exception as exc:
                failed_groups += 1
                print("price group failed", kind, start or "full", len(group), str(exc)[:140])
        if not fresh_parts:
            raise RuntimeError("no prices downloaded")
        fresh = _price_frame(pd.concat(fresh_parts, ignore_index=True))
        # A full download is already the adjusted series, so it is merged even when the
        # closes differ. Only a short incremental overlap can ask for that full download.
        full_set = {s for s, item in plan.items() if item["kind"] == "full"}
        incremental_fresh = fresh[~fresh["ticker"].isin(full_set)] if len(fresh) else fresh
        full_fresh = fresh[fresh["ticker"].isin(full_set)] if len(fresh) else fresh
        merged, mismatches = merge_price_rows(cached, incremental_fresh, settings)
        if len(full_fresh):
            merged, _ignored = merge_price_rows(merged, full_fresh, settings, hold_back=[])
        refetched = pd.DataFrame(columns=PRICE_COLS)
        refetch_failed = False
        if mismatches:
            try:
                refetched = _download_long(mismatches, cfg, None, threads, settings["history_period"])
                if len(refetched):
                    merged, _ignored = merge_price_rows(merged, refetched, settings, hold_back=[])
            except Exception as exc:
                refetch_failed = True
                print("adjustment refetch failed", str(exc)[:140])
        full_symbols = [s for s, item in plan.items() if item["kind"] == "full"] + list(mismatches)
        got = [p for p in fresh_parts if len(p)]
        if len(refetched):
            got.append(refetched)
        repairs = note_price_repairs(
            repairs, merged, pd.concat(got, ignore_index=True), full_symbols, settings["repair_below_bars"])
        merged = _save_prices(path, merged)
        save_price_repairs(cache, repairs)
        if refresh_all and failed_groups == 0:
            STAMPS["prices_full_refresh"] = today
        last = str(pd.to_datetime(merged["date"]).max().date()) if len(merged) else ""
        reasons = {}
        for item in plan.values():
            reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
        note = "incremental %d, full %d (new %d, repair %d, refresh %d), waiting for backfill %d, adjustment refetch %d, %d rows, %d at a time" % (
            reasons.get("update", 0),
            reasons.get("new", 0) + reasons.get("repair", 0) + reasons.get("refresh", 0),
            reasons.get("new", 0), reasons.get("repair", 0), reasons.get("refresh", 0),
            reasons.get("waiting", 0), len(mismatches), len(merged), threads,
        )
        if failed_groups:
            note += ", %d groups failed and kept prior bars" % failed_groups
        if refetch_failed:
            note += ", adjustment refetch failed and kept prior bars"
        if refresh_all:
            note = "weekly full refresh. " + note
        log("Prices (Yahoo Finance)", "OK", last, note)
        return merged
    except Exception as exc:
        if len(cached):
            log("Prices (Yahoo Finance)", "CACHED", cached["date"].max(), str(exc)[:160])
            return cached
        log("Prices (Yahoo Finance)", "MISSING", "", str(exc)[:160])
        return pd.DataFrame()


# ---------------------------------------------------------------- universe
# One row per stock. A name in more than one list keeps every flag, so Looker can filter.
FLAGS = ("in_sp500", "in_sp400", "in_sp600", "in_ndx100", "in_growth", "in_liquid")
INDEX_SOURCES = {
    "sp500": {
        "flag": "in_sp500",
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "cache": "sp500.csv",
        "legacy": "universe.csv",
        "log": "Universe (Wikipedia S&P 500)",
        "stamp": "universe_sp500",
    },
    "sp400": {
        "flag": "in_sp400",
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "cache": "sp400.csv",
        "legacy": None,
        "log": "Universe (Wikipedia S&P 400)",
        "stamp": "universe_sp400",
    },
    "sp600": {
        "flag": "in_sp600",
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        "cache": "sp600.csv",
        "legacy": None,
        "log": "Universe (Wikipedia S&P 600)",
        "stamp": "universe_sp600",
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
# Eleven GICS sectors. Wikipedia ICB names and Yahoo profile names both land here.
# Industry is a separate column and is not renamed.
ICB_TO_GICS = {
    "Technology": "Information Technology",
    "Information Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Communication Services": "Communication Services",
    "Health Care": "Health Care",
    "Healthcare": "Health Care",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Consumer Defensive": "Consumer Staples",
    "Industrials": "Industrials",
    "Utilities": "Utilities",
    "Financials": "Financials",
    "Financial Services": "Financials",
    "Real Estate": "Real Estate",
    "Energy": "Energy",
    "Basic Materials": "Materials",
    "Materials": "Materials",
}
GICS_SECTORS = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)


def gics_sector(name):
    """Map an ICB or Yahoo sector onto one GICS name. Blank stays blank."""
    if name is None:
        return ""
    try:
        if pd.isna(name):
            return ""
    except (ValueError, TypeError):
        pass
    text = str(name).strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    return ICB_TO_GICS.get(text, text)


def index_switches(cfg):
    raw = cfg.get("indexes") or {}
    return {
        "sp500": bool(raw.get("sp500", True)),
        "sp400": bool(raw.get("sp400", True)),
        "sp600": bool(raw.get("sp600", True)),
        "ndx100": bool(raw.get("ndx100", True)),
        "growth": bool(raw.get("growth", True)),
        "liquid": bool(raw.get("liquid", True)),
    }


def membership_label(in_sp500, in_ndx100, in_growth, in_sp400="no", in_sp600="no", in_liquid="no"):
    """Stable tag: SP500 / SP400 / SP600 / NDX100 / Growth / Liquid. A holding outside those lists is Focus."""
    parts = []
    if in_sp500 == "yes":
        parts.append("SP500")
    if in_sp400 == "yes":
        parts.append("SP400")
    if in_sp600 == "yes":
        parts.append("SP600")
    if in_ndx100 == "yes":
        parts.append("NDX100")
    if in_growth == "yes":
        parts.append("Growth")
    if in_liquid == "yes":
        parts.append("Liquid")
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
    switch_on = switches.get(key, True)
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
    agg = {
        "company": lambda s: next((x for x in s if isinstance(x, str) and str(x).strip() and str(x).lower() != "nan"), ""),
        "sector": lambda s: next((x for x in s if isinstance(x, str) and str(x).strip() and str(x).lower() != "nan"), ""),
    }
    for flag in FLAGS:
        agg[flag] = (lambda s, _flag=flag: "yes" if (s == "yes").any() else "no")
    df = df.groupby("ticker", as_index=False).agg(agg)
    df["index_membership"] = [
        membership_label(a, b, c, d, e, f)
        for a, b, c, d, e, f in zip(
            df["in_sp500"], df["in_ndx100"], df["in_growth"], df["in_sp400"], df["in_sp600"], df["in_liquid"])
    ]

    def keep(row):
        if row["ticker"] in always:
            return True
        if switches.get("sp500", True) and row["in_sp500"] == "yes":
            return True
        if switches.get("sp400", True) and row["in_sp400"] == "yes":
            return True
        if switches.get("sp600", True) and row["in_sp600"] == "yes":
            return True
        if switches.get("ndx100", True) and row["in_ndx100"] == "yes":
            return True
        if switches.get("growth", True) and row["in_growth"] == "yes":
            return True
        if switches.get("liquid", True) and row["in_liquid"] == "yes":
            return True
        return False

    return df[df.apply(keep, axis=1)].reset_index(drop=True)


_LISTED_BAD = (
    "PREFERRED", "WARRANT", "DEPOSITARY", "NOTES", "RIGHT", "UNIT ", "BOND", "DEBENTURE",
    "CLOSED-END", "CLOSED END", "MUTUAL FUND", "EXCHANGE-TRADED", "EXCHANGE TRADED",
)


def _norm_symbol(symbol):
    return str(symbol or "").upper().replace(".", "-").replace("$", "-").replace("/", "-").strip()


def _listed_name_blocked(name):
    """True for ETFs, funds, warrants, preferreds, and similar non-common names."""
    text = (name or "").upper()
    if any(word in text for word in _LISTED_BAD):
        return True
    # "FUND" as a word, not a name like FUNDAMENTAL.
    if text.endswith(" FUND") or text.endswith(" FUNDS") or text.endswith("-FUND") or " FUND " in text:
        return True
    return False


def parse_listed_common(nasdaq_text, other_text):
    """Common stocks from the Nasdaq Trader symbol files. ETFs, tests, and preferreds stay out."""
    good = set()

    def take(text, sym_i, name_i, etf_i, test_i):
        for line in (text or "").splitlines()[1:]:
            if line.startswith("File Creation"):
                continue
            parts = line.split("|")
            if len(parts) <= max(sym_i, name_i, etf_i, test_i):
                continue
            if parts[etf_i].strip().upper() == "Y" or parts[test_i].strip().upper() == "Y":
                continue
            name = parts[name_i].upper()
            if _listed_name_blocked(name):
                continue
            symbol = _norm_symbol(parts[sym_i])
            if symbol:
                good.add(symbol)

    take(nasdaq_text, 0, 1, 6, 3)
    take(other_text, 0, 1, 4, 6)
    return good


def _market_cap_number(value):
    text = str(value or "").replace(",", "").replace("$", "").strip()
    if not text or text.upper() in ("N/A", "NA", "NONE"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _price_number(value):
    text = str(value or "").replace(",", "").replace("$", "").strip()
    if not text or text.upper() in ("N/A", "NA", "NONE"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _volume_number(value):
    text = str(value or "").replace(",", "").strip()
    if not text or text.upper() in ("N/A", "NA", "NONE"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def select_liquid_names(rows, listed, already, min_market_cap, room, min_price=0, min_volume=0):
    """Screener rows that clear the cap, price, and volume floors and are listed common stock."""
    if room <= 0:
        return []
    listed = set(listed or [])
    already = {_norm_symbol(t) for t in (already or [])}
    picked = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        cap = _market_cap_number(row.get("marketCap"))
        if cap is None or cap < float(min_market_cap):
            continue
        if float(min_price or 0) > 0:
            price = _price_number(row.get("lastsale") or row.get("price") or row.get("lastSale"))
            if price is None or price <= float(min_price):
                continue
        if float(min_volume or 0) > 0:
            volume = _volume_number(row.get("volume"))
            if volume is None or volume <= float(min_volume):
                continue
        symbol = _norm_symbol(row.get("symbol"))
        if not symbol or symbol in already or symbol not in listed:
            continue
        if _listed_name_blocked(row.get("name") or ""):
            continue
        picked.append((cap, symbol))
    picked.sort(key=lambda item: (-item[0], item[1]))
    return [symbol for _cap, symbol in picked[:int(room)]]


def liquid_settings(cfg):
    raw = cfg.get("liquid_names") or {}
    try:
        floor = float(raw.get("min_market_cap", 300000000))
    except (TypeError, ValueError):
        floor = 300000000.0
    try:
        cap = int(raw.get("max_stocks", 2500))
    except (TypeError, ValueError):
        cap = 2500
    try:
        min_price = float(raw.get("min_price", 5))
    except (TypeError, ValueError):
        min_price = 5.0
    try:
        min_volume = float(raw.get("min_volume", 100000))
    except (TypeError, ValueError):
        min_volume = 100000.0
    return {
        "on": bool((cfg.get("features") or {}).get("liquid_names", True)) and bool((cfg.get("indexes") or {}).get("liquid", True)),
        "min_market_cap": floor,
        "max_stocks": max(1, cap),
        "min_price": max(0.0, min_price),
        "min_volume": max(0.0, min_volume),
    }


def _read_text(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return ""
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def load_listed_common(cfg, cache, mode):
    """Nasdaq Trader symbol files. Hourly and offline reuse the saved copy."""
    nas_p = os.path.join(cache, "nasdaqlisted.txt")
    oth_p = os.path.join(cache, "otherlisted.txt")
    nas, oth = _read_text(nas_p), _read_text(oth_p)
    fresh = mode == "full" and (STAMPS.get("listed_common") != today_et() or not nas or not oth or "--force-slow" in sys.argv)
    if fresh:
        try:
            headers = session_headers(cfg)
            nas_r = netutil.http_get(requests, "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", headers, 40, max_tries=rl(cfg)["max_retries"])
            oth_r = netutil.http_get(requests, "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", headers, 40, max_tries=rl(cfg)["max_retries"])
            nas, oth = nas_r.text, oth_r.text
            open(nas_p, "w", encoding="utf-8").write(nas)
            open(oth_p, "w", encoding="utf-8").write(oth)
            STAMPS["listed_common"] = today_et()
            log("Listed symbols (Nasdaq Trader)", "OK", today_et(), "nasdaq and other exchanges")
        except Exception as exc:
            log("Listed symbols (Nasdaq Trader)", "CACHED" if nas or oth else "MISSING", "", str(exc)[:160])
    elif nas or oth:
        log("Listed symbols (Nasdaq Trader)", "OK", STAMPS.get("listed_common", ""), "reused cache")
    else:
        log("Listed symbols (Nasdaq Trader)", "MISSING", "", "no cache and this run does not download the symbol files")
    return parse_listed_common(nas, oth)


def load_liquid(cfg, cache, mode, already, listed):
    """Large common stocks that are not already on an index. One screener pass a day, no Yahoo."""
    settings = liquid_settings(cfg)
    path = os.path.join(cache, "liquid_screener.json")
    rows = None
    if os.path.exists(path):
        try:
            rows = json.load(open(path))
        except Exception:
            rows = None
    if not settings["on"]:
        log("Liquid names (Nasdaq screener)", "OK", "", "switch is off")
        return pd.DataFrame()
    def _screener_has_filters(saved):
        if not saved or not isinstance(saved, list) or not isinstance(saved[0], dict):
            return False
        return "volume" in saved[0] or "lastsale" in saved[0]

    allow = mode == "full" and (STAMPS.get("liquid_names") != today_et() or not rows or not _screener_has_filters(rows) or "--force-slow" in sys.argv)
    if allow:
        try:
            lim = netutil.RateLimiter(rl(cfg)["nasdaq_requests_per_second"])
            headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
            # One official screener download includes last sale and volume for every name.
            url = "https://api.nasdaq.com/api/screener/stocks?download=true"
            r = netutil.http_get(requests, url, headers, 60, limiter=lim, max_tries=rl(cfg)["max_retries"])
            payload = r.json()
            got = ((payload.get("data") or payload).get("rows")) or []
            rows = [{
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "marketCap": row.get("marketCap"),
                "lastsale": row.get("lastsale") or row.get("lastSale"),
                "volume": row.get("volume"),
            } for row in got if isinstance(row, dict)]
            json.dump(rows, open(path, "w"))
            STAMPS["liquid_names"] = today_et()
            log("Liquid names (Nasdaq screener)", "OK", today_et(), "%d rows" % len(rows))
        except Exception as exc:
            log("Liquid names (Nasdaq screener)", "CACHED" if rows else "MISSING", "", str(exc)[:160])
    elif rows:
        log("Liquid names (Nasdaq screener)", "OK", STAMPS.get("liquid_names", ""), "reused cache")
    else:
        log("Liquid names (Nasdaq screener)", "MISSING", "", "no cache and this run does not call the screener")
        return pd.DataFrame()
    room = settings["max_stocks"] - len(set(already or []))
    picked = select_liquid_names(
        rows, listed, already, settings["min_market_cap"], room,
        min_price=settings.get("min_price", 0), min_volume=settings.get("min_volume", 0),
    )
    if not picked:
        return pd.DataFrame()
    return _blank_flags(pd.DataFrame([{"ticker": t, "company": "", "sector": ""} for t in picked]), "in_liquid")


def core_tickers(universe, holdings, watch):
    """Names that keep a daily Yahoo profile and a daily SEC refresh. The wider list does not."""
    ordered = [str(t).upper() for t in list(holdings or []) + list(watch or [])]
    always = set(ordered)
    out = []
    if universe is not None and len(universe):
        for _, row in universe.iterrows():
            ticker = str(row.get("ticker") or "")
            if ticker in always or row.get("in_sp500") == "yes" or row.get("in_ndx100") == "yes" or row.get("in_growth") == "yes":
                out.append(ticker)
    for ticker in ordered:
        if ticker not in out:
            out.append(ticker)
    return list(dict.fromkeys(out))


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
    return resolve_cik(out, (cfg.get("sec_facts") or {}).get("cik_overrides"))


def resolve_cik(ticker_to_cik, overrides):
    """Company-tickers map, then config overrides. Overrides fix a ticker that points at the wrong filer."""
    out = dict(ticker_to_cik or {})
    for ticker, cik in (overrides or {}).items():
        symbol = str(ticker).upper().replace(".", "-").strip()
        text = str(cik or "").strip()
        if symbol and text:
            out[symbol] = text.zfill(10)
    return out


def sec_rolling_settings(cfg):
    raw = cfg.get("sec_facts") or {}
    try:
        batch = int(raw.get("batch_per_run", 120))
    except (TypeError, ValueError):
        batch = 120
    try:
        every = int(raw.get("refresh_every_days", 7))
    except (TypeError, ValueError):
        every = 7
    return {
        "on": bool((cfg.get("features") or {}).get("sec_rolling", True)),
        "batch_per_run": max(1, batch),
        "refresh_every_days": max(1, every),
        "full_universe": bool(raw.get("full_universe", True)),
        "use_bulk_zip": bool(raw.get("use_bulk_zip", True)),
    }


def load_sec_cycle(cache):
    path = os.path.join(cache, "sec_cycle.json")
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_sec_cycle(cache, cycle):
    with open(os.path.join(cache, "sec_cycle.json"), "w") as f:
        json.dump(cycle, f, indent=1, sort_keys=True)


def rolling_sec_pool(tickers, core, cycle, today, batch, every_days, already_today):
    """Core names every full run. Everyone else, oldest first, at most `batch` a run."""
    core = set(core or [])
    already = set(already_today or [])
    must = [t for t in tickers if t in core and t not in already]
    rest = [t for t in tickers if t not in core and t not in already]

    def age(ticker):
        stamp = cycle.get(ticker)
        if not stamp:
            return 10 ** 9
        try:
            return (pd.Timestamp(str(today)[:10]) - pd.Timestamp(str(stamp)[:10])).days
        except (TypeError, ValueError):
            return 10 ** 9

    due = [t for t in rest if age(t) >= int(every_days)]
    due.sort(key=lambda t: (-age(t), t))
    return must + due[:int(batch)]


def slow_source_settings(cfg):
    """How many profiles and 13F rows one full run may refresh.

    Company facts already rotate. Profiles and Nasdaq holdings did not: every
    full run asked for the whole daily list again, two requests a name. At the
    current list size that alone ran past 40 minutes.
    """
    raw = cfg.get("slow_sources") or {}
    try:
        batch = int(raw.get("batch_per_run", 60))
    except (TypeError, ValueError):
        batch = 60
    try:
        every = int(raw.get("refresh_every_days", 7))
    except (TypeError, ValueError):
        every = 7
    return {"batch_per_run": max(1, batch), "refresh_every_days": max(1, every)}


# One-time 13F/insider fill for the whole universe. Off unless the workflow
# input ownership_full is set. The 35-minute budget leaves room for scores
# and the backtest inside the 120-minute job; leftover names chain to the
# next manual-style full run and resume from today's progress file.
OWNERSHIP_FULL_BUDGET_SEC = 2100
OWNERSHIP_FULL_MAX_RUNS = 8
OWNERSHIP_STATUS_FILE = "ownership_full_status.json"


def ownership_full_on(env=None):
    env = os.environ if env is None else env
    val = str((env or {}).get("DESK_OWNERSHIP_FULL") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def ownership_full_run_index(env=None):
    env = os.environ if env is None else env
    try:
        return max(0, int((env or {}).get("DESK_OWNERSHIP_RUN") or 0))
    except (TypeError, ValueError):
        return 0


def ownership_full_budget_sec(env=None):
    env = os.environ if env is None else env
    try:
        return max(30, int((env or {}).get("DESK_OWNERSHIP_BUDGET_SEC") or OWNERSHIP_FULL_BUDGET_SEC))
    except (TypeError, ValueError):
        return OWNERSHIP_FULL_BUDGET_SEC


def ownership_full_max_runs(env=None):
    env = os.environ if env is None else env
    try:
        return max(1, int((env or {}).get("DESK_OWNERSHIP_MAX_RUNS") or OWNERSHIP_FULL_MAX_RUNS))
    except (TypeError, ValueError):
        return OWNERSHIP_FULL_MAX_RUNS


def holders_batch_per_run(settings, n_tickers, mode, env=None):
    """Usual 60-name slice, or every name when ownership_full is on for a full run."""
    if ownership_full_on(env) and mode == "full":
        return max(1, int(n_tickers))
    return int(settings["batch_per_run"])


def ownership_should_chain(waiting, fetched, run_index, max_runs):
    """Continue only when this chunk saved names and more are still waiting."""
    if int(waiting or 0) <= 0 or int(fetched or 0) <= 0:
        return False
    return int(run_index or 0) + 1 < int(max_runs)


def write_ownership_status(cache, status):
    path = os.path.join(cache, OWNERSHIP_STATUS_FILE)
    with open(path, "w") as f:
        json.dump(status or {}, f, indent=1, sort_keys=True)
    return path


def read_ownership_status(cache):
    path = os.path.join(cache, OWNERSHIP_STATUS_FILE)
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def emit_ownership_status_output(cache, dest=None):
    """Tell the workflow whether to start the next ownership_full run."""
    status = read_ownership_status(cache)
    chain = "true" if status.get("chain") else "false"
    dest = dest or os.environ.get("GITHUB_OUTPUT")
    if dest:
        with open(dest, "a") as fh:
            fh.write("ownership_chain=%s\n" % chain)
            fh.write("ownership_waiting=%s\n" % int(status.get("waiting") or 0))
    return chain, status


def load_named_cycle(cache, name):
    path = os.path.join(cache, "%s_cycle.json" % name)
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_named_cycle(cache, name, cycle):
    with open(os.path.join(cache, "%s_cycle.json" % name), "w") as f:
        json.dump(cycle, f, indent=1, sort_keys=True)


def _cycle_age(cycle, ticker, today):
    stamp = (cycle or {}).get(ticker)
    if not stamp:
        return 10 ** 9
    try:
        return (pd.Timestamp(str(today)[:10]) - pd.Timestamp(str(stamp)[:10])).days
    except (TypeError, ValueError):
        return 10 ** 9


def slow_refresh_pool(tickers, have, cycle, today, batch, every_days, already_today):
    """Missing names first, then the stalest saved names, at most `batch`.

    Names fetched today are left out so a restarted run does not repeat them.
    """
    already = set(already_today or [])
    have = set(have or [])
    missing = [t for t in tickers if t not in have and t not in already]
    due = [t for t in tickers if t in have and t not in already and _cycle_age(cycle, t, today) >= int(every_days)]
    due.sort(key=lambda t: (-_cycle_age(cycle, t, today), t))
    return (missing + due)[:max(0, int(batch))]


def merge_ticker_rows(prior, fresh_rows):
    """Keep saved rows for tickers this run did not refresh."""
    if not fresh_rows:
        return prior if prior is not None else pd.DataFrame()
    fresh = pd.DataFrame(fresh_rows)
    if "ticker" not in fresh.columns:
        return fresh
    if prior is None or len(prior) == 0 or "ticker" not in getattr(prior, "columns", []):
        return fresh
    got = set(fresh["ticker"].astype(str))
    keep = prior[~prior["ticker"].astype(str).isin(got)]
    return pd.concat([keep, fresh], ignore_index=True)


def checkpoint_progress(note):
    """Commit the cache so a later timeout does not drop a finished download.

    The desk step used to commit once, after every source. A timeout threw away
    prices that had already been written. Off unless the workflow asks for it.
    """
    if os.environ.get("DESK_CHECKPOINT") != "1":
        return
    folder = root()
    import subprocess
    def run(args):
        return subprocess.run(args, cwd=folder, capture_output=True, text=True)
    if run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        print("checkpoint skipped, not a git checkout")
        return
    run(["git", "config", "user.name", "stock-desk-bot"])
    run(["git", "config", "user.email", "stock-desk-bot@users.noreply.github.com"])
    added = run(["git", "add", "cache"])
    if added.returncode != 0:
        print("checkpoint add failed", (added.stderr or "")[:200])
        return
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    committed = run(["git", "commit", "-m", "Checkpoint desk cache %s" % note])
    if committed.returncode != 0:
        print("checkpoint commit failed", (committed.stderr or "")[:200])
        return
    pushed = run(["git", "push"])
    if pushed.returncode != 0:
        print("checkpoint push failed", (pushed.stderr or "")[:200])
        return
    print("checkpoint saved", note)


def _need_fetch(name, cache_file, mode):
    exists = os.path.exists(cache_file) and os.path.getsize(cache_file) > 0
    return netutil.decide_slow(STAMPS.get(name), today_et(), exists, mode, force="--force-slow" in sys.argv)


def _missing_tickers(df, tickers):
    """Names in today's universe that are not in the saved file yet."""
    if df is None or len(df) == 0 or "ticker" not in getattr(df, "columns", []):
        return list(tickers)
    have = set(df["ticker"].astype(str))
    return [t for t in tickers if t not in have]


def _balance_sheet_blank(annual):
    """True when the cache has filings but equity and debt are both empty.

    The old parser kept only facts tagged CY####. Balance-sheet facts usually
    have no such tag, so those two columns were saved as all blank.
    """
    if annual is None or len(annual) == 0:
        return False
    for col in ("equity", "debt"):
        if col not in annual.columns:
            continue
        if pd.to_numeric(annual[col], errors="coerce").notna().any():
            return False
    return True


def _flow_gap(annual):
    """True when recent years have revenue but the income-statement frame was dropped.

    Facts with no CY#### tag used to be skipped. That left net income blank on
    filings that do report it. One full run refetches so the new parser can keep them.
    """
    if annual is None or len(annual) == 0 or "net_income" not in getattr(annual, "columns", []):
        return False
    end = pd.to_datetime(annual["end"], errors="coerce") if "end" in annual.columns else pd.Series(pd.NaT, index=annual.index)
    recent = annual[end >= pd.Timestamp("2022-01-01")]
    if len(recent) < 100 or "revenue" not in recent.columns:
        return False
    rev = pd.to_numeric(recent["revenue"], errors="coerce")
    ni = pd.to_numeric(recent["net_income"], errors="coerce")
    return int((rev.notna() & ni.isna()).sum()) >= 80



def _bulk_dir(cache):
    path = os.path.join(cache, "bulk")
    os.makedirs(path, exist_ok=True)
    return path


def _download_sec_zip(cfg, cache, url, filename, stamp_key, timeout=300):
    """Download an official SEC zip once a day. Returns the path, or empty on failure."""
    dest = os.path.join(_bulk_dir(cache), filename)
    if os.path.exists(dest) and os.path.getsize(dest) > 0 and STAMPS.get(stamp_key) == today_et():
        return dest
    headers = session_headers(cfg, sec=True)
    lim = netutil.RateLimiter(rl(cfg)["sec_requests_per_second"])
    try:
        print("SEC downloading %s" % filename)
        profiles.http_download(requests, url, dest, headers, timeout=timeout, limiter=lim)
    except Exception as exc:
        print("SEC zip failed %s: %s" % (filename, str(exc)[:160]))
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest
        return ""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        STAMPS[stamp_key] = today_et()
        return dest
    return ""


def apply_companyfacts_zip(tickers, cik, cfg, cache, annual, quarters, annual_p, quarter_p):
    """Fill annual and quarterly statements for the whole universe from companyfacts.zip."""
    wanted = {t: cik[t] for t in tickers if t in cik}
    if not wanted:
        return False, annual, quarters, []
    path = _download_sec_zip(cfg, cache, profiles.COMPANYFACTS_ZIP_URL, "companyfacts.zip", "sec_companyfacts_zip", timeout=600)
    if not path:
        return False, annual, quarters, list(wanted)
    try:
        fresh_a, fresh_q, found, missing = profiles.parse_companyfacts_from_zip(path, wanted, fund.parse_companyfacts)
    except Exception as exc:
        print("SEC companyfacts zip parse failed:", str(exc)[:160])
        return False, annual, quarters, list(wanted)
    if found:
        if len(fresh_a):
            keep = annual[~annual["ticker"].isin(fresh_a["ticker"])] if len(annual) and "ticker" in annual.columns else annual
            annual = pd.concat([keep, fresh_a], ignore_index=True) if len(keep) else fresh_a
            annual.to_csv(annual_p, index=False)
        if len(fresh_q):
            keep = quarters[~quarters["ticker"].isin(fresh_q["ticker"])] if len(quarters) and "ticker" in quarters.columns else quarters
            quarters = pd.concat([keep, fresh_q], ignore_index=True) if len(keep) else fresh_q
            quarters.to_csv(quarter_p, index=False)
    leftover = [t for t in missing if t in cik]
    print("SEC companyfacts zip: %d names, %d leftover" % (len(found), len(leftover)))
    return True, annual, quarters, leftover


def load_sec(tickers, cik, cfg, cache, mode, core=None):
    annual_p = os.path.join(cache, "annual.csv")
    quarter_p = os.path.join(cache, "quarters.csv")
    annual, quarters = read_csv(annual_p), read_csv(quarter_p)
    decision = _need_fetch("sec_facts", annual_p, mode)
    gaps = None
    sheet_blank = _balance_sheet_blank(annual)
    flow_gap = _flow_gap(annual)
    rolling_early = sec_rolling_settings(cfg)
    want_bulk = mode == "full" and rolling_early.get("use_bulk_zip", True) and STAMPS.get("sec_facts_bulk") != today_et()
    want_all = mode == "full" and rolling_early.get("full_universe", True) and STAMPS.get("sec_facts_bulk") != today_et()
    if decision == "reuse" and not want_bulk and not want_all:
        gaps = _missing_tickers(annual, tickers) if mode == "full" else []
        gaps = [t for t in gaps if t in cik]
        # One full run may refetch when the saved statements are unusable.
        # Hourly and offline never call the SEC. This is the same daily pass, not an extra source.
        if mode == "full" and sheet_blank:
            print("SEC equity and debt are blank in the cache; refetching company facts")
            gaps = None
        elif mode == "full" and flow_gap:
            print("SEC annual net income is missing where revenue is present; refetching company facts")
            gaps = None
        elif not gaps:
            status = "PARTIAL" if sheet_blank else "OK"
            note = "reused cache (slow sources refresh at most once a day)"
            if sheet_blank:
                note = "reused cache; equity and debt are blank on every row. This run does not call the SEC."
            log("Fundamentals (SEC EDGAR company facts)", status, STAMPS.get("sec_facts", ""), note)
            return annual, quarters
        else:
            print("SEC filling %d names added since the daily fetch" % len(gaps))
    elif decision == "reuse" and (want_bulk or want_all):
        # A full run with the official zip (or whole-universe pull) still
        # refreshes every name once a day, even if yesterday's cache exists.
        gaps = None
    if decision == "missing":
        log("Fundamentals (SEC EDGAR company facts)", "MISSING", "", "no cache and this run does not call the SEC")
        return annual, quarters
    rolling = sec_rolling_settings(cfg)
    # Official zip or a whole-universe pull still runs on a full day even if a
    # earlier cache stamp exists, so one run can fill every name.
    zip_leftover = None
    if mode == "full" and rolling.get("use_bulk_zip", True) and STAMPS.get("sec_facts_bulk") != today_et():
        ok, annual, quarters, zip_leftover = apply_companyfacts_zip(
            tickers, cik, cfg, cache, annual, quarters, annual_p, quarter_p
        )
        if ok:
            STAMPS["sec_facts_bulk"] = today_et()
            cycle = load_sec_cycle(cache)
            for t in (tickers or []):
                if t in cik and len(annual) and "ticker" in annual.columns and t in set(annual["ticker"].astype(str)):
                    cycle[t] = today_et()
            save_sec_cycle(cache, cycle)
            STAMPS["sec_facts"] = today_et()
            if not zip_leftover:
                note = "%d names from official companyfacts.zip" % (annual["ticker"].nunique() if len(annual) else 0)
                status = "PARTIAL" if _balance_sheet_blank(annual) else "OK"
                if status == "PARTIAL":
                    note += "; equity and debt are still blank"
                log("Fundamentals (SEC EDGAR company facts)", status, today_et(), note)
                return annual, quarters
            print("SEC filling %d names not in the official zip" % len(zip_leftover))
    lim = netutil.RateLimiter(rl(cfg)["sec_requests_per_second"])
    headers = session_headers(cfg, sec=True)
    # A new day refreshes everyone. A crash the same day continues where it stopped.
    # A balance-sheet refetch ignores today's progress: those rows were parsed without equity.
    done = progress_load(cache, "sec")
    if mode == "full" and (sheet_blank or flow_gap) and not gaps and zip_leftover is None:
        done = set()
    new_a, new_q, fails = [], [], 0
    pool = gaps if gaps else [t for t in tickers if t in cik]
    if zip_leftover is not None:
        pool = zip_leftover
    cycle = load_sec_cycle(cache)
    # The official zip (or full_universe) fills every name in one full run.
    # The older daily slice is only used when that switch is off.
    if zip_leftover is None and rolling.get("full_universe", True) and mode == "full":
        pool = [t for t in tickers if t in cik]
    elif rolling["on"] and not (sheet_blank or flow_gap) and zip_leftover is None:
        # A blank-sheet repair still walks everyone. Otherwise the S&P 400 and 600
        # are a daily slice, and the S&P 500, Nasdaq-100, and growth names stay daily.
        pool = rolling_sec_pool(pool, core, cycle, today_et(), rolling["batch_per_run"], rolling["refresh_every_days"], done)
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
    for t in todo:
        if t in done:
            cycle[t] = today_et()
    save_sec_cycle(cache, cycle)
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
        if rolling.get("full_universe", True) or zip_leftover is not None:
            STAMPS["sec_facts_bulk"] = today_et()
        note = "%d names" % annual["ticker"].nunique() if len(annual) else "0"
        if fails:
            note += ", %d failed and kept prior rows" % fails
        status = "OK"
        if _balance_sheet_blank(annual):
            status = "PARTIAL"
            note += "; equity and debt are still blank"
        log("Fundamentals (SEC EDGAR company facts)", status, today_et(), note)
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



def load_sec_profiles(tickers, cik, cfg, cache, mode):
    """Name, country, exchange, and SIC industry from SEC submissions. Whole universe on a full run."""
    path = os.path.join(cache, "sec_profiles.csv")
    prior = read_csv(path)
    if mode != "full":
        status = "OK" if len(prior) else "MISSING"
        log("Company profiles (SEC EDGAR submissions)", status, STAMPS.get("sec_profiles", ""),
            "reused cache" if len(prior) else "no cache and this run does not call the SEC")
        return prior
    wanted = {t: cik[t] for t in tickers if t in (cik or {})}
    if not wanted:
        log("Company profiles (SEC EDGAR submissions)", "MISSING" if not len(prior) else "CACHED", "", "no CIK map")
        return prior
    rolling = sec_rolling_settings(cfg)
    rows = pd.DataFrame()
    leftover = list(wanted)
    if rolling.get("use_bulk_zip", True):
        zpath = _download_sec_zip(cfg, cache, profiles.SUBMISSIONS_ZIP_URL, "submissions.zip", "sec_submissions_zip", timeout=600)
        if zpath:
            try:
                rows = profiles.parse_submissions_from_zip(zpath, wanted)
                have = set(rows["ticker"].astype(str)) if len(rows) and "ticker" in rows.columns else set()
                leftover = [t for t in wanted if t not in have]
                print("SEC submissions zip: %d names, %d leftover" % (len(have), len(leftover)))
            except Exception as exc:
                print("SEC submissions zip parse failed:", str(exc)[:160])
                leftover = list(wanted)
    if leftover:
        lim = netutil.RateLimiter(rl(cfg)["sec_requests_per_second"])
        headers = session_headers(cfg, sec=True)
        fetched = []
        for i, t in enumerate(leftover):
            url = "https://data.sec.gov/submissions/CIK%s.json" % wanted[t]
            try:
                r = netutil.http_get(requests, url, headers, 60, limiter=lim, max_tries=rl(cfg)["max_retries"])
                fetched.append(profiles.parse_submissions_profile(r.json(), ticker=t))
            except Exception as exc:
                if i < 3:
                    print("sec submissions fail", t, str(exc)[:100])
            if (i + 1) % 80 == 0:
                print("SEC submissions %d / %d" % (i + 1, len(leftover)))
        if fetched:
            add = pd.DataFrame(fetched)
            rows = pd.concat([rows, add], ignore_index=True) if len(rows) else add
    if rows is None or len(rows) == 0:
        status = "CACHED" if len(prior) else "MISSING"
        log("Company profiles (SEC EDGAR submissions)", status, STAMPS.get("sec_profiles", ""),
            "kept the saved profiles" if len(prior) else "no submissions data")
        return prior
    # Merge: new rows replace the same ticker, other prior rows stay.
    if len(prior) and "ticker" in prior.columns:
        keep = prior[~prior["ticker"].astype(str).isin(set(rows["ticker"].astype(str)))]
        rows = pd.concat([keep, rows], ignore_index=True)
    rows.to_csv(path, index=False)
    STAMPS["sec_profiles"] = today_et()
    log("Company profiles (SEC EDGAR submissions)", "OK", today_et(), "%d names" % rows["ticker"].nunique())
    return rows


def load_nasdaq_earnings(cfg, cache, mode, start=None):
    """Next earnings dates from the Nasdaq calendar. One call per day. Never wipe the saved file on failure."""
    path = os.path.join(cache, "nasdaq_earnings_calendar.csv")
    prior = read_csv(path)
    if mode != "full":
        status = "OK" if len(prior) else "MISSING"
        log("Earnings dates (Nasdaq calendar)", status, STAMPS.get("nasdaq_earnings", ""),
            "reused cache" if len(prior) else "no cache and this run does not call Nasdaq")
        return prior
    block = cfg.get("earnings_calendar") or {}
    try:
        days_ahead = int(block.get("days_ahead", 60))
    except (TypeError, ValueError):
        days_ahead = 60
    skip_weekends = bool(block.get("skip_weekends", True))
    start = pd.Timestamp(start or today_et())
    days = profiles.calendar_days(start, days_ahead=days_ahead, skip_weekends=skip_weekends)
    lim = netutil.RateLimiter(rl(cfg)["nasdaq_requests_per_second"])
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    fresh_rows, failed = [], 0
    for i, day in enumerate(days):
        url = "https://api.nasdaq.com/api/calendar/earnings?date=%s" % day
        try:
            r = netutil.http_get(requests, url, headers, 30, limiter=lim, max_tries=rl(cfg)["max_retries"])
            payload = r.json()
            fresh_rows.extend(profiles.parse_nasdaq_earnings_payload(payload, day))
        except Exception as exc:
            failed += 1
            if failed <= 3:
                print("nasdaq earnings fail", day, str(exc)[:100])
    fresh = pd.DataFrame(fresh_rows)
    if failed and not len(fresh):
        log("Earnings dates (Nasdaq calendar)", "CACHED" if len(prior) else "MISSING", STAMPS.get("nasdaq_earnings", ""),
            "kept the saved calendar after %d failed days" % failed)
        return prior
    merged = profiles.keep_calendar_on_failure(prior, fresh, failed=False)
    if merged is None or len(merged) == 0:
        log("Earnings dates (Nasdaq calendar)", "CACHED" if len(prior) else "MISSING", "", "empty calendar, kept the saved file")
        return prior
    merged.to_csv(path, index=False)
    STAMPS["nasdaq_earnings"] = today_et()
    note = "%d rows, %d weekdays" % (len(merged), len(days))
    if failed:
        note += ", %d days failed and kept prior rows" % failed
    log("Earnings dates (Nasdaq calendar)", "OK", today_et(), note)
    return merged


def load_finnhub_websites(tickers, cfg, cache, mode):
    """Optional company websites. Runs only when FINNHUB_API_KEY is already in the environment."""
    path = os.path.join(cache, "finnhub_profiles.csv")
    prior = read_csv(path)
    key = profiles.finnhub_api_key()
    if not key:
        log("Company websites (Finnhub)", "OK", "", "skipped; no FINNHUB_API_KEY")
        return prior
    if mode != "full":
        log("Company websites (Finnhub)", "OK" if len(prior) else "MISSING", STAMPS.get("finnhub_websites", ""),
            "reused cache" if len(prior) else "no cache")
        return prior
    have = set()
    if len(prior) and "ticker" in prior.columns:
        filled = prior.copy()
        if "website" in filled.columns:
            have = set(filled[filled["website"].astype(str).str.strip() != ""]["ticker"].astype(str))
    todo = [t for t in tickers if t not in have][:60]
    if not todo:
        log("Company websites (Finnhub)", "OK", STAMPS.get("finnhub_websites", ""), "already filled")
        return prior
    lim = netutil.RateLimiter(1.0)  # well under the free-tier cap
    headers = {"User-Agent": session_headers(cfg).get("User-Agent", "Mozilla/5.0")}
    rows, fails = [], 0
    for i, t in enumerate(todo):
        url = "https://finnhub.io/api/v1/stock/profile2?symbol=%s&token=%s" % (t, key)
        try:
            r = netutil.http_get(requests, url, headers, 30, limiter=lim, max_tries=2)
            rows.append(profiles.parse_finnhub_profile(r.json(), t))
        except Exception:
            fails += 1
    fresh = pd.DataFrame(rows)
    if not len(fresh):
        log("Company websites (Finnhub)", "CACHED" if len(prior) else "MISSING", "", "kept the saved websites")
        return prior
    if len(prior) and "ticker" in prior.columns:
        keep = prior[~prior["ticker"].astype(str).isin(set(fresh["ticker"].astype(str)))]
        fresh = pd.concat([keep, fresh], ignore_index=True)
    fresh.to_csv(path, index=False)
    STAMPS["finnhub_websites"] = today_et()
    log("Company websites (Finnhub)", "OK", today_et(), "%d names, %d failed" % (len(fresh), fails))
    return fresh


def load_yahoo(tickers, cfg, cache, mode):
    info_p = os.path.join(cache, "yahoo_info.csv")
    earn_p = os.path.join(cache, "earnings.csv")
    info, earn = read_csv(info_p), read_csv(earn_p)
    decision = _need_fetch("yahoo_slow", info_p, mode)
    if decision == "missing":
        log("Analyst and profile (Yahoo Finance)", "MISSING", "", "no cache and this run does not call Yahoo profiles")
        log("Earnings dates (Yahoo Finance)", "MISSING", "", "no cache")
        return info, earn
    if decision == "reuse" and mode != "full":
        log("Analyst and profile (Yahoo Finance)", "OK", STAMPS.get("yahoo_slow", ""), "reused cache (slow sources refresh at most once a day)")
        log("Earnings dates (Yahoo Finance)", "OK", STAMPS.get("yahoo_slow", ""), "reused cache")
        return info, earn
    settings = slow_source_settings(cfg)
    have = set(info["ticker"].astype(str)) if len(info) and "ticker" in info.columns else set()
    cycle = load_named_cycle(cache, "yahoo")
    done = progress_load(cache, "yahoo")
    pool = slow_refresh_pool(
        list(tickers), have, cycle, today_et(),
        settings["batch_per_run"], settings["refresh_every_days"], done)
    if not pool:
        STAMPS["yahoo_slow"] = today_et()
        note = "reused cache (at most %d profiles a full run, again after %d days)" % (
            settings["batch_per_run"], settings["refresh_every_days"])
        log("Analyst and profile (Yahoo Finance)", "OK", today_et(), note)
        log("Earnings dates (Yahoo Finance)", "OK", today_et(), "reused cache")
        return info, earn
    print("Yahoo profiles refreshing %d names (at most %d a full run)" % (len(pool), settings["batch_per_run"]))
    import yfinance as yf
    lim = netutil.RateLimiter(rl(cfg)["yahoo_profile_per_second"])
    rows, erows, fails = [], [], 0
    old_info = info.set_index("ticker") if len(info) and "ticker" in info.columns else None
    base_info, base_earn = info, earn
    todo = list(pool)
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
                # Same tk.info response as above. One more field, no new request.
                "market_cap": inf.get("marketCap"),
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
        if (i + 1) % 25 == 0 or (i + 1) == len(todo):
            print("Yahoo profiles %d / %d" % (i + 1, len(todo)))
            info = merge_ticker_rows(base_info, rows)
            if len(info) and "ticker" in info.columns:
                info = info.drop_duplicates("ticker", keep="last")
                info.to_csv(info_p, index=False)
            earn = merge_ticker_rows(base_earn, erows)
            if len(earn):
                earn.to_csv(earn_p, index=False)
            for name in done:
                cycle[name] = today_et()
            save_named_cycle(cache, "yahoo", cycle)
            progress_save(cache, "yahoo", done)
            checkpoint_progress("yahoo profiles %d/%d" % (i + 1, len(todo)))
    fail_rate = fails / max(len(todo), 1)
    if fail_rate > 0.5:
        log("Analyst and profile (Yahoo Finance)", "CACHED" if len(info) else "MISSING", "", "%d of %d failed" % (fails, len(tickers)))
        log("Earnings dates (Yahoo Finance)", "CACHED" if len(earn) else "MISSING", "", "same pass as profiles")
    else:
        STAMPS["yahoo_slow"] = today_et()
        log("Analyst and profile (Yahoo Finance)", "OK", today_et(), "%d names, %d failed" % (len(info), fails))
        log("Earnings dates (Yahoo Finance)", "OK" if len(earn) else "MISSING", today_et(), "%d rows" % len(earn))
    return info, earn


def _parse_asof(value):
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    return pd.Timestamp(ts)


def _latest_holder_rows(rows):
    """One row per filer, and only the newest quarter for that ticker.

    The holdings table mixes quarter-end dates. Summing them, or listing both,
    counts the same shares twice.
    """
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    if "ticker" not in frame.columns:
        return rows
    frame["_asof"] = frame["as_of"].map(_parse_asof) if "as_of" in frame.columns else pd.NaT
    kept = []
    for _ticker, sub in frame.groupby(frame["ticker"].astype(str), sort=False):
        latest = sub["_asof"].max()
        if pd.isna(latest):
            chunk = sub
        else:
            chunk = sub[sub["_asof"] == latest]
        chunk = chunk.copy()
        chunk["_owner"] = chunk["owner"].astype(str).str.strip().str.lower() if "owner" in chunk.columns else ""
        chunk = chunk.sort_values("_asof").drop_duplicates("_owner", keep="last")
        kept.append(chunk.drop(columns=["_asof", "_owner"], errors="ignore"))
    if not kept:
        return []
    return pd.concat(kept, ignore_index=True).to_dict("records")


def attach_share_market_cap(info, close, annual, quarters):
    """Fill a missing market cap from the last price times SEC shares. No new download."""
    shares = latest_shares_by_ticker(annual, quarters)
    if not shares or close is None or len(close) == 0:
        return info
    last = close.ffill().iloc[-1]
    rows = info.to_dict("records") if info is not None and len(info) else []
    by_ticker = {}
    for row in rows:
        by_ticker[str(row.get("ticker") or "")] = row
    for ticker, count in shares.items():
        try:
            px = float(last.get(ticker))
            count_n = float(count)
        except (TypeError, ValueError):
            continue
        if px != px or px <= 0 or count_n != count_n or count_n <= 0:
            continue
        cap = px * count_n
        row = by_ticker.get(ticker)
        if row is None:
            row = {"ticker": ticker, "market_cap": cap}
            rows.append(row)
            by_ticker[ticker] = row
        elif scoring._f(row.get("market_cap")) is None:
            row["market_cap"] = cap
    return pd.DataFrame(rows) if rows else info


def latest_shares_by_ticker(annual, quarters):
    """Newest SEC share count for each ticker. Blank stays blank."""
    parts = []
    for frame in (quarters, annual):
        if frame is None or len(frame) == 0 or "ticker" not in getattr(frame, "columns", []) or "shares" not in frame.columns:
            continue
        sub = frame[["ticker", "end", "shares"]].copy()
        sub["end"] = pd.to_datetime(sub["end"], errors="coerce")
        sub["shares"] = pd.to_numeric(sub["shares"], errors="coerce")
        sub = sub.dropna(subset=["end", "shares"])
        sub = sub[sub["shares"] > 0]
        parts.append(sub)
    if not parts:
        return {}
    all_rows = pd.concat(parts, ignore_index=True).sort_values("end")
    last = all_rows.drop_duplicates("ticker", keep="last")
    return dict(zip(last["ticker"].astype(str), last["shares"].astype(float)))


def ownership_percent(inst_shares, sec_shares, nasdaq_so_m, fallback_pct):
    """Holdings divided by the share count that matches the filing.

    Nasdaq divides total reported holdings by its own shares-outstanding figure.
    That denominator is often one class or a stale count, so the percent prints
    above 100. SEC shares can be one class too. The denominator is the larger of
    the two counts. Above 100 after that still means the holdings were counted
    twice; the caller flags it instead of pretending the raw percent was right.
    Returns (percent or None, exceeds_shares).
    """
    inst = _parse_int(inst_shares)
    sec = _parse_int(sec_shares)
    nq = _parse_int(nasdaq_so_m)
    if nq is not None and 0 < nq < 1_000_000:
        nq = nq * 1_000_000.0
    # A share count under 1,000,000 that matches Nasdaq after * 1,000,000 was
    # reported in millions (MCD). NVR's real 2.8 million shares is already above that.
    if sec is not None and 0 < sec < 1_000_000:
        scaled = sec * 1_000_000.0
        if nq and abs(scaled - nq) / nq <= 0.35:
            sec = scaled
        elif not nq:
            sec = scaled
    # Either source can be one share class. The smaller count pushes the percent
    # through 100. Use the larger count; still above 100 means the holdings overlap.
    denoms = [v for v in (sec, nq) if v and v > 0]
    denom = max(denoms) if denoms else None
    if inst is not None and denom and denom > 0:
        pct = inst / denom * 100.0
        return round(pct, 2), pct > 100.0
    own, capped = cap_ownership(fallback_pct)
    if own is None:
        return None, False
    return own, bool(capped)


def apply_ownership(holders, annual, quarters):
    """Replace Nasdaq's ownership percent with holdings / SEC shares."""
    if holders is None or len(holders) == 0:
        return holders
    out = holders.copy()
    shares = latest_shares_by_ticker(annual, quarters)
    pcts = []
    overs = []
    for _, r in out.iterrows():
        pct, over = ownership_percent(
            r.get("inst_shares"), shares.get(str(r.get("ticker"))), r.get("nasdaq_so_m"), r.get("ownership_pct"))
        pcts.append(pct)
        overs.append(over)
    out["ownership_pct"] = pcts
    out["_ownership_over"] = overs
    return out


def filer_name(name):
    """Keep a filer's own casing. Nasdaq title-cases short names (Fmr Llc, Blackrock)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = str(name).strip()
    if not text:
        return ""
    known = {
        "fmr llc": "FMR LLC",
        "blackrock, inc.": "BlackRock, Inc.",
        "blackrock inc.": "BlackRock, Inc.",
        "blackrock, inc": "BlackRock, Inc.",
    }
    if text.lower() in known:
        return known[text.lower()]
    out = []
    for word in text.split():
        bare = word.strip(",")
        if bare.lower() in ("llc", "lp", "llp"):
            suffix = "," if word.endswith(",") else ""
            out.append(bare.upper() + suffix)
        else:
            out.append(word)
    return " ".join(out)


def cap_ownership(value):
    """Nasdaq's share of shares outstanding can exceed 100 when share classes overlap.

    Cap the published figure at 100 and say so. The raw feed is not a sum we control.
    """
    n = _parse_int(value)
    if n is None:
        return None, False
    if n > 100:
        return 100.0, True
    return n, False


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


def load_holders(tickers, cfg, cache, mode, clock=None, budget_sec=None):
    path = os.path.join(cache, "holders.csv")
    detail_p = os.path.join(cache, "holder_rows.csv")
    summary, detail = read_csv(path), read_csv(detail_p)
    decision = _need_fetch("holders", path, mode)
    # The saved percent is Nasdaq's raw ratio. Recomputing it needs the holdings
    # total and Nasdaq's share count, which older caches did not keep.
    missing_parts = len(summary) > 0 and "inst_shares" not in summary.columns
    if decision == "missing":
        log("Institutional 13F and insider (Nasdaq)", "MISSING", "", "no cache and this run does not call Nasdaq")
        return summary, detail
    if decision == "reuse" and mode != "full":
        log("Institutional 13F and insider (Nasdaq)", "OK", STAMPS.get("holders", ""), "reused cache (slow sources refresh at most once a day)")
        return summary, detail
    settings = slow_source_settings(cfg)
    have = set(summary["ticker"].astype(str)) if len(summary) and "ticker" in summary.columns else set()
    cycle = load_named_cycle(cache, "holders")
    done = progress_load(cache, "holders")
    full = ownership_full_on() and mode == "full"
    batch = holders_batch_per_run(settings, len(tickers), mode)
    if missing_parts:
        print("13F cache has no holdings total; refreshing a batch so ownership is not just capped")
    pool = slow_refresh_pool(
        list(tickers), have, {} if missing_parts else cycle, today_et(),
        batch, settings["refresh_every_days"], done)
    if not pool:
        STAMPS["holders"] = today_et()
        note = "reused cache (at most %d names a full run, again after %d days)" % (
            batch, settings["refresh_every_days"])
        if full:
            note = "ownership_full: every name already fetched today"
            write_ownership_status(cache, {
                "active": True, "chain": False, "waiting": 0, "fetched_this_run": 0,
                "done_today": len(done), "universe": len(tickers), "stopped_for_budget": False,
            })
        log("Institutional 13F and insider (Nasdaq)", "OK", today_et(), note)
        return summary, detail
    if full:
        print("Nasdaq ownership_full refreshing %d of %d names (cap lifted for this run)" % (len(pool), len(tickers)))
    else:
        print("Nasdaq refreshing %d names (at most %d a full run)" % (len(pool), batch))
    lim = netutil.RateLimiter(rl(cfg)["nasdaq_requests_per_second"])
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    sums, rows, fails = [], [], 0
    old = summary.set_index("ticker") if len(summary) and "ticker" in summary.columns else None
    base_summary, base_detail = summary, detail
    todo = list(pool)
    if done:
        print("Nasdaq skipping %d names already fetched today" % len(done))
    clock = clock or time.monotonic
    budget = ownership_full_budget_sec() if budget_sec is None else budget_sec
    started = clock()
    stopped_for_budget = False
    fetched_now = 0
    for i, t in enumerate(todo):
        if full and budget is not None and (clock() - started) >= float(budget):
            stopped_for_budget = True
            print("Nasdaq ownership_full: stopping after %d names to finish this run inside the 120-minute limit; %d still waiting" % (i, len(todo) - i))
            break
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
            so_s = ((hd.get("ownershipSummary") or {}).get("ShareoutstandingTotal") or {}).get("value")
            own, _capped = cap_ownership(own_s)
            inst_shares = None
            for r in ((hd.get("activePositions") or {}).get("rows") or []):
                if "Total Institutional" in (r.get("positions") or ""):
                    inst_shares = _parse_int(r.get("shares"))
            table = ((hd.get("holdingsTransactions") or {}).get("table") or {})
            parsed_rows = []
            for r in (table.get("rows") or []):
                if not as_of:
                    as_of = r.get("date") or ""
                parsed_rows.append({
                    "ticker": t, "owner": filer_name(r.get("ownerName")), "shares": _parse_int(r.get("sharesHeld")),
                    "share_change": _parse_int(r.get("sharesChange")), "as_of": r.get("date") or "",
                })
            parsed_rows = _latest_holder_rows(parsed_rows)
            rows.extend(parsed_rows)
            buys = sells = None
            for r in ((idata.get("numberOfTrades") or {}).get("rows") or []):
                name = r.get("insiderTrade") or ""
                if "Buy" in name:
                    buys = _parse_int(r.get("months3"))
                elif "Sell" in name:
                    sells = _parse_int(r.get("months3"))
            sums.append({
                "ticker": t, "inst_up": increased, "inst_down": decreased, "holders": holders,
                "ownership_pct": own, "inst_shares": inst_shares, "nasdaq_so_m": _parse_int(so_s),
                "as_of": as_of, "insider_buys": buys, "insider_sells": sells,
            })
            done.add(t)
            fetched_now += 1
        except Exception:
            fails += 1
            if old is not None and t in old.index:
                sums.append(old.loc[t].to_dict())
        if (i + 1) % 40 == 0 or (i + 1) == len(todo):
            print("Nasdaq %d / %d" % (i + 1, len(todo)))
            summary = merge_ticker_rows(base_summary, sums)
            if len(summary) and "ticker" in summary.columns:
                summary = summary.drop_duplicates("ticker", keep="last")
                summary.to_csv(path, index=False)
            detail = merge_ticker_rows(base_detail, rows)
            if len(detail):
                detail.to_csv(detail_p, index=False)
            for name in done:
                cycle[name] = today_et()
            save_named_cycle(cache, "holders", cycle)
            progress_save(cache, "holders", done)
            checkpoint_progress("nasdaq holders %d/%d" % (i + 1, len(todo)))
    if sums or rows:
        # A budget stop can land between 40-name checkpoints; flush what we have.
        summary = merge_ticker_rows(base_summary, sums)
        if len(summary) and "ticker" in summary.columns:
            summary = summary.drop_duplicates("ticker", keep="last")
            summary.to_csv(path, index=False)
        detail = merge_ticker_rows(base_detail, rows)
        if len(detail):
            detail.to_csv(detail_p, index=False)
        for name in done:
            cycle[name] = today_et()
        save_named_cycle(cache, "holders", cycle)
        progress_save(cache, "holders", done)
        if fetched_now:
            checkpoint_progress("nasdaq holders %d/%d" % (fetched_now, len(todo)))
    fail_rate = fails / max(len(todo), 1)
    waiting = [name for name in tickers if name not in done]
    if fail_rate > 0.5 and not fetched_now:
        log("Institutional 13F and insider (Nasdaq)", "CACHED" if len(summary) else "MISSING", "", "%d of %d failed" % (fails, len(tickers)))
    else:
        STAMPS["holders"] = today_et()
        note = "%d names, %d failed" % (len(summary), fails)
        if stopped_for_budget:
            note += "; stopped to stay inside the 120-minute job, %d waiting for the next ownership_full run" % len(waiting)
        log("Institutional 13F and insider (Nasdaq)", "OK" if not stopped_for_budget else "PARTIAL", today_et(), note)
    if full:
        write_ownership_status(cache, {
            "active": True,
            "chain": ownership_should_chain(len(waiting), fetched_now, ownership_full_run_index(), ownership_full_max_runs()),
            "waiting": len(waiting),
            "fetched_this_run": fetched_now,
            "done_today": len(done),
            "universe": len(tickers),
            "stopped_for_budget": stopped_for_budget,
            "run_index": ownership_full_run_index(),
        })
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
                sube["earnings_dt"] = profiles.parse_earnings_dt(sube["earnings_dt"])
                past = sube[pd.to_numeric(sube["eps_actual"], errors="coerce").notna()].sort_values("earnings_dt")
                if len(past):
                    last = past.iloc[-1]
                    eps_flag = scoring.beat_flag(scoring._f(last["eps_actual"]), scoring._f(last["eps_estimate"]))
        sector = gics_sector(u.get("sector") or inf.get("sector") or "")
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
            "industry": (str(u.get("industry") or "").strip() or inf.get("industry") or ""),
            "country": (str(u.get("country") or "").strip() or inf.get("country") or ""),
            "website": (str(u.get("website") or "").strip() or inf.get("website") or ""),
            "sector_source": (str(u.get("sector_source") or "").strip() or ""),
            "index_membership": u.get("index_membership") or membership_label(u.get("in_sp500"), u.get("in_ndx100"), u.get("in_growth")),
            "universe": u.get("index_membership") or membership_label(u.get("in_sp500"), u.get("in_ndx100"), u.get("in_growth")),
            "price": round(mkt["price"], 2),
            "upside_pct": _upside_pct(extra.get("target_mean"), mkt["price"]),
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
                dts = profiles.parse_earnings_dt(sube["earnings_dt"])
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
        df = scoring.apply_sector_point_fallback(df, scfg)
        misses, counts = [], []
        for _, rec in df.iterrows():
            fields = tables.missing_fields(rec)
            misses.append(";".join(fields))
            counts.append(len(fields))
        df["missing_fields"] = misses
        df["missing_count"] = counts
        df = assign_ranks(df)
    return df, prepared


def assign_ranks(df):
    """Rank 1..N by score, then fewer missing inputs, then ticker.

    A row with no score stays blank. Missing is not ranked as zero, and it does not take a number.
    """
    if df is None or len(df) == 0 or "score" not in getattr(df, "columns", []):
        return df
    out = df.copy()
    score = pd.to_numeric(out["score"], errors="coerce")
    if "missing_count" in out.columns:
        miss = pd.to_numeric(out["missing_count"], errors="coerce").fillna(10 ** 9)
    else:
        miss = pd.Series(0, index=out.index)
    ticker = out["ticker"].astype(str) if "ticker" in out.columns else pd.Series("", index=out.index)
    order = pd.DataFrame({"score": score, "miss": miss, "ticker": ticker}, index=out.index)
    order = order.sort_values(["score", "miss", "ticker"], ascending=[False, True, True], na_position="last", kind="mergesort")
    out = out.loc[order.index].copy()
    n = int(order["score"].notna().sum())
    ranks = list(range(1, n + 1)) + [pd.NA] * (len(out) - n)
    out["rank"] = pd.array(ranks, dtype="Int64")
    front = ["rank"] + [c for c in out.columns if c != "rank"]
    return out[front]


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


def build_portfolio(holds, scores, history, today=None):
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
        week = _week_score(history, t, today)
        change = None if week is None or scoring._f(r.get("score")) is None else int(r["score"]) - int(week)
        status = "On track"
        if scoring._f(r.get("stop")) and price < float(r["stop"]):
            status = "Below stop"
        elif r.get("next_earnings"):
            try:
                days = (pd.Timestamp(r["next_earnings"]) - _desk_day(today)).days
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


def _desk_day(today=None):
    """The desk's calendar day at midnight, no time zone. score_history.csv dates are New York dates,
    so the default is today in New York, not the runner's clock (UTC on GitHub)."""
    day = pd.Timestamp(today if today is not None else today_et())
    if day.tzinfo is not None:
        day = day.tz_localize(None)
    return day.normalize()


def _week_score(history, ticker, today=None):
    """Latest saved score that is at least 7 days older than today (New York date unless given)."""
    if history is None or len(history) == 0:
        return None
    sub = history[history["ticker"] == ticker].copy()
    if not len(sub):
        return None
    sub["date"] = pd.to_datetime(sub["date"])
    cut = _desk_day(today) - pd.Timedelta(days=7)
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


# Scorecard chart window. About half a year of sessions. The job's full history
# stays in cache/ohlcv.csv.gz and is not copied into the sheet.
CHART_BARS = 126
# Daily bars published for the price chart. None keeps every session in the
# price cache (about five years). The 1Y view needs roughly 200 extra sessions
# so a 200-day average is warm at the left edge. The browser computes averages.
CANDLE_BARS = None
_TICKER_FILE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,12}$")


def _upside_pct(target_mean, price):
    """Percent upside from the mean analyst target. Blank when either input is missing."""
    target = scoring._f(target_mean)
    px = scoring._f(price)
    if target is None or px is None or px <= 0:
        return None
    return round((target / px - 1) * 100, 2)


def _column_blank(df, col):
    if df is None or len(df) == 0 or col not in getattr(df, "columns", []):
        return True
    return not pd.to_numeric(df[col], errors="coerce").notna().any()


def price_file(close, scores):
    if close is None or close.empty or scores is None or len(scores) == 0:
        return pd.DataFrame()
    names = [t for t in scores["ticker"] if t in close.columns]
    # Average each ticker on the sessions it actually traded, using the full
    # cache, and only then keep the chart window. A holiday hole in the wide
    # frame used to blank the next 20 or 50 bars.
    sma20 = pd.DataFrame(index=close.index, columns=names, dtype=float)
    sma50 = pd.DataFrame(index=close.index, columns=names, dtype=float)
    for t in names:
        traded = pd.to_numeric(close[t], errors="coerce").dropna()
        sma20[t] = traded.rolling(20, min_periods=20).mean()
        sma50[t] = traded.rolling(50, min_periods=50).mean()
    px = close[names].tail(CHART_BARS)
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


def candle_file(long_df, tickers, bars=CANDLE_BARS):
    """OHLC sessions per ticker for the site price chart.

    High, low, close, volume, and open come from the price cache. Open stays
    blank when that cache has no open column. `bars` is None to keep the whole
    cache, or a session count to keep only the tail. Moving averages are not
    stored here; the chart computes them in the browser.
    """
    cols = ["date", "ticker", "open", "high", "low", "close", "volume"]
    if long_df is None or len(long_df) == 0 or not tickers or "close" not in getattr(long_df, "columns", []):
        return pd.DataFrame(columns=cols)
    want = []
    for t in tickers:
        s = str(t or "").strip().upper()
        if _TICKER_FILE.match(s):
            want.append(s)
    want = list(dict.fromkeys(want))
    if not want:
        return pd.DataFrame(columns=cols)
    x = long_df[long_df["ticker"].astype(str).str.upper().isin(want)].copy()
    if not len(x):
        return pd.DataFrame(columns=cols)
    x["ticker"] = x["ticker"].astype(str).str.upper()
    x["date"] = pd.to_datetime(x["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col not in x.columns:
            x[col] = np.nan
        else:
            x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.dropna(subset=["close"]).sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
    parts = []
    for _, g in x.groupby("ticker", sort=False):
        g = g.copy()
        if bars:
            g = g.tail(int(bars))
        parts.append(g)
    if not parts:
        return pd.DataFrame(columns=cols)
    out = pd.concat(parts, ignore_index=True)
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].round(2)
    out["volume"] = out["volume"].round(0).astype("Int64")
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out[cols]


INDEX_SERIES = (
    ("SPY", "SPY", False),
    ("QQQ", "QQQ", False),
    ("^VIX", "VIX", True),
)


def write_index_proxy_files(long_df, out_dir):
    """Copy index and ETF series that are already in the price frame.

    This does not download anything. SPY and QQQ stay labeled as files, not as
    the indexes. A VIX volume of 0 is written blank so a later test cannot
    treat it as a real share-volume print. A symbol that is absent is skipped
    and any older file is left in place.
    """
    os.makedirs(out_dir, exist_ok=True)
    if long_df is None or len(long_df) == 0 or "ticker" not in getattr(long_df, "columns", []):
        return []
    frame = long_df.copy()
    frame["ticker"] = frame["ticker"].astype(str)
    written = []
    for src, name, blank_zero in INDEX_SERIES:
        g = frame[frame["ticker"] == src]
        if not len(g):
            continue
        g = g.sort_values("date").copy()
        # Older caches have no open column. Leave it blank, the same way candle files do.
        # A missing open is not a zero and must not stop the desk update.
        def _px(col):
            if col not in g.columns:
                return pd.Series([pd.NA] * len(g), index=g.index, dtype="Float64")
            return pd.to_numeric(g[col], errors="coerce").round(2)
        out = pd.DataFrame({
            "date": pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d"),
            "open": _px("open"),
            "high": _px("high"),
            "low": _px("low"),
            "close": _px("close"),
        })
        vol = pd.to_numeric(g["volume"], errors="coerce")
        if blank_zero:
            vol = vol.where(vol > 0)
        out["volume"] = vol.round(0).astype("Int64")
        out.to_csv(os.path.join(out_dir, name + ".csv"), index=False, na_rep="")
        written.append(name)
    return written


def write_candle_files(frame, out_dir):
    """One compact CSV per ticker. Returns how many files were written."""
    os.makedirs(out_dir, exist_ok=True)
    if frame is None or len(frame) == 0 or "ticker" not in frame.columns:
        return 0
    keep = set()
    cols = [c for c in frame.columns if c != "ticker"]
    for ticker, g in frame.groupby("ticker", sort=False):
        name = str(ticker) + ".csv"
        keep.add(name)
        g[cols].to_csv(os.path.join(out_dir, name), index=False, na_rep="")
    for name in os.listdir(out_dir):
        if name.endswith(".csv") and name not in keep:
            os.remove(os.path.join(out_dir, name))
    return len(keep)


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


def load_trading_floor(buy, frames, close, opn, vol, news, scores, asof, cfg, cache, mode):
    """Trading Floor (features.trading_floor). Built from what this run already has.

    Headlines: the desk's own stored headlines first. Only picks with none of those get one free
    Google News RSS request each, only on the full run, at most once a day (trading_floor.news.google_news).
    Hourly and offline runs reuse cache/trading_floor_news.csv. No Yahoo request is made here.
    """
    p = trading_floor.config(cfg)
    picks = trading_floor.pick_stocks(buy, frames, close, p)
    path = os.path.join(cache, "trading_floor_news.csv")
    cached = read_csv(path)
    floor_news = cached
    src = "Trading Floor headlines (Google News RSS)"
    n = p["news"]
    if n.get("on", True) and n.get("google_news", True) and picks:
        need = [pk for pk in picks if not trading_floor.headlines_for(pk["ticker"], pk.get("company"), news, None, asof, p)[0]]
        decision = _need_fetch("trading_floor_news", path, mode) if os.path.exists(path) else ("fetch" if mode == "full" else "missing")
        if decision == "fetch" and need:
            lim = netutil.RateLimiter(n.get("google_per_second", 1))
            rows, failed = trading_floor.fetch_google_news(need, p, today_et(), wait=lim.wait)
            done = [pk["ticker"] for pk in need if pk["ticker"] not in failed]
            floor_news = trading_floor.merge_news_cache(cached, rows, done, today_et(), n.get("keep_days", 14))
            floor_news.to_csv(path, index=False)
            STAMPS["trading_floor_news"] = today_et()
            status = "OK" if not failed else ("PARTIAL" if done else ("CACHED" if len(cached) else "MISSING"))
            log(src, status, today_et(), "%d requests for %d picks without desk headlines, %d headlines, %d failed (they say No fresh headlines found)." % (
                len(need), len(need), len(rows), len(failed)))
        else:
            log(src, "OK" if len(cached) else "MISSING", STAMPS.get("trading_floor_news", ""),
                ("reused cache" if len(cached) else "no cache yet") + ", no request this run (the fetch runs once a day on the full run, only for picks without desk headlines)")
    earn = {}
    if scores is not None and len(scores) and "next_earnings" in scores.columns:
        earn = dict(zip(scores["ticker"].astype(str), scores["next_earnings"]))
    floor = trading_floor.build_floor(picks, close, opn, vol, news, floor_news, asof, cfg, earnings=earn)
    c = trading_floor.counts(floor)
    log("Trading Floor", "OK", asof, "%d stocks debated: BUY %d, WAIT %d, SKIP %d. Research only, no orders, no alerts." % (
        len(floor), c["BUY"], c["WAIT"], c["SKIP"]))
    return floor


def build_price_tickers(cfg, cache, mode, hold_tickers, watch_tickers):
    """Universe symbols plus the sector ETFs, SPY, QQQ, and VIX. First-seen order, no duplicates."""
    features = cfg["features"]
    switches = index_switches(cfg)
    if features.get("universe", True):
        sp = load_index("sp500", cfg, cache, mode)
        mid = load_index("sp400", cfg, cache, mode)
        small = load_index("sp600", cfg, cache, mode)
        ndx = load_index("ndx100", cfg, cache, mode)
        growth = growth_frame(cfg)
        listed = load_listed_common(cfg, cache, mode)
        base = combine_indexes([sp, mid, small, ndx, growth], hold_tickers, watch_tickers, switches)
        liquid = load_liquid(cfg, cache, mode, list(base["ticker"]) if len(base) else [], listed)
        universe = combine_indexes([base, liquid], hold_tickers, watch_tickers, switches)
        log("Universe size", "OK", len(universe), "%d names after S&P 400, S&P 600, and liquid additions" % len(universe))
    else:
        universe = combine_indexes([], hold_tickers, watch_tickers, switches)
        log("Universe feature", "OK", "", "feature off: scoring the holdings and watchlist only")
    etfs = [e["ticker"] for e in cfg.get("sector_etfs", [])]
    # QQQ is one more name in the same Yahoo batch as SPY. It does not add a request.
    extras = etfs + ["SPY", "QQQ", "^VIX"]
    tickers = list(dict.fromkeys(list(universe["ticker"]) + extras))
    return universe, tickers


def _backfill_chunk(plan):
    fetch = sorted(
        s for s, item in plan.items()
        if item.get("kind") == "full" and item.get("reason") in ("new", "short")
    )
    waiting = sorted(s for s, item in plan.items() if item.get("reason") in ("waiting", "short_later"))
    return fetch, waiting


def run_history_backfill(cfg=None, fetcher=None, today=None):
    """Download five-year daily bars for names that have none, then stop.

    One chunk, capped by fast_backfill_per_run while features.fast_history_backfill
    is on. Merges into the price cache and does not call Yahoo for profiles,
    news, filings, or the names that already have bars. Prints a BACKFILL line.
    Returns 0 when the chunk finished, the switch is off, or every remaining
    name has no bars. Returns 2 when a transient failure left work unfinished
    after any good bars were saved. Returns 1 when the failure needs a person
    (auth) or the download died before a per-symbol result.
    """
    cfg = cfg or load_cfg()
    data, cache, inp = paths()
    load_stamps(cache)
    settings = price_settings_for(cfg, "backfill")
    on = fast_history_backfill_on(cfg) and incremental_prices_on(cfg)
    status = {
        "enabled": 1 if on else 0,
        "fetched": 0,
        "waiting": 0,
        "cap": settings["backfill_per_run"],
        "concurrency": settings["chart_concurrency"],
        "universe": 0,
        "outcome": 0,
        "unavailable": 0,
        "incomplete": 0,
        "transient": 0,
    }
    if not on:
        emit_backfill_status(status)
        print("Fast history backfill is off. No Yahoo calls.", flush=True)
        return 0
    holds = holdings_table(cfg, inp)
    watch = watch_table(cfg, inp)
    hold_tickers = [str(t).upper() for t in holds["ticker"]] if len(holds) else []
    watch_tickers = [str(t).upper() for t in watch["ticker"]] if len(watch) else []
    # Full mode so a stale constituent cache cannot hide the new lists. Wikipedia
    # and the Nasdaq files are not Yahoo chart calls.
    universe, tickers = build_price_tickers(cfg, cache, "full", hold_tickers, watch_tickers)
    status["universe"] = len(universe)
    save_stamps(cache)
    path = os.path.join(cache, "ohlcv.csv.gz")
    cached = read_csv(path) if os.path.exists(path) else pd.DataFrame()
    today_s = str(today or today_et())[:10]
    gaps = load_price_gaps(cache)
    plan = classify_price_fetches(tickers, cached, settings, True, gaps=gaps, today=today_s)
    fetch, waiting = _backfill_chunk(plan)
    counts, _last = _cached_price_stats(cached)
    wanted = {str(t).upper().replace(".", "-") for t in tickers}
    short = []
    for symbol, bars in sorted(counts.items()):
        symbol = str(symbol).upper()
        if symbol not in wanted or int(bars) <= 0 or int(bars) >= MIN_HISTORY_BARS:
            continue
        gap = gaps.get(symbol) or {}
        if gap_is_open(gap, today_s) and gap.get("kind") == "short":
            continue
        short.append(symbol)
    room = max(0, int(settings["backfill_per_run"]) - len(fetch))
    deferred_short = short[room:]
    fetch = list(fetch) + short[:room]
    status["waiting"] = len(waiting) + len(deferred_short)
    status["incomplete"] = sum(
        1 for symbol, bars in counts.items()
        if str(symbol).upper() in wanted and 0 < int(bars) < MIN_HISTORY_BARS
    )
    if not fetch:
        status["unavailable"] = sum(1 for item in plan.values() if item.get("reason") == "unavailable")
        status["outcome"] = 3 if status["unavailable"] else 0
        emit_backfill_status(status)
        print("No names are waiting for a first history.", flush=True)
        return 0

    def default_fetcher(symbols):
        outcomes = []
        try:
            frame = _download_long(
                symbols, cfg, None, settings["chart_concurrency"], settings["history_period"], outcomes=outcomes,
            )
        except Exception as exc:
            if outcomes:
                return pd.DataFrame(columns=PRICE_COLS), outcomes
            raise
        return frame, outcomes

    fetcher = fetcher or default_fetcher
    try:
        fetched = fetcher(fetch)
        fresh, outcomes = fetched if isinstance(fetched, tuple) else (fetched, [])
    except Exception as exc:
        kind = failure_kind(exc)
        status["outcome"] = 2 if kind == "auth" else 1
        status["transient"] = 0 if kind == "auth" else len(fetch)
        status["waiting"] = len(waiting) + (0 if kind == "auth" else len(fetch))
        emit_backfill_status(status)
        print("backfill download failed:", str(exc)[:200], flush=True)
        return 1 if kind == "auth" else 2

    outcomes = list(outcomes or [])
    unavailable = [row for row in outcomes if row.get("kind") == "unavailable"]
    transient = [row for row in outcomes if row.get("kind") == "transient"]
    auth = [row for row in outcomes if row.get("kind") == "auth"]
    for row in unavailable:
        remember_price_gap(
            gaps, row.get("symbol"), "unavailable", row.get("detail") or "no daily bars returned",
            today_s, GAP_UNAVAILABLE_DAYS,
        )
    got = []
    if fresh is not None and len(fresh):
        merged, _ignored = merge_price_rows(cached, fresh, settings, hold_back=[])
        merged = _save_prices(path, merged)
        counts = merged.groupby(merged["ticker"].astype(str)).size()
        got = sorted(set(fresh["ticker"].astype(str)))
        for symbol in got:
            if symbol in counts.index and int(counts[symbol]) < MIN_HISTORY_BARS:
                remember_price_gap(
                    gaps, symbol, "short", "fewer than %d daily bars" % MIN_HISTORY_BARS,
                    today_s, GAP_SHORT_DAYS,
                )
    if unavailable or any(row.get("kind") == "short" for row in []):
        save_price_gaps(cache, gaps)
    elif fresh is not None and len(fresh):
        save_price_gaps(cache, gaps)
    status["fetched"] = len(got)
    status["unavailable"] = len(unavailable)
    status["transient"] = len(transient)
    status["waiting"] = len(waiting) + len(transient)
    if auth:
        status["outcome"] = 2
    elif transient:
        status["outcome"] = 1
    elif not got and unavailable:
        status["outcome"] = 3
    else:
        status["outcome"] = 0
    emit_backfill_status(status)
    if unavailable:
        print("No daily bars for: %s. Recorded as missing data, not delisted. Recheck after %d days." % (
            ", ".join(sorted(row.get("symbol") or "" for row in unavailable)), GAP_UNAVAILABLE_DAYS,
        ), flush=True)
    if auth:
        print("backfill stopped for access: %s" % auth[0].get("detail", "")[:200], flush=True)
        return 1
    if transient:
        print("backfill paused after a transient price error (%d names). Saved bars were kept." % len(transient), flush=True)
        return 2
    print(
        "Backfill saved %d new histories (%d still waiting, cap %d, %d at a time). Cache only. No profiles, filings, news, or options."
        % (status["fetched"], status["waiting"], status["cap"], status["concurrency"]),
        flush=True,
    )
    return 0


def export_cached_scores(data_dir=None, cache_dir=None, cfg=None):
    """Write scores and candle files from the price cache already on disk.

    Does not download prices and does not rewrite the price cache. A name with
    fewer than 30 bars is left out. An existing score row is kept when its
    price and session date still match the cache, so this export does not
    invent a newer session.
    """
    cfg = cfg or load_cfg()
    data_dir = data_dir or os.path.join(root(), "data")
    cache_dir = cache_dir or os.path.join(root(), "cache")
    cache_path = os.path.join(cache_dir, "ohlcv.csv.gz")
    before = None
    if os.path.exists(cache_path):
        before = (os.path.getsize(cache_path), open(cache_path, "rb").read(64))
    prices = read_csv(cache_path) if os.path.exists(cache_path) else pd.DataFrame()
    universe = read_csv(os.path.join(data_dir, "universe.csv"))
    existing = read_csv(os.path.join(data_dir, "scores.csv"))
    report = {
        "scored": 0,
        "kept": 0,
        "recomputed": 0,
        "short": 0,
        "absent": 0,
        "price_as_of": "",
    }
    if len(prices) == 0 or len(universe) == 0 or "ticker" not in prices.columns:
        return report
    prices = prices.copy()
    prices["ticker"] = prices["ticker"].astype(str).str.upper()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices = prices.dropna(subset=["date"])
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["close"])
    counts = prices.groupby("ticker").size()
    last = prices.sort_values("date").groupby("ticker", as_index=False).tail(1).set_index("ticker")
    have = {}
    if len(existing) and "ticker" in existing.columns:
        have = {str(row["ticker"]).upper(): row for _, row in existing.iterrows()}
    keep_rows = []
    recompute = []
    for _, row in universe.iterrows():
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        bars = int(counts[ticker]) if ticker in counts.index else 0
        if bars <= 0:
            report["absent"] += 1
            continue
        if bars < MIN_HISTORY_BARS:
            report["short"] += 1
            continue
        session = str(pd.Timestamp(last.loc[ticker, "date"]).date())
        close_px = round(float(last.loc[ticker, "close"]), 2)
        old = have.get(ticker)
        old_px = None
        try:
            old_px = round(float(old["price"]), 2) if old is not None and old.get("price") not in ("", None) else None
        except (TypeError, ValueError, KeyError):
            old_px = None
        old_day = str(old.get("price_as_of") or "")[:10] if old is not None else ""
        if old is not None and old_px == close_px and old_day == session:
            keep_rows.append(old)
        else:
            recompute.append(ticker)
    fresh = pd.DataFrame()
    if recompute:
        subset = universe[universe["ticker"].astype(str).str.upper().isin(recompute)].copy()
        subset["ticker"] = subset["ticker"].astype(str).str.upper()
        close = wide_from_long(prices, "close")
        high = wide_from_long(prices, "high")
        low = wide_from_long(prices, "low")
        vol = wide_from_long(prices, "volume")
        annual = read_csv(os.path.join(cache_dir, "annual.csv"))
        quarters = read_csv(os.path.join(cache_dir, "quarters.csv"))
        info = read_csv(os.path.join(cache_dir, "yahoo_info.csv"))
        holders = read_csv(os.path.join(cache_dir, "holders.csv"))
        earnings = read_csv(os.path.join(cache_dir, "earnings.csv"))
        fresh, _prepared = build_scores(subset, close, high, low, vol, annual, quarters, info, holders, earnings, cfg)
        if len(fresh):
            fresh = fresh.drop(columns=["prepared"], errors="ignore")
            fresh = attach_status(fresh, "OK", "CACHED", "CACHED", "CACHED")
            fresh["note"] = "Price history from the saved cache. This export did not download prices."
    frames = []
    if keep_rows:
        frames.append(pd.DataFrame(keep_rows))
    if len(fresh):
        frames.append(fresh)
    if not frames:
        return report
    scores = pd.concat(frames, ignore_index=True)
    scores = assign_ranks(scores)
    write_out(gated(scores, "scores", True, "No scores."), "scores", data_dir)
    candles = candle_file(prices, list(scores["ticker"].astype(str)))
    write_candle_files(candles, os.path.join(data_dir, "ohlc"))
    if before is not None and os.path.exists(cache_path):
        after = (os.path.getsize(cache_path), open(cache_path, "rb").read(64))
        if after != before:
            raise RuntimeError("export changed the price cache")
    report["kept"] = len(keep_rows)
    report["recomputed"] = 0 if len(fresh) == 0 else int(fresh["ticker"].nunique())
    report["scored"] = int(scores["ticker"].nunique())
    if "price_as_of" in scores.columns and len(scores):
        report["price_as_of"] = str(scores["price_as_of"].astype(str).str.slice(0, 10).max())
    return report


def main(argv=None):
    global ROOT
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = "full"
    if "--offline" in argv:
        mode = "offline"
    elif "--hourly" in argv:
        mode = "hourly"
    elif "--backfill" in argv:
        mode = "backfill"
    elif "--full" in argv:
        mode = "full"
    ROOT = os.environ.get("DESK_ROOT") or os.path.dirname(os.path.abspath(__file__))
    if mode == "backfill":
        LOG.clear()
        STAMPS.clear()
        return run_history_backfill(load_cfg())
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

    universe, tickers = build_price_tickers(cfg, cache, mode, hold_tickers, watch_tickers)
    long = load_prices(tickers, cfg, cache, mode)
    checkpoint_progress("prices")
    close, high, low, vol = wide_from_long(long, "close"), wide_from_long(long, "high"), wide_from_long(long, "low"), wide_from_long(long, "volume")
    price_status = source_status("Prices (Yahoo Finance)")

    score_on = features.get("score_breakdown", True) or features.get("scorecard", True) or features.get("top_stocks", True)
    cik = cik_map(cfg, cache, mode) if score_on else {}
    sec_tickers = [t for t in universe["ticker"] if t in (cik or {})]
    if not score_on:
        annual, quarters = pd.DataFrame(), pd.DataFrame()
        info, earnings = pd.DataFrame(), pd.DataFrame()
        holders, holder_rows = pd.DataFrame(), pd.DataFrame()
        profiles_df, finnhub_df = pd.DataFrame(), pd.DataFrame()
    else:
        daily_names = core_tickers(universe, hold_tickers, watch_tickers)
        annual, quarters = load_sec(list(universe["ticker"]), cik, cfg, cache, mode, core=daily_names) if cik else (pd.DataFrame(), pd.DataFrame())
        if not cik and score_on:
            log("Fundamentals (SEC EDGAR company facts)", "MISSING", "", "no CIK map")
        # Yahoo profiles stay on the original daily list. 13F stays on that list
        # too, unless ownership_full is on for this run, in which the cap is
        # lifted and every universe name is eligible. Hourly reuses the cache.
        info, earnings = load_yahoo(daily_names, cfg, cache, mode)
        holder_names = list(universe["ticker"]) if (ownership_full_on() and mode == "full") else daily_names
        holders, holder_rows = load_holders(holder_names, cfg, cache, mode)
        # SEC profiles and the Nasdaq calendar cover the whole universe. They
        # do not add Yahoo calls. Finnhub websites run only when a key already exists.
        profiles_df = load_sec_profiles(list(universe["ticker"]), cik or {}, cfg, cache, mode)
        nasdaq_cal = load_nasdaq_earnings(cfg, cache, mode)
        earnings = profiles.merge_earnings_dates(earnings, nasdaq_cal, now=pd.Timestamp.now(tz="UTC"))
        finnhub_df = load_finnhub_websites(list(universe["ticker"]), cfg, cache, mode)
    if len(annual) or len(quarters):
        annual, quarters = fund.adjust_pershare_for_splits(annual, quarters)
    info = attach_share_market_cap(info, close, annual, quarters)
    if len(holders):
        holders = apply_ownership(holders, annual, quarters)
    if len(holder_rows):
        holder_rows = pd.DataFrame(_latest_holder_rows(holder_rows.to_dict("records")))
        if len(holder_rows) and "owner" in holder_rows.columns:
            holder_rows["owner"] = holder_rows["owner"].map(filer_name)
    # fill sector gaps from Yahoo
    if len(info) and len(universe):
        imap = info.set_index("ticker")
        for i, u in universe.iterrows():
            t = u["ticker"]
            if t in imap.index:
                row = imap.loc[t]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[-1]
                sector = gics_sector(u.get("sector")) or gics_sector(row.get("sector"))
                if sector:
                    universe.at[i, "sector"] = sector
                if not u.get("company") and row.get("company"):
                    universe.at[i, "company"] = row.get("company")
    if len(universe) and "sector" in universe.columns:
        universe["sector"] = universe["sector"].map(gics_sector)
    # SIC sectors and names fill blanks only. Wikipedia and Yahoo values stay.
    if "profiles_df" in locals() and len(profiles_df):
        universe = profiles.apply_profiles_to_universe(universe, profiles_df)
        info = profiles.apply_profiles_to_info(info, profiles_df)
    if "finnhub_df" in locals() and len(finnhub_df):
        web_only = finnhub_df.copy()
        for col in ("company", "sector", "industry", "country"):
            if col in web_only.columns:
                web_only[col] = ""
        universe = profiles.apply_profiles_to_universe(universe, web_only)
        if len(info) and "website" not in info.columns:
            info["website"] = ""
        info = profiles.apply_profiles_to_info(info, web_only)

    scores, prepared = build_scores(universe, close, high, low, vol, annual, quarters, info, holders, earnings, cfg) if len(close) else (pd.DataFrame(), {})
    scores = apply_feature_blanks(scores, features)
    fin_status = source_status("Fundamentals (SEC EDGAR company facts)")
    an_status = source_status("Analyst and profile (Yahoo Finance)")
    hold_status = source_status("Institutional 13F and insider (Nasdaq)")
    scores = attach_status(scores, price_status, fin_status, an_status, hold_status)
    if len(scores) and _column_blank(scores, "roe") and _column_blank(scores, "de"):
        for row in LOG:
            if "SEC EDGAR" in row["source"] and row["status"] == "OK":
                row["status"] = "PARTIAL"
                row["note"] = (row["note"] + " " if row["note"] else "") + "roe and de are blank on every scored row."
    if len(scores):
        scores["in_holdings"] = np.where(scores["ticker"].isin(hold_tickers), "yes", "no")
    scores = assign_ranks(scores)

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
    if len(scores) and long is not None and len(long):
        candle_frame = candle_file(long, list(scores["ticker"]))
        n_candles = write_candle_files(candle_frame, os.path.join(data, "ohlc"))
        if n_candles:
            span = int(candle_frame.groupby("ticker").size().max()) if len(candle_frame) else 0
            note = "%d tickers, up to %d cached sessions. No new download." % (n_candles, span)
            if "open" not in long.columns or not pd.to_numeric(long["open"], errors="coerce").notna().any():
                note += " Open is blank until the next full price download."
            log("Price candles", "OK", asof, note)
        wrote = write_index_proxy_files(long, os.path.join(data, "index_ohlc"))
        if wrote:
            log("Index series", "OK", asof, "%s copied from the price frame already downloaded. No new request." % ", ".join(wrote))
    news_out = news_rows(news, scores) if len(scores) else pd.DataFrame()
    headlines = news_out[news_out["kind"] == "headline"] if len(news_out) and "kind" in news_out.columns else pd.DataFrame()
    details = tables.score_details(scores) if len(scores) else pd.DataFrame()
    fins = tables.financials_long(scores) if len(scores) else pd.DataFrame()
    company = tables.company_rows(annual, close) if features.get("company_financials", True) else pd.DataFrame()
    hpe = tables.historical_pe(close, prepared) if features.get("historical_pe", True) else pd.DataFrame()
    if len(hpe):
        hpe["note"] = "Median trailing P/E of the stocks on this desk. There is no free official S&P 500 P/E series, so that line is not drawn."
    fresh = tables.freshness_table(scores) if features.get("freshness_flags", True) else pd.DataFrame()
    # institutional long rows
    inst_rows = []
    if len(holders):
        for _, r in holders.iterrows():
            own = r.get("ownership_pct")
            try:
                own_n = float(own)
            except (TypeError, ValueError):
                own_n = None
            over = bool(r.get("_ownership_over")) or (own_n is not None and own_n > 100)
            note = ""
            if over:
                note = "Reported holdings exceed shares outstanding; capped"
            inst_rows.append({
                "ticker": r["ticker"], "row_type": "summary", "owner": "",
                "increased_shares": r.get("inst_up"), "decreased_shares": r.get("inst_down"),
                "holders": r.get("holders"), "ownership_pct": own,
                "shares": "", "share_change": "", "as_of": r.get("as_of"),
                "pts_institutional": scores.set_index("ticker")["pts_institutional"].get(r["ticker"]) if len(scores) else "",
                "note": note,
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
        # Open is already in the saved daily bars (same Yahoo download). No new request.
        opn = wide_from_long(long, "open") if long is not None and len(long) and "open" in long.columns else None
        setup_frames = setups.build_setups(close, high, low, vol, universe, quarters, annual, holders, features, scores=scores, cfg=cfg, opn=opn)
    else:
        setup_frames = {k: pd.DataFrame() for k in (
            "scanner_vcp", "scanner_canslim", "scanner_box", "scanner_breakdown", "scanner_flag", "scanner_leaders",
            "scanner_qullamaggie", "scanner_marios", "scanner_52w", "highs_lows_history", "scanner_volume",
            "scorecard_canslim",
        )}
    def _n(frame):
        if frame is None or len(frame) == 0 or "ticker" not in getattr(frame, "columns", []):
            return 0
        return int((frame["ticker"].astype(str) != "").sum())
    ep_on = features.get("scanner_ep", True)
    if ep_on and len(close) and len(universe) and long is not None and len(long) and "open" in long.columns:
        # now_et only tells the scan whether today's bar is still forming (hourly runs in market hours).
        setup_frames["scanner_ep"] = episodic_pivot.scan_ep(
            close, high, low, vol, wide_from_long(long, "open"), universe, cfg,
            earnings=earnings, quarters=quarters, info=info, now_et=pd.Timestamp.now(tz=ET) if mode != "offline" else None,
        )
    else:
        setup_frames["scanner_ep"] = pd.DataFrame()
    log("Episodic pivot", "OK", asof if ep_on else "", ("EP rows %d. Cached prices, earnings dates, and profiles only. No new downloads." % _n(setup_frames["scanner_ep"])) if ep_on else "feature off")
    gap_on = features.get("scanner_gap_up", True)
    if gap_on and len(close) and len(universe) and long is not None and len(long) and "open" in long.columns:
        # Same saved daily bars (cache/ohlcv.csv.gz). No new request.
        setup_frames["scanner_gap_up"] = gap_up.scan_gap_up(close, high, low, vol, wide_from_long(long, "open"), universe, cfg)
    else:
        setup_frames["scanner_gap_up"] = pd.DataFrame()
    log("Pattern scanners", "OK", asof, "VCP %d, CANSLIM %d, box %d, breakdown %d, flag %d, Qullamaggie %d, Marios %d, high volume %d, leaders %d, 52-week %d names over %d sessions. No new downloads." % (
        _n(setup_frames["scanner_vcp"]), _n(setup_frames["scanner_canslim"]),
        _n(setup_frames["scanner_box"]), _n(setup_frames.get("scanner_breakdown")),
        _n(setup_frames["scanner_flag"]), _n(setup_frames.get("scanner_qullamaggie")), _n(setup_frames.get("scanner_marios")), _n(setup_frames.get("scanner_volume")), _n(setup_frames["scanner_leaders"]),
        _n(setup_frames.get("scanner_52w")),
        0 if setup_frames.get("highs_lows_history") is None else len(setup_frames.get("highs_lows_history")),
    ))
    buy_on = features.get("buy_setups", True)
    if buy_on and len(close):
        buy = setups.build_buy_setups(
            setup_frames.get("scanner_vcp"), setup_frames.get("scanner_box"),
            setup_frames.get("scanner_flag"), setup_frames.get("scanner_canslim"),
            scores, close, setup_frames.get("scanner_52w"),
            qullamaggie=setup_frames.get("scanner_qullamaggie"), marios=setup_frames.get("scanner_marios"),
            ep=setup_frames.get("scanner_ep") if ep_on else None,
        )
    else:
        buy = pd.DataFrame()
    if gap_on:
        # Gap Up does not feed Buy setups. It only names the other scanners each stock is on.
        setup_frames["scanner_gap_up"] = gap_up.attach_other_scanners(setup_frames.get("scanner_gap_up"), dict(
            setup_frames, scanner_growth=g, scanner_quality=q, scanner_dividend=d, scanner_wheel=w), cfg)
    log("Gap up", "OK", asof if gap_on else "", ("Gap up rows %d. Cached daily bars only. No new downloads." % _n(setup_frames["scanner_gap_up"])) if gap_on else "feature off")
    log("Buy setups", "OK", asof, "Buy setups %d. Research list only. Built from the scanners already on the desk. No new downloads." % _n(buy))
    floor_on = features.get("trading_floor", True)
    floor = pd.DataFrame()
    if floor_on and len(close):
        try:
            floor = load_trading_floor(buy, setup_frames, close, wide_from_long(long, "open") if long is not None and len(long) and "open" in long.columns else None,
                                       vol, news, scores, asof, cfg, cache, mode)
        except Exception as ex:
            log("Trading Floor", "MISSING", "", "skipped this run: %s" % ex)
    elif not floor_on:
        log("Trading Floor", "OK", "", "feature off")
    paper_on = features.get("trading_floor_paper", True)
    if paper_on and mode in ("full", "offline") and len(close) and long is not None and len(long) and "open" in long.columns:
        # FAKE MONEY paper test of the Trading Floor's BUY calls. Saved daily bars only, no new request.
        # Hourly runs never touch the paper files; a second full run on the same day changes nothing.
        try:
            paper_cfg = trading_floor_paper.config(cfg)
            state = trading_floor_paper.load_state(data)
            # The asof bar counts only once that session is over (after 16:15 ET), so a manual full run
            # during the session never fills or exits on a half-day bar.
            now_et = pd.Timestamp.now(tz=ET)
            asof_final = asof < now_et.strftime("%Y-%m-%d") or now_et.strftime("%H:%M") >= "16:15"
            state = trading_floor_paper.update(state, {"open": wide_from_long(long, "open"), "high": high, "low": low, "close": close},
                                               floor, asof, paper_cfg, asof_final=asof_final)
            trading_floor_paper.save_state(state, data)
            sm = state["summary"]
            log("Trading Floor paper test", "OK", sm.get("last_bar", ""), "FAKE MONEY. Equity %s, open %s, waiting %s, closed %s. Fills at the next session's open. No orders, no broker, no new downloads." % (
                sm.get("equity"), sm.get("open_count"), sm.get("pending_count"), sm.get("closed_count")))
        except Exception as ex:
            log("Trading Floor paper test", "CACHED", "", "kept the last paper files: %s" % ex)
    elif paper_on:
        log("Trading Floor paper test", "OK", "", "unchanged: it updates only on the full after-close run")
    else:
        log("Trading Floor paper test", "OK", "", "feature off: the paper files are left as they were")
    opt_on = features.get("options", True)
    ideas = pd.DataFrame()
    skipped_opt = pd.DataFrame()
    if not opt_on:
        log("Options chains", "OK", "", "feature off. Education only. No broker.")
    else:
        try:
            import options.ideas as options_ideas
            now_et = pd.Timestamp.now(tz=ET).to_pydatetime()
            cal = earn_pages.get("calendar") if isinstance(earn_pages, dict) else pd.DataFrame()
            ideas, skipped_opt, check, logged, new_stamp = options_ideas.publish(
                close, vol, buy, setup_frames.get("scanner_breakdown"), cal,
                cache, mode, now_et, STAMPS.get("options_chains"),
            )
            if new_stamp:
                STAMPS["options_chains"] = new_stamp
            if check is not None:
                check.to_csv(os.path.join(data, "options_spreads_check.csv"), index=False)
            log("Options chains", logged[0], logged[1], logged[2])
        except Exception as ex:
            log("Options chains", "CACHED", "", "kept the last options file. %s" % ex)
            ideas = read_csv(os.path.join(data, "options_ideas.csv"))
            skipped_opt = read_csv(os.path.join(data, "options_skipped.csv"))
    rot = sector_rotation.build(
        close, high, scores, cfg.get("sector_etfs") or [],
        scanners={
            "vcp": setup_frames.get("scanner_vcp"),
            "box": setup_frames.get("scanner_box"),
            "flag": setup_frames.get("scanner_flag"),
            "canslim": setup_frames.get("scanner_canslim"),
        },
        buy_setups=buy if len(buy) else None,
        fred=sector_rotation.read_fred_cache(cache),
        cfg=cfg.get("sector_rotation"),
    )
    if features.get("sector_rotation", True):
        log("Sector rotation", "OK", asof, rot.get("log") or "No new downloads.")
    else:
        log("Sector rotation", "OK", "", "feature off")

    insider = holders[["ticker", "insider_buys", "insider_sells"]].rename(columns={"insider_buys": "buys_3m", "insider_sells": "sells_3m"}) if len(holders) else pd.DataFrame()
    if len(insider) and len(scores):
        insider["pts_insider"] = insider["ticker"].map(scores.set_index("ticker")["pts_insider"])

    # walls note. nearest expiry is computed from the expiry column already on file.
    if len(walls):
        walls = tables.mark_nearest_expiry(walls)
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
        "scorecard_canslim": gated(setup_frames.get("scorecard_canslim"), "scorecard_canslim", features.get("scorecard_canslim", True), "No scorecard CAN SLIM letters. Missing letters stay no data yet, not a fail. No new downloads."),
        "scanner_box": gated(setup_frames["scanner_box"], "scanner_box", features.get("scanner_box", True), "No box setups in the cached prices."),
        "scanner_breakdown": gated(setup_frames.get("scanner_breakdown"), "scanner_breakdown", features.get("scanner_breakdown", True), "No breakdowns in the cached prices."),
        "scanner_volume": gated(setup_frames.get("scanner_volume"), "scanner_volume", features.get("scanner_volume", True), "No high-volume names in the cached prices."),
        "scanner_flag": gated(setup_frames["scanner_flag"], "scanner_flag", features.get("scanner_flag", True), "No flag setups in the cached prices."),
        "scanner_qullamaggie": gated(setup_frames.get("scanner_qullamaggie"), "scanner_qullamaggie", features.get("scanner_qullamaggie", True), "No Qullamaggie setups in the cached prices."),
        "scanner_marios": gated(setup_frames.get("scanner_marios"), "scanner_marios", features.get("scanner_marios", True), "No Marios setups in the cached prices."),
        "scanner_ep": gated(setup_frames.get("scanner_ep"), "scanner_ep", features.get("scanner_ep", True), "No episodic pivots in the cached prices. An EP needs a gap of 10% or more on at least 3 times normal volume."),
        "scanner_gap_up": gated(setup_frames.get("scanner_gap_up"), "scanner_gap_up", features.get("scanner_gap_up", True), "No holding gap ups in the last 21 trading days of cached prices."),
        "scanner_leaders": gated(setup_frames["scanner_leaders"], "scanner_leaders", features.get("scanner_leaders", True), "No leaders. A leader is a ready or just-broken VCP, a strict CANSLIM qualify, or both."),
        "scanner_52w": gated(setup_frames.get("scanner_52w"), "scanner_52w", features.get("scanner_52w", True), "No 52-week rows. The scan used cached prices only."),
        "highs_lows_history": gated(setup_frames.get("highs_lows_history"), "highs_lows_history", features.get("scanner_52w", True), "No 52-week history in the cached prices."),
        "buy_setups": gated(buy, "buy_setups", buy_on, "No buy setups. The list is built from the scanners already on the desk. This desk never places trades."),
        "trading_floor": gated(floor, "trading_floor", floor_on, "No picks to debate today. The Trading Floor reads Buy setups and the cross-scanner picks. Research only."),
        "options_ideas": gated(ideas, "options_ideas", opt_on, "No debit spreads. Education only. This desk never places a trade."),
        "options_skipped": gated(skipped_opt, "options_skipped", opt_on, "No names were skipped. Education only. This desk never places a trade."),
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
        "sector_rotation": gated(rot["sector_rotation"], "sector_rotation", features.get("sector_rotation", True), "No sector rotation. SPY or the sector ETFs were missing from the price cache."),
        "sector_rotation_tails": gated(rot["sector_rotation_tails"], "sector_rotation_tails", features.get("sector_rotation", True), "No relative-rotation tails."),
        "sector_rotation_history": gated(rot["sector_rotation_history"], "sector_rotation_history", features.get("sector_rotation", True), "No relative-rotation history."),
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

    partial_pages = []
    for name, df in files.items():
        if df is None or "data_status" not in getattr(df, "columns", []):
            continue
        if (df["data_status"].astype(str) == "PARTIAL").any():
            partial_pages.append(name)
    if partial_pages:
        log("Column check", "PARTIAL", "", "A column is blank on every row: " + ", ".join(partial_pages) + ". Blank is missing, not zero.")
    else:
        log("Column check", "OK", "", "No measured column is blank on every row.")
    files["updates_log"] = pd.DataFrame(LOG)

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
        "tabs": sorted(list(files) + (["paper_equity", "paper_summary", "paper_trades"] if paper_on else [])),
    }
    with open(os.path.join(data, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    # Market news reads market_today.csv and sectors.csv from disk, so it runs
    # after those files are written. Full and hourly fetch free RSS and the
    # Nasdaq calendar. Offline does not, so the test job stays offline. No Yahoo.
    mn_on = features.get("market_news", True)
    if not mn_on:
        log("Market news brief", "OK", "", "feature off. Research only. No broker.")
    else:
        try:
            import market_news.brief as market_news_brief
            now_et = pd.Timestamp.now(tz=ET).to_pydatetime()
            if mode == "full":
                mn_mode = "full"
            elif mode == "offline":
                mn_mode = "offline"
            else:
                mn_mode = "hourly"
            extra = {}
            if mn_mode == "offline":
                extra["fetch_calendar"] = lambda: {
                    "next": None,
                    "week": [],
                    "text": "Offline run. Calendar not fetched.",
                    "source": "offline",
                }
            brief = market_news_brief.publish(
                data_dir=data,
                cache_dir=cache,
                mode=mn_mode,
                now_et=now_et,
                **extra,
            )
            log(
                "Market news brief",
                "OK",
                brief.get("session", ""),
                "%s · mood %s · %d headlines" % (
                    brief.get("slot"),
                    (brief.get("mood") or {}).get("label"),
                    len(brief.get("headlines") or []),
                ),
            )
        except Exception as ex:
            log("Market news brief", "CACHED", "", "kept the last market_brief.json. %s" % ex)
    # rewrite updates log now that backtest and the rest have logged
    write_out(pd.DataFrame(LOG), "updates_log", data)
    print("wrote %d files to %s" % (len(files), data))
    return files


if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        sys.exit(result)
