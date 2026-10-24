"""Parse SEC company-facts JSON into annual and quarterly statements.

Filings become usable the day after the SEC `filed` date so a same-day signal
cannot see a report that may have landed after the close.
Missing concepts stay missing. They are never filled with zero.
"""
import re
import numpy as np
import pandas as pd

ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")
QUARTER_FORMS = ANNUAL_FORMS + ("10-Q", "10-Q/A")
ANNUAL_FRAME = re.compile(r"^CY\d{4}$")
QUARTER_FRAME = re.compile(r"^CY\d{4}Q[1-4]$")

REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues",
    "RevenuesNetOfInterestExpense",
    "RegulatedAndUnregulatedOperatingRevenue",
]
# Later tags fill a year the earlier tag left blank. NetIncomeLoss is still preferred.
NI_CONCEPTS = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
    "IncomeLossFromContinuingOperations",
    "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
]
EPS_CONCEPTS = ["EarningsPerShareDiluted"]
GP_CONCEPTS = ["GrossProfit"]
OI_CONCEPTS = ["OperatingIncomeLoss"]
EQUITY_CONCEPTS = ["StockholdersEquity"]
DEBT_NC = ["LongTermDebtNoncurrent"]
DEBT_CUR = ["LongTermDebtCurrent", "DebtCurrent"]
DEBT_LT = ["LongTermDebt"]
OCF_CONCEPTS = ["NetCashProvidedByUsedInOperatingActivities"]
CAPEX_CONCEPTS = ["PaymentsToAcquirePropertyPlantAndEquipment"]
DPS_CONCEPTS = ["CommonStockDividendsPerShareDeclared"]
SHARES_FLOW = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
SHARES_INSTANT = ["CommonStockSharesOutstanding"]


def _duration(row):
    if not row.get("start") or not row.get("end"):
        return None
    return (pd.Timestamp(row["end"]) - pd.Timestamp(row["start"])).days


def _ok_form(form, allowed_prefixes):
    form = form or ""
    return any(form.startswith(p) for p in allowed_prefixes)


def _units(gaap, names):
    for name in names:
        concept = gaap.get(name)
        if not concept:
            continue
        units = concept.get("units") or {}
        for key in ("USD", "USD/shares", "shares", "pure"):
            if units.get(key):
                return units[key], name
        if units:
            key = next(iter(units))
            return units[key], name
    return [], None


def _select(rows, frame_re, dur_lo, dur_hi, flow, forms):
    best = {}
    for row in rows:
        frame = row.get("frame") or ""
        if not frame_re.fullmatch(frame):
            continue
        if not _ok_form(row.get("form"), forms):
            continue
        dur = _duration(row)
        if flow:
            if dur is None or dur < dur_lo or dur > dur_hi:
                continue
        else:
            if dur is not None and dur > 5:
                continue
        prev = best.get(frame)
        if prev is None or str(row.get("filed") or "") >= str(prev.get("filed") or ""):
            best[frame] = row
    return best


def _series(gaap, names, frame_re, dur_lo, dur_hi, flow, forms):
    rows, used = _units(gaap, names)
    if not rows:
        return {}, None
    picked = _select(rows, frame_re, dur_lo, dur_hi, flow, forms)
    out = {}
    for frame, row in picked.items():
        out[frame] = {
            "val": row.get("val"),
            "end": row.get("end"),
            "filed": row.get("filed"),
            "concept": used,
        }
    return out, used


def _series_fallback(gaap, names, frame_re, dur_lo, dur_hi, flow, forms):
    """Prefer the first concept. Later concepts fill only the frames it missed."""
    merged = {}
    used = None
    for name in names:
        got, tag = _series(gaap, [name], frame_re, dur_lo, dur_hi, flow, forms)
        if not got:
            continue
        if used is None:
            used = tag
        for frame, item in got.items():
            if frame not in merged:
                merged[frame] = item
    return merged, used


def _first_with_rows(gaap, concept_groups, frame_re, dur_lo, dur_hi, flow, forms, minimum):
    for names in concept_groups:
        got, used = _series(gaap, names, frame_re, dur_lo, dur_hi, flow, forms)
        if len(got) >= minimum:
            return got, used
    return {}, None


def _merge_frames(maps, flow_keys, instant_keys):
    frames = set()
    for m in maps.values():
        frames.update(m)
    rows = []
    for frame in sorted(frames):
        rec = {"frame": frame}
        filed = None
        end = None
        for key, mp in maps.items():
            item = mp.get(frame)
            if not item:
                rec[key] = np.nan
                continue
            rec[key] = item["val"]
            filed = item["filed"] or filed
            end = item["end"] or end
        rec["filed"] = filed
        rec["end"] = end
        rows.append(rec)
    return pd.DataFrame(rows)


def _debt_map(gaap, frame_re, forms, flow):
    """Add current and long-term pieces when both exist. Do not invent zero."""
    nc, _ = _series(gaap, DEBT_NC, frame_re, 0, 0, False, forms)
    cur, _ = _series(gaap, DEBT_CUR, frame_re, 0, 0, False, forms)
    lt, _ = _series(gaap, DEBT_LT, frame_re, 0, 0, False, forms)
    frames = set(nc) | set(cur) | set(lt)
    out = {}
    for frame in frames:
        if frame in nc and frame in cur:
            val = float(nc[frame]["val"]) + float(cur[frame]["val"])
            src = nc[frame]
        elif frame in lt:
            val = lt[frame]["val"]
            src = lt[frame]
        elif frame in nc:
            val = nc[frame]["val"]
            src = nc[frame]
        else:
            continue
        out[frame] = {"val": val, "end": src["end"], "filed": src["filed"], "concept": "debt"}
    return out


def _instant_by_end(gaap, names, forms):
    """Balance-sheet facts keyed by period end.

    Companyfacts often stores equity and debt with no CY#### frame, or with an
    instant frame such as CY2024Q3I. Matching the income-statement row is by
    the period end date. A flow (a start date more than a few days before the
    end) is not a balance-sheet stock and is ignored. The latest filing wins.
    """
    rows, used = _units(gaap, names)
    best = {}
    for row in rows:
        if not _ok_form(row.get("form"), forms):
            continue
        dur = _duration(row)
        frame = row.get("frame") or ""
        if not (dur is None or dur <= 5 or str(frame).endswith("I")):
            continue
        end = str(row.get("end") or "")[:10]
        if len(end) < 10:
            continue
        prev = best.get(end)
        if prev is None or str(row.get("filed") or "") >= str(prev.get("filed") or ""):
            best[end] = row
    out = {}
    for end, row in best.items():
        out[end] = {"val": row.get("val"), "end": row.get("end"), "filed": row.get("filed"), "concept": used}
    return out


def _debt_by_end(gaap, forms):
    """Same debt rule as _debt_map, keyed by period end instead of a CY frame."""
    nc = _instant_by_end(gaap, DEBT_NC, forms)
    cur = _instant_by_end(gaap, DEBT_CUR, forms)
    lt = _instant_by_end(gaap, DEBT_LT, forms)
    ends = set(nc) | set(cur) | set(lt)
    out = {}
    for end in ends:
        if end in nc and end in cur:
            val = float(nc[end]["val"]) + float(cur[end]["val"])
            src = nc[end]
        elif end in lt:
            val = lt[end]["val"]
            src = lt[end]
        elif end in nc:
            val = nc[end]["val"]
            src = nc[end]
        else:
            continue
        out[end] = {"val": val, "end": src["end"], "filed": src["filed"], "concept": "debt"}
    return out


def _attach_by_end(df, by_end, column):
    """Fill a blank balance-sheet column from facts that share the row's period end.

    A value already taken from a CY frame is kept. Missing stays missing.
    """
    if df is None or len(df) == 0 or not by_end or "end" not in df.columns:
        return df
    df = df.copy()
    if column not in df.columns:
        df[column] = np.nan
    ends = df["end"].astype(str).str[:10]
    for i, end in ends.items():
        item = by_end.get(end)
        if not item:
            continue
        if pd.isna(df.at[i, column]):
            df.at[i, column] = item["val"]
    return df


def _unframed_one(gaap, names, forms, dur_lo, dur_hi):
    """One annual flow concept with no CY#### frame, keyed by period end.

    Companyfacts often leaves `frame` null on a 10-K. Those facts are still
    the fiscal year when fp is FY, the form is an annual report, and the
    period is about 365 days. The latest filing wins.
    """
    rows, used = _units(gaap, names)
    best = {}
    for row in rows:
        frame = row.get("frame") or ""
        if ANNUAL_FRAME.fullmatch(frame):
            continue
        if not _ok_form(row.get("form"), forms):
            continue
        if (row.get("fp") or "") != "FY":
            continue
        dur = _duration(row)
        if dur is None or dur < dur_lo or dur > dur_hi:
            continue
        end = str(row.get("end") or "")[:10]
        if len(end) < 10:
            continue
        prev = best.get(end)
        if prev is None or str(row.get("filed") or "") >= str(prev.get("filed") or ""):
            best[end] = {
                "val": row.get("val"),
                "end": row.get("end"),
                "filed": row.get("filed"),
                "concept": used,
                "fy": row.get("fy"),
            }
    return best


def _unframed_fallback(gaap, names, forms, dur_lo=350, dur_hi=380):
    """First concept wins. Later concepts fill only the period ends it missed."""
    merged = {}
    for name in names:
        got = _unframed_one(gaap, [name], forms, dur_lo, dur_hi)
        for end, item in got.items():
            if end not in merged:
                merged[end] = item
    return merged


def _apply_unframed_flows(df, maps):
    """Attach unframed annual flows by period end.

    A CY row for that end keeps its values. Blank columns are filled. An end
    with no CY row becomes its own row, labeled FY{year}.
    """
    if not maps or not any(maps.values()):
        return df if df is not None else pd.DataFrame()
    if df is None or len(df) == 0:
        df = pd.DataFrame(columns=["frame", "end", "filed"])
    else:
        df = df.copy()
    existing = {}
    if "end" in df.columns:
        for i, end in df["end"].astype(str).str[:10].items():
            existing.setdefault(end, []).append(i)
    for col, by_end in maps.items():
        if col not in df.columns:
            df[col] = np.nan
        for end, idxs in existing.items():
            item = by_end.get(end)
            if not item:
                continue
            for i in idxs:
                if pd.isna(df.at[i, col]):
                    df.at[i, col] = item["val"]
    new_rows = []
    ends = set()
    for by_end in maps.values():
        ends.update(by_end)
    for end in sorted(ends):
        if end in existing:
            continue
        rec = {col: np.nan for col in maps}
        rec["frame"] = "FY" + end[:4]
        rec["end"] = end
        rec["filed"] = None
        for col, by_end in maps.items():
            item = by_end.get(end)
            if not item:
                continue
            rec[col] = item["val"]
            rec["filed"] = item.get("filed") or rec["filed"]
            rec["end"] = item.get("end") or end
            fy = item.get("fy")
            try:
                if fy is not None and str(fy).strip() != "":
                    rec["frame"] = "FY" + str(int(float(fy)))
            except (TypeError, ValueError):
                pass
        new_rows.append(rec)
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    return df


def parse_companyfacts(payload):
    """Return (annual_df, quarter_df) for one company. Empty frames if nothing usable."""
    facts = (payload or {}).get("facts") or {}
    gaap = facts.get("us-gaap") or facts.get("ifrs-full") or {}
    empty = pd.DataFrame()
    if not gaap:
        return empty, empty

    annual_specs = {
        "revenue": [REVENUE_CONCEPTS],
        "net_income": [NI_CONCEPTS],
        "eps": [EPS_CONCEPTS],
        "gross_profit": [GP_CONCEPTS],
        "op_income": [OI_CONCEPTS],
        "ocf": [OCF_CONCEPTS],
        "capex": [CAPEX_CONCEPTS],
        "dps": [DPS_CONCEPTS],
        "shares": [SHARES_FLOW, SHARES_INSTANT],
    }
    annual_forms = ("10-K", "20-F", "40-F")
    amaps = {}
    for key, groups in annual_specs.items():
        if key == "net_income":
            amaps[key], _ = _series_fallback(gaap, NI_CONCEPTS, ANNUAL_FRAME, 300, 380, True, annual_forms)
            continue
        amaps[key], _ = _first_with_rows(gaap, groups, ANNUAL_FRAME, 300, 380, True, annual_forms, 1)
    # shares and equity and debt are instant (a stock, not a flow)
    shares_i, _ = _first_with_rows(gaap, [SHARES_INSTANT], ANNUAL_FRAME, 0, 0, False, ("10-K", "20-F", "40-F"), 1)
    if shares_i and not amaps.get("shares"):
        amaps["shares"] = shares_i
    equity, _ = _first_with_rows(gaap, [EQUITY_CONCEPTS], ANNUAL_FRAME, 0, 0, False, ("10-K", "20-F", "40-F"), 1)
    amaps["equity"] = equity
    amaps["debt"] = _debt_map(gaap, ANNUAL_FRAME, ("10-K", "20-F", "40-F"), False)
    annual = _merge_frames(amaps, [], [])
    # Real filings usually omit the CY#### frame on the balance sheet. Attach by period end.
    annual = _attach_by_end(annual, _instant_by_end(gaap, EQUITY_CONCEPTS, annual_forms), "equity")
    annual = _attach_by_end(annual, _debt_by_end(gaap, annual_forms), "debt")
    # The same filings often omit the CY#### frame on the income statement.
    # Keep those fiscal years. A framed value for the same period end still wins.
    flow_names = {
        "revenue": REVENUE_CONCEPTS,
        "net_income": NI_CONCEPTS,
        "eps": EPS_CONCEPTS,
        "gross_profit": GP_CONCEPTS,
        "op_income": OI_CONCEPTS,
        "ocf": OCF_CONCEPTS,
        "capex": CAPEX_CONCEPTS,
        "dps": DPS_CONCEPTS,
        "shares": SHARES_FLOW,
    }
    unframed = {key: _unframed_fallback(gaap, names, annual_forms) for key, names in flow_names.items()}
    annual = _apply_unframed_flows(annual, unframed)

    qmaps = {}
    q_flow = {
        "revenue": [REVENUE_CONCEPTS],
        "net_income": [NI_CONCEPTS],
        "eps": [EPS_CONCEPTS],
        "ocf": [OCF_CONCEPTS],
        "capex": [CAPEX_CONCEPTS],
        "dps": [DPS_CONCEPTS],
    }
    quarter_forms = ("10-Q", "10-K", "20-F", "40-F")
    for key, groups in q_flow.items():
        if key == "net_income":
            qmaps[key], _ = _series_fallback(gaap, NI_CONCEPTS, QUARTER_FRAME, 75, 110, True, quarter_forms)
            continue
        qmaps[key], _ = _first_with_rows(gaap, groups, QUARTER_FRAME, 75, 110, True, quarter_forms, 1)
    qmaps["equity"], _ = _first_with_rows(gaap, [EQUITY_CONCEPTS], QUARTER_FRAME, 0, 0, False, ("10-Q", "10-K", "20-F", "40-F"), 1)
    qmaps["debt"] = _debt_map(gaap, QUARTER_FRAME, ("10-Q", "10-K", "20-F", "40-F"), False)
    qmaps["shares"], _ = _first_with_rows(gaap, [SHARES_INSTANT, SHARES_FLOW], QUARTER_FRAME, 75, 110, True, ("10-Q", "10-K", "20-F", "40-F"), 1)
    if not qmaps["shares"]:
        qmaps["shares"], _ = _first_with_rows(gaap, [SHARES_INSTANT], QUARTER_FRAME, 0, 0, False, ("10-Q", "10-K", "20-F", "40-F"), 1)
    quarters = _merge_frames(qmaps, [], [])
    quarters = _attach_by_end(quarters, _instant_by_end(gaap, EQUITY_CONCEPTS, quarter_forms), "equity")
    quarters = _attach_by_end(quarters, _debt_by_end(gaap, quarter_forms), "debt")
    return annual, quarters


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(x):
        return np.nan
    return x


def _price_on_or_after(closes, day):
    if closes is None or len(closes) == 0 or day is None or pd.isna(day):
        return np.nan
    idx = closes.index
    i = idx.searchsorted(pd.Timestamp(day))
    if i >= len(idx):
        return np.nan
    val = closes.iloc[i]
    return float(val) if pd.notna(val) else np.nan


_SPLIT_FACTORS = (2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50)


def _near_split(ratio):
    """Nearest common split, or None when the share-count jump is not one."""
    import math
    if ratio is None or not np.isfinite(ratio) or ratio < 1.7:
        return None
    best = min(_SPLIT_FACTORS, key=lambda f: abs(math.log(ratio / f)))
    if abs(math.log(ratio / best)) > math.log(1.12):
        return None
    return int(best)


def _split_factor_for_ticker(shares_rows):
    """Vote a split factor from share-count jumps on overlapping filings.

    A later 10-K often restates shares after a split. Older rows stay on the
    pre-split count. Prices in the cache are already split-adjusted, so the
    per-share figures have to be scaled by that same ratio. Buybacks move the
    count a few percent and do not match a whole split.
    """
    obs = []
    for end, filed, shares in shares_rows:
        sh = _num(shares)
        if not np.isfinite(sh) or sh <= 0:
            continue
        end_ts = pd.to_datetime(end, errors="coerce")
        filed_ts = pd.to_datetime(filed, errors="coerce")
        if pd.isna(end_ts):
            continue
        obs.append((end_ts, filed_ts, float(sh)))
    if len(obs) < 2:
        return None
    votes = {}
    for i, (end_a, filed_a, sh_a) in enumerate(obs):
        for end_b, filed_b, sh_b in obs[i + 1:]:
            if abs((end_a - end_b).days) > 800:
                continue
            big, small = (sh_b, sh_a) if sh_b > sh_a else (sh_a, sh_b)
            factor = _near_split(big / small)
            if not factor:
                continue
            # The larger count should be the one filed later, or on a later period.
            later_is_big = False
            if sh_b > sh_a:
                later_is_big = (pd.notna(filed_b) and pd.notna(filed_a) and filed_b >= filed_a) or end_b >= end_a
            else:
                later_is_big = (pd.notna(filed_a) and pd.notna(filed_b) and filed_a >= filed_b) or end_a >= end_b
            if not later_is_big:
                continue
            votes[factor] = votes.get(factor, 0) + 1
    if not votes:
        return None
    factor = max(votes, key=lambda f: (votes[f], f))
    if votes[factor] < 1:
        return None
    return factor


def _apply_factor(df, factor, pre_mask, cols):
    if df is None or len(df) == 0 or not factor or not pre_mask.any():
        return df
    out = df
    for col in cols:
        if col not in out.columns:
            continue
        vals = pd.to_numeric(out[col], errors="coerce")
        if col == "shares":
            out.loc[pre_mask, col] = vals[pre_mask] * factor
        else:
            out.loc[pre_mask, col] = vals[pre_mask] / factor
    return out


def _normalize_share_units(frame):
    """Put share counts on a raw-share basis.

    A few filers switch the shares tag to millions (McDonald's 2021+ is 716.4
    next to a 2020 count of 750,100,000). That is the same share count, not a
    reverse split. Values under one million that land on the larger cluster
    after multiplying by one million are scaled. A real count such as NVR's
    2.8 million is left alone.
    """
    if frame is None or len(frame) == 0 or "shares" not in frame.columns or "ticker" not in frame.columns:
        return frame
    out = frame
    grouped = out.groupby(out["ticker"].astype(str)).groups
    for _ticker, idx in grouped.items():
        sh = pd.to_numeric(out.loc[idx, "shares"], errors="coerce")
        vals = sh[sh > 0]
        if len(vals) == 0:
            continue
        big = vals[vals >= 1_000_000]
        if len(big):
            med = float(big.median())
            if med <= 0:
                continue
            close = (sh > 0) & (sh < 1_000_000) & ((sh * 1_000_000 - med).abs() / med <= 0.35)
            if close.any():
                out.loc[close[close].index, "shares"] = sh[close] * 1_000_000
        elif float(vals.median()) < 100_000:
            small = (sh > 0) & (sh < 1_000_000)
            out.loc[small[small].index, "shares"] = sh[small] * 1_000_000
    return out


def adjust_pershare_for_splits(annual, quarters):
    """Scale pre-split EPS, dividends and share counts onto the adjusted-price basis.

    The price cache is already split-adjusted. SEC per-share facts are not, until
    a filing after the split restates them. Rows still on the old count are divided
    (EPS, DPS) or multiplied (shares) by the split. A ratio under 1 or over 500,
    and a yield over 15%, is dropped later by the sanity guard.
    """
    annual = annual.copy() if annual is not None and len(annual) else pd.DataFrame()
    quarters = quarters.copy() if quarters is not None and len(quarters) else pd.DataFrame()
    annual = _normalize_share_units(annual)
    quarters = _normalize_share_units(quarters)
    if (len(annual) == 0 and len(quarters) == 0) or "ticker" not in (annual.columns if len(annual) else quarters.columns):
        return annual, quarters
    tickers = set()
    if len(annual) and "ticker" in annual.columns:
        tickers.update(annual["ticker"].astype(str))
    if len(quarters) and "ticker" in quarters.columns:
        tickers.update(quarters["ticker"].astype(str))
    for ticker in tickers:
        rows = []
        for frame in (annual, quarters):
            if len(frame) == 0 or "ticker" not in frame.columns or "shares" not in frame.columns:
                continue
            sub = frame[frame["ticker"].astype(str) == ticker]
            for _, r in sub.iterrows():
                rows.append((r.get("end"), r.get("filed"), r.get("shares")))
        factor = _split_factor_for_ticker(rows)
        if not factor:
            continue
        dated = []
        for end, _filed, shares in rows:
            sh = _num(shares)
            end_ts = pd.to_datetime(end, errors="coerce")
            if np.isfinite(sh) and sh > 0 and pd.notna(end_ts):
                dated.append((end_ts, float(sh)))
        if len(dated) < 2:
            continue
        sizes = sorted(sh for _end, sh in dated)
        cut = max(range(len(sizes) - 1), key=lambda i: sizes[i + 1] / sizes[i])
        if sizes[cut + 1] / sizes[cut] < 1.7:
            continue
        post = float(np.median(sizes[cut + 1:]))
        # The bigger share count has to be the newer one. A reverse split, or an
        # old un-restated count, leaves the latest year on the smaller number.
        small_ends = [end for end, sh in dated if sh < post / 1.8]
        large_ends = [end for end, sh in dated if sh >= post / 1.8]
        if not small_ends or not large_ends:
            continue
        if pd.Series(large_ends).median() <= pd.Series(small_ends).median():
            continue
        newest = max(dated, key=lambda item: item[0])
        if newest[1] < post / 1.8:
            continue
        def _pre_mask(frame):
            if len(frame) == 0 or "ticker" not in frame.columns or "shares" not in frame.columns:
                return pd.Series(False, index=frame.index)
            sh = pd.to_numeric(frame["shares"], errors="coerce")
            mine = frame["ticker"].astype(str) == ticker
            scaled = sh * factor
            return mine & sh.notna() & (sh > 0) & (scaled / post).between(0.45, 2.2) & (sh < post / 1.8)
        annual = _apply_factor(annual, factor, _pre_mask(annual), ("eps", "dps", "shares"))
        quarters = _apply_factor(quarters, factor, _pre_mask(quarters), ("eps", "dps", "shares"))
    return annual, quarters


def guard_multiple(value, lo=1.0, hi=500.0):
    """Drop a P/E that is still on the wrong split basis. Missing stays missing."""
    x = _num(value)
    if not np.isfinite(x) or x < lo or x > hi:
        return None
    return float(x)


def guard_yield(value, hi=0.15):
    """Drop a yield above 15%. A split-mismatched dividend prints in that range."""
    x = _num(value)
    if not np.isfinite(x) or x < 0 or x > hi:
        return None
    return float(x)


def prepare_annual(annual, closes):
    """One row per fiscal year with historical multiples and the prior 3-year averages.

    Averages use shift(1), so the current year is not included in its own baseline.
    """
    if annual is None or len(annual) == 0:
        return pd.DataFrame()
    df = annual.copy()
    df["filed"] = pd.to_datetime(df["filed"], errors="coerce")
    df["fy_end"] = pd.to_datetime(df["end"], errors="coerce")
    df = df.dropna(subset=["filed", "fy_end"]).sort_values(["fy_end", "filed"])
    df = df.drop_duplicates("fy_end", keep="last")
    for col in ("revenue", "net_income", "eps", "gross_profit", "op_income", "equity", "debt", "ocf", "capex", "dps", "shares"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = df[col].map(_num)
    # No dividend tag at all means the company did not report one. That is a real zero.
    # A missing year next to years that did report a dividend is also treated as zero for that year.
    if df["dps"].notna().any():
        df["dps"] = df["dps"].fillna(0.0)
    else:
        df["dps"] = 0.0
    df["fcf"] = df["ocf"] - df["capex"]
    df.loc[df["ocf"].isna() | df["capex"].isna(), "fcf"] = np.nan
    df["known_on"] = df["filed"] + pd.Timedelta(days=1)
    df["hist_px"] = df["known_on"].map(lambda d: _price_on_or_after(closes, d))
    df["pe"] = df["hist_px"] / df["eps"]
    df.loc[df["eps"] <= 0, "pe"] = np.nan
    # A P/E under 1, or over 500, is a split mismatch (pre-split EPS, post-split price).
    df.loc[(df["pe"] < 1) | (df["pe"] > 500), "pe"] = np.nan
    mcap = df["hist_px"] * df["shares"]
    df["ps"] = mcap / df["revenue"]
    df.loc[(df["revenue"] <= 0) | df["shares"].isna(), "ps"] = np.nan
    df["pfcf"] = mcap / df["fcf"]
    df.loc[(df["fcf"] <= 0) | df["shares"].isna(), "pfcf"] = np.nan
    df["de"] = df["debt"] / df["equity"]
    df.loc[df["equity"] <= 0, "de"] = np.nan
    df["roe"] = df["net_income"] / df["equity"]
    df.loc[df["equity"] <= 0, "roe"] = np.nan
    prev_rev = df["revenue"].shift(1)
    prev_eps = df["eps"].shift(1)
    df["rev_g"] = df["revenue"] / prev_rev - 1
    df.loc[prev_rev <= 0, "rev_g"] = np.nan
    df["eps_g"] = df["eps"] / prev_eps - 1
    df.loc[prev_eps <= 0, "eps_g"] = np.nan
    df["div_y"] = df["dps"] / df["hist_px"]
    df.loc[df["hist_px"] <= 0, "div_y"] = np.nan
    df.loc[(df["div_y"] < 0) | (df["div_y"] > 0.15), "div_y"] = np.nan
    for col in ("pe", "ps", "pfcf", "de", "rev_g", "eps_g", "roe", "div_y"):
        df[col + "_avg"] = df[col].shift(1).rolling(3, min_periods=2).mean()
    df["avg_years"] = df["revenue"].shift(1).rolling(3, min_periods=1).count()
    return df.reset_index(drop=True)


def latest_ttm(quarters, asof):
    """Sum of the last four quarterly flows known on or before asof. None if the span looks wrong."""
    if quarters is None or len(quarters) == 0:
        return None
    q = quarters.copy()
    q["filed"] = pd.to_datetime(q["filed"], errors="coerce")
    q["period_end"] = pd.to_datetime(q["end"], errors="coerce")
    q = q.dropna(subset=["filed", "period_end"])
    q["known_on"] = q["filed"] + pd.Timedelta(days=1)
    q = q[q["known_on"] <= pd.Timestamp(asof)].sort_values("period_end")
    if len(q) < 4:
        return None
    last = q.tail(4)
    span = (last["period_end"].iloc[-1] - last["period_end"].iloc[0]).days
    if span < 200 or span > 400:
        return None
    out = {"period_end": last["period_end"].iloc[-1], "filed": last["filed"].max()}
    for col in ("revenue", "net_income", "eps", "ocf", "capex"):
        if col not in last.columns:
            out[col] = np.nan
            continue
        vals = pd.to_numeric(last[col], errors="coerce")
        out[col] = float(vals.sum()) if vals.notna().all() else np.nan
    if np.isfinite(out["ocf"]) and np.isfinite(out["capex"]):
        out["fcf"] = out["ocf"] - out["capex"]
    else:
        out["fcf"] = np.nan
    for col in ("equity", "debt", "shares"):
        if col in last.columns:
            out[col] = _num(last[col].iloc[-1])
        else:
            out[col] = np.nan
    if len(q) >= 8:
        prev = q.iloc[-8:-4]
        prev_rev = pd.to_numeric(prev["revenue"], errors="coerce") if "revenue" in prev else None
        prev_eps = pd.to_numeric(prev["eps"], errors="coerce") if "eps" in prev else None
        if prev_rev is not None and prev_rev.notna().all() and prev_rev.sum() > 0 and np.isfinite(out["revenue"]):
            out["rev_g"] = out["revenue"] / float(prev_rev.sum()) - 1
        if prev_eps is not None and prev_eps.notna().all() and prev_eps.sum() > 0 and np.isfinite(out["eps"]):
            out["eps_g"] = out["eps"] / float(prev_eps.sum()) - 1
    if not np.isfinite(out.get("revenue", np.nan)) or out["revenue"] <= 0:
        return None
    return out


def _sane_multiple(x, hi):
    if x is None or not np.isfinite(x) or x <= 0 or x > hi:
        return None
    return float(x)


def _sane_ratio(x, lo, hi):
    if x is None or not np.isfinite(x) or x < lo or x > hi:
        return None
    return float(x)


def metrics_asof(prep, asof, price, quarters=None):
    """Point-in-time fundamental snapshot. Uses only rows with known_on <= asof."""
    blank = {
        "basis": None, "filed": None, "fy_end": None, "avg_years": 0,
        "ttm_pe": None, "ps": None, "de": None, "pfcf": None,
        "rev_growth": None, "eps_growth": None, "roe": None, "div_yield": None,
        "ttm_pe_avg": None, "ps_avg": None, "de_avg": None, "pfcf_avg": None,
        "rev_growth_avg": None, "eps_growth_avg": None, "roe_avg": None, "div_yield_avg": None,
        "eps": None, "revenue": None, "fcf": None, "shares": None, "dps": None,
        "gross_profit": None, "op_income": None, "net_income": None, "equity": None, "debt": None,
        "fcf_per_share": None,
    }
    if prep is None or len(prep) == 0 or asof is None:
        return blank
    known = prep[prep["known_on"] <= pd.Timestamp(asof)]
    if known.empty:
        return blank
    row = known.iloc[-1]
    eps = _num(row.get("eps"))
    revenue = _num(row.get("revenue"))
    fcf = _num(row.get("fcf"))
    shares = _num(row.get("shares"))
    equity = _num(row.get("equity"))
    debt = _num(row.get("debt"))
    dps = _num(row.get("dps"))
    net_income = _num(row.get("net_income"))
    rev_g = _num(row.get("rev_g"))
    eps_g = _num(row.get("eps_g"))
    roe = _num(row.get("roe"))
    basis = "latest annual report"
    filed = row.get("filed")
    fy_end = row.get("fy_end")
    ttm = latest_ttm(quarters, asof) if quarters is not None else None
    if ttm is not None and pd.Timestamp(ttm["period_end"]) > pd.Timestamp(fy_end):
        basis = "trailing four quarters"
        filed = ttm["filed"]
        if np.isfinite(ttm.get("eps", np.nan)):
            eps = ttm["eps"]
        if np.isfinite(ttm.get("revenue", np.nan)):
            revenue = ttm["revenue"]
        if np.isfinite(ttm.get("fcf", np.nan)):
            fcf = ttm["fcf"]
        if np.isfinite(ttm.get("net_income", np.nan)):
            net_income = ttm["net_income"]
        if np.isfinite(ttm.get("equity", np.nan)):
            equity = ttm["equity"]
        if np.isfinite(ttm.get("debt", np.nan)):
            debt = ttm["debt"]
        if np.isfinite(ttm.get("shares", np.nan)):
            shares = ttm["shares"]
        if "rev_g" in ttm:
            rev_g = ttm["rev_g"]
        if "eps_g" in ttm:
            eps_g = ttm["eps_g"]
        if np.isfinite(net_income) and np.isfinite(equity) and equity > 0:
            roe = net_income / equity
        fy_end = ttm["period_end"]
    price = _num(price)
    mcap = price * shares if np.isfinite(price) and np.isfinite(shares) else np.nan
    pe = price / eps if np.isfinite(price) and np.isfinite(eps) and eps > 0 else np.nan
    ps = mcap / revenue if np.isfinite(mcap) and np.isfinite(revenue) and revenue > 0 else np.nan
    pfcf = mcap / fcf if np.isfinite(mcap) and np.isfinite(fcf) and fcf > 0 else np.nan
    de = debt / equity if np.isfinite(debt) and np.isfinite(equity) and equity > 0 else np.nan
    div_y = dps / price if np.isfinite(dps) and np.isfinite(price) and price > 0 else np.nan
    fcf_ps = fcf / shares if np.isfinite(fcf) and np.isfinite(shares) and shares > 0 else np.nan
    out = dict(blank)
    out.update({
        "basis": basis,
        "filed": None if pd.isna(filed) else str(pd.Timestamp(filed).date()),
        "fy_end": None if pd.isna(fy_end) else str(pd.Timestamp(fy_end).date()),
        "avg_years": int(row["avg_years"]) if pd.notna(row.get("avg_years")) else 0,
        "ttm_pe": guard_multiple(pe),
        "ps": _sane_multiple(ps, 500),
        "pfcf": _sane_multiple(pfcf, 2000),
        "de": _sane_ratio(de, 0, 50),
        "rev_growth": _sane_ratio(rev_g, -0.95, 10),
        "eps_growth": _sane_ratio(eps_g, -0.95, 10),
        "roe": _sane_ratio(roe, -1.5, 3),
        "div_yield": guard_yield(div_y),
        "ttm_pe_avg": guard_multiple(_num(row.get("pe_avg"))),
        "ps_avg": _sane_multiple(_num(row.get("ps_avg")), 500),
        "pfcf_avg": _sane_multiple(_num(row.get("pfcf_avg")), 2000),
        "de_avg": _sane_ratio(_num(row.get("de_avg")), 0, 50),
        "rev_growth_avg": _sane_ratio(_num(row.get("rev_g_avg")), -0.95, 10),
        "eps_growth_avg": _sane_ratio(_num(row.get("eps_g_avg")), -0.95, 10),
        "roe_avg": _sane_ratio(_num(row.get("roe_avg")), -1.5, 3),
        "div_yield_avg": guard_yield(_num(row.get("div_y_avg"))),
        "eps": None if not np.isfinite(eps) else float(eps),
        "revenue": None if not np.isfinite(revenue) else float(revenue),
        "fcf": None if not np.isfinite(fcf) else float(fcf),
        "shares": None if not np.isfinite(shares) else float(shares),
        "dps": None if not np.isfinite(dps) else float(dps),
        "gross_profit": None if not np.isfinite(_num(row.get("gross_profit"))) else float(row.get("gross_profit")),
        "op_income": None if not np.isfinite(_num(row.get("op_income"))) else float(row.get("op_income")),
        "net_income": None if not np.isfinite(net_income) else float(net_income),
        "equity": None if not np.isfinite(equity) else float(equity),
        "debt": None if not np.isfinite(debt) else float(debt),
        "fcf_per_share": None if not np.isfinite(fcf_ps) else float(fcf_ps),
    })
    return out
