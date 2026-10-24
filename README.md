# Nick's Stock Desk

A stock research desk for Nick. It scores stocks, writes the tables, and stops there.

It does not place trades. It does not call a broker. It does not pick option contracts. The wheel page is a stock screen. Put and call walls are a mood gauge.

## How the numbers get to the screen

```text
GitHub Action (stock_desk.py on a schedule)
        |  writes CSVs
        v
data/*.csv on GitHub
        |  Desk menu copies each file into a tab
        v
Google Sheet
        |  one tab per page
        v
Looker Studio (dark theme, one page per CSV)
```

The sheet and Looker do no math that matters. The Python job does the work so the pages stay fast.

## The universe

Three lists, deduped to one row per ticker:

- S&P 500, from Wikipedia, cached in `cache/sp500.csv`
- Nasdaq-100, from Wikipedia's list of NASDAQ-100 companies, cached in `cache/ndx100.csv`
- The growth names in `config.json`

`index_membership` reads `SP500`, `NDX100`, `Growth`, or a combination such as `SP500 / NDX100`. Looker should filter that column with Contains. Each list has a switch under `indexes` in `config.json` (`sp500`, `ndx100`, `growth`). Turning one off drops names that are only in that list. A name that is also in a list that is still on stays, and the tag still shows every list it belongs to. Holdings and the watchlist are always scored. If Wikipedia fails, the saved list is reused and the updates log says CACHED.

## The score

Each piece is +1, 0, or -1 against that company's own recent history. A missing piece is left blank. It is not stored as 0 and it does not move the score.

Lower is better: forward P/E, trailing P/E, price/sales, debt/equity, price/free cash flow.
Higher is better: revenue growth, EPS growth, return on equity, dividend yield.

Within 5% of the company's own 3-year average is a flat 0. That band is `scoring.flat_band_pct` in `config.json`.

Also added, when we have them:

| Piece | Range | What it uses |
| --- | --- | --- |
| Trend | +1 / 0 / -1 | Price versus the 20-day and 50-day averages |
| Oscillator | +1 / 0 / -1 | RSI-14 rising and between 45 and 70 is +1. 75 or above, or 30 or below, is -1 |
| Analyst rating | +2 to -2 | Yahoo recommendation mean. +2 needs a strong score and at least 5 analysts |
| 13F trend | +1 / 0 / -1 | Shares increased versus shares decreased in the latest Nasdaq holdings summary |
| Insider | +1 / 0 / -1 | Open-market buys versus sells over three months |
| Earnings | +1 / 0 / -1 | Latest earnings versus the estimate. Revenue versus estimate is not in the free feed, so it is left blank |
| Sector | +1 / 0 / -1 | Sector ETF versus the S&P 500 over three months, outside a 2% band |

The desk score is the sum of the pieces we actually have. `scores.csv` has every component in its own column. `score_details.csv` is the same breakdown in a long list for the scorecard.

Forward P/E has no free history. Its baseline is the 3-year average of year-end trailing P/E. The column `forward_pe_avg_basis` says so.

The industry column is the middle value of the other stocks in the same sector on this desk. It needs at least four peers. It is not a paid industry database, and it is not added into the score a second time.

BUY, HOLD, and AVOID are research labels. A high score that is extended, in a downtrend, or missing most of its financials is labeled HOLD instead of BUY. Entry, stop, and the trade target are a plan for study. The analyst target, the price/free-cash-flow target, the PEG-style target, and the blend of those are separate valuation levels.

## Pattern scanners

Five more pages, each with its own switch in `config.json`: `scanner_vcp`, `scanner_canslim`, `scanner_box`, `scanner_flag`, `scanner_leaders`. They read the price file and the daily fundamental cache. They do not call Yahoo, SEC, or Nasdaq. If QQQ is not already in the price file, the CANSLIM market line says QQQ is not verified, and the job does not download it to fill the hole.

Every row has the ticker, the index tags, a status of READY, WATCHING, or BROKEN OUT today, a pivot, a stop, a target, a strength score, a plain-English reason, and a freshness flag. FRESH means the last bar is SPY's latest session and the history is long enough. PARTIAL means that session is present but the history is short. STALE means the last bar is older than SPY's latest session. A later one-off bar, such as VIX, does not move that date. A missing fundamental is the words `not verified`, never a made-up number.

### VCP

Source of truth: `reference/nicks_minervini_with_exit_strategy.pine`, using the indicator's default settings.

- Trend template, all 8 points: price above the 150 and 200, the 150 above the 200, the 200 higher than 20 sessions ago, the 50 above the 150 and 200, price above the 50, at least 30% above the 52-week low, within 25% of the 52-week high, and ahead of SPY over both 126 and 252 sessions.
- A contraction is a swing high followed by a swing low. Swings use 4 bars left and 3 bars right, so a turn confirms 3 sessions later. A pullback under 3%, or shorter than 2 bars, is ignored. A lower high and a lower low extend the same contraction. The base starts at the highest swing high unless a later high beats it by more than 5%. The live count is the latest run of tightening pullbacks, at most 4.
- READY: 8/8 and at least two tightening pullbacks, and the close is still at or under the buy point (the high of the latest contraction).
- BROKEN OUT today: that same setup, and today's close crossed above the buy point on volume above 1.5 times the 50-day average.
- Exit, once a buy prints: stop 7% under that bar's close, moved to breakeven after a gain of 2.5 times the initial risk, sell part at 20%, trail is a close under the 20-day average after three days in the trade, and a 25% jump in 10 days is a climax warning rather than the target.

What is not a separate rule, or not a perfect copy:

- The on-chart labels, the score table, the volume triangles, and the distance box are display. The scan does not need them.
- Before a buy prints, the stop and target columns apply the same 7% and 20% to the pivot. The indicator itself waits and uses the breakout bar's close. After a buy, the columns match that close, including a stop that has moved to breakeven.
- A tie for the high or the low is not a swing. That is how TradingView's pivot function works.
- Rule 8 uses SPY, which is the indicator's default. SPY is lined up on the stock's sessions. If SPY has no bar that day, the prior SPY close is used. A holiday can make that one session differ from TradingView.
- Prices are the split-adjusted daily bars already in the cache. A TradingView chart on a different adjustment can disagree by a few cents.
- The page leaves off symbols with no contraction. A single contraction is listed as WATCHING only when the template is at least 6/8. The indicator still draws on every symbol.
- Strength is the template (up to 80) plus 5 points per contraction, up to 4. The indicator does not define that score. It is only for sorting.

### CANSLIM

The method is `reference/canslim_vcp_nse_run.py` and `reference/canslim_vcp_nse_SCAN.md`, pointed at US stocks.

- Relative strength is the stock's return minus SPY's return over 126 and 63 sessions, blended 60/40, then ranked inside the liquid names on this desk. The NSE scan did this against the Nifty.
- Market direction uses the same three labels (confirmation, mixed, correction) from price versus the 21, 50, and 200 day averages. SPY is always the benchmark. QQQ is added when its prices are already cached. Both have to be constructive for a joint confirmation, and either one under its 200-day average is a correction. If QQQ is absent, the label follows SPY and QQQ stays not verified.
- Strict qualify is the NSE rule: above the 50 and 200, the 21-day average rising, RS percentile at least 55, and either the range-contraction score at least 2 or within 15% of the 52-week closing high.
- C is the latest reported quarter versus the same quarter a year earlier, from the cached SEC EPS. A is the latest year versus the prior year. I is whether cached institutional shares increased or decreased. If the two periods or the increase/decrease pair are missing, that letter is not verified.
- N's product or news catalyst, S's float, and L's industry-group rank are not verified. The NSE write-up left those the same way. S does show the 20-day average share volume. The liquidity line is still 200,000 shares.
- BROKEN OUT today means a strict name closed at a new high on volume above 1.5 times the 50-day average. READY means strict and within 5% of that high. Other strict or soft names are WATCHING.
- The pivot is the 52-week closing high, which is what the NSE scan used. It is not the VCP buy point. Stop and target are blank. That scan never set them. The reason mentions the 50-day average only as the line that would drop the trend qualify, not as an order.
- The NSE script kept a top 12 and backfilled with stretch names. This page lists every strict or soft name and marks `qualify` as `strict` or `soft`. It does not cut the list at 12.
- The 20/40/60 day range score on this page is the NSE heuristic. Nick's contraction count is the VCP page.
- Strength is the NSE ranking formula: `0.45 × RS percentile + 8 × trend + 7 × contraction score`, plus a small bonus for being near the high.

### Box and flag

These two are desk rules. They are not in the Pine script.

- Box: the longest window of 15 to 40 sessions, ending yesterday, whose high-to-low range is at most 10% of the middle and whose first and last closes drift by at most 5%. Pivot is the range high, stop is the range low, target is the range high plus the height of the range. BROKEN OUT today is a close above that high on volume above 1.5 times the 50-day average. READY is a close within 2% under the high.
- Flag: a rise of at least 15% in 3 to 12 sessions, then 3 to 15 sessions that do not make a higher high, retrace less than half the pole, and drift down or sideways. Pivot is the flag high, stop is the flag low, target is the flag high plus the pole height. The breakout test is the same volume rule.

### Leaders

A leader is a VCP that is READY or BROKEN OUT today, or a strict CANSLIM qualify, or both. One row per ticker. When both hit, the pivot, stop, and target come from the VCP rules, and strength is the average of the VCP strength and the RS percentile. A letter that was not verified on the CANSLIM page stays not verified here.

## Rate limits

Slow sources are fetched at most once per US session and reused on the hourly runs.

- Prices: one batched Yahoo download (`yfinance` multi-ticker), not one call per stock.
- SEC EDGAR company facts, Yahoo profiles and earnings dates, Nasdaq 13F summaries and insider counts, and option chains: once a day. Option chains cover the holdings, the watchlist, and the top scores only (about 40 names, nearest expiries), so the page stays small.
- Requests are spaced (SEC stays under 8 per second, under the SEC's 10 per second rule) with a User-Agent of `NickStockDesk research nicks-stock-desk@example.com`.
- A 429 or a dropped connection waits and retries with a longer pause each time (1.5s, 3s, 6s, 12s).
- If a source still fails, the previous file is kept and `updates_log.csv` says CACHED. If there is no previous file, the page gets one MISSING row and a plain-English note. Missing cells inside a row stay blank.

Hourly runs (`--hourly`) refresh prices and rebuild the tables from the cache. The after-close run and a manual run (`--full`) refresh the slow sources.

## What is intentionally missing

| Feed | What you will see | Why |
| --- | --- | --- |
| AAII sentiment | `aaii_sentiment.csv` is one MISSING row | AAII does not publish a free machine-readable survey. The number is not guessed. Use the put/call page. |
| Official S&P 500 P/E | `historical_pe.csv` column `official_sp500_pe` is blank and `official_status` is MISSING | No free official daily series is reliable here, and FRED is often blocked on GitHub runners. The chart that does draw is the median trailing P/E of the stocks on this desk. It is labeled as that. |
| FRED yields | Blank on `market_today.csv` when the log says MISSING or CACHED | The job tries. If GitHub blocks FRED, the rest of the desk still runs. |
| Revenue vs estimate | Earnings heatmap says `revenue n/a` | The free earnings feed has the EPS estimate and the reported EPS, not a revenue estimate. A missing revenue line is not called a mixed quarter. |
| Full 13F book | A summary plus the largest holders | Reprinting every fund makes the page slow. `institutional_13f.csv` is pre-aggregated. |

## Files

| Path | Role |
| --- | --- |
| `stock_desk.py` | The job |
| `scoring.py` | Score, verdicts, targets, alerts, backtest |
| `fundamentals.py` | SEC filing parser. A filing counts the day after it was filed |
| `netutil.py` | Rate gate, retry, once-a-day decision |
| `tables.py` | One table per Looker page |
| `setups.py` | VCP, CANSLIM, box, flag, and leaders. No network calls |
| `reference/` | Nick's Pine script and the NSE CANSLIM scan these pages follow |
| `config.json` | Feature switches, score lines, rate limits, growth names, 19 sector ETFs |
| `input/holdings.csv` | Shares and average cost. Example rows are marked `example=yes` |
| `input/my_watchlist.csv` | Extra tickers |
| `data/*.csv` | What the Sheet imports |
| `cache/` | Saved downloads so a failed run can fall back |
| `tests/` | Offline tests. They do not call the network |
| `.github/workflows/update.yml` | Schedule. A copy lives in `workflow_copy/update.yml` |
| `apps_script/Refresh.gs` | Sheet menu |
| `SETUP.md` | Click-by-click for Nick |
| `LOOKER_SPEC.md` | One section per page |

Turn a page off by setting its key to `false` in `config.json`. The CSV is still written, with headers only, so the Sheet formula does not break.

## Backtest

Once a month the job asks what the score would have been using only prices and filings that were already public, then looks at the next 1, 4, and 12 weeks. Analyst ratings, insider trades, 13F, and earnings surprise are not in the test, because there is no free history of those series. Trading costs of 0.1% each way are included. Today's membership list is used, so delisted stocks are missing and the test is tilted up. Read `backtest_summary.csv` column `headline`. If it says there is no clear edge, that is the result.

## Tests

```bash
pip install -r requirements.txt
python tests/test_net.py
python tests/test_scoring.py
python tests/test_fundamentals.py
python tests/test_job.py
python tests/test_setups.py
python tests/test_universe.py
```

A full refresh, from this folder:

```bash
python stock_desk.py --full
```
