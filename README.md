# Nick's Stock Desk

A stock research desk for Nick. It scores stocks, writes the tables, and stops there.

It does not place trades. It does not call a broker. The wheel page is a stock screen. Put and call walls are a mood gauge. The Options page is education on debit spreads, not an order. Every options card says education, not financial advice.

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
- READY: 8 of 8 and at least two tightening pullbacks, and the close is still at or under the buy point (the high of the latest contraction). The score is written as "8 of 8" so a spreadsheet does not treat it as a date.
- BROKEN OUT today: that same setup, and today's close crossed above the buy point on volume above 1.5 times the 50-day average.
- WATCHING: 8 of 8, and either one tightening pullback so far, or two or more with the close above the buy point without a 1.5 times volume cross today, or a trade still open from a buy that printed at 8 of 8 (it stays listed if the score drops later, and the reason says so). A one-pullback stock is never READY or BROKEN OUT, so it never feeds Buy setups. An open trade is never READY (READY means not bought yet): if it dips back under the buy point it stays WATCHING with `in_trade` yes, and the reason says it dipped.
- A stock is listed only at 8 of 8. `vcp.show_weaker_trend` in `config.json` (off by default) brings back stocks under 8 of 8, labeled `WATCHING (trend not 8/8)` and listed last. Those rows never feed Buy setups, Leaders, or sector rotation.
- Exit, once a buy prints: stop 7% under that bar's close, moved to breakeven after a gain of 2.5 times the initial risk, sell part at 20%, trail is a close under the 20-day average after three days in the trade, and a 25% jump in 10 days is a climax warning rather than the target.

What is not a separate rule, or not a perfect copy:

- The on-chart labels, the score table, the volume triangles, and the distance box are display. The scan does not need them.
- Before a buy prints, the stop and target columns apply the same 7% and 20% to the pivot. The indicator itself waits and uses the breakout bar's close. After a buy, the columns match that close, including a stop that has moved to breakeven.
- A tie for the high or the low is not a swing. That is how TradingView's pivot function works.
- Rule 8 uses SPY, which is the indicator's default. SPY is lined up on the stock's sessions. If SPY has no bar that day, the prior SPY close is used. A holiday can make that one session differ from TradingView.
- Prices are the split-adjusted daily bars already in the cache. A TradingView chart on a different adjustment can disagree by a few cents.
- The page leaves off every symbol under 8 of 8. With `vcp.show_weaker_trend` on, a weaker name needs two tightening pullbacks, a live trade, or one pullback with the template at least 6/8. The indicator still draws on every symbol.
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

### 52-week highs and lows

Switch: `scanner_52w`, on by default. The page is `52-week.html`. It reads the cached daily high, low, close, and volume, plus the score, verdict, sector, and index tags already on the desk. It does not call Yahoo.

The 52-week high and low are the highest high and the lowest low of the last 252 sessions, including that session. A new high today means the close is at or above the highest high of the prior 252 sessions. A new low today means the close is at or below the lowest low of those sessions. An intraday poke through the old high does not count unless the close holds it. Near the high means the close is within 5% of the 52-week high. That is the zone Minervini prefers. A high on volume is a new high with volume at least 1.5 times the 50-day average (`W52_VOL_MULT` in `setups.py`). `highs_lows_history.csv` counts those names each session and is backfilled from the same cache, so the chart has more than a year of history before the next download.

### Buy setups

Switch: `buy_setups`, on by default. A second switch, `buy_setups.market_filter`, is also on by default. The page is `buy-setups.html`. It reads the VCP, box, flag, and CANSLIM files, the scores, the 52-week file, and the cached closes. It does not call Yahoo. Research list, not a recommendation. This desk never places trades and it does not send alerts.

A name qualifies when one of those scanners is READY or BROKEN OUT today, the verdict is BUY, the close is above the 50-day and the 200-day averages, and the risk from the entry to the stop is 8% or less. Entry is the buy point of the strongest scanner that agrees. VCP uses the Minervini pivot. The stop is the tighter of 7% under that entry or the setup's own stop. Target 1 is 20% above the entry, or 20% above the breakout close. Target 2 is the entry plus three times the dollar risk. With the market filter on, the list is empty unless SPY's close is above its 50-day and 200-day averages and the 50-day is above the 200-day. QQQ is shown the same way and does not decide the list. The page can still show the hidden names greyed.

### Breakdowns

Switch: `scanner_breakdown`, on by default. The page is `breakdowns.html`. It reads the cached daily high, low, close, and volume. It does not call Yahoo.

The trend is the close under the 50-day average, the 50-day under the 200-day, and the 200-day not higher than it was 20 sessions ago. The base is the longest window of 20 to 60 sessions, ending yesterday, whose high-to-low range is at most 10% of the middle, whose first and last closes drift by at most 5%, and whose second half is tighter than its first half. BROKEN DOWN today is a close under that low on volume at least 1.4 times the 50-day average. WATCHING is a close within 3% above that low, or a close under it without that volume. The chart line is the base low. The stop is the base high. The target is the entry minus twice the dollar risk from the entry up to the base high. A broken-down name uses today's close as the entry. A name that is still above the low uses the base low.

### Company one-liners

Switch: `company_blurbs`, on by default. Every drop-down row chart, the scorecard, the earnings tracker, and company financials show one plain-English line under the stock's name, such as "Makes iPhones and Macs and runs the App Store." The lines live in `data/company_blurbs.csv` (ticker, blurb). It is a static file written by hand. The hourly job does not fetch, rewrite, or delete it, and the site loads it once per visit. A ticker with no line shows nothing. Add a row there when a new name joins the universe.

Switch: `scanner_descriptions`, on by default. Every scanner page (Top stocks, Buy setups, the 12 Scanners pages, Options, Sector rotation, and the 7 Technicals pages) opens with a short "What this scanner does" (or "What this page does") box, styled like the India desk. Tabbed pages (52-week, High volume, Options) add a second "This tab" box that changes with the tab, and multi-part pages (Sector rotation, the 52-week chart, Options skipped) get a short line above each part. The text lives in `DESC` in `site/js/pages.js` and follows the rules in `setups.py`, `tables.py`, and `scoring.py`. Thresholds that come from settings (growth, quality, dividend, wheel, BUY score) are read from `data/settings.csv`, so the text follows the config. No data file or download changes.

### High volume

Switch: `scanner_volume`, on by default. The page is `volume.html`, under Scanners. The file is `data/scanner_volume.csv`, built in `setups.scan_volume` from the cached daily close, high, low, and volume. It does not call Yahoo and adds no request. Volume ratio is today's volume divided by the average of the 50 sessions before today. Rows are written from 1.5 times so the page can filter 1.5x, 2x (default), 3x, and 5x, with an Up / Down / All direction filter. Tabs: Volume spike today; Up or down on volume (BUYING when the close is up on the spike, SELLING when down); Unusual volume streak (3 or more sessions in a row above the prior 50-day average, with the streak length); Quiet before a move (10-day average volume under 0.6 times the 50-day average while the close is within 5% of the 63-session high and above the 50-day average). A name whose last bar is older than SPY's is skipped. The row chart adds an amber 50-day average volume line on the volume bars.

### Options

Switch: `options`, on by default. The page is `options.html`, under its own Options menu group, with Calls and Puts tabs. Education, not financial advice. The desk does not place a trade and it does not call a broker.

Calls are debit spreads for the first 15 names on the buy-setup list, in that list's order, including names the market filter greys out. Those stay greyed on the Calls tab. Puts are debit spreads for the first 15 breakdowns, with BROKEN DOWN today ahead of WATCHING.

Expiry is 45 to 60 days, falling back to 30 to 75. The long strike is about 0.55 to 0.65 delta. The short strike is about 0.30 delta, or the strike nearest the setup target when that target is closer to the stock than the 0.30-delta strike. For calls the target is buy-setup target 1. For puts it is the breakdown target. The debit has to be at most 40% of the width. When it is not, the long strike walks toward the short strike until it fits. A name is skipped, with one plain reason, when earnings fall on or before expiry, when at-the-money implied vol is more than 1.3 times the 20-day realized vol, when either leg has open interest under 500 or a bid-ask wider than 10% of the mid (or wider than $0.10 when the mid is under $1), when the stock is under $10, or when average volume is under 1 million.

Price Check solves implied vol from the mid and compares the debit with a blend of the 20-day realized vol, the 60-day realized vol, and at-the-money implied vol. CHEAP is under 0.9 times that fair value. FAIR is 0.9 to 1.2. OVERPAYING is above 1.2. The score runs from 0 to 100. Liquidity is A, B, or C from the worse leg. The exit is a double, or the stock at the short strike, or the setup failing (a close under the buy-setup stop or the 50-day average for calls, a close back above the breakdown level for puts), and the spread is closed by 21 days to expiry. Sizing is the contract count for a $2k, $5k, and $10k account at about 2% to 5% of the debit.

Quotes are one delayed Cboe request per ticker, only for those names, with a pause of about a second and a half. Raw chains stay in `cache/options_chains/` and are not committed. A full run refreshes them. An hourly run refreshes them only around 10:30 ET and 3:30 ET, once per window. The risk-free rate is the Treasury 3-month yield, with a fallback. Greeks are computed in `options/`. If Cboe fails, the last good chain is kept and the page shows its as-of time. A failure here does not stop the rest of the update. `options_spreads_check.csv` is the same math in a small file for a cross-check. It is not a sheet tab.

### Sector rotation

The sector rotation page uses the 11 SPDR sector ETFs and SPY already in the price cache. It does not add a Yahoo request. Dollar, oil, and gold are not in that cache and they are not in the two FRED files (the 10-year yield and the 10-year minus 2-year spread), so the page lists those three as missing.

RS is the ETF close divided by SPY on daily, weekly, or monthly bars. RS-Ratio is 100 plus the z-score of the smoothed RS versus its rolling mean. RS-Momentum is 100 plus the z-score of the change in RS-Ratio. A flat window has z-score 0, so it sits at 100. 100 counts as the strong side of each axis. This is a desk calculation, not the commercial JdK indicator. The windows are `sector_rotation.windows` in `config.json` (daily 10/40/5/40, weekly 6/26/4/26, monthly 3/12/2/12).

The 0–100 score blends relative strength versus SPY over 21, 63, and 126 sessions, breadth above the 50-day and 200-day averages, names within 5% of a 252-session high, buy setups, the average desk score, the share of BUY verdicts, and a weekly quadrant bonus. Weights are `sector_rotation.weight.*`. A missing factor is dropped and the rest are renormalized. It is not treated as zero. The rate notes are general tendencies, not a forecast. The page does not send a notification.

## Update schedule (New York market time)

The update follows New York time all year, Monday to Friday: hourly at 10:15, 11:15, and so on through 17:15 ET, and the full run at 18:30 ET. That is 7:15 AM to 2:15 PM and 3:30 PM Pacific, in summer and winter. GitHub cron only knows UTC, so `update.yml` lists the UTC times for both EDT and EST (`15 14-22 * * 1-5` and `30 22,23 * * 1-5`). The first step, `watchdog.py guard`, works out which cron fired, converts it to New York time, and stops the run in a few seconds, before any data step, unless it is one of those slots. The 18:30 ET slot is the full run. So there is still exactly one update per slot and the Yahoo traffic does not change. Manual runs are never skipped and are full runs unless you pick `hourly`.

## Missed updates (self-heal)

Switch: `self_heal_schedule`, on by default. GitHub sometimes skips or delays scheduled runs. `.github/workflows/watchdog.yml` runs at 7, 22, 37, and 52 minutes past the hour on weekdays, from 14:00 UTC to 00:59 UTC the next day, which covers the update hours in both EDT and EST. It runs `watchdog.py check`, which reads the update workflow's recent runs with the built-in GITHUB_TOKEN and reads this switch from `config.json`. Expected slots are the New York slots above. It does nothing when the switch is off, when an update is queued or running, or when the latest slot already has a run. It starts one update only when that slot is at least 20 minutes past, at most 3 hours old, and the last real update started more than 75 minutes ago. A run that the guard stopped (the other DST cron) is not a real update. The make-up uses the slot's own mode: `hourly`, or `full` for 18:30 ET. A failed run counts as having run, so it is not retried. Both workflows have a concurrency group, so runs never overlap. The guard also makes a late cron and a make-up for the same slot collapse into one run, whether or not the switch is on. If the guard cannot read the run list, the update runs as it always did. Run the watchdog by hand from the Actions tab. `dry_run` is on by default and only prints the decision. The update does not chain into another run when it finishes, because that could loop and add Yahoo traffic.

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
