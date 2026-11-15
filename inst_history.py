"""13F fund-holder history for the CANSLIM I check (free SEC data only).

Source: the SEC "Form 13F data sets" (structured ZIPs on sec.gov,
https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets). Each ZIP
holds every 13F filed in a date range (SUBMISSION, COVERPAGE and INFOTABLE tsv).

For every stock in universe.csv and every report quarter we store:
  holders  = how many distinct 13F filers (CIK) report a long share position
  shares   = total shares those filers report (put/call rows and principal
             amounts are left out)
in data/inst_13f_history.csv. CUSIPs are mapped to tickers with the free
OpenFIGI mapping API (no key, 25 requests a minute, 10 CUSIPs per request).
Every CUSIP that was looked up is kept in data/inst_13f_cusip_map.csv, so the
same CUSIP is never asked about twice.

Which filing counts for a filer and a quarter:
  - the newest original 13F-HR or "RESTATEMENT" amendment replaces earlier ones
  - "NEW HOLDINGS" amendments filed after it add their positions
  - 13F NOTICE filings have no holdings and are skipped
A quarter is complete when an ingested ZIP covers 45 days after quarter end
(the 13F deadline). Only complete quarters are used for the trend.

Manual run (one-time backfill or a catch-up), from the repo root:
    python inst_history.py --backfill 6        # last 6 quarterly ZIPs
    python inst_history.py --update            # newest ZIP if not ingested yet
The full desk run (stock_desk.py, full mode) also calls update_history() once a
day when features.inst_13f_history is on; it only downloads when the SEC has
published a ZIP that is not in the history yet (about once a quarter).
Raw ZIPs go to cache/bulk/13f/ and are never committed.
"""
import argparse
import io
import json
import os
import re
import sys
import time
import zipfile

import pandas as pd

LIST_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
SEC_BASE = "https://www.sec.gov"
FIGI_URL = "https://api.openfigi.com/v3/mapping"
HISTORY_FILE = "inst_13f_history.csv"
CUSIP_FILE = "inst_13f_cusip_map.csv"
SETS_FILE = "inst_13f_sets.json"
DEADLINE_DAYS = 45
HIST_COLS = ["ticker", "period", "holders", "shares", "cusips", "complete"]
MAP_COLS = ["cusip", "ticker", "name", "source"]

_MON = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


# ---------------------------------------------------------------- listing

def parse_listing(html):
    """ZIP links on the SEC data-set page, newest first: [(url, filename, start, end)].

    Handles both name styles: 01jun2026-31aug2026_form13f.zip and 2023q4_form13f.zip.
    start/end are pandas Timestamps of the filing-date range the ZIP covers.
    """
    out, seen = [], set()
    for href in re.findall(r'href="([^"]+_form13f\.zip)"', html or "", flags=re.I):
        name = href.rsplit("/", 1)[-1]
        if name in seen:
            continue
        rng = zip_range(name)
        if rng is None:
            continue
        seen.add(name)
        url = href if href.startswith("http") else SEC_BASE + href
        out.append((url, name, rng[0], rng[1]))
    out.sort(key=lambda r: r[3], reverse=True)
    return out


def zip_range(name):
    m = re.match(r"(\d{2})([a-z]{3})(\d{4})-(\d{2})([a-z]{3})(\d{4})_form13f\.zip$", name, re.I)
    if m:
        d1, m1, y1, d2, m2, y2 = m.groups()
        s = pd.Timestamp(int(y1), _MON[m1.upper()], int(d1))
        e = pd.Timestamp(int(y2), _MON[m2.upper()], int(d2))
        return s, e
    m = re.match(r"(\d{4})q([1-4])_form13f\.zip$", name, re.I)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        s = pd.Timestamp(y, 3 * q - 2, 1)
        e = s + pd.offsets.QuarterEnd(0)
        return s, e
    return None


def period_label(ts):
    ts = pd.Timestamp(ts)
    return "%dQ%d" % (ts.year, (ts.month - 1) // 3 + 1)


def period_end(label):
    y, q = int(label[:4]), int(label[-1])
    return pd.Timestamp(y, 3 * q, 1) + pd.offsets.MonthEnd(0)


def _sec_date(s):
    return pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")


# ---------------------------------------------------------------- parsing

def _read_tsv(zf, name, usecols, chunksize=None):
    member = [n for n in zf.namelist() if n.upper().endswith(name.upper())]
    if not member:
        raise ValueError("%s missing from zip" % name)
    return pd.read_csv(zf.open(member[0]), sep="\t", usecols=usecols, dtype=str,
                       keep_default_na=False, quoting=3, chunksize=chunksize,
                       on_bad_lines="skip", encoding_errors="replace")


def parse_zip(path_or_buf, chunksize=1_000_000, with_names=False):
    """One 13F data-set ZIP -> (filings, positions).

    filings: accession, cik, period (2026Q2), filing_date, kind
             (kind is "base" for 13F-HR or a RESTATEMENT amendment, "add" for a
             NEW HOLDINGS amendment)
    positions: accession, cusip (9 chars, upper), shares (long SH rows only)
    with_names=True also returns names: cusip, name (NAMEOFISSUER as filed), rows
    """
    with zipfile.ZipFile(path_or_buf) as zf:
        sub = _read_tsv(zf, "SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"])
        cov = _read_tsv(zf, "COVERPAGE.tsv", ["ACCESSION_NUMBER", "ISAMENDMENT", "AMENDMENTTYPE", "REPORTTYPE"])
        f = sub.merge(cov, on="ACCESSION_NUMBER", how="left").fillna("")
        f = f[f["SUBMISSIONTYPE"].str.upper().isin(["13F-HR", "13F-HR/A"])]
        f = f[~f["REPORTTYPE"].str.upper().str.contains("NOTICE")]
        amend = f["SUBMISSIONTYPE"].str.upper().eq("13F-HR/A") | f["ISAMENDMENT"].str.upper().isin(["Y", "TRUE", "1"])
        new_hold = f["AMENDMENTTYPE"].str.upper().str.contains("NEW HOLDINGS")
        kind = pd.Series("base", index=f.index)
        kind[amend & new_hold] = "add"
        per = _sec_date(f["PERIODOFREPORT"])
        filings = pd.DataFrame({
            "accession": f["ACCESSION_NUMBER"].str.strip(),
            "cik": f["CIK"].str.strip().str.lstrip("0"),
            "period": per.map(lambda x: period_label(x) if pd.notna(x) else ""),
            "filing_date": _sec_date(f["FILING_DATE"]),
            "kind": kind,
        })
        filings = filings[(filings["period"] != "") & filings["filing_date"].notna()].reset_index(drop=True)
        keep = set(filings["accession"])
        parts, nparts = [], []
        for ch in _read_tsv(zf, "INFOTABLE.tsv", ["ACCESSION_NUMBER", "NAMEOFISSUER", "CUSIP", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"], chunksize=chunksize):
            ch = ch[ch["ACCESSION_NUMBER"].isin(keep)]
            ch = ch[(ch["SSHPRNAMTTYPE"].str.strip().str.upper() == "SH") & (ch["PUTCALL"].str.strip() == "")]
            cus = ch["CUSIP"].str.strip().str.upper()
            ch = ch.assign(cusip=cus, shares=pd.to_numeric(ch["SSHPRNAMT"].str.replace(",", ""), errors="coerce").fillna(0.0))
            ch = ch[ch["cusip"].str.len() == 9]
            if with_names:
                nparts.append(ch.groupby(["cusip", "NAMEOFISSUER"]).size().rename("rows").reset_index())
            parts.append(ch.groupby(["ACCESSION_NUMBER", "cusip"], as_index=False)["shares"].sum())
        pos = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["ACCESSION_NUMBER", "cusip", "shares"])
        pos = pos.rename(columns={"ACCESSION_NUMBER": "accession"})
        pos = pos.groupby(["accession", "cusip"], as_index=False)["shares"].sum()
    if with_names:
        names = (pd.concat(nparts, ignore_index=True) if nparts else pd.DataFrame(columns=["cusip", "NAMEOFISSUER", "rows"]))
        names = names.rename(columns={"NAMEOFISSUER": "name"}).groupby(["cusip", "name"], as_index=False)["rows"].sum()
        return filings, pos, names
    return filings, pos


def pick_filings(filings):
    """Accessions that count for each (cik, period): newest base filing plus later NEW HOLDINGS adds."""
    if filings is None or len(filings) == 0:
        return filings.iloc[0:0] if filings is not None else pd.DataFrame()
    f = filings.sort_values(["filing_date", "accession"])
    base = f[f["kind"] == "base"].groupby(["cik", "period"], as_index=False).tail(1)
    adds = f[f["kind"] == "add"].merge(base[["cik", "period", "filing_date"]].rename(columns={"filing_date": "base_date"}),
                                       on=["cik", "period"], how="inner")
    adds = adds[adds["filing_date"] >= adds["base_date"]].drop(columns=["base_date"])
    return pd.concat([base, adds], ignore_index=True)


def cusip_counts(filings, positions):
    """Per (period, cusip): holders (distinct CIK) and total shares."""
    chosen = pick_filings(filings)
    if len(chosen) == 0 or len(positions) == 0:
        return pd.DataFrame(columns=["period", "cusip", "holders", "shares"])
    p = positions.merge(chosen[["accession", "cik", "period"]], on="accession", how="inner")
    p = p.groupby(["period", "cik", "cusip"], as_index=False)["shares"].sum()
    p = p[p["shares"] > 0]
    out = p.groupby(["period", "cusip"]).agg(holders=("cik", "nunique"), shares=("shares", "sum")).reset_index()
    return out


def ticker_history_from_positions(filings, positions, cusip_map, universe_tickers, complete_periods):
    """Roll positions up to universe tickers. A ticker with two CUSIPs in one quarter
    (a CUSIP change) counts each filer once (holders) and adds the shares."""
    chosen = pick_filings(filings)
    cols = HIST_COLS
    if len(chosen) == 0 or len(positions) == 0 or cusip_map is None or len(cusip_map) == 0:
        return pd.DataFrame(columns=cols)
    uni = {str(t).strip().upper() for t in universe_tickers}
    m = cusip_map[cusip_map["ticker"].astype(str).str.upper().isin(uni)][["cusip", "ticker"]]
    p = positions.merge(m, on="cusip", how="inner")
    p = p.merge(chosen[["accession", "cik", "period"]], on="accession", how="inner")
    p = p[p["shares"] > 0]
    if len(p) == 0:
        return pd.DataFrame(columns=cols)
    g = p.groupby(["ticker", "period"]).agg(
        holders=("cik", "nunique"), shares=("shares", "sum"), cusips=("cusip", lambda s: "|".join(sorted(set(s))))).reset_index()
    g["shares"] = g["shares"].round(0).astype("int64")
    g["complete"] = g["period"].isin(set(complete_periods)).map({True: "yes", False: "no"})
    return g[cols].sort_values(["ticker", "period"]).reset_index(drop=True)


def main_periods(set_ranges, periods):
    """Quarters whose first filing day (the day after quarter end) falls inside one of the ZIPs."""
    out = []
    for per in periods:
        day = period_end(per) + pd.Timedelta(days=1)
        if any(pd.Timestamp(s) <= day <= pd.Timestamp(e) for s, e in set_ranges):
            out.append(per)
    return out


def complete_periods(set_ranges, periods):
    """A period is complete when an ingested ZIP's filing range reaches 45 days after quarter end
    and the ZIPs together cover from quarter end to that deadline."""
    out = []
    spans = sorted((pd.Timestamp(s), pd.Timestamp(e)) for s, e in set_ranges)
    for per in periods:
        end = period_end(per)
        need_to = end + pd.Timedelta(days=DEADLINE_DAYS)
        cur = end + pd.Timedelta(days=1)
        for s, e in spans:
            if s <= cur <= e + pd.Timedelta(days=1):
                cur = max(cur, e + pd.Timedelta(days=1))
        if cur > need_to:
            out.append(per)
    return out


# ---------------------------------------------------------------- CUSIP map

US_EXCH = {"US", "UN", "UW", "UQ", "UA", "UR", "UF", "UV", "UP", "UD", "UT", "UX"}


def figi_ticker(rows):
    """Pick the US-listed ticker out of one OpenFIGI mapping result (foreign listings are skipped)."""
    best = None
    for r in rows or []:
        t = str(r.get("ticker") or "").strip()
        if not t or str(r.get("exchCode") or "") not in US_EXCH:
            continue
        st = str(r.get("securityType2") or r.get("securityType") or "")
        score = 2 if st in ("Common Stock", "Depositary Receipt", "Mutual Fund", "REIT") else 1
        if r.get("exchCode") == "US":
            score += 2
        if best is None or score > best[0]:
            best = (score, t.replace("/", "-").replace(" ", "-").upper(), str(r.get("name") or ""))
    return (best[1], best[2]) if best else ("", "")


def figi_job(cusip, exch="US"):
    """OpenFIGI job for one 9-character id. Non-US issuers (Accenture G1151C101, Chubb
    H1467J104) use CINS numbers, which start with a letter and need idType ID_CINS."""
    job = {"idType": "ID_CINS" if cusip[:1].isalpha() else "ID_CUSIP", "idValue": cusip}
    if exch:
        job["exchCode"] = exch
    return job


def map_cusips(cusips, requests_mod, known=None, sleep=time.sleep, per_minute=24, batch=10, log=print, max_cusips=None,
               exch="US", source="openfigi"):
    """Look up CUSIPs at OpenFIGI. Returns rows {cusip, ticker, name, source}.
    A CUSIP with no result is kept with a blank ticker so it is not asked again."""
    known = set(known or [])
    todo = [c for c in dict.fromkeys(cusips) if c not in known]
    if max_cusips is not None:
        todo = todo[: int(max_cusips)]
    out = []
    gap = 60.0 / per_minute
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        body = [figi_job(c, exch) for c in part]
        res = None
        for attempt in range(5):
            try:
                r = requests_mod.post(FIGI_URL, json=body, timeout=30, headers={"Content-Type": "application/json"})
            except Exception as exc:
                log("OpenFIGI error %s" % str(exc)[:80])
                sleep(gap * (attempt + 1))
                continue
            if r.status_code == 429:
                sleep(max(gap, 10.0) * (attempt + 1))
                continue
            if r.status_code != 200:
                log("OpenFIGI HTTP %s" % r.status_code)
                sleep(gap)
                continue
            res = r.json()
            break
        if res is None:
            log("OpenFIGI gave up on %d CUSIPs; they stay unmapped for now" % len(part))
            sleep(gap)
            continue
        for c, item in zip(part, res):
            t, n = figi_ticker((item or {}).get("data"))
            out.append({"cusip": c, "ticker": t, "name": n, "source": source})
        if (i // batch) % 25 == 0:
            log("OpenFIGI %d/%d" % (min(i + batch, len(todo)), len(todo)))
        sleep(gap)
    return out


_NAME_DROP = {"INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC", "NV", "SA", "AG", "SE", "LP",
              "HOLDINGS", "HOLDING", "HLDGS", "GROUP", "GRP", "THE", "NEW", "COM", "COMMON", "SHS", "SHARES", "STK",
              "STOCK", "ORD", "ORDINARY", "CL", "CLASS", "A", "PAR", "USD", "CHG", "INTL", "INTERNATIONAL", "DEL"}


_NAME_ABBR = {"INDS": "INDUSTRIES", "INDL": "INDUSTRIAL", "FINL": "FINANCIAL", "PPTYS": "PROPERTIES",
              "SVCS": "SERVICES", "TECHNOLOGIES": "TECH", "TECHNOLOGY": "TECH", "PHARMACEUTICALS": "PHARMACEUTICAL",
              "MGMT": "MANAGEMENT", "BANCORPORATION": "BANCORP", "COMMUNICATIONS": "COMMUNICATION", "COMM": "COMMUNICATION"}


def name_key(name):
    """Issuer name with punctuation, spacing and corporate words removed: 'Exxon Mobil Corp' and
    'EXXONMOBIL HOLDINGS CORP COM SHS' both give 'EXXONMOBIL'."""
    words = re.sub(r"[^A-Z0-9 ]", " ", str(name or "").upper()).split()
    return "".join(_NAME_ABBR.get(w, w) for w in words if w not in _NAME_DROP)


def company_fallback(counts, names, cmap, companies, min_holders=20):
    """Last resort for universe stocks with no mapped CUSIP at all: OpenFIGI sometimes
    answers a live US CUSIP with foreign listings only (ONEOK 682680103, Qorvo 74736K101).
    Tie the unmapped equity CUSIP whose most-filed 13F issuer name matches the universe
    company name (same name key, and no other universe company has that key); with two
    such CUSIPs the one with more holders wins. Returns rows with source "company name"."""
    if not companies or cmap is None or len(cmap) == 0 or counts is None or len(counts) == 0:
        return []
    have = set(cmap.loc[cmap["ticker"].fillna("") != "", "ticker"])
    key_to = {}
    for t, nm in companies.items():
        k = name_key(nm)
        if k:
            key_to.setdefault(k, set()).add(t)
    blank = set(cmap.loc[cmap["ticker"].fillna("") == "", "cusip"])
    keys, top = _name_index(names[names["cusip"].isin(blank)] if names is not None and len(names) else names)
    peak = counts.groupby("cusip")["holders"].max().to_dict()
    best = {}
    for c in blank:
        if peak.get(c, 0) < min_holders or not c[6:8].isdigit():
            continue
        k = (keys.get(c) or [""])[0]
        ts = key_to.get(k, set())
        if len(ts) != 1:
            continue
        t = next(iter(ts))
        if t in have:
            continue
        if t not in best or peak[c] > peak[best[t]]:
            best[t] = c
    return [{"cusip": c, "ticker": t, "name": str(top.get(c, "")) + " (company name)", "source": "company name"}
            for t, c in sorted(best.items())]


def _name_index(names):
    """{cusip: [name keys, most-filed first]} and {cusip: most-filed name as written}."""
    if names is None or len(names) == 0:
        return {}, {}
    n = names.assign(key=names["name"].map(name_key))
    k = n.groupby(["cusip", "key"], as_index=False)["rows"].sum().sort_values(["cusip", "rows"], ascending=[True, False])
    keys = {c: [x for x in g["key"] if x] for c, g in k.groupby("cusip")}
    top = n.sort_values("rows", ascending=False).drop_duplicates("cusip").set_index("cusip")["name"].to_dict()
    return keys, top


def continuity_map(counts, names, cmap, universe_tickers, min_holders=20, max_overlap=2, min_share=0.25):
    """Tie retired CUSIPs to a universe ticker. OpenFIGI does not map a CUSIP once it is
    retired (Exxon's 30231G102, Honeywell's 438516106, Carnival's 143658300), but many
    filers keep reporting it, so without this the holder count would collapse or jump.

    An unmapped CUSIP (blank ticker, at least min_holders filers in some quarter) is tied
    to a ticker when exactly one universe ticker has a mapped CUSIP with the same 6-char
    issuer code (7th and 8th characters digits, so equity, not debt), or, failing that,
    exactly one has the same issuer name key. It is skipped when both CUSIPs had
    min_holders filers in more than max_overlap of the same quarters (two live securities,
    not a renumbering), when the 7th and 8th characters are not digits (debt, not stock),
    or when its peak holder count is under min_share of the ticker's own peak (units,
    notes and other small side issues). Returns rows {cusip, ticker, name, source="continuity"}.
    """
    if cmap is None or len(cmap) == 0 or counts is None or len(counts) == 0:
        return []
    uni = {str(t).upper() for t in universe_tickers}
    # Anchors are OpenFIGI answers only, so one tie never leads to another.
    mapped = cmap[(cmap["ticker"].fillna("") != "") & cmap["ticker"].isin(uni) & (cmap["source"] != "continuity")]
    blank = cmap[(cmap["ticker"].fillna("") == "")]["cusip"].tolist()
    if not len(mapped) or not blank:
        return []
    live = counts[counts["holders"] >= min_holders]
    live_periods = live.groupby("cusip")["period"].apply(set).to_dict()
    peak = counts.groupby("cusip")["holders"].max().to_dict()
    keys, top = _name_index(names)
    by_prefix, by_key, tick_cusips = {}, {}, {}
    for c, t in zip(mapped["cusip"], mapped["ticker"]):
        tick_cusips.setdefault(t, set()).add(c)
        by_prefix.setdefault(c[:6], set()).add(t)
        for k in keys.get(c, [])[:1]:
            by_key.setdefault(k, set()).add(t)
    out = []
    for c in blank:
        if c not in live_periods or not c[6:8].isdigit():
            continue
        cand = by_prefix.get(c[:6], set())
        how = "issuer code"
        if len(cand) != 1:
            hits = set()
            for k in keys.get(c, [])[:1]:
                hits |= by_key.get(k, set())
            cand, how = hits, "issuer name"
        if len(cand) != 1:
            continue
        t = next(iter(cand))
        mine = live_periods[c]
        theirs = set().union(*[live_periods.get(x, set()) for x in tick_cusips[t]])
        if len(mine & theirs) > max_overlap:
            continue
        if peak.get(c, 0) < min_share * max(peak.get(x, 0) for x in tick_cusips[t]):
            continue
        out.append({"cusip": c, "ticker": t, "name": str(top.get(c, "")) + " (" + how + ")",
                    "source": "continuity"})
    return out


# ---------------------------------------------------------------- files

def load_sets(data_dir):
    path = os.path.join(data_dir, SETS_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_sets(data_dir, sets):
    with open(os.path.join(data_dir, SETS_FILE), "w") as fh:
        json.dump(sets, fh, indent=1, sort_keys=True)


def load_history(data_dir):
    path = os.path.join(data_dir, HISTORY_FILE)
    if not os.path.exists(path):
        return pd.DataFrame(columns=HIST_COLS)
    df = pd.read_csv(path, dtype={"ticker": str, "period": str, "cusips": str, "complete": str})
    return df


def load_cusip_map(data_dir):
    path = os.path.join(data_dir, CUSIP_FILE)
    if not os.path.exists(path):
        return pd.DataFrame(columns=MAP_COLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


# ---------------------------------------------------------------- trend for CANSLIM I

def holder_count_trend(history, ticker, tolerance_pct=2.0, max_jump_pct=50.0):
    """Fund-holder count trend over the newest two complete quarters.

    Returns (trend, info). trend is "up", "flat", "down" or "" when not verified
    (fewer than two complete quarters on file, the two are not back to back, or the
    count moved more than max_jump_pct percent either way, which is almost always a
    CUSIP change: a retired CUSIP that OpenFIGI no longer maps, as with Carnival in
    2026, rather than funds really piling in or out). info["reason"] says which.
    A drop no bigger than tolerance_pct percent counts as flat.
    """
    info = {}
    if history is None or len(history) == 0:
        return "", info
    sub = history[(history["ticker"] == ticker)]
    if "complete" in sub.columns:
        sub = sub[sub["complete"].astype(str) == "yes"]
    if len(sub) < 2:
        return "", {"reason": "quarters"}
    sub = sub.sort_values("period")
    a, b = sub.iloc[-2], sub.iloc[-1]
    prev_end = period_end(str(b["period"])) - pd.offsets.QuarterEnd(1)
    if period_label(prev_end) != str(a["period"]):
        return "", {"reason": "quarters"}
    h0, h1 = float(a["holders"]), float(b["holders"])
    if h0 <= 0:
        return "", {"reason": "quarters"}
    chg = (h1 - h0) / h0 * 100.0
    info = {"reason": "","period_old": str(a["period"]), "period_new": str(b["period"]), "holders_old": int(h0), "holders_new": int(h1),
            "change_pct": chg, "shares_old": a.get("shares"), "shares_new": b.get("shares")}
    if max_jump_pct is not None and abs(chg) > float(max_jump_pct):
        info["reason"] = "jump"
        return "", info
    if h1 > h0:
        return "up", info
    if chg >= -abs(float(tolerance_pct)):
        return "flat", info
    return "down", info


# ---------------------------------------------------------------- driver

def _get(requests_mod, url, ua, stream=False, timeout=120):
    return requests_mod.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=timeout, stream=stream)


def download_zip(requests_mod, url, dest, ua, sleep=time.sleep):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    r = _get(requests_mod, url, ua, stream=True, timeout=600)
    r.raise_for_status()
    with open(tmp, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
    os.replace(tmp, dest)
    sleep(1.0)  # SEC asks for at most 10 requests a second; we stay far below
    return dest


def _companies(data_dir, universe_tickers):
    path = os.path.join(data_dir, "universe.csv")
    if not os.path.exists(path):
        return {}
    u = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "company" not in u.columns:
        return {}
    want = {str(t).upper() for t in universe_tickers}
    return {t: c for t, c in zip(u["ticker"], u["company"]) if t in want}


def build(zip_paths, universe_tickers, data_dir, requests_mod=None, min_holders=20, log=print, map_limit=None):
    """Parse ZIPs, map new CUSIPs, and write the history files. Returns a stats dict."""
    fl, ps, ranges, names, nms = [], [], [], [], []
    for path in zip_paths:
        t0 = time.time()
        f, p, nm = parse_zip(path, with_names=True)
        nms.append(nm)
        fl.append(f)
        ps.append(p)
        rng = zip_range(os.path.basename(path))
        ranges.append(rng)
        names.append(os.path.basename(path))
        log("parsed %s: %d filings, %d positions, %.0fs" % (os.path.basename(path), len(f), len(p), time.time() - t0))
    filings = pd.concat(fl, ignore_index=True)
    positions = pd.concat(ps, ignore_index=True).groupby(["accession", "cusip"], as_index=False)["shares"].sum()
    counts = cusip_counts(filings, positions)
    periods = sorted(counts["period"].unique())
    sets = load_sets(data_dir)
    all_ranges = list(ranges) + [(pd.Timestamp(v["start"]), pd.Timestamp(v["end"])) for v in sets.values()]
    done = complete_periods(all_ranges, periods)
    # Only quarters whose main filing window (the day after quarter end) is inside one of
    # these ZIPs are written; a few late filers for older quarters are not a full count.
    keep = main_periods(ranges, periods)
    cmap = load_cusip_map(data_dir)
    known = set(cmap["cusip"]) if len(cmap) else set()
    # Map every CUSIP that some quarter shows with at least min_holders filers.
    cand = counts[counts["period"].isin(keep) & (counts["holders"] >= min_holders)]
    cand = cand.sort_values("holders", ascending=False)["cusip"].drop_duplicates().tolist()
    if requests_mod is not None:
        new = map_cusips(cand, requests_mod, known=known, log=log, max_cusips=map_limit)
        # Second pass for CUSIPs with no US ticker yet: CINS ids and any exchange, keeping
        # only US listings. Each CUSIP gets this second look once (source openfigi2).
        tried = pd.concat([cmap, pd.DataFrame(new, columns=MAP_COLS)], ignore_index=True).drop_duplicates("cusip", keep="last")
        blank = tried[(tried["ticker"].fillna("") == "") & (tried["source"] == "openfigi")]["cusip"]
        # (continuity rows are re-checked on every build, below)
        blank = [c for c in cand if c in set(blank)]
        if blank:
            log("OpenFIGI second pass for %d CUSIPs" % len(blank))
            new = new + map_cusips(blank, requests_mod, known=set(), log=log, exch=None, source="openfigi2")
        if new:
            cmap = pd.concat([cmap, pd.DataFrame(new)], ignore_index=True).drop_duplicates("cusip", keep="last")
    all_names = pd.concat(nms, ignore_index=True).groupby(["cusip", "name"], as_index=False)["rows"].sum()
    cont = continuity_map(counts[counts["period"].isin(keep)], all_names, cmap, universe_tickers, min_holders=min_holders)
    if cont:
        log("continuity: %d retired CUSIPs tied to a ticker" % len(cont))
        cmap = pd.concat([cmap, pd.DataFrame(cont)], ignore_index=True).drop_duplicates("cusip", keep="last")
    companies = _companies(data_dir, universe_tickers)
    byname = company_fallback(counts[counts["period"].isin(keep)], all_names, cmap, companies, min_holders=min_holders)
    if byname:
        log("company name: %d CUSIPs tied to a ticker" % len(byname))
        cmap = pd.concat([cmap, pd.DataFrame(byname)], ignore_index=True).drop_duplicates("cusip", keep="last")
    if len(cmap):
        cmap = cmap.sort_values("cusip").reset_index(drop=True)
        cmap[MAP_COLS].to_csv(os.path.join(data_dir, CUSIP_FILE), index=False)
    hist = ticker_history_from_positions(filings[filings["period"].isin(keep)], positions, cmap, universe_tickers, done)
    old = load_history(data_dir)
    if len(old):
        # Older quarters may have turned complete now that a later ZIP is in.
        old["complete"] = old["period"].isin(set(complete_periods(all_ranges, old["period"].unique()))).map({True: "yes", False: "no"})
        old = old[~old["period"].isin(set(hist["period"]))]
        hist = pd.concat([old, hist], ignore_index=True).sort_values(["ticker", "period"]).reset_index(drop=True)
    hist[HIST_COLS].to_csv(os.path.join(data_dir, HISTORY_FILE), index=False)
    for n, rng in zip(names, ranges):
        sets[n] = {"start": str(rng[0].date()), "end": str(rng[1].date()), "ingested": time.strftime("%Y-%m-%d")}
    save_sets(data_dir, sets)
    return {"periods": keep, "complete": done, "cusips_checked": len(cmap), "rows": len(hist)}


def needed_zips(listing, sets, quarters, force=False):
    """ZIPs to read, oldest first. A backfill (force) takes the newest `quarters` ZIPs (each
    ZIP covers about one quarter of filing dates). A normal update takes the newest ZIP plus
    the one before it, so late filers for the previous quarter are counted too, and keeps
    the older quarters already in the history."""
    n = int(quarters) if force else 2
    return list(reversed(listing[:n]))


def update_history(cfg, root, requests_mod, universe_tickers, log=print, force=False, quarters=6):
    """Download the newest SEC 13F ZIP if it is not ingested yet, and rebuild the history.

    Returns a short status string. Never raises: a failure keeps the files as they are.
    """
    data_dir = os.path.join(root, "data")
    raw_dir = os.path.join(root, "cache", "bulk", "13f")
    ua = ((cfg or {}).get("rate_limits") or {}).get("sec_user_agent") or "NickStockDesk research nicks-stock-desk@example.com"
    try:
        html = _get(requests_mod, LIST_URL, ua, timeout=60).text
        listing = parse_listing(html)
        if not listing:
            return "no 13F ZIP links found on the SEC page"
        sets = load_sets(data_dir)
        if not force and listing[0][1] in sets:
            return "13F history is current (%s)" % listing[0][1]
        want = needed_zips(listing, sets, quarters, force=force)
        paths = []
        for url, name, _s, _e in want:
            log("SEC 13F ZIP %s" % name)
            paths.append(download_zip(requests_mod, url, os.path.join(raw_dir, name), ua))
        st = build(paths, universe_tickers, data_dir, requests_mod=requests_mod, log=log)
        return "13F history rebuilt: quarters %s, complete %s" % (",".join(st["periods"]), ",".join(st["complete"]))
    except Exception as exc:
        return "13F history update failed, kept the old files: %s" % str(exc)[:200]


def main(argv=None):
    import requests
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill", type=int, default=0, help="rebuild from the newest N quarterly ZIPs")
    ap.add_argument("--update", action="store_true", help="ingest the newest ZIP if it is new")
    ap.add_argument("--zips", nargs="*", help="build from ZIP files already on disk")
    a = ap.parse_args(argv)
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(root, "config.json")))
    uni = pd.read_csv(os.path.join(root, "data", "universe.csv"), dtype=str)["ticker"].tolist()
    if a.zips:
        print(build(sorted(a.zips, key=lambda p: zip_range(os.path.basename(p))[1]), uni, os.path.join(root, "data"), requests_mod=requests))
        return 0
    n = a.backfill or 6
    print(update_history(cfg, root, requests, uni, force=bool(a.backfill), quarters=n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
