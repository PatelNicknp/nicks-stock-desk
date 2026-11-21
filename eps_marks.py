"""EPS markers for the Chart Viewer's MarketSurge-style chart (data/eps_marks.csv).

One row per reported quarter: the report day and the EPS change against the same quarter a year before
("EPS +36%" under the price bars). Built only from files the desk already saves: the SEC quarterly EPS
(cache/eps_history.csv) and, where the desk has them, the real report days in earnings_history.csv.
No new download. Research only.
"""
import os
import sys

import pandas as pd

COLS = ["ticker", "date", "eps", "yoy_pct"]
DEFAULTS = {"quarters": 12, "fresh_days": 120, "default_lag_days": 40, "match_days": 50}


def settings(cfg):
    raw = ((cfg or {}).get("eps_marks") or {})
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        try:
            out[k] = int(raw.get(k, DEFAULTS[k]))
        except (TypeError, ValueError):
            pass
    return out


def _quarters(hist):
    """Quarterly rows with the period end, filed date, and the frame's year and quarter."""
    if hist is None or not len(hist):
        return pd.DataFrame(columns=["ticker", "year", "q", "eps", "end", "filed"])
    q = hist[hist["kind"].astype(str) == "Q"].copy()
    m = q["frame"].astype(str).str.extract(r"CY(\d{4})Q([1-4])")
    q["year"] = pd.to_numeric(m[0], errors="coerce")
    q["q"] = pd.to_numeric(m[1], errors="coerce")
    q["eps"] = pd.to_numeric(q["eps"], errors="coerce")
    q["end"] = pd.to_datetime(q["end"], errors="coerce")
    q["filed"] = pd.to_datetime(q["filed"], errors="coerce")
    q = q.dropna(subset=["year", "q", "eps"])
    q["ticker"] = q["ticker"].astype(str).str.upper()
    return q.drop_duplicates(["ticker", "year", "q"], keep="last")


def build(hist, earnings=None, cfg=None):
    """Frame of COLS. The report day is the earnings_history day within match_days of the quarter end when the desk has
    one; else the SEC filed day when it came within fresh_days of the quarter end; else the quarter end plus this stock's
    usual filing lag (default_lag_days when unknown). The SEC 'filed' day of an older quarter is often a later restatement,
    which is why it is not used as is."""
    s = settings(cfg)
    q = _quarters(hist)
    if not len(q):
        return pd.DataFrame(columns=COLS)
    real = {}
    if earnings is not None and len(earnings) and "eps_actual" in earnings.columns:
        e = earnings.copy()
        e["d"] = pd.to_datetime(e["earnings_date"], errors="coerce")
        e = e[pd.to_numeric(e["eps_actual"], errors="coerce").notna() & e["d"].notna()]
        for t, g in e.groupby(e["ticker"].astype(str).str.upper()):
            real[t] = sorted(g["d"].tolist())
    rows = []
    for t, g in q.groupby("ticker"):
        g = g.sort_values(["year", "q"])
        lag = (g["filed"] - g["end"]).dt.days
        fresh = lag[(lag >= 0) & (lag <= s["fresh_days"])]
        usual = int(fresh.median()) if len(fresh) else s["default_lag_days"]
        by = {(int(r.year), int(r.q)): float(r.eps) for r in g.itertuples()}
        for r in g.tail(s["quarters"]).itertuples():
            if pd.isna(r.end):
                continue
            day = None
            for d in real.get(t, []):
                if 0 <= (d - r.end).days <= s["match_days"]:
                    day = d
                    break
            if day is None:
                lg = (r.filed - r.end).days if not pd.isna(r.filed) else None
                day = r.filed if lg is not None and 0 <= lg <= s["fresh_days"] else r.end + pd.Timedelta(days=usual)
            prior = by.get((int(r.year) - 1, int(r.q)))
            yoy = round((float(r.eps) / prior - 1) * 100) if prior is not None and prior > 0 else None
            rows.append({"ticker": t, "date": day.strftime("%Y-%m-%d"), "eps": round(float(r.eps), 4), "yoy_pct": yoy})
    out = pd.DataFrame(rows, columns=COLS)
    out["yoy_pct"] = out["yoy_pct"].astype("Int64")
    return out.sort_values(["ticker", "date"]).reset_index(drop=True)


def export_frame(frame, feature_on=True):
    cols = COLS + ["data_status"]
    if not feature_on:
        return pd.DataFrame(columns=cols)
    if frame is None or not len(frame):
        return pd.DataFrame([{"data_status": "MISSING"}], columns=cols)
    out = frame.copy()
    out["data_status"] = "OK"
    return out[cols]


def main(argv=None):
    """python eps_marks.py: rebuild data/eps_marks.csv from cache/eps_history.csv and data/earnings_history.csv. No download."""
    import json
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(root, "config.json")))
    hist = pd.read_csv(os.path.join(root, "cache", "eps_history.csv"))
    ep = os.path.join(root, "data", "earnings_history.csv")
    earn = pd.read_csv(ep) if os.path.exists(ep) else None
    out = export_frame(build(hist, earn, cfg), ((cfg.get("features") or {}).get("eps_marks", True)))
    out.to_csv(os.path.join(root, "data", "eps_marks.csv"), index=False)
    print("eps marks", len(out), "rows,", out["ticker"].nunique(), "stocks")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
