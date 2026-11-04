# Trading Floor rules

The Trading Floor is a page (`site/trading-floor.html`, page id `tradingfloor`) where six desk roles
talk through today's top picks in plain words. It is research only: it never places an order, never
calls a broker, and sends no alerts or notifications.

This file is the full rule book, so another desk (for example the India desk) can rebuild the exact
same thing. Code: `trading_floor.py`. Wiring: `load_trading_floor()` in `stock_desk.py`. Tests:
`tests/test_trading_floor.py`. Output: `data/trading_floor.csv`. Headline cache:
`cache/trading_floor_news.csv`.

## Switches

- `features.trading_floor` (true): the whole page. Off writes an empty `trading_floor.csv` with the
  headers, makes no headline requests, hides the menu item, and the page says "Turned off in Settings".
- Every number below is in the `trading_floor` block of `config.json` and shows in Settings as
  `trading_floor.<group>.<key>`. Each role has `on` (off means that role votes 0 and says
  "Off in Settings"), and each check has its own `*_check` switch.

## Which stocks

1. The Buy setups list, in that page's own order (broken out today first, then the most scanners
   agreeing, then nearest the entry, then the highest score).
2. If that is shorter than `max_stocks` and `fill_from_scanners` is on: stocks that are READY or
   BROKEN OUT today on at least `fill_min_scanners` of the pattern scanners (VCP, Box, Flag,
   Qullamaggie, Marios, EP, CANSLIM; rows marked Too wide are left out, the same as Buy setups).
   Their entry is the strongest scanner's buy point, and the stop and target come from the same
   `setups.buy_levels` rule Buy setups uses. Ordered broken out first, then most scanners, then strength.
3. At most `max_stocks` in all.

| key | value |
| --- | --- |
| max_stocks | 15 |
| fill_from_scanners | true |
| fill_min_scanners | 2 |

## Facts every role reads (no new downloads)

All from the daily bars the desk already saved (`cache/ohlcv.csv.gz`) and the files it already built.

- price = last close; day change = last close vs the close before.
- MA10, MA20, MA50 = simple averages of the last 10, 20, 50 closes; "% over MAn" = price / MAn - 1.
- run = % change over the last `sentiment.run_days` sessions.
- up streak = closes in a row higher than the close before.
- gap = today's open vs yesterday's close.
- volume ratio = today's volume / the average of the `scout.avg_days` (50) sessions before today.
  This is the same 50-day number the High volume page uses (`setups._prior_avg`).
- volume streak = days in a row with volume above that average.
- entry, stop, target, risk %, reward/risk = the levels already on Buy setups (target = Target 1).
- market = Buy setups' `market_ok` (SPY above its 50 and 200-day averages, 50 above 200).
- next earnings = `next_earnings` from `scores.csv`.

## Headlines (News)

- Fresh = published within `news.fresh_days` days of the price date (the as-of date, not the clock).
- With `news.name_match` on, a headline counts only if it names the ticker or the first distinctive
  word of the company name (stored feeds sometimes file unrelated stories under a ticker).
- At most `news.max_headlines` per stock, newest first.
- Source order: the desk's own stored headlines (`cache/news.csv`, the headline sentiment feed) first.
  Only picks with no fresh desk headline use `cache/trading_floor_news.csv`.
- That cache is filled from the free Google News RSS search (no key): one request per pick that has
  no desk headline, query `"<company>" OR <ticker> stock when:<fresh_days>d`, at
  `news.google_per_second` (1) per second, `news.google_timeout_s` (15 s) timeout, no retries.
  Only on the full after-close run, at most once per day (the `trading_floor_news` stamp), never on
  hourly or offline runs. So at most `max_stocks` (15) requests a day, usually fewer. No Yahoo request
  is added. Rows older than `news.keep_days` (14) are dropped from the cache.
- A failed request is soft: that stock says "No fresh headlines found" and the Skeptic counts it.

| key | value |
| --- | --- |
| news.on | true |
| news.fresh_days | 3 |
| news.max_headlines | 5 |
| news.name_match | true |
| news.google_news | true |
| news.google_per_second | 1 |
| news.google_timeout_s | 15 |
| news.keep_days | 14 |

## The roles and their points

Each of the five voting roles gives +1, 0, or -1. The Chief does not vote; it adds them up.

### 1. News: why it is moving

- Tone of each fresh headline uses the desk's existing word list (`scoring.headline_tone`:
  beat, raise, upgrade, record, surge, jump, approval, win are positive; miss, downgrade, lawsuit,
  probe, investigation, recall, plunge, layoff, fraud, cut are negative; both or neither is 0).
- Sum of tones > 0: **+1**. Sum < 0: **-1**. Sum = 0: **0**. No fresh headline: **0** and the line
  says "No fresh headlines found".

### 2. Scout: unusual volume

- ratio >= `scout.hot_ratio` (1.5) and the day closed up: **+1** (buyers showing up).
- ratio >= 1.5 and the day closed flat or down: **-1** (selling).
- ratio < `scout.thin_ratio` (0.7): **-1** (thin).
- otherwise, if `scout.streak_check` and volume above normal `scout.streak_days` (3) or more days in
  a row: **+1**.
- otherwise **0**. No volume on file: **0**.

| key | value |
| --- | --- |
| scout.on | true |
| scout.avg_days | 50 |
| scout.hot_ratio | 1.5 |
| scout.thin_ratio | 0.7 |
| scout.streak_check | true |
| scout.streak_days | 3 |

### 3. Charts: entry, stop, target

- **Veto (-1)** when entry, stop, or target is missing, or not stop < entry < target.
- **Veto (-1)** when `charts.veto_below_stop` is on and the price is at or under the stop.
- **+1** when reward/risk >= `charts.min_reward_risk` (2.0) and risk % <= `charts.max_risk_pct` (8.0).
- otherwise **0**.

| key | value |
| --- | --- |
| charts.on | true |
| charts.min_reward_risk | 2.0 |
| charts.max_risk_pct | 8.0 |
| charts.veto_below_stop | true |

### 4. Skeptic: the case against

One objection for each of these (each has its own switch):

- `no_news_check`: no fresh headline (only while News is on).
- `thin_volume_check`: volume ratio < `thin_volume_ratio` (0.8).
- `extended_ma_check`: price >= `max_above_ma20_pct` (10%) over MA20, or else >= `max_above_ma50_pct`
  (25%) over MA50 (one objection at most).
- `extended_entry_check`: price >= `max_above_entry_pct` (5%) over the entry (chasing).
- `market_check`: SPY not in an uptrend (Buy setups' market_ok is "no").
- `earnings_check`: next earnings 0 to `earnings_days` (7) calendar days after the as-of date.

Points: no objections **+1**, one **0**, two or more **-1**.
**Hard no** when there are `hard_no_objections` (3) or more objections, or the price is
`hard_no_above_entry_pct` (10%) or more over the entry.

| key | value |
| --- | --- |
| skeptic.on | true |
| skeptic.no_news_check | true |
| skeptic.thin_volume_check | true |
| skeptic.thin_volume_ratio | 0.8 |
| skeptic.extended_ma_check | true |
| skeptic.max_above_ma20_pct | 10.0 |
| skeptic.max_above_ma50_pct | 25.0 |
| skeptic.extended_entry_check | true |
| skeptic.max_above_entry_pct | 5.0 |
| skeptic.market_check | true |
| skeptic.earnings_check | true |
| skeptic.earnings_days | 7 |
| skeptic.hard_no_objections | 3 |
| skeptic.hard_no_above_entry_pct | 10.0 |

### 5. Sentiment: is the crowd too hot

From price, volume, and the headline count only (no social or paid feeds). One hot flag each:

- `run_check`: up `run_pct` (15%) or more over `run_days` (5) sessions.
- `ma10_check`: `max_above_ma10_pct` (8%) or more over MA10.
- `ma20_check`: `max_above_ma20_pct` (12%) or more over MA20.
- `gap_check`: today's open `gap_pct` (5%) or more over yesterday's close.
- `streak_check`: `up_streak_days` (6) or more up closes in a row.
- `buzz_check`: `buzz_headlines` (5) or more fresh headlines.

Points: no flags **+1** (calm), one flag **0** (warming up), `hot_flags` (2) or more **-1** (too hot).

| key | value |
| --- | --- |
| sentiment.on | true |
| sentiment.run_check | true |
| sentiment.run_days | 5 |
| sentiment.run_pct | 15.0 |
| sentiment.ma10_check | true |
| sentiment.max_above_ma10_pct | 8.0 |
| sentiment.ma20_check | true |
| sentiment.max_above_ma20_pct | 12.0 |
| sentiment.gap_check | true |
| sentiment.gap_pct | 5.0 |
| sentiment.streak_check | true |
| sentiment.up_streak_days | 6 |
| sentiment.buzz_check | true |
| sentiment.buzz_headlines | 5 |
| sentiment.hot_flags | 2 |

### 6. Chief: the call

total = News + Scout + Charts + Skeptic + Sentiment (from -5 to +5).

1. Charts veto: **SKIP**.
2. total >= `verdict.buy_min_total` (2) and no Skeptic hard no: **BUY**.
3. total >= `verdict.wait_min_total` (0): **WAIT** (this includes a +2 or better held back by a hard no).
4. otherwise: **SKIP**.

The Chief's line names the call, the total, and which roles were for (+1) and against (-1).

| key | value |
| --- | --- |
| verdict.buy_min_total | 2 |
| verdict.wait_min_total | 0 |

## The page

- A short "What this page does" box at the top, KPI cards (stocks debated, BUY, WAIT, SKIP, with
  fresh news), and an All / BUY / WAIT / SKIP filter.
- One card per stock, BUY first, then WAIT, then SKIP, highest total first: ticker, company, the
  call, the total, then the Chief's line and one line per role with its points. Charts veto and
  Skeptic hard no show as small red tags. The News line links to the headline when there is one.
- Tap the stock (or Chart) to open the same price chart the scanner rows use, with Entry (amber),
  Stop (red), and Target (green) lines and the desk's moving-average colors (MA10 green, MA20
  orange, MA50 blue, MA150 yellow, MA200 red). "Open in Chart Viewer" opens the Buy setups list
  (or All scanner stocks for a cross-scanner pick) at that stock.
- Menu: Overview, right under Buy setups. It is a summary page, not a screener, so it is not in the
  Technical / Fundamental split.
- Layout: one column of cards on a phone, two on an iPad, three on a wide screen.

## Output columns (`data/trading_floor.csv`)

rank, ticker, company, sector, pick_source, setup_sources, best_status, price, price_as_of, day_pct,
entry, stop, target1, risk_pct, reward_risk, dist_to_entry_pct, volume_ratio, volume_streak, ma10,
ma20, ma50, pct_above_ma10, pct_above_ma20, pct_above_ma50, run_pct, up_streak, gap_pct,
headline_count, headline, headline_link, headline_source, news_pts, news_line, scout_pts,
scout_line, charts_pts, charts_line, charts_veto, skeptic_pts, skeptic_line, skeptic_objections,
skeptic_hard_no, sentiment_pts, sentiment_line, total, verdict, chief_line, data_status, note,
disclaimer.
