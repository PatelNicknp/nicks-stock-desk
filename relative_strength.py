"""MarketSmith / O'Neil style RS Rating (1 to 99), from saved daily closes.

This is the desk's one RS score. It ranks every stock in the desk's US
universe against every other stock, the way MarketSmith and IBD do. It is not
measured against SPY. The VCP page's rule 8 (stock close divided by SPY, the
RS line in Nick's indicator) is a separate check and is not this number.

Formula choice: discrete quarters (below), not overlapping windows. O'Neil's
published method weights the latest three months 40% and each of the three
earlier quarters 20%. Discrete quarters keep each quarter's move in its own
bucket, so the latest quarter really counts double. The overlapping form
(0.4*ROC63 + 0.2*ROC126 + 0.2*ROC189 + 0.2*ROC252) counts the latest quarter in
all four terms, which gives it about 100% of the weight instead of 40%.

ETFs and funds are not stocks, so they are left out of the race and stay
blank, like MarketSmith's stock-only ranking. The ETF list is the ETF column of
the Nasdaq Trader symbol files the desk already saves (cache/nasdaqlisted.txt
and cache/otherlisted.txt), plus the sector ETFs, SPY, QQQ and index symbols.

No download and no API key. It is worked out on every run from the closes
already in memory (cache/ohlcv.csv.gz), so the RS column, the scanners and
Nick 360 always use the same number.

A quarter is 63 trading sessions, about three months.

    Q1  latest 63 sessions
    Q2  the 63 sessions before that (3 to 6 months ago)
    Q3  6 to 9 months ago
    Q4  9 to 12 months ago

Each Q is that quarter's price change: end / start - 1.
RS raw = 0.4*Q1 + 0.2*Q2 + 0.2*Q3 + 0.2*Q4.

The rank is 1 to 99 across every covered stock that has a raw score.
99 is the strongest and 1 is the weakest. Ties share the middle of the tie.
One scored stock on its own is 99.

A stock with fewer than a full year of closes (253 sessions: today plus 252)
is left blank. It is not stored as 0, and it is not given a partial-year rank.
A new listing is not in the same race as a stock that has all four quarters.
A zero or missing price inside the year is blank for the same reason.

The sentence on the site reads the rank as a share of the list:
"RS 85: beat 85% of stocks over the past year".
"""

import numpy as np
import pandas as pd

QUARTER = 63
WEIGHTS = (0.4, 0.2, 0.2, 0.2)
MIN_BARS = 4 * QUARTER + 1  # 253: the close today and the close 252 sessions ago
LEADER_MIN = 70

SHORT_NOTE = "Needs a full year of daily prices."
FUND_NOTE = "ETFs and funds are not ranked. RS compares stocks only."
GAP_NOTE = "A price in the past year was missing, so RS is blank."

COLUMNS = [
    "ticker", "rs", "rs_raw", "q1", "q2", "q3", "q4", "bars",
    "rs_label", "rs_note", "as_of", "data_status",
]


def settings_from(cfg):
    """Quarter length, weights, history requirement, and Minervini's line."""
    block = {}
    if isinstance(cfg, dict):
        raw = cfg.get("relative_strength") or {}
        if isinstance(raw, dict):
            block = raw
    quarter = _pos_int(block.get("quarter_sessions"), QUARTER)
    weights = (
        _float(block.get("weight_q1"), WEIGHTS[0]),
        _float(block.get("weight_q2"), WEIGHTS[1]),
        _float(block.get("weight_q3"), WEIGHTS[2]),
        _float(block.get("weight_q4"), WEIGHTS[3]),
    )
    need = 4 * quarter + 1
    min_bars = max(need, _pos_int(block.get("min_bars"), need))
    leader = _pos_int(block.get("leader_min"), LEADER_MIN)
    return {
        "quarter": quarter,
        "weights": weights,
        "min_bars": min_bars,
        "leader_min": leader,
    }


def feature_on(cfg):
    """feature.rs_rank: shows or hides the RS column and the RS 70 filter only."""
    if not isinstance(cfg, dict):
        return True
    features = cfg.get("features")
    if not isinstance(features, dict):
        return True
    return bool(features.get("rs_rank", True))


def quarter_returns(closes, quarter=QUARTER):
    """Four quarterly price changes from a stock's own closes, oldest first.

    Returns (q1, q2, q3, q4) or None when there are not enough sessions or a
    starting price is missing or zero. Q1 is the latest quarter.
    """
    values = np.asarray(closes, dtype=float)
    values = values[np.isfinite(values)]
    need = 4 * int(quarter) + 1
    if quarter < 1 or values.size < need:
        return None
    window = values[-need:]
    pts = window[:: int(quarter)]
    if pts.size != 5 or not np.isfinite(pts).all() or np.any(pts[:-1] <= 0) or pts[-1] <= 0:
        return None
    q4 = pts[1] / pts[0] - 1.0
    q3 = pts[2] / pts[1] - 1.0
    q2 = pts[3] / pts[2] - 1.0
    q1 = pts[4] / pts[3] - 1.0
    return (float(q1), float(q2), float(q3), float(q4))


def raw_score(quarters, weights=WEIGHTS):
    """Weighted quarterly changes. None if any quarter is missing."""
    if quarters is None or len(quarters) != 4:
        return None
    if any(q is None or not np.isfinite(q) for q in quarters):
        return None
    w = tuple(weights) if weights is not None else WEIGHTS
    if len(w) != 4 or any(not np.isfinite(x) for x in w):
        return None
    return float(sum(a * b for a, b in zip(w, quarters)))


def rank_1_to_99(raw):
    """Map raw scores to integers 1 through 99. 99 is the strongest.

    Average rank is used for ties, then scaled so the weakest scored name is
    1 and the strongest is 99. A single name is 99. Blank raw scores are
    dropped and are not part of the count.
    """
    series = pd.to_numeric(pd.Series(raw), errors="coerce")
    series = series[np.isfinite(series.to_numpy(dtype=float))]
    if len(series) == 0:
        return pd.Series(dtype="float")
    if len(series) == 1:
        return pd.Series({series.index[0]: 99})
    order = series.rank(method="average", ascending=True)
    n = float(len(series))
    scaled = 1.0 + (order - 1.0) / (n - 1.0) * 98.0
    rounded = np.floor(scaled.to_numpy(dtype=float) + 0.5).astype(int)
    rounded = np.clip(rounded, 1, 99)
    return pd.Series(rounded, index=series.index)


def label_for(rs):
    """Plain sentence. RS 85 reads as beating 85% of the ranked stocks."""
    if rs is None or rs == "" or (isinstance(rs, float) and not np.isfinite(rs)):
        return ""
    try:
        n = int(rs)
    except (TypeError, ValueError):
        return ""
    if n < 1 or n > 99:
        return ""
    return "RS %d: beat %d%% of stocks over the past year" % (n, n)


def empty_table():
    return pd.DataFrame(columns=COLUMNS)


def _closes_of(close, ticker):
    if close is None or ticker not in getattr(close, "columns", []):
        return np.asarray([], dtype=float)
    series = close[ticker]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    series = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    return series.to_numpy(dtype=float)


def etf_symbols(nasdaq_text, other_text):
    """ETF symbols from the saved Nasdaq Trader files (ETF column = Y). No download."""
    out = set()

    def take(text, sym_i, etf_i):
        for line in (text or "").splitlines()[1:]:
            if line.startswith("File Creation"):
                continue
            parts = line.split("|")
            if len(parts) <= max(sym_i, etf_i):
                continue
            if parts[etf_i].strip().upper() != "Y":
                continue
            sym = str(parts[sym_i] or "").upper().replace(".", "-").replace("$", "-").replace("/", "-").strip()
            if sym:
                out.add(sym)

    take(nasdaq_text, 0, 6)
    take(other_text, 0, 4)
    return out


def fund_tickers(universe, etfs=None, extra=None):
    """Universe tickers that are ETFs or funds, so they stay out of the race.

    etfs: symbols flagged ETF in the Nasdaq Trader files. extra: more symbols
    (sector ETFs, SPY, QQQ). Index symbols that start with ^ always count.
    """
    if universe is None or not isinstance(universe, pd.DataFrame) or len(universe) == 0 or "ticker" not in universe.columns:
        return set()
    flagged = set(str(t).strip().upper() for t in (etfs or ())) | set(str(t).strip().upper() for t in (extra or ()))
    out = set()
    for t in universe["ticker"].astype(str):
        key = t.strip().upper()
        if key.startswith("^") or key in flagged:
            out.add(t)
    return out


def build(close, tickers, cfg=None, as_of="", skip=None):
    """One row per covered stock. Ranked names get 1 to 99. The rest stay blank.

    skip: tickers left out of the race (fund units and ETFs). They keep a row
    with a blank RS and a note, so the page can say why.
    """
    spec = settings_from(cfg)
    skip = set(str(t) for t in (skip or ()))
    names = []
    seen = set()
    for ticker in list(tickers or []):
        name = str(ticker).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    rows = []
    raw_map = {}
    for name in names:
        values = _closes_of(close, name)
        bars = int(values.size)
        quarters = None
        note = ""
        if name in skip:
            note = FUND_NOTE
        elif bars < spec["min_bars"]:
            note = SHORT_NOTE
        else:
            quarters = quarter_returns(values, spec["quarter"])
            if quarters is None:
                note = GAP_NOTE
        raw = raw_score(quarters, spec["weights"]) if quarters is not None and name not in skip else None
        if raw is None and not note:
            note = GAP_NOTE
        if raw is not None:
            raw_map[name] = raw
            note = ""
        q1 = q2 = q3 = q4 = ""
        if quarters is not None and raw is not None:
            q1, q2, q3, q4 = quarters
        rows.append({
            "ticker": name,
            "rs": "",
            "rs_raw": "" if raw is None else round(float(raw), 6),
            "q1": "" if q1 == "" else round(float(q1), 6),
            "q2": "" if q2 == "" else round(float(q2), 6),
            "q3": "" if q3 == "" else round(float(q3), 6),
            "q4": "" if q4 == "" else round(float(q4), 6),
            "bars": bars,
            "rs_label": "",
            "rs_note": note,
            "as_of": as_of or "",
            "data_status": "OK",
        })
    ranks = rank_1_to_99(raw_map)
    for row in rows:
        if row["ticker"] not in ranks.index:
            continue
        score = int(ranks.loc[row["ticker"]])
        row["rs"] = score
        row["rs_label"] = label_for(score)
        row["rs_note"] = ""
    if not rows:
        return empty_table()
    return pd.DataFrame(rows, columns=COLUMNS)


def rs_map(ratings):
    """{TICKER: rs} for ranked names only. Blank ranks are left out."""
    out = {}
    if ratings is None or not isinstance(ratings, pd.DataFrame) or len(ratings) == 0:
        return out
    if "ticker" not in ratings.columns or "rs" not in ratings.columns:
        return out
    nums = pd.to_numeric(ratings["rs"], errors="coerce")
    for ticker, val in zip(ratings["ticker"].astype(str), nums):
        if np.isfinite(val):
            out[ticker.strip().upper()] = int(val)
    return out


def attach(frame, ratings):
    """Copy rs, rs_label, and rs_note onto a scanner or setup table."""
    if frame is None or not isinstance(frame, pd.DataFrame) or len(frame) == 0:
        return frame
    if "ticker" not in frame.columns:
        return frame
    out = frame.copy()
    blank = pd.Series([""] * len(out), index=out.index)
    if ratings is None or not isinstance(ratings, pd.DataFrame) or len(ratings) == 0 or "ticker" not in ratings.columns:
        out["rs"] = blank
        out["rs_label"] = blank
        out["rs_note"] = blank
        return out
    table = ratings.drop_duplicates("ticker", keep="last").copy()
    table["_key"] = table["ticker"].astype(str).str.upper()
    table = table.drop_duplicates("_key", keep="last").set_index("_key")
    keys = out["ticker"].astype(str).str.upper()
    out["rs"] = keys.map(table["rs"]) if "rs" in table.columns else blank
    out["rs_label"] = keys.map(table["rs_label"]) if "rs_label" in table.columns else blank
    out["rs_note"] = keys.map(table["rs_note"]) if "rs_note" in table.columns else blank
    out["rs_label"] = out["rs_label"].fillna("")
    out["rs_note"] = out["rs_note"].fillna("")
    rs_num = pd.to_numeric(out["rs"], errors="coerce")
    out["rs"] = ["" if not np.isfinite(v) else int(v) for v in rs_num]
    return out


def _pos_int(value, fallback):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return int(fallback)
    return n if n > 0 else int(fallback)


def _float(value, fallback):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if not np.isfinite(n):
        return float(fallback)
    return n
