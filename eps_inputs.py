"""EPS history for the EPS Rating, filled from free SEC data the desk already has.

The plain statement parser (fundamentals.parse_companyfacts) keeps one EPS tag
per company and only facts the SEC stamped with a CY frame. About half the desk
then had no EPS Rating. This module rebuilds a per-quarter and per-year EPS
history from the same companyfacts JSON (the nightly companyfacts.zip the desk
already downloads, or the per-company fallback). No new provider.

What it fills that the plain parser misses:
  1. More EPS tags, tried per period, not one tag for the whole company
     (IncomeLossFromContinuingOperationsPerDilutedShare, EarningsPerShareBasicAndDiluted,
     IFRS DilutedEarningsLossPerShare and friends). Diluted first, then basic.
  2. Periods with no CY frame. Every fact is keyed by its own start and end date.
  3. Fiscal Q4. A 10-K has the full year, not the 3-month Q4, so
     Q4 = full year - 9-month year to date (or - Q1 - Q2 - Q3). Same for a missing
     Q2 or Q3 from the 6- and 9-month year-to-date numbers. Labeled "derived".
  4. No EPS tag at all for a period: net income / diluted weighted shares for
     that same period. Labeled "ni_shares".
  5. Stock splits. When a later filing restates an older period by a clean split
     ratio (2:1, 4:1, 10:1, 1:10 ...), older values that were never restated are
     scaled by that ratio, so a 5-year growth rate is not broken by a split.

Labels follow the SEC frame rule: a period is named by the calendar quarter or
year its midpoint falls in (CY2026Q3, CY2025), so it plugs straight into the
EPS Rating code. Missing stays missing, never zero.

Two extra quarterly sources for companies the SEC has no quarters for (most
foreign 20-F and 40-F filers): the Yahoo earnings history the desk already
saved (cache/earnings.csv, no new download) and a small saved history of the
Nasdaq earnings-surprise page (4 quarters a page, kept and grown run by run).
They are used only when the SEC has no usable recent quarter, and a company's
quarters always come from one source so a year-over-year change never mixes them.
"""
import math
import re

import numpy as np
import pandas as pd

EPS_TAGS_DILUTED = [
    "EarningsPerShareDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
    "EarningsPerShareBasicAndDiluted",
    "IncomeLossFromContinuingOperationsPerBasicAndDilutedShare",
    "DilutedEarningsLossPerShare",
    "DilutedEarningsPerShare",
    "BasicAndDilutedEarningsLossPerShare",
    "DilutedEarningsLossPerShareFromContinuingOperations",
]
EPS_TAGS_BASIC = [
    "EarningsPerShareBasic",
    "IncomeLossFromContinuingOperationsPerBasicShare",
    "BasicEarningsLossPerShare",
    "BasicEarningsPerShare",
    "BasicEarningsLossPerShareFromContinuingOperations",
]
EPS_TAGS = EPS_TAGS_DILUTED + EPS_TAGS_BASIC
NI_TAGS = [
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "NetIncomeLoss",
    "ProfitLossAttributableToOwnersOfParent",
    "ProfitLoss",
]
SHARE_TAGS = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageShares",
    "AdjustedWeightedAverageShares",
]
FORMS = ("10-K", "10-Q", "20-F", "40-F", "6-K", "10-KT", "10-QT")

Q_DAYS = (75, 110)
H_DAYS = (165, 200)
N_DAYS = (255, 290)
A_DAYS = (350, 380)

SPLIT_RATIOS = [2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 40, 50, 1.5, 2.5]
COLUMNS = ["ticker", "frame", "kind", "eps", "start", "end", "filed", "source"]


def _ts(text):
    try:
        return pd.Timestamp(str(text)[:10])
    except Exception:
        return None


def label_for(start, end, annual):
    """SEC style label from the period midpoint: CY2026Q3 or CY2026."""
    s, e = _ts(start), _ts(end)
    if s is None or e is None:
        return ""
    if annual:
        # By the end date, not the midpoint: a June year end sits right on a
        # midpoint boundary. Ends from Jan 1 to Jan 15 belong to the year before.
        return "CY%d" % (e - pd.Timedelta(days=15)).year
    mid = s + (e - s) / 2
    return "CY%dQ%d" % (mid.year, (mid.month - 1) // 3 + 1)


def _days(start, end):
    s, e = _ts(start), _ts(end)
    if s is None or e is None:
        return None
    return (e - s).days + 1


def _ok_form(form):
    form = str(form or "")
    return any(form.startswith(f) for f in FORMS)


def _per_share_units(units):
    """EPS units are '<currency>/shares'. Prefer USD, else the first currency."""
    keys = [k for k in (units or {}) if str(k).endswith("/shares")]
    if not keys:
        return []
    keys.sort(key=lambda k: (k != "USD/shares", k))
    return units.get(keys[0]) or []


def _money_units(units):
    keys = [k for k in (units or {}) if "/" not in str(k) and str(k) not in ("shares", "pure")]
    if not keys:
        return []
    keys.sort(key=lambda k: (k != "USD", k))
    return units.get(keys[0]) or []


def _facts(payload):
    facts = (payload or {}).get("facts") or {}
    us = facts.get("us-gaap") or {}
    ifrs = facts.get("ifrs-full") or {}
    return us, ifrs


def _concept(us, ifrs, name):
    return us.get(name) or ifrs.get(name)


def _rows_by_period(rows):
    """{(start, end): [rows]} for duration facts in allowed forms."""
    out = {}
    for row in rows or []:
        if not row.get("start") or not row.get("end") or row.get("val") is None:
            continue
        if not _ok_form(row.get("form")):
            continue
        try:
            val = float(row["val"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(val):
            continue
        key = (str(row["start"])[:10], str(row["end"])[:10])
        out.setdefault(key, []).append({"val": val, "filed": str(row.get("filed") or ""), "accn": str(row.get("accn") or "")})
    return out


def _clean_ratio(r):
    """The split ratio r is close to, or None."""
    if r is None or not math.isfinite(r) or r <= 0:
        return None
    for k in SPLIT_RATIOS:
        for cand in (float(k), 1.0 / float(k)):
            if abs(r / cand - 1.0) <= 0.03:
                return cand
    return None


def split_events(eps_periods):
    """[(filed_date, factor)] from periods a later filing restated by a clean split ratio.

    factor multiplies a value filed before filed_date to put it on today's share count.
    """
    found = {}
    for key, rows in eps_periods.items():
        rows = sorted(rows, key=lambda x: x["filed"])
        for a, b in zip(rows, rows[1:]):
            if a["val"] == 0 or b["filed"] <= a["filed"]:
                continue
            if (a["val"] > 0) != (b["val"] > 0):
                continue
            f = _clean_ratio(b["val"] / a["val"])
            if f is None or f == 1.0:
                continue
            found.setdefault((b["filed"][:7], round(f, 4)), []).append(b["filed"])
    events = []
    for (_month, f), dates in found.items():
        if len(dates) < 2:
            continue  # one restated period could be a real restatement, not a split
        events.append((min(dates), f))
    events.sort()
    merged = []
    for d, f in events:
        if merged and merged[-1][1] == f and (_ts(d) - _ts(merged[-1][0])).days <= 120:
            continue
        merged.append((d, f))
    return merged


def _adjust(val, filed, events):
    out = val
    for d, f in events:
        if filed < d:
            out *= f
    return out


def _pick(period_rows, events):
    """Latest filing for a period, split adjusted."""
    best = max(period_rows, key=lambda x: x["filed"])
    return _adjust(best["val"], best["filed"], events), best["filed"]


def eps_periods(payload):
    """{(start, end): (eps, filed, source)} from EPS tags, then net income / shares."""
    us, ifrs = _facts(payload)
    merged = {}
    raw_all = {}
    for name in EPS_TAGS:
        concept = _concept(us, ifrs, name)
        if not concept:
            continue
        got = _rows_by_period(_per_share_units(concept.get("units")))
        for key, rows in got.items():
            raw_all.setdefault(key, []).extend(rows)
            if key not in merged:
                merged[key] = (rows, "sec")
    events = split_events(raw_all)
    out = {}
    for key, (rows, src) in merged.items():
        val, filed = _pick(rows, events)
        out[key] = (val, filed, src)
    # Net income / diluted weighted shares for periods with no EPS tag.
    ni, sh = {}, {}
    for name in NI_TAGS:
        concept = _concept(us, ifrs, name)
        if concept:
            for key, rows in _rows_by_period(_money_units(concept.get("units"))).items():
                ni.setdefault(key, rows)
    for name in SHARE_TAGS:
        concept = _concept(us, ifrs, name)
        if concept:
            for key, rows in _rows_by_period((concept.get("units") or {}).get("shares")).items():
                sh.setdefault(key, rows)
    for key in set(ni) & set(sh):
        if key in out:
            continue
        n = max(ni[key], key=lambda x: x["filed"])
        s = max(sh[key], key=lambda x: x["filed"])
        if s["val"] <= 0:
            continue
        # Shares from a pre-split filing are scaled the other way.
        shares = s["val"] / _adjust(1.0, s["filed"], events) if events else s["val"]
        out[key] = (n["val"] / shares, max(n["filed"], s["filed"]), "ni_shares")
    # Last resort: net income / the shares outstanding on the cover of the same filing.
    cover = {}
    dei = ((payload or {}).get("facts") or {}).get("dei") or {}
    for row in ((dei.get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}).get("shares") or []:
        try:
            v = float(row.get("val"))
        except (TypeError, ValueError):
            continue
        if v > 0 and row.get("accn"):
            cover[str(row["accn"])] = cover.get(str(row["accn"]), 0.0) + v  # classes add up
    if cover:
        for key, rows in ni.items():
            if key in out:
                continue
            n = max(rows, key=lambda x: x["filed"])
            shares = cover.get(n.get("accn", ""))
            if shares:
                out[key] = (n["val"] / shares, n["filed"], "ni_cover_shares")
    return out


def _between(days, lo_hi):
    return days is not None and lo_hi[0] <= days <= lo_hi[1]


def _near(a, b, tol=6):
    ta, tb = _ts(a), _ts(b)
    return ta is not None and tb is not None and abs((ta - tb).days) <= tol


def build_history(periods, derive=True):
    """Quarter and year rows [(frame, kind, eps, start, end, filed, source)] from eps_periods output."""
    quarters, years, halves, nines = {}, {}, {}, {}
    for (start, end), (val, filed, src) in periods.items():
        d = _days(start, end)
        item = {"start": start, "end": end, "eps": val, "filed": filed, "source": src}
        if _between(d, Q_DAYS):
            quarters[end] = item
        elif _between(d, A_DAYS):
            years[end] = item
        elif _between(d, H_DAYS):
            halves[(start, end)] = item
        elif _between(d, N_DAYS):
            nines[(start, end)] = item
    if derive:
        for end, fy in years.items():
            fs = fy["start"]
            inside = sorted((q for q in quarters.values() if _ts(q["end"]) <= _ts(end) and _ts(q["start"]) >= _ts(fs) - pd.Timedelta(days=6)),
                            key=lambda q: q["end"])
            q_by_n = {}
            for q in inside:
                n = int(round(((_ts(q["end"]) - _ts(fs)).days + 1) / 91.3))
                if 1 <= n <= 4:
                    q_by_n[n] = q
            ytd6 = next((h for (s, e), h in halves.items() if _near(s, fs)), None)
            ytd9 = next((h for (s, e), h in nines.items() if _near(s, fs)), None)
            filed = fy["filed"]

            def add(n, start, stop, val, parts):
                if n in q_by_n or val is None or not math.isfinite(val):
                    return
                if not _between(_days(start, stop), Q_DAYS):
                    return
                f = max([filed] + [p["filed"] for p in parts])
                item = {"start": start, "end": stop, "eps": val, "filed": f, "source": "derived"}
                quarters.setdefault(stop, item)
                q_by_n[n] = item

            def next_day(text):
                return (_ts(text) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

            if 2 not in q_by_n and ytd6 is not None and 1 in q_by_n:
                add(2, next_day(q_by_n[1]["end"]), ytd6["end"], ytd6["eps"] - q_by_n[1]["eps"], [ytd6, q_by_n[1]])
            if 3 not in q_by_n and ytd9 is not None and ytd6 is not None:
                add(3, next_day(ytd6["end"]), ytd9["end"], ytd9["eps"] - ytd6["eps"], [ytd9, ytd6])
            if 4 not in q_by_n:
                if ytd9 is not None:
                    add(4, next_day(ytd9["end"]), end, fy["eps"] - ytd9["eps"], [ytd9])
                elif all(k in q_by_n for k in (1, 2, 3)):
                    add(4, next_day(q_by_n[3]["end"]), end, fy["eps"] - sum(q_by_n[k]["eps"] for k in (1, 2, 3)),
                        [q_by_n[k] for k in (1, 2, 3)])
    rows = []
    for kind, bucket in (("Q", quarters), ("A", years)):
        by_label = {}
        for end, item in bucket.items():
            label = label_for(item["start"], item["end"], kind == "A")
            prev = by_label.get(label)
            # Two periods with one label: the later end wins, a real tag beats a derived one.
            rank = (item["source"] != "derived", item["end"])
            if prev is None or rank > (prev["source"] != "derived", prev["end"]):
                by_label[label] = item
        for label, item in by_label.items():
            rows.append((label, kind, round(float(item["eps"]), 6), item["start"], item["end"], item["filed"], item["source"]))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows


def parse_eps_history(payload, ticker="", derive=True):
    """One company's EPS history as a DataFrame with COLUMNS."""
    try:
        rows = build_history(eps_periods(payload), derive=derive)
    except Exception:
        rows = []
    df = pd.DataFrame(rows, columns=COLUMNS[1:])
    df.insert(0, "ticker", ticker)
    return df


# ---------------------------------------------------------------- other quarterly sources
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def nasdaq_quarter_label(text):
    """'Sep 2026' (a fiscal quarter end month) -> CY2026Q3 by the quarter midpoint."""
    m = re.match(r"^\s*([A-Za-z]{3})[a-z]*[\s/]+(\d{4})\s*$", str(text or ""))
    if not m or m.group(1).lower() not in _MONTHS:
        return ""
    end = pd.Timestamp(int(m.group(2)), _MONTHS[m.group(1).lower()], 1) + pd.offsets.MonthEnd(0)
    return label_for((end - pd.Timedelta(days=90)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), False)


def parse_nasdaq_surprise(payload, ticker):
    """Rows from api.nasdaq.com/api/company/<sym>/earnings-surprise (up to 4 quarters)."""
    out = []
    try:
        rows = (((payload or {}).get("data") or {}).get("earningsSurpriseTable") or {}).get("rows") or []
    except AttributeError:
        rows = []
    for row in rows:
        label = nasdaq_quarter_label(row.get("fiscalQtrEnd"))
        try:
            eps = float(str(row.get("eps")).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        if not label or not math.isfinite(eps):
            continue
        out.append({"ticker": ticker, "frame": label, "kind": "Q", "eps": eps, "start": "", "end": "",
                    "filed": str(row.get("dateReported") or ""), "source": "nasdaq"})
    return pd.DataFrame(out, columns=COLUMNS)


def merge_saved(old, fresh, source):
    """Keep every saved quarter, let a fresh page replace the same ticker and quarter."""
    frames = [f for f in (old, fresh) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    df["source"] = source
    df = df.drop_duplicates(subset=["ticker", "frame"], keep="last")
    return df[COLUMNS].sort_values(["ticker", "frame"]).reset_index(drop=True)


def yahoo_quarters(earnings):
    """Quarter rows from the saved Yahoo earnings history (cache/earnings.csv). No download.

    The report date is mapped to the last calendar quarter that ended at least 10
    days before it, which is the quarter being reported for nearly every company.
    """
    if earnings is None or len(earnings) == 0 or "eps_actual" not in earnings.columns:
        return pd.DataFrame(columns=COLUMNS)
    out = []
    for t, dt, eps in zip(earnings["ticker"].astype(str), earnings["earnings_dt"], pd.to_numeric(earnings["eps_actual"], errors="coerce")):
        if not np.isfinite(eps):
            continue
        d = _ts(dt)
        if d is None:
            continue
        ref = (d - pd.Timedelta(days=10)).normalize()
        if ref.tz is not None:
            ref = ref.tz_localize(None)
        if ref.is_quarter_end:
            qend = ref
        else:
            qend = pd.Timestamp(ref.year, ((ref.month - 1) // 3) * 3 + 1, 1) - pd.Timedelta(days=1)
        label = "CY%dQ%d" % (qend.year, (qend.month - 1) // 3 + 1)
        out.append({"ticker": t, "frame": label, "kind": "Q", "eps": float(eps), "start": "",
                    "end": qend.strftime("%Y-%m-%d"), "filed": d.strftime("%Y-%m-%d"), "source": "yahoo"})
    df = pd.DataFrame(out, columns=COLUMNS)
    return df.sort_values("filed").drop_duplicates(subset=["ticker", "frame"], keep="last")


def _quarter_index(label):
    m = re.match(r"^CY(\d{4})Q([1-4])$", str(label))
    return int(m.group(1)) * 4 + int(m.group(2)) - 1 if m else None


def usable_quarters(rows, asof, max_age_quarters=3):
    """True when a ticker's quarters have a recent latest quarter and its year-ago quarter."""
    if rows is None or len(rows) == 0:
        return False
    idx = [i for i in (_quarter_index(f) for f in rows["frame"]) if i is not None]
    if not idx:
        return False
    latest = max(idx)
    now = _quarter_index("CY%dQ%d" % (asof.year, (asof.month - 1) // 3 + 1))
    return (now - latest) <= max_age_quarters and (latest - 4) in set(idx)


def combine(sec, extra_sources, asof=None, max_age_quarters=3):
    """SEC history first. Another source's quarters replace a ticker's SEC quarters
    only when the SEC ones are missing or stale and the other source is usable."""
    asof = pd.Timestamp(asof) if asof is not None else pd.Timestamp.today()
    sec = sec if sec is not None and len(sec) else pd.DataFrame(columns=COLUMNS)
    sec_q = sec[sec["kind"] == "Q"]
    by_t = {t: g for t, g in sec_q.groupby("ticker")}
    keep = [sec]
    replaced = {}
    for src in extra_sources:
        if src is None or len(src) == 0:
            continue
        for t, g in src.groupby("ticker"):
            if t in replaced or usable_quarters(by_t.get(t), asof, max_age_quarters):
                continue
            if not usable_quarters(g, asof, max_age_quarters):
                continue
            replaced[t] = str(g["source"].iloc[0])
            keep.append(g)
    out = pd.concat([k for k in keep if len(k)], ignore_index=True) if any(len(k) for k in keep) else pd.DataFrame(columns=COLUMNS)
    if replaced and len(out):
        drop = out["ticker"].isin(list(replaced)) & (out["kind"] == "Q") & (out["source"].isin(["sec", "derived", "ni_shares"]))
        out = out[~drop]
    return out.reset_index(drop=True), replaced


def as_rating_frames(history):
    """(quarters_df, annual_df) with ticker, frame, eps for ms_screens.eps_ratings."""
    if history is None or len(history) == 0:
        empty = pd.DataFrame(columns=["ticker", "frame", "eps"])
        return empty, empty
    h = history.copy()
    h["eps"] = pd.to_numeric(h["eps"], errors="coerce")
    q = h[h["kind"] == "Q"][["ticker", "frame", "eps"]].reset_index(drop=True)
    a = h[h["kind"] == "A"][["ticker", "frame", "eps"]].reset_index(drop=True)
    return q, a


def add_plain_rows(eq, ea, quarters, annual, tickers):
    """Add the plain parser's CY-framed EPS rows for tickers the history does not have."""
    have = set(eq["ticker"].astype(str)) | set(ea["ticker"].astype(str))
    missing = set(str(t) for t in tickers) - have
    if not missing:
        return eq, ea
    out = []
    for frame_df, base, pat in ((quarters, eq, r"^CY\d{4}Q[1-4]$"), (annual, ea, r"^CY\d{4}$")):
        add = None
        if frame_df is not None and len(frame_df) and {"ticker", "frame", "eps"} <= set(frame_df.columns):
            sub = frame_df[frame_df["ticker"].astype(str).isin(missing) & frame_df["frame"].astype(str).str.match(pat)]
            add = sub[["ticker", "frame", "eps"]]
        out.append(pd.concat([base, add], ignore_index=True) if add is not None and len(add) else base)
    return out[0], out[1]
