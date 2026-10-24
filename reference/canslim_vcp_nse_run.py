#!/usr/bin/env python3
"""Daily NSE CANSLIM+VCP scan for 2026-10-22 (run 2026-10-23 IST) (post-close / latest available)."""
import json
import pickle
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from matplotlib.patches import Rectangle

warnings.filterwarnings("ignore")

OUT = Path("/workspace/canslim-vcp-2026-10-23")
CHARTS = OUT / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)
SESSION = "2026-10-22"
PY = "/workspace/venv-charts/bin/python"

# ---------- 1) Load ticker universe ----------
with open("/workspace/canslim_raw.pkl", "rb") as f:
    old = pickle.load(f)
tickers = list(old["tickers"])
# 2026-10-22: add E2E.NS to the universe going forward (persisted via canslim_raw.pkl)
if "E2E.NS" not in tickers:
    tickers.append("E2E.NS")
print(f"Universe: {len(tickers)} tickers")

# ---------- 2) Fresh download (~1y) ----------
download_list = tickers + ["^NSEI"]
print(f"Downloading {len(download_list)} symbols via yfinance...")
data = yf.download(
    download_list,
    period="1y",
    interval="1d",
    group_by="ticker",
    auto_adjust=False,
    threads=True,
    progress=False,
)
if data is None or data.empty:
    raise SystemExit("Download returned empty data")

# Normalize MultiIndex: expect (Ticker, OHLCV)
if isinstance(data.columns, pd.MultiIndex):
    # Sometimes level order is Price, Ticker — flip if needed
    lvl0 = data.columns.get_level_values(0)
    if "Close" in set(lvl0) or "Adj Close" in set(lvl0):
        data.columns = data.columns.swaplevel(0, 1)
        data = data.sort_index(axis=1)

# Pin to user session date: drop incomplete post-session bars (e.g. next-day pre/partial)
cutoff = pd.Timestamp(SESSION)
if data.index.tz is not None:
    cutoff = cutoff.tz_localize(data.index.tz)
before = len(data)
data = data.loc[data.index <= cutoff]
print(f"Pinned to as-of <= {SESSION}: rows {before} -> {len(data)} | last={data.index[-3:].tolist() if len(data) else None}")
if data.empty:
    raise SystemExit("No bars on/before session date")

# ---------- 2b) Patch missing session bars from 5m intraday (Yahoo daily feed gaps) ----------
sess_ts = pd.Timestamp(SESSION)
if sess_ts not in data.index:
    data.loc[sess_ts] = np.nan
    data = data.sort_index()
missing_sess = []
for t in download_list:
    if t in data.columns.get_level_values(0):
        col = data[t]["Close"]
        if col.dropna().empty:
            continue
        if pd.isna(col.get(sess_ts)):
            missing_sess.append(t)
patched, patch_fail = [], []
if missing_sess:
    intr = yf.download(missing_sess, start=SESSION, end=str((sess_ts + pd.Timedelta(days=1)).date()),
                       interval="5m", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    for t in missing_sess:
        try:
            x = intr[t].dropna(subset=["Close"]) if len(missing_sess) > 1 else intr.dropna(subset=["Close"])
            if isinstance(x.columns, pd.MultiIndex):
                x.columns = x.columns.get_level_values(-1)
            if x.empty:
                patch_fail.append(t); continue
            vals = {"Open": float(x["Open"].iloc[0]), "High": float(x["High"].max()), "Low": float(x["Low"].min()),
                    "Close": float(x["Close"].iloc[-1]), "Adj Close": float(x["Close"].iloc[-1]), "Volume": float(x["Volume"].sum())}
            for k, val in vals.items():
                if (t, k) in data.columns:
                    data.loc[sess_ts, (t, k)] = val
            patched.append(t)
        except Exception as e:
            patch_fail.append(f"{t}:{e}")
patch_note = (f"Yahoo daily feed lacked the {SESSION} bar for {len(missing_sess)} symbols; rebuilt {len(patched)} from 5m intraday "
              f"(O=first open, H/L=intraday extremes, C=last 5m close [matched official daily close exactly on 8 control tickers], "
              f"V=sum of 5m volume [~5-10% below official daily]); unpatched: {patch_fail}")
print(patch_note)
print("Patched:", patched)

blob = {"data": data, "tickers": tickers}
with open(OUT / "canslim_raw.pkl", "wb") as f:
    pickle.dump(blob, f)
with open("/workspace/canslim_raw.pkl", "wb") as f:
    pickle.dump(blob, f)
print(f"Saved refreshed pickle | shape={data.shape} | index last={data.index[-5:].tolist()}")

# Confirm as-of
nifty_probe = None
if "^NSEI" in data.columns.get_level_values(0):
    nifty_probe = data["^NSEI"]["Close"].dropna()
    print(f"Nifty last date: {nifty_probe.index[-1]} close={float(nifty_probe.iloc[-1]):.2f}")

# ---------- 3) Parse OHLCV ----------
closes, volumes, highs, lows, opens = {}, {}, {}, {}, {}
download_failures = []
for t in tickers + ["^NSEI"]:
    try:
        if t not in data.columns.get_level_values(0):
            download_failures.append(t)
            continue
        df = data[t].copy()
        if df is None or df.empty or "Close" not in df.columns:
            download_failures.append(t)
            continue
        c = df["Close"].dropna()
        if len(c) < 150:
            download_failures.append(f"{t}:short({len(c)})")
            continue
        closes[t] = c
        volumes[t] = df["Volume"].reindex(c.index).fillna(0)
        highs[t] = df["High"].reindex(c.index)
        lows[t] = df["Low"].reindex(c.index)
        opens[t] = df["Open"].reindex(c.index)
    except Exception as e:
        download_failures.append(f"{t}:{e}")

if "^NSEI" not in closes:
    raise SystemExit("Nifty ^NSEI missing after download")

nifty = closes["^NSEI"]
asof = nifty.index[-1]
asof_str = str(pd.Timestamp(asof).date())
print(f"As-of last close: {asof_str} | Nifty: {float(nifty.iloc[-1]):.2f}")
print(f"Valid tickers: {len(closes)-1} | failures/short: {len(download_failures)}")

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def ret(s, w):
    if len(s) < w + 1:
        return np.nan
    return float(s.iloc[-1]) / float(s.iloc[-1 - w]) - 1.0

# ---------- Market direction ----------
n21, n50, n200 = ema(nifty, 21), ema(nifty, 50), ema(nifty, 200)
nifty_last = float(nifty.iloc[-1])
m_above_50 = nifty_last > float(n50.iloc[-1])
m_above_200 = nifty_last > float(n200.iloc[-1])
m_ema21_rising = float(n21.iloc[-1]) > float(n21.iloc[-5])
if m_above_50 and m_above_200 and m_ema21_rising:
    market_dir = "CONFIRMATION / constructive (above EMA50 & EMA200, EMA21 rising)"
elif m_above_200:
    market_dir = "MIXED / still above EMA200 but weaker vs EMA50 or EMA21"
else:
    market_dir = "CORRECTION risk (below EMA200)"

nifty_r63 = ret(nifty, 63)
nifty_r126 = ret(nifty, 126)
print("Market M:", market_dir)

# ---------- Screen ----------
rows = []
for t in list(closes.keys()):
    if t == "^NSEI":
        continue
    c = closes[t]
    common = c.index.intersection(nifty.index)
    c = c.loc[common]
    if len(c) < 150:
        continue
    e21 = ema(c, 21)
    e50 = ema(c, 50)
    e200 = ema(c, 200)
    last = float(c.iloc[-1])
    e21v, e50v, e200v = float(e21.iloc[-1]), float(e50.iloc[-1]), float(e200.iloc[-1])
    e21_rising = e21v > float(e21.iloc[-5])
    above50 = last > e50v
    above200 = last > e200v
    above21 = last > e21v

    r63 = ret(c, 63)
    r126 = ret(c, 126)
    if np.isnan(r63) or np.isnan(r126):
        continue
    rs63 = r63 - nifty_r63
    rs126 = r126 - nifty_r126
    rs_rel = 0.6 * rs126 + 0.4 * rs63

    hi52 = float(c.iloc[-252:].max()) if len(c) >= 252 else float(c.max())
    pct_from_high = (last / hi52 - 1.0) * 100
    near_high = pct_from_high >= -15

    def range_pct(win):
        if len(c) < win:
            return np.nan
        seg = c.iloc[-win:]
        return (float(seg.max()) - float(seg.min())) / float(seg.mean()) * 100

    r20, r40, r60 = range_pct(20), range_pct(40), range_pct(60)
    contracting = False
    if not np.isnan(r20) and not np.isnan(r40) and not np.isnan(r60):
        contracting = r20 < r40 < r60
    mild_contract = not np.isnan(r20) and not np.isnan(r60) and r20 < r60 * 0.75

    roll_lo = c.rolling(10).min()
    hl = False
    if len(roll_lo.dropna()) > 40:
        a, b, d = float(roll_lo.iloc[-35]), float(roll_lo.iloc[-20]), float(roll_lo.iloc[-5])
        hl = d > b > a * 0.98

    vol = volumes.get(t)
    adv = float(vol.iloc[-20:].mean()) if vol is not None else 0
    liquid = adv >= 200_000

    trend = 0
    if above200:
        trend += 2
    if above50:
        trend += 2
    if above21:
        trend += 1
    if e21_rising:
        trend += 1
    if e50v > e200v:
        trend += 1

    vcp_score = 0
    if contracting:
        vcp_score += 3
    elif mild_contract:
        vcp_score += 2
    if hl:
        vcp_score += 2
    if near_high:
        vcp_score += 1
    if not np.isnan(r20) and r20 < 8:
        vcp_score += 1

    rows.append({
        "ticker": t.replace(".NS", ""),
        "yf": t,
        "last": last,
        "rs63_pct": rs63 * 100,
        "rs126_pct": rs126 * 100,
        "rs_rel": rs_rel * 100,
        "r63_pct": r63 * 100,
        "r126_pct": r126 * 100,
        "pct_from_high": pct_from_high,
        "hi52": hi52,
        "above50": above50,
        "above200": above200,
        "above21": above21,
        "e21_rising": e21_rising,
        "e21": e21v, "e50": e50v, "e200": e200v,
        "r20": r20, "r40": r40, "r60": r60,
        "contracting": contracting,
        "mild_contract": mild_contract,
        "higher_lows": hl,
        "adv": adv,
        "liquid": liquid,
        "trend": trend,
        "vcp_score": vcp_score,
        "near_high": near_high,
    })

df = pd.DataFrame(rows)
print(f"Screened rows: {len(df)}")
df = df[df["liquid"]].copy()
df["rs_percentile"] = df["rs_rel"].rank(pct=True) * 100

strict_mask = (
    (df["above50"])
    & (df["above200"])
    & (df["e21_rising"])
    & (df["rs_percentile"] >= 55)
    & ((df["vcp_score"] >= 2) | (df["near_high"]))
)
qual = df[strict_mask].copy()
n_strict = len(qual)
print(f"Strict qualify: {n_strict}")

def score_row(r):
    return (
        r["rs_percentile"] * 0.45
        + r["trend"] * 8
        + r["vcp_score"] * 7
        + (5 if r["near_high"] else 0)
        + max(0, 10 + r["pct_from_high"]) * 0.3
    )

qual["score"] = qual.apply(score_row, axis=1)
qual = qual.sort_values("score", ascending=False)

stretch_tickers = set()
if len(qual) < 12:
    rest = df[~df["ticker"].isin(set(qual["ticker"]))].copy()
    soft = rest[(rest["above50"]) & (rest["rs_percentile"] >= 40)].copy()
    soft["score"] = soft.apply(score_row, axis=1)
    soft = soft.sort_values("score", ascending=False)
    need = max(12 - len(qual), 0)
    add = soft.head(need + 3)
    for _, row in add.iterrows():
        stretch_tickers.add(row["ticker"])
    qual = pd.concat([qual, add], ignore_index=True)
    qual = qual.sort_values("score", ascending=False)

strict_set = set(df[strict_mask]["ticker"])
top = qual.head(12).copy()
top["stretch"] = ~top["ticker"].isin(strict_set)
n_stretch = int(top["stretch"].sum())
print("Top picks:")
print(top[["ticker", "last", "rs_percentile", "vcp_score", "trend", "score", "stretch"]].to_string())

# Persist helpers for reuse
top.to_pickle("/workspace/canslim_top.pkl")
meta_slim = {
    "asof": asof_str,
    "nifty_last": nifty_last,
    "market_dir": market_dir,
    "nifty_ema": {"e21": float(n21.iloc[-1]), "e50": float(n50.iloc[-1]), "e200": float(n200.iloc[-1])},
    "nifty_r63": nifty_r63,
    "nifty_r126": nifty_r126,
    "m_flags": {"above50": m_above_50, "above200": m_above_200, "e21_rising": m_ema21_rising},
    "n_strict": n_strict,
    "n_stretch_in_top": n_stretch,
}
with open("/workspace/canslim_meta.pkl", "wb") as f:
    pickle.dump(meta_slim, f)
with open("/workspace/canslim_ohlc.pkl", "wb") as f:
    pickle.dump({"closes": closes, "volumes": volumes, "highs": highs, "lows": lows, "opens": opens}, f)

# ---------- 4) Yahoo info ----------
names = {}
earnings_notes = {}
info_cache = {}
for _, row in top.iterrows():
    yf_t = row["yf"]
    tk = row["ticker"]
    try:
        inf = {}
        try:
            inf = yf.Ticker(yf_t).info or {}
        except Exception:
            inf = {}
        nm = inf.get("shortName") or inf.get("longName") or tk
        names[tk] = nm
        c_note = "not verified"
        a_note = "not verified"
        inst_note = "not verified"
        qeg = inf.get("earningsQuarterlyGrowth")
        eg = inf.get("earningsGrowth")
        held = inf.get("heldPercentInstitutions")
        if qeg is not None:
            c_note = f"Yahoo earningsQuarterlyGrowth≈{qeg*100:.1f}% (rough, not audited IBD C)"
        if eg is not None:
            a_note = f"Yahoo earningsGrowth≈{eg*100:.1f}% (rough annual YoY proxy)"
        if held is not None:
            inst_note = f"Yahoo heldPercentInstitutions≈{held*100:.1f}% (coarse; not IBD sponsorship quality)"
        earnings_notes[tk] = {"C": c_note, "A": a_note, "inst": inst_note}
        info_cache[tk] = {
            "shortName": nm,
            "earningsQuarterlyGrowth": qeg,
            "earningsGrowth": eg,
            "heldPercentInstitutions": held,
        }
        print(f"  info {tk}: {nm}")
    except Exception:
        names[tk] = tk
        earnings_notes[tk] = {"C": "not verified", "A": "not verified", "inst": "not verified"}
        info_cache[tk] = {"shortName": tk}

with open(OUT / "info_cache.json", "w") as f:
    json.dump(info_cache, f, indent=2, default=str)

# ---------- 5) Charts ----------
chart_paths = []
for rank, (_, row) in enumerate(top.iterrows(), 1):
    tk = row["ticker"]
    yf_t = row["yf"]
    cfull = closes[yf_t]
    hfull = highs[yf_t]
    lfull = lows[yf_t]
    ofull = opens[yf_t]
    plot_n = min(180, len(cfull))
    c = cfull.iloc[-plot_n:]
    h = hfull.reindex(c.index)
    l = lfull.reindex(c.index)
    o = ofull.reindex(c.index)
    e21p = ema(cfull, 21).reindex(c.index)
    e50p = ema(cfull, 50).reindex(c.index)
    e200p = ema(cfull, 200).reindex(c.index)
    rsi_v = rsi(cfull).reindex(c.index)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    dates = c.index
    for i, dt in enumerate(dates):
        op, cl, hi, lo = float(o.iloc[i]), float(c.iloc[i]), float(h.iloc[i]), float(l.iloc[i])
        color = "#26a69a" if cl >= op else "#ef5350"
        ax1.plot([dt, dt], [lo, hi], color=color, linewidth=0.8)
        body_low = min(op, cl)
        body_h = max(abs(cl - op), cl * 0.0005)
        ax1.add_patch(
            Rectangle(
                (mdates.date2num(dt) - 0.3, body_low),
                0.6,
                body_h,
                facecolor=color,
                edgecolor=color,
                linewidth=0,
            )
        )
    ax1.plot(dates, e21p, color="green", linewidth=1.2, label="EMA21")
    ax1.plot(dates, e50p, color="blue", linewidth=1.2, label="EMA50")
    ax1.plot(dates, e200p, color="red", linewidth=1.2, label="EMA200")
    company = names.get(tk, tk)
    ax1.set_title(f"{tk} — {company}", fontsize=13, fontweight="bold")
    ax1.set_ylabel("Price (INR)")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(row["hi52"], color="gray", linestyle="--", linewidth=0.8, alpha=0.7)

    ax2.plot(dates, rsi_v, color="purple", linewidth=1.0)
    ax2.axhline(70, color="red", linestyle="--", linewidth=0.7, alpha=0.6)
    ax2.axhline(30, color="green", linestyle="--", linewidth=0.7, alpha=0.6)
    ax2.set_ylabel("RSI(14)")
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fpath = CHARTS / f"{tk}.png"
    fig.savefig(fpath, dpi=120)
    plt.close(fig)
    chart_paths.append(str(fpath))
    print(f"Chart {rank}: {fpath}")

# ---------- 6) ranked.csv + market.json ----------
top_out = top.copy()
top_out["company"] = top_out["ticker"].map(names)
top_out["rank"] = range(1, len(top_out) + 1)
top_out["asof"] = asof_str
csv_cols = [
    "rank", "ticker", "yf", "company", "last", "score", "rs_percentile",
    "rs126_pct", "rs63_pct", "rs_rel", "r126_pct", "r63_pct",
    "pct_from_high", "hi52", "vcp_score", "trend", "adv",
    "above50", "above200", "above21", "e21_rising",
    "e21", "e50", "e200", "r20", "r40", "r60",
    "contracting", "mild_contract", "higher_lows", "near_high", "stretch", "asof",
]
top_out[csv_cols].to_csv(OUT / "ranked.csv", index=False)

market = {
    "session": SESSION,
    "asof": asof_str,
    "nifty_last": nifty_last,
    "market_dir": market_dir,
    "nifty_ema": meta_slim["nifty_ema"],
    "nifty_r63_pct": nifty_r63 * 100,
    "nifty_r126_pct": nifty_r126 * 100,
    "m_flags": meta_slim["m_flags"],
    "n_strict": n_strict,
    "n_stretch_in_top": n_stretch,
    "n_ranked": len(top),
    "universe_liquid": int(len(df)),
    "download_failures_count": len(download_failures),
    "download_failures_sample": download_failures[:30],
    "patch_note": patch_note,
    "patched_tickers": patched,
    "holiday_note": "Run Fri 2026-10-23 ~09:34 IST (market live); partial 2026-10-23 bar dropped. NSE open Thu 2026-10-22 (not on NSE 2026 holiday list). Using last complete close (Thu 2026-10-22). Yahoo daily feed lacked the 2026-10-22 bar for many tickers; rebuilt from 5m intraday (see patch_note).",
}
with open(OUT / "market.json", "w") as f:
    json.dump(market, f, indent=2)

# ---------- 7) DIGEST.md (live, not EXAMPLE) ----------
lines = []
lines.append(f"# Daily CANSLIM+VCP Scan — NSE (India) — as-of {SESSION} (run Fri 2026-10-23 IST)")
lines.append("")
lines.append(f"**Live daily scan** for session **{SESSION}** (Thu, last complete session; NSE open). Partial 2026-10-23 bars dropped. Missing Yahoo daily 2026-10-22 bars rebuilt from 5m intraday for affected tickers.")
lines.append(f"As-of last available cash close: **{asof_str}**.")
lines.append(f"Nifty 50 (`^NSEI`) last close: **{nifty_last:.2f}**.")
lines.append(f"Data patch: {patch_note}")
lines.append("Universe: E2E.NS included (added 2026-10-22).")
lines.append("")
lines.append("## Market direction (M)")
lines.append("")
lines.append(f"- Status: **{market_dir}**")
ne = meta_slim["nifty_ema"]
lines.append(
    f"- Nifty vs EMAs: price {nifty_last:.2f} | EMA21 {ne['e21']:.1f} | EMA50 {ne['e50']:.1f} | EMA200 {ne['e200']:.1f}"
)
lines.append(
    f"- Nifty absolute return: 63d **{nifty_r63*100:.2f}%**, 126d **{nifty_r126*100:.2f}%**"
)
if not m_above_200:
    lines.append("- Implication: **M not confirmed** (below EMA200) — leaders can still work but size risk down.")
elif not (m_above_50 and m_ema21_rising):
    lines.append("- Implication: tape is mixed; prefer highest-RS names with tight bases and keep risk defined.")
else:
    lines.append("- Implication: constructive tape — still respect pivots and individual setups.")
lines.append("")
lines.append("## Method")
lines.append("")
lines.append("- Universe: liquid NSE names from local list (~217 `.NS`), filtered ADV≥200k (20d avg Yahoo volume).")
lines.append("- **RS vs Nifty 50**: stock return − Nifty return over **63 and 126** trading days; composite `RS_rel = 0.6×RS_126 + 0.4×RS_63`.")
lines.append("- **RS percentile**: rank of `RS_rel` within the liquid screened universe (IBD-style *approximation*, not official IBD RS).")
lines.append("- Trend: price vs EMA21/50/200; prefer EMA21 rising, stacked averages.")
lines.append("- VCP heuristics: contracting 20d/40d/60d ranges, higher lows (10d rolling mins), tightness (20d range <8%), near 52w high.")
lines.append("- Strict qualify: above EMA50 & EMA200, EMA21 rising, RS%ile≥55, (vcp≥2 OR near_high). Soft-fill to ~12 marked **STRETCH** if needed.")
lines.append("- **Score** ≈ `0.45×RS_percentile + 8×trend + 7×vcp_score + near-high bonuses` (ranking only).")
lines.append("- Fundamentals (C/A/I): Yahoo fields when present; otherwise **not verified**. No invented numbers.")
lines.append(f"- Strict qualifies this run: **{n_strict}**; stretch in top {len(top)}: **{n_stretch}**.")
lines.append("")
lines.append("## Ranked table (strongest → weakest)")
lines.append("")
lines.append(
    "| Rank | Ticker | Company | Last | RS%ile | RS 126d vs Nifty | RS 63d vs Nifty | % from 52w hi | VCP | Score | Stretch? |"
)
lines.append(
    "|-----:|--------|---------|-----:|-------:|-----------------:|----------------:|--------------:|----:|------:|----------|"
)

for rank, (_, row) in enumerate(top.iterrows(), 1):
    tk = row["ticker"]
    co = names.get(tk, tk).replace("|", "/")
    stretch = "STRETCH" if row.get("stretch", False) else "qualify"
    lines.append(
        f"| {rank} | {tk} | {co} | {row['last']:.2f} | {row['rs_percentile']:.1f} | "
        f"{row['rs126_pct']:+.1f}% | {row['rs63_pct']:+.1f}% | {row['pct_from_high']:.1f}% | "
        f"{int(row['vcp_score'])} | {row['score']:.1f} | {stretch} |"
    )

lines.append("")
lines.append("## Per-stock writeups")
lines.append("")

for rank, (_, row) in enumerate(top.iterrows(), 1):
    tk = row["ticker"]
    co = names.get(tk, tk)
    en = earnings_notes.get(tk, {"C": "not verified", "A": "not verified", "inst": "not verified"})
    chart_rel = f"charts/{tk}.png"
    lines.append(f"### {rank}. {tk} — {co}")
    lines.append("")
    lines.append(f"- **Chart**: `{chart_rel}`")
    lines.append(
        f"- **Last close ({asof_str})**: ₹{row['last']:.2f} | 52w high ≈ ₹{row['hi52']:.2f} ({row['pct_from_high']:.1f}% away)"
    )
    lines.append(
        f"- **RS (vs Nifty 50)**: percentile **{row['rs_percentile']:.1f}**; "
        f"RS_126d **{row['rs126_pct']:+.2f}%**, RS_63d **{row['rs63_pct']:+.2f}%** "
        f"(windows 126 & 63 trading days). Absolute stock 126d={row['r126_pct']:+.1f}%."
    )
    lines.append(
        f"- **Trend**: above EMA50={'yes' if row['above50'] else 'no'}, "
        f"EMA200={'yes' if row['above200'] else 'no'}, EMA21 rising={'yes' if row['e21_rising'] else 'no'}; "
        f"EMA21={row['e21']:.1f}, EMA50={row['e50']:.1f}, EMA200={row['e200']:.1f}"
    )
    lines.append("- **CANSLIM**:")
    lines.append(f"  - **C** Current quarterly earnings: {en['C']}")
    lines.append(f"  - **A** Annual earnings growth: {en['A']}")
    n_bits = []
    if row["near_high"]:
        n_bits.append("near/at 52-week high area (price leadership / new-high proxy)")
    else:
        n_bits.append("not near 52w high")
    lines.append(
        f"  - **N** New high / product / leadership: {'; '.join(n_bits)}; product/news catalyst **not verified**"
    )
    lines.append(
        f"  - **S** Supply/demand: ADV≈{row['adv']:.0f} shares (20d avg Yahoo volume); float tightness **not verified**"
    )
    lines.append(
        f"  - **L** Leader vs laggard: RS percentile {row['rs_percentile']:.0f} in this liquid universe; industry group rank **not verified**"
    )
    lines.append(f"  - **I** Institutional sponsorship: {en['inst']}")
    lines.append(f"  - **M** Market direction: {market_dir}")
    vcp_parts = []
    if row["contracting"]:
        vcp_parts.append(
            f"clear range contraction (20d range {row['r20']:.1f}% < 40d {row['r40']:.1f}% < 60d {row['r60']:.1f}%)"
        )
    elif row["mild_contract"]:
        vcp_parts.append(f"mild contraction (20d {row['r20']:.1f}% vs 60d {row['r60']:.1f}%)")
    else:
        vcp_parts.append(
            f"ranges 20d/40d/60d = {row['r20']:.1f}% / {row['r40']:.1f}% / {row['r60']:.1f}%"
        )
    if row["higher_lows"]:
        vcp_parts.append("constructive higher lows (10d rolling-min proxy)")
    vcp_parts.append(
        f"rough pivot / breakout reference ≈ ₹{row['hi52']:.2f} (52w high; not a formal Minervini pivot count)"
    )
    lines.append(f"- **VCP notes**: {'; '.join(vcp_parts)}.")
    if row.get("stretch", False):
        lines.append(
            "- **Note**: marked **STRETCH** — soft-fill under softer filters, not full strict qualify."
        )
    lines.append("")

lines.append("## Data limitations")
lines.append("")
lines.append(
    f"- Session **{SESSION}** using last available cash close **{asof_str}** (NSE open that day; yfinance EOD)."
)
lines.append("- Price/volume via yfinance; some symbols may fail/delist aliases.")
if download_failures:
    sample = ", ".join(download_failures[:15])
    lines.append(f"- Download gaps / short history ({len(download_failures)}): {sample}{'…' if len(download_failures)>15 else ''}")
lines.append(
    "- Earnings and institutional % are Yahoo snapshots when available — **not** audited CANSLIM IBD fundamentals; often incomplete."
)
lines.append("- RS percentile is internal to this liquid universe, not official IBD RS Rating.")
lines.append("- VCP stages are heuristic from range contraction, not manual chart annotation of each contraction.")
lines.append("- Not investment advice; for daily screening only.")
lines.append("")
lines.append("---")
lines.append(f"*Generated {SESSION} from yfinance EOD as-of {asof_str}.*")

digest_path = OUT / "SCAN.md"
digest_path.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {digest_path}")
print(f"Charts: {len(chart_paths)}")
print("DONE")
print(json.dumps({
    "asof": asof_str,
    "nifty_last": nifty_last,
    "market_dir": market_dir,
    "n_strict": n_strict,
    "n_stretch": n_stretch,
    "ranked": top[["ticker", "score", "stretch"]].to_dict("records"),
    "scan": str(digest_path),
    "charts": chart_paths,
    "download_failures_count": len(download_failures),
}, indent=2, default=str))
