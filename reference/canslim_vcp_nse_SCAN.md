# Daily CANSLIM+VCP Scan — NSE (India) — as-of 2026-10-22 (run Fri 2026-10-23 IST)

**Live daily scan** for session **2026-10-22** (Thu, last complete session; NSE open). Partial 2026-10-23 bars dropped. Missing Yahoo daily 2026-10-22 bars rebuilt from 5m intraday for affected tickers.
As-of last available cash close: **2026-10-22**.
Nifty 50 (`^NSEI`) last close: **22687.65**.
Data patch: Yahoo daily feed lacked the 2026-10-22 bar for 91 symbols; rebuilt 91 from 5m intraday (O=first open, H/L=intraday extremes, C=last 5m close [matched official daily close exactly on 8 control tickers], V=sum of 5m volume [~5-10% below official daily]); unpatched: []
Universe: E2E.NS included (added 2026-10-22).

## Market direction (M)

- Status: **CORRECTION risk (below EMA200)**
- Nifty vs EMAs: price 22687.65 | EMA21 22879.2 | EMA50 23255.1 | EMA200 24095.6
- Nifty absolute return: 63d **-5.45%**, 126d **-7.69%**
- Implication: **M not confirmed** (below EMA200) — leaders can still work but size risk down.

## Method

- Universe: liquid NSE names from local list (~217 `.NS`), filtered ADV≥200k (20d avg Yahoo volume).
- **RS vs Nifty 50**: stock return − Nifty return over **63 and 126** trading days; composite `RS_rel = 0.6×RS_126 + 0.4×RS_63`.
- **RS percentile**: rank of `RS_rel` within the liquid screened universe (IBD-style *approximation*, not official IBD RS).
- Trend: price vs EMA21/50/200; prefer EMA21 rising, stacked averages.
- VCP heuristics: contracting 20d/40d/60d ranges, higher lows (10d rolling mins), tightness (20d range <8%), near 52w high.
- Strict qualify: above EMA50 & EMA200, EMA21 rising, RS%ile≥55, (vcp≥2 OR near_high). Soft-fill to ~12 marked **STRETCH** if needed.
- **Score** ≈ `0.45×RS_percentile + 8×trend + 7×vcp_score + near-high bonuses` (ranking only).
- Fundamentals (C/A/I): Yahoo fields when present; otherwise **not verified**. No invented numbers.
- Strict qualifies this run: **14**; stretch in top 12: **0**.

## Ranked table (strongest → weakest)

| Rank | Ticker | Company | Last | RS%ile | RS 126d vs Nifty | RS 63d vs Nifty | % from 52w hi | VCP | Score | Stretch? |
|-----:|--------|---------|-----:|-------:|-----------------:|----------------:|--------------:|----:|------:|----------|
| 1 | CASTROLIND | CASTROL INDIA LIMITED | 197.38 | 83.1 | +15.9% | +11.7% | -2.1% | 7 | 149.7 | qualify |
| 2 | LAURUSLABS | LAURUS LABS LIMITED | 2002.50 | 99.5 | +87.4% | +32.4% | -3.2% | 7 | 148.8 | qualify |
| 3 | KOTAKBANK | KOTAK MAHINDRA BANK LTD | 437.00 | 94.5 | +22.0% | +20.1% | -2.4% | 6 | 147.8 | qualify |
| 4 | DRREDDY | DR. REDDY S LABORATORIES | 1239.00 | 76.0 | +9.2% | +10.2% | -9.9% | 7 | 136.2 | qualify |
| 5 | COFORGE | COFORGE LIMITED | 1908.80 | 98.9 | +55.3% | +35.2% | -5.3% | 4 | 134.9 | qualify |
| 6 | DLF | DLF LIMITED | 663.25 | 82.5 | +16.9% | +7.3% | -14.9% | 5 | 133.1 | qualify |
| 7 | HAL | HINDUSTAN AERONAUTICS LTD | 4875.00 | 87.4 | +19.5% | +12.0% | -4.4% | 4 | 130.0 | qualify |
| 8 | FEDERALBNK | FEDERAL BANK LTD | 347.80 | 88.0 | +25.3% | +3.9% | -6.4% | 4 | 129.7 | qualify |
| 9 | ICICIBANK | ICICI BANK LTD. | 1398.50 | 67.2 | +8.4% | +2.5% | -4.4% | 5 | 127.9 | qualify |
| 10 | PERSISTENT | PERSISTENT SYSTEMS LTD | 5740.50 | 86.3 | +15.4% | +18.0% | -12.5% | 4 | 127.9 | qualify |
| 11 | PETRONET | PETRONET LNG LIMITED | 290.40 | 80.3 | +12.2% | +9.3% | -10.2% | 5 | 124.1 | qualify |
| 12 | TECHM | TECH MAHINDRA LIMITED | 1829.10 | 96.7 | +29.6% | +22.7% | -0.3% | 1 | 114.4 | qualify |

## Per-stock writeups

### 1. CASTROLIND — CASTROL INDIA LIMITED

- **Chart**: `charts/CASTROLIND.png`
- **Last close (2026-10-22)**: ₹197.38 | 52w high ≈ ₹201.67 (-2.1% away)
- **RS (vs Nifty 50)**: percentile **83.1**; RS_126d **+15.90%**, RS_63d **+11.70%** (windows 126 & 63 trading days). Absolute stock 126d=+8.2%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=195.9, EMA50=193.1, EMA200=189.4
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈42.5% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈42.1% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈3159899 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 83 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈16.9% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 4.3% < 40d 8.9% < 60d 9.2%); constructive higher lows (10d rolling-min proxy); rough pivot / breakout reference ≈ ₹201.67 (52w high; not a formal Minervini pivot count).

### 2. LAURUSLABS — LAURUS LABS LIMITED

- **Chart**: `charts/LAURUSLABS.png`
- **Last close (2026-10-22)**: ₹2002.50 | 52w high ≈ ₹2069.20 (-3.2% away)
- **RS (vs Nifty 50)**: percentile **99.5**; RS_126d **+87.39%**, RS_63d **+32.37%** (windows 126 & 63 trading days). Absolute stock 126d=+79.7%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=2011.4, EMA50=1926.1, EMA200=1532.1
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈125.5% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈125.2% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈1426505 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 99 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈34.1% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 4.8% < 40d 11.6% < 60d 16.2%); constructive higher lows (10d rolling-min proxy); rough pivot / breakout reference ≈ ₹2069.20 (52w high; not a formal Minervini pivot count).

### 3. KOTAKBANK — KOTAK MAHINDRA BANK LTD

- **Chart**: `charts/KOTAKBANK.png`
- **Last close (2026-10-22)**: ₹437.00 | 52w high ≈ ₹447.95 (-2.4% away)
- **RS (vs Nifty 50)**: percentile **94.5**; RS_126d **+22.04%**, RS_63d **+20.11%** (windows 126 & 63 trading days). Absolute stock 126d=+14.4%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=431.4, EMA50=419.5, EMA200=408.4
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈22.5% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈22.5% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈25768097 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 95 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈47.2% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 10.8% < 40d 11.0% < 60d 15.2%); constructive higher lows (10d rolling-min proxy); rough pivot / breakout reference ≈ ₹447.95 (52w high; not a formal Minervini pivot count).

### 4. DRREDDY — DR. REDDY S LABORATORIES

- **Chart**: `charts/DRREDDY.png`
- **Last close (2026-10-22)**: ₹1239.00 | 52w high ≈ ₹1375.70 (-9.9% away)
- **RS (vs Nifty 50)**: percentile **76.0**; RS_126d **+9.19%**, RS_63d **+10.20%** (windows 126 & 63 trading days). Absolute stock 126d=+1.5%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=1216.3, EMA50=1206.8, EMA200=1235.0
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈-68.7% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈-68.7% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈2139681 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 76 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈53.8% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 5.9% < 40d 9.4% < 60d 9.8%); constructive higher lows (10d rolling-min proxy); rough pivot / breakout reference ≈ ₹1375.70 (52w high; not a formal Minervini pivot count).

### 5. COFORGE — COFORGE LIMITED

- **Chart**: `charts/COFORGE.png`
- **Last close (2026-10-22)**: ₹1908.80 | 52w high ≈ ₹2014.60 (-5.3% away)
- **RS (vs Nifty 50)**: percentile **98.9**; RS_126d **+55.33%**, RS_63d **+35.18%** (windows 126 & 63 trading days). Absolute stock 126d=+47.6%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=1876.8, EMA50=1822.2, EMA200=1651.6
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈63.4% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈30.9% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈2156560 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 99 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈59.9% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 12.4% < 40d 15.7% < 60d 17.8%); rough pivot / breakout reference ≈ ₹2014.60 (52w high; not a formal Minervini pivot count).

### 6. DLF — DLF LIMITED

- **Chart**: `charts/DLF.png`
- **Last close (2026-10-22)**: ₹663.25 | 52w high ≈ ₹779.50 (-14.9% away)
- **RS (vs Nifty 50)**: percentile **82.5**; RS_126d **+16.85%**, RS_63d **+7.26%** (windows 126 & 63 trading days). Absolute stock 126d=+9.2%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=663.2, EMA50=660.2, EMA200=654.7
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈10.3% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈10.1% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈3278224 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 83 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈14.2% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 6.9% < 40d 10.6% < 60d 10.6%); rough pivot / breakout reference ≈ ₹779.50 (52w high; not a formal Minervini pivot count).

### 7. HAL — HINDUSTAN AERONAUTICS LTD

- **Chart**: `charts/HAL.png`
- **Last close (2026-10-22)**: ₹4875.00 | 52w high ≈ ₹5099.00 (-4.4% away)
- **RS (vs Nifty 50)**: percentile **87.4**; RS_126d **+19.54%**, RS_63d **+12.02%** (windows 126 & 63 trading days). Absolute stock 126d=+11.9%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=4825.7, EMA50=4784.5, EMA200=4595.7
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈14.9% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈14.9% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈689458 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 87 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈16.3% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 9.2% < 40d 10.0% < 60d 11.4%); rough pivot / breakout reference ≈ ₹5099.00 (52w high; not a formal Minervini pivot count).

### 8. FEDERALBNK — FEDERAL BANK LTD

- **Chart**: `charts/FEDERALBNK.png`
- **Last close (2026-10-22)**: ₹347.80 | 52w high ≈ ₹371.70 (-6.4% away)
- **RS (vs Nifty 50)**: percentile **88.0**; RS_126d **+25.29%**, RS_63d **+3.91%** (windows 126 & 63 trading days). Absolute stock 126d=+17.6%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=334.7, EMA50=335.8, EMA200=310.9
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈51.1% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈45.5% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈8972681 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 88 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈60.6% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 9.5% < 40d 11.7% < 60d 15.8%); rough pivot / breakout reference ≈ ₹371.70 (52w high; not a formal Minervini pivot count).

### 9. ICICIBANK — ICICI BANK LTD.

- **Chart**: `charts/ICICIBANK.png`
- **Last close (2026-10-22)**: ₹1398.50 | 52w high ≈ ₹1463.10 (-4.4% away)
- **RS (vs Nifty 50)**: percentile **67.2**; RS_126d **+8.41%**, RS_63d **+2.52%** (windows 126 & 63 trading days). Absolute stock 126d=+0.7%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=1364.8, EMA50=1371.9, EMA200=1363.6
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈22.3% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈22.1% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈12176650 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 67 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈59.2% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 7.9% < 40d 11.8% < 60d 12.1%); rough pivot / breakout reference ≈ ₹1463.10 (52w high; not a formal Minervini pivot count).

### 10. PERSISTENT — PERSISTENT SYSTEMS LTD

- **Chart**: `charts/PERSISTENT.png`
- **Last close (2026-10-22)**: ₹5740.50 | 52w high ≈ ₹6563.50 (-12.5% away)
- **RS (vs Nifty 50)**: percentile **86.3**; RS_126d **+15.39%**, RS_63d **+18.04%** (windows 126 & 63 trading days). Absolute stock 126d=+7.7%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=5647.8, EMA50=5533.0, EMA200=5433.5
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈-25.4% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈-26.3% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈682193 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 86 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈45.5% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 14.8% < 40d 14.8% < 60d 14.9%); rough pivot / breakout reference ≈ ₹6563.50 (52w high; not a formal Minervini pivot count).

### 11. PETRONET — PETRONET LNG LIMITED

- **Chart**: `charts/PETRONET.png`
- **Last close (2026-10-22)**: ₹290.40 | 52w high ≈ ₹323.40 (-10.2% away)
- **RS (vs Nifty 50)**: percentile **80.3**; RS_126d **+12.23%**, RS_63d **+9.30%** (windows 126 & 63 trading days). Absolute stock 126d=+4.5%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=290.9, EMA50=288.1, EMA200=282.6
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈35.1% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈35.1% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈2227148 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 80 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈27.3% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: clear range contraction (20d range 5.0% < 40d 6.5% < 60d 8.2%); rough pivot / breakout reference ≈ ₹323.40 (52w high; not a formal Minervini pivot count).

### 12. TECHM — TECH MAHINDRA LIMITED

- **Chart**: `charts/TECHM.png`
- **Last close (2026-10-22)**: ₹1829.10 | 52w high ≈ ₹1834.70 (-0.3% away)
- **RS (vs Nifty 50)**: percentile **96.7**; RS_126d **+29.56%**, RS_63d **+22.66%** (windows 126 & 63 trading days). Absolute stock 126d=+21.9%.
- **Trend**: above EMA50=yes, EMA200=yes, EMA21 rising=yes; EMA21=1629.4, EMA50=1589.1, EMA200=1530.4
- **CANSLIM**:
  - **C** Current quarterly earnings: Yahoo earningsQuarterlyGrowth≈32.7% (rough, not audited IBD C)
  - **A** Annual earnings growth: Yahoo earningsGrowth≈32.5% (rough annual YoY proxy)
  - **N** New high / product / leadership: near/at 52-week high area (price leadership / new-high proxy); product/news catalyst **not verified**
  - **S** Supply/demand: ADV≈3910244 shares (20d avg Yahoo volume); float tightness **not verified**
  - **L** Leader vs laggard: RS percentile 97 in this liquid universe; industry group rank **not verified**
  - **I** Institutional sponsorship: Yahoo heldPercentInstitutions≈44.3% (coarse; not IBD sponsorship quality)
  - **M** Market direction: CORRECTION risk (below EMA200)
- **VCP notes**: ranges 20d/40d/60d = 22.9% / 23.0% / 22.8%; rough pivot / breakout reference ≈ ₹1834.70 (52w high; not a formal Minervini pivot count).

## Data limitations

- Session **2026-10-22** using last available cash close **2026-10-22** (NSE open that day; yfinance EOD).
- Price/volume via yfinance; some symbols may fail/delist aliases.
- Download gaps / short history (4): LTIM.NS:short(0), MCDOWELL-N.NS:short(0), TATAMOTORS.NS:short(0), ZOMATO.NS:short(0)
- Earnings and institutional % are Yahoo snapshots when available — **not** audited CANSLIM IBD fundamentals; often incomplete.
- RS percentile is internal to this liquid universe, not official IBD RS Rating.
- VCP stages are heuristic from range contraction, not manual chart annotation of each contraction.
- Not investment advice; for daily screening only.

---
*Generated 2026-10-22 from yfinance EOD as-of 2026-10-22.*