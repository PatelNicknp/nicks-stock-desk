# Looker Studio spec

Build one report. Dark theme, a left navigation, and one page per section below. Each page reads one Sheet tab. The tab has the same name as the CSV. The sheet is filled by the Desk menu in `apps_script/Refresh.gs` (see `SETUP.md`). Do not add IMPORTDATA formulas. Do not blend tabs to compute a score. The job already did that.

Research line, on every page, as a text box under the title:

`Research only. Not a recommendation to buy or sell. This desk never places trades. Stocks only, no option contracts.`

## Theme

| Item | Value |
| --- | --- |
| Report background | `#0B0F17` |
| Page and panel background | `#121826` |
| Text | `#E6EBF5` |
| Muted labels | `#8B96AD` |
| Grid lines | `#1E293B` |
| Up / positive | `#22C55E` |
| Down / negative | `#EF4444` |
| Hold / caution | `#F59E0B` |
| Links and the selected nav item | `#7C9CFF` |
| Font | Roboto, or Arial if Roboto is missing |
| Canvas | 1400 x 1800 to start. Let long tables scroll |
| Outer margin | 24 px |
| Card padding | 16 px |
| Chart background | same as the panel, no white cards |

Navigation style: fixed left, about 220 px, collapsible groups. The selected page uses the blue accent. Do not use Looker's default white theme.

## Shared color rules

Score points (`pts_*` columns and the `heat` column), conditional formatting on the table:

| Value | Fill | Text |
| --- | --- | --- |
| 2 or +2 | `#166534` | `#E6EBF5` |
| 1 or +1 | `#14532D` | `#E6EBF5` |
| 0 | `#283146` | `#E6EBF5` |
| -1 | `#7F1D1D` | `#E6EBF5` |
| -2 | `#B91C1C` | `#E6EBF5` |
| blank | no fill | show the text `n/a` with color `#D6A64A` |

Do not color a blank cell as zero. In the table's missing-data setting, display `n/a`, not `0`.

Return columns (`day_pct`, `week_pct`, `ret_*`, and the heatmap returns): diverging, red below zero, green above, midpoint zero, on the same dark panel. Do not reuse the -2..+2 scale for returns.

Verdict text colors: BUY `#22C55E`, HOLD `#F59E0B`, AVOID `#EF4444`.

## Left navigation

Overview

1. Today
2. Top stocks
3. Stock scorecard
4. Watchlist and portfolio
5. Alerts
6. Backtest

Scanners

7. Growth
8. Quality
9. Dividend
10. Wheel (stocks only)
11. VCP
12. CANSLIM
13. Box breakout
14. Flag breakout
15. Leaders

Earnings

16. Calendar
17. Strength heatmap
18. Report cards

Sentiment

19. Put/call ratio
20. Put and call walls
21. Analyst ratings
22. 13F tracker
23. AAII
24. Insider trading
25. Headline sentiment
26. XLY/XLP

Financials

27. Summary
28. Earnings tracker
29. Company financials
30. Dividend fundamentals

Macro

31. Sector rotation
32. Macro screener
33. Sector macro scores
34. Historical P/E

Technicals

35. 52-week breakouts
36. Trends
37. Pullbacks
38. Gainers and losers
39. Breadth
40. Sector performance
41. Heatmaps

System

42. Data updates
43. Help

## Page template

Unless a page says otherwise:

- Title on the left, the research line under it.
- A date chip bound to `market_today.updated_pt` (add that data source once and reuse the chip).
- A ticker drop-down (search enabled) when the table has a `ticker` column. Default: all.
- The table under the charts. Sort is specified per page.
- Hide `data_status`, `note`, and `disclaimer` from the main table. Put `note` in a one-line text box that shows when `data_status` is `MISSING` or `PARTIAL`. `PARTIAL` means a column is blank on every row. A blank is missing data, not a zero.

---

## 1. Today

Source: `market_today`. Also a small table from `sectors` (top 5 by `day_pct`) and `alerts` (latest 8).

Scorecards in one row:

- S&P 500 price and `spy_day_pct`
- Nasdaq-100 ETF day change, `qqq_day_pct`. Leave it blank when that cell is empty. Do not draw it as 0.
- How many names are labeled BUY, `buy_count`
- Breadth, `% above the 50-day` (`breadth_sma50`) with `breadth_sma50_week_ago` as the comparison. A blank cell is a missing reading, not 0.
- Advancers and decliners
- 52-week highs (`highs_52w`)
- Put/call zone (`put_call_zone`) and the 5-day average
- VIX
- 10-year yield (`fred_dgs10`) and the 10y-2y (`fred_t10y2y`). If those are blank, the card says `n/a`, not 0. FRED is often blocked.

Under that, a line from `breadth_history`: four lines, `% above 20 / 50 / 100 / 200`, last six months. A blank point is a session that did not have enough prices. Leave the gap. Do not plot it as zero.

A bar of `sectors.day_pct` for the 11 big sector ETFs (filter `ticker` in XLK, XLV, XLF, XLI, XLC, XLY, XLP, XLE, XLU, XLRE, XLB).

## 2. Top stocks

Source: `scores`.

Filter bar: verdict (multi-select, default BUY and HOLD), sector, confidence, and index membership. `sector` is one of the 11 GICS sectors. Industry stays in its own column and is not renamed.

`index_membership` is text such as `SP500`, `NDX100`, `Growth`, or `SP500 / NDX100` when a stock is in more than one list. Filter with **Contains**, not equals, so `SP500` still matches `SP500 / NDX100`. The same three tags are on the `universe` tab as `in_sp500`, `in_ndx100`, and `in_growth` (yes or no) if you would rather filter on a single flag. A holding that is not in any of the three lists is tagged `Focus`.

Table columns, in this order: rank, ticker, company, sector, score, verdict, reason, price, day_pct, timing, entry_low, entry_high, stop, trade_target, target_blended, confidence, missing_count.

Sort: score descending.

Color `score` with the point scale. Color `verdict` with the chip colors. Color `day_pct` with the return scale.

Do not show the component columns here. They are on the scorecard.

## 3. Stock scorecard

This is the single-stock page. Data sources: `scores` (filter to the ticker control), `score_details` (same ticker), `prices` (same ticker), `news` (same ticker), `earnings_history` (same ticker).

Header: ticker, company, sector, price, day change, verdict chip, confidence.

One sentence: `reason`.

Plan row: entry low, entry high, stop, trade target, reward/risk. If the label is AVOID, entry and trade target are blank on purpose.

Valuation row: `target_analyst` plus `target_analyst_kind`, `target_pfcf`, `target_peg`, `target_blended`, and `target_blend_n` so it is obvious when the blend used only one input.

Score row: five boxes, `pts_tech`, `pts_fin`, `pts_sent`, `pts_earnings`, `pts_sector`, using the point colors, and the total `score`.

Breakdown table from `score_details`: group_name, item, points_label, now_value, avg_value, vs_industry. Color `points`. Blank points show `n/a`. `points_label` is the words `plus 1`, `minus 1`, `zero`, or `n/a` (the numeric `points` column is the number). That file is only those columns plus `ticker`. The long disclaimer is not repeated on every row. The research line on the page covers it.

A second small table from `scores`, one row, the industry point columns (`pts_*_ind`). Caption: "Versus other stocks in this sector on the desk, not a paid industry set. Not added into the score again."

Chart from `prices`: close, sma20, sma50. Reference lines for entry_low, entry_high, stop, and trade_target (constant lines from the latest row).

News list: headline, publisher, published. Rows with `kind = desk_note` are the desk's own sentence, styled in the muted color so they are not mistaken for an article.

Earnings spark: last reports from `earnings_history`, surprise and `move_1d_pct`.

Footer facts: `fundamentals_basis`, `fundamentals_filed`, `fin_avg_years`, `forward_pe_avg_basis`, `missing_fields`.

## 4. Watchlist and portfolio

Two stacked panels.

Portfolio summary, source `portfolio_summary`: value, day P/L, total gain, average score, needs attention. If `example_warning` is not blank, show it in amber above the numbers.

Holdings table, source `portfolio`: ticker, shares, avg cost, price, value, gain, gain_pct, weight_pct, score, score_week_change, verdict, stop, status. Sort status so "Below stop", "Weakening", and "Earnings soon" are visually distinct (red, amber, blue). Color score with the point scale.

Watchlist, source `watchlist`: ticker, price, score, verdict, entry zone, distance_to_entry_pct, timing, note_input. Sort by score descending.

## 5. Alerts

Source: `alerts`, plus `score_changes` underneath.

Alerts table: ticker, kind, text, score, score_prev, verdict, verdict_prev, price. Hide rows where `kind` is `info` from the count, but show that single line when it is the only row ("no changes yet").

Score changes: ticker, score, score_prev, score_change, verdict, day_pct. Sort by the absolute change. Color `score_change` with the return scale (a drop is red).

Caption: "These are changes since the previous run. Nothing is emailed and nothing is sent to a broker."

## 6. Backtest

Sources: `backtest_summary`, `backtest_equity`, `backtest_buckets`, `backtest_yearly`, `backtest_notes`.

Top of the page: the `headline` where `is_headline` is `yes`. Large type. If it says there is no clear edge, do not decorate it with a green banner.

Three scorecards from that same headline row: top-20 yearly pace (`top20_cagr_pct`), S&P 500 pace (`spy_cagr_pct`), max drawdown (`top20_max_drawdown_pct`).

Line chart from `backtest_equity`: top20, spy, bottom20. The first row is 10,000 for each curve.

Table from `backtest_buckets`. Filter control for horizon (1w, 4w, 12w), default 12w. Sort buckets by `bucket_order` (1 through 6). The bucket text is `Scores 0 or below`, `Scores 1 to 3`, `Scores 4 to 5`, `Scores 6 to 7`, `Scores 8 to 9`, `Scores 10 or more`. Color `excess_pct` with the return scale. This is where a high-score bucket can be red. Leave it red.

Year table from `backtest_yearly`.

Notes table from `backtest_notes`, always visible, not behind a click. It is the list of limits (costs, no look-ahead for filings, what was left out, no delisted names).

## 7. Growth scanner

Source: `scanner_growth`. Default filter `passes = yes`. Columns: ticker, company, sector, price, score, verdict, rev_growth, eps_growth, rs_spy_3m, why. Sort by rev_growth descending. A control can show the names that did not pass.

## 8. Quality scanner

Source: `scanner_quality`. Default `passes = yes`. Columns: ticker, company, sector, roe, de, pts_roe, pts_de, score, verdict, why. Color the point columns.

## 9. Dividend scanner

Source: `scanner_dividend`. Default `passes = yes`. Columns: ticker, company, div_yield, div_yield_avg, pts_div_yield, score, verdict, why.

## 10. Wheel (stocks only)

Source: `scanner_wheel`. Default `passes = yes`.

Columns: ticker, company, sector, price, score, verdict, timing, rsi14, above_sma200, dollar_volume, why.

There is no strike, no expiry, no premium, and no contract symbol. Do not add one. The `why` text says this is not an option contract. Title the page "Wheel candidates (stocks only)".

## 11. VCP

Source: `scanner_vcp`. These rows follow Nick's TradingView indicator in `reference/nicks_minervini_with_exit_strategy.pine`. They are computed from the prices already on file. This page does not download anything.

Default filter: `status` is `READY` or `BROKEN OUT today`. A second control can show `WATCHING`.

Columns: ticker, index_membership, status, pivot, stop, target, trail, strength, trend_score, contractions, depths, reason, freshness.

Sort by status (broken out, then ready, then watching), then strength descending.

`trend_score` is the 8-point template, written `8 of 8` so a sheet does not turn it into a date. `r1` through `r8` are PASS or FAIL for the eight rules. Color PASS green and FAIL red. `pivot` is the buy point (the high of the latest contraction). `stop` is 7% under the buy price. `target` is 20% above it (the "sell part" level). `trail` is the 20-day average the indicator uses after a buy.

Title the page "VCP". Under the table, show `note`. It says the stop and target use the buy point until a buy prints, and that a tie is not a pivot.

## 12. CANSLIM

Source: `scanner_canslim`. Same letters as the NSE scan in `reference/canslim_vcp_nse_SCAN.md`, scored against SPY. QQQ is used for market direction only when that price is already in the file.

Default filter: `status` is `READY` or `BROKEN OUT today`, and `qualify` is `strict`.

Columns: ticker, index_membership, status, pivot, strength, qualify, c_quarterly_eps, c_status, a_annual_eps, a_status, n_pct_from_high, s_adv, l_rs_percentile, i_trend, m_market, m_qqq, reason, freshness.

Sort by strength descending.

Leave `stop` and `target` off the table. They are blank on purpose. A cell that says `not verified` stays as text. Do not replace it with zero. Color `i_trend` up green and down red. `m_qqq` will read `not verified` until QQQ is already in the price file.

## 13. Box breakout

Source: `scanner_box`.

Default filter: `status` is `READY` or `BROKEN OUT today`.

Columns: ticker, index_membership, status, pivot, stop, target, strength, range_days, range_width_pct, volume_ratio, reason, freshness.

Sort by strength descending. `pivot` is the range high, `stop` is the range low, and `target` is the range high plus the height of the range.

## 14. Flag breakout

Source: `scanner_flag`.

Default filter: `status` is `READY` or `BROKEN OUT today`.

Columns: ticker, index_membership, status, pivot, stop, target, strength, pole_pct, flag_bars, retrace_pct, volume_ratio, reason, freshness.

Sort by strength descending. `pivot` is the flag high, `stop` is the flag low, and `target` is the flag high plus the height of the pole.

## 15. Leaders

Source: `scanner_leaders`. This is the VCP page and the CANSLIM page on one row per ticker.

Default filter: `status` is `READY` or `BROKEN OUT today`.

Columns: ticker, index_membership, status, on_vcp, on_canslim, pivot, stop, target, strength, vcp_status, canslim_status, vcp_strength, canslim_strength, reason, freshness.

Sort by strength descending. When a name is on both scans, the buy point, stop, and target are the VCP ones. A CANSLIM-only row leaves stop and target blank.

## 16. Earnings calendar

Source: `earnings_calendar`.

Filter: `days_away` between 0 and 14 by default, plus a toggle for holdings (`owns = yes`).

Columns: ticker, company, next_earnings, when_hint, days_away, last_eps_actual, last_eps_estimate, last_surprise_pct, last_1d_move_pct, avg_1d_move_pct, n_past.

Color `last_1d_move_pct` and `last_surprise_pct` with the return scale. Blank move means the price history did not cover that session. Show `n/a`.

Caption: "The one-day move is the next session after a report that hit at or after 4pm Eastern, otherwise the session of the report. The average is the last eight reports."

## 17. Earnings strength heatmap

Source: `earnings_heatmap`.

Pivot: rows are tickers, columns are `quarter`, values are `heat`. Color `heat` with the point scale. The label field (`label`) is the tooltip or a second table. You will see `eps beat, revenue n/a` often. That is honest. Do not rename it to "double beat".

A double beat would require both lines. This free feed does not have the revenue estimate.

## 18. Earnings report cards

Source: `earnings_cards`.

Cards or a table: ticker, grade, summary, sources. Grade colors: A `#166534`, B `#14532D`, C `#283146`, D `#7F1D1D`, F `#B91C1C`. Blank grade means there was no history. Show `n/a`.

Caption: "Grades are a fixed rule on the last few earnings beats and revenue growth versus the company's own history. They are not a write-up from a person, and they are not a trade."

## 19. Put/call ratio

Source: `put_call`. Filter `name = EQUITY PUT/CALL RATIO`.

Line chart: `value` and `ma5`. Two constant reference lines from `fear_line` and `greed_line` (1.0 and 0.7 unless `settings` says otherwise).

Latest zone (`zone`) as a chip: Fear red, Greed green, Neutral muted.

Caption: "Market mood only. Not an option position."

## 20. Put and call walls

Source: `option_walls`.

Ticker drop-down, then expiry drop-down. Default the expiry filter to `nearest_expiry = true` (the first expiry on or after today for that ticker).

Bar chart: strike on the x-axis, open_interest on the y-axis, one series for calls and one for puts (green and red).

A two-row table where `is_wall = yes`: the strike with the most call open interest and the strike with the most put open interest.

Caption under the title, not optional: "Open interest by strike. Sentiment only. Not a contract to trade. Chains refresh once a day for the focus list, so most of the universe is not on this page."

If the page is the MISSING row, show the note and no chart.

## 21. Analyst ratings

Source: `analyst_ratings`.

Columns: ticker, company, analyst_mean, analyst_count, pts_analyst, target_analyst, target_analyst_kind, price, upside_pct. Sort by pts_analyst descending. Color `pts_analyst` with the point scale. Blank rating is `n/a`. `upside_pct` is the mean target divided by price, minus 1, in percent. It is blank when the mean target or the price is missing.

`upside_pct` may be blank. Do not calculate it inside Looker if the column is blank. Leave it.

## 22. 13F tracker

Source: `institutional_13f`.

Summary table, filter `row_type = summary`: ticker, increased_shares, decreased_shares, holders, ownership_pct, as_of, pts_institutional. Color the points.

Second table, filter `row_type = top_holder`, driven by the same ticker control: owner, shares, share_change, as_of.

Caption: "Summary of the latest public holdings file, plus the largest holders. Not every fund. Built this way so the page stays fast."

## 23. AAII

Source: `aaii_sentiment`.

This page is a MISSING state on purpose. Show `note` in the body text, large enough to read. Do not draw a fake bullish/bearish chart. Do not type in a number by hand.

Link text to the put/call page: "The free mood gauge is the put/call ratio."

## 24. Insider trading

Source: `insider_trading`.

Columns: ticker, buys_3m, sells_3m, pts_insider. Sort buys descending. Color the points. Blank counts are `n/a`, not zero buys.

Caption: "Open-market buy and sell counts over three months, from Nasdaq's public insider summary."

## 25. Headline sentiment

Source: `headline_sentiment`.

List: ticker, headline, publisher, published, tone, tone_note. Color `tone` with the point scale (1, 0, -1). The link column can be a URL field.

Caption: "Tone is a word rule on the headline (beat, upgrade, probe, layoff, and similar). It is not added into the desk score."

## 26. XLY/XLP

Source: `xly_xlp`.

Line chart: `ratio` and `ratio_sma50`. Latest `zone` as a chip (Risk on / Risk off).

Caption: "Consumer discretionary divided by consumer staples. Above the 50-day average of the ratio is labeled risk on."

## 27. Financials summary

Source: `financials_summary`.

Ticker control. Table: metric, direction, now_value, avg_3y, pts_vs_self, industry_median, pts_vs_industry.

Color both point columns with the point scale. Blank is `n/a`.

Caption: "Direction says whether a lower or a higher number earns the point. The industry median needs four peers."

## 28. Earnings tracker

Source: `earnings_tracker`.

Columns: ticker, earnings_date, eps_estimate, eps_actual, surprise_pct. Sort by earnings_date descending. Color surprise. A blank actual is a future date. Do not mark it as a miss.

## 29. Company financials

Source: `company_financials`.

Ticker control. Table by fiscal year: fy_end, revenue, gross_profit, op_income, net_income, eps, gross_margin, operating_margin, net_margin, fcf.

If gross profit was not in the filing, the margin cells are blank. Leave them blank. Do not show 0%.

Caption: "Annual figures from SEC filings. Margins are blank when the filing did not include that line."

## 30. Dividend fundamentals

Source: `dividend_scanner`. This is the full list, not only the names that pass the screen.

Columns: ticker, company, sector, price, div_yield, div_yield_avg, dps, pts_div_yield, verdict. Sort by div_yield descending. A yield of 0 can be real (the company does not pay). A blank yield means we could not tell. The freshness page separates those.

## 31. Sector rotation

Source: `sector_rotation`, `sector_rotation_tails`, `sector_rotation_history`, and `scores` for the stocks inside a sector.

Switch: `feature.sector_rotation` (default on).

Scatter chart, one point per SPDR sector ETF versus SPY. RS is the ETF close divided by SPY. RS-Ratio is 100 plus the z-score of smoothed RS versus its rolling mean. RS-Momentum is 100 plus the z-score of the change in RS-Ratio. This is a desk z-score, not the commercial JdK indicator. Daily windows are smooth 10, ratio 40, change span 5, momentum 40. Weekly is 6 / 26 / 4 / 26. Monthly is 3 / 12 / 2 / 12. A toggle switches daily, weekly, and monthly. Each sector draws a tail of the last 4, 8, or 12 points (default 8). Quadrants, with 100 counting as the strong side: Leading green top-right, Weakening yellow bottom-right, Lagging red bottom-left, Improving blue top-left. Tap a point to read the ticker, date, RS-Ratio, RS-Momentum, and quadrant.

Table sorted by `score` descending (rank 1 is the highest). Columns: score, quadrant_d, quadrant_w, quadrant_m, the 1/3/6 month relative-strength factors, breadth, near-high count, buy-setup count, desk average, BUY share, and `reason`. Weights are `sector_rotation.weight.*`. A missing factor is left out of the average. It is not zero. Tapping a row lists that sector's top stocks from `scores`, and the ticker links to the scorecard.

Macro card: trend of the 10-year yield (`dgs10_trend`) and the 10-year minus 2-year spread (`t10y2y_trend`) over about 63 observations, plus a static "historically tends to favor" line. Label it as general tendencies, not a forecast. Dollar, oil, and gold are not in the cache. Show them as missing. Do not invent a reading.

What changed: `change_daily` and `change_weekly`. A real move reads "Energy moved from Improving to Leading". `unchanged` means no move. History is `sector_rotation_history`, backfilled from the cached prices.

Caption: research only, no notification, and the z-score is not the commercial indicator.

## 32. Macro screener

Source: `macro_screener`.

Table: date, category, indicator, actual, forecast, surprise, signal. Color `signal` with the point scale.

Caption: "Signal is +1 when the surprise is in the direction that usually helps stocks (for unemployment and jobless claims, lower is the helpful direction). It is a label, not a forecast."

If the only row is MISSING, show the note. Do not invent a CPI number.

## 33. Sector macro scores

Source: `sector_macro`. Also show `sectors` if you want the price change next to the macro score. Keep them as two tables. Do not blend.

Columns: ticker, name, macro_growth, macro_inflation, macro_jobs, macro_score, plain_english. Color the four number columns with the point scale.

These weights are fixed in the job (for example, hotter inflation helps energy and hurts technology). The help page says they are a sketch.

## 34. Historical P/E

Source: `historical_pe`.

Line chart: `desk_median_trailing_pe`. Tooltip shows `n`.

A text box bound to `official_status`: it should read MISSING. Next to it, the note that this is the desk's median trailing P/E, not the official S&P 500 P/E.

Do not add a line for `official_sp500_pe`. It is blank.

## 35. 52-week breakouts

Source: `breakouts`.

Columns: ticker, company, sector, price, dist_52w_high_pct, volume_ratio, score, verdict. Sort by dist_52w_high_pct descending (closest to the high, or through it, first).

If the table's only row is the MISSING note, that means nobody is within 1% of a 52-week high today. That is a result, not a broken feed. The note says which.

## 36. Trends

Source: `trends`.

Columns: ticker, trend_label, sma_alignment, above_sma20, above_sma50, above_sma100, above_sma200, price, score.

Color the four `above_*` columns: 1 green, 0 red, blank `n/a`.

Filter chips for Uptrend, Downtrend, Mixed. Default Uptrend.

Uptrend means the price is above all four averages. Downtrend means it is below all four.

## 37. Pullbacks

Source: `pullbacks`. Default filter `passes = yes`.

Columns: ticker, company, price, rsi14, entry_low, entry_high, score, verdict, why.

Caption: "An uptrend (above the 50-day and the 200-day) with price back in the pullback or entry area, and RSI under 70."

## 38. Gainers and losers

Source: `gainers_losers`.

Two tables, or one table with a side filter. Gainers: `side = gainer`, sort day_pct descending. Losers: `side = loser`, sort day_pct ascending. Columns: ticker, company, sector, price, day_pct, score, verdict. Color day_pct.

## 39. Breadth

Source: `breadth_history`.

Line chart, four series: pct_above_sma20, pct_above_sma50, pct_above_sma100, pct_above_sma200. Last six months is enough. Y-axis 0 to 100.

Scorecards for the latest point of each line.

## 40. Sector performance

Source: `sector_performance`.

Table: sector, day_pct, week_pct, month_pct, month3_pct, ytd_pct, pct_above_sma50, score_avg, n. Color the return columns. This is equal-weight across the desk's stocks in that sector, not the ETF. The ETF view is the Top sectors numbers inside `sectors`.

## 41. Heatmaps

Source: `heatmaps`.

Table, one row per ticker: ret_1d, ret_1w, ret_1m, ret_ytd, and the four above-average flags. Color returns with the diverging scale. Color the flags 1 green / 0 red.

A sector drop-down filters the rows. Default all.

Optional second view: a pivot of average `ret_1d` by sector. If you build it, label it "average of the stocks above", so it is not confused with the ETF.

## 42. Data updates

Source: `updates_log`.

Table: checked_pt, source, status, latest, note. Sort by checked_pt descending.

Status colors: OK `#166534`, CACHED `#92400E`, MISSING `#7F1D1D`, text `#E6EBF5`.

No other decoration. This page is how you see whether a number is fresh.

## 43. Help

Source: `help`.

A two-column list: topic, plain_english. No upsells, no links to a course, no "unlock". The text already explains the score, the blanks, the backtest limits, and the feeds that stay MISSING.

`settings` can sit in a collapsed table at the bottom for the switches (`feature.*`) and the score lines (`scoring.*`). You do not need to chart it.

## Top sectors (lives under Today and as its own scroll on the sectors page)

Source: `sectors`. Nineteen ETFs.

Columns: ticker, name, day_pct, week_pct, month_pct, month3_pct, ytd_pct, rs_3m_pct, score_avg, n_stocks, pct_above_sma50, macro_growth, macro_inflation, macro_jobs, macro_score.

Color returns with the diverging scale. Color the macro columns with the point scale. If the macro cells are blank, show the note that the surprise feed was missing. Performance can still be on the page.

The nineteen names are the 11 SPDR sector ETFs plus semiconductors, biotech, regional banks, homebuilders, retail, oil and gas, aerospace and defense, and metals and mining.

## Field reminder

`prices.csv` is the scorecard chart only: the last 126 trading days (about half a year), one row per stock per day, columns `date`, `ticker`, `close`, `sma20`, `sma50`, `entry_low`, `entry_high`, `stop`, `trade_target`. Do not ask Looker to compute moving averages. The job keeps the longer daily history in `cache/ohlcv.csv.gz`. That cache is not a sheet tab.

`score_details.csv` is the scorecard breakdown only: `ticker`, `group_name`, `item`, `points`, `points_label`, `now_value`, `avg_value`, `vs_industry`.

`score_history.csv` is a memory file for the week-ago score. It is not a page. Do not add it as a data source. The refresh script does not copy it into the sheet.

After this change, in Looker, open the `prices` and `score_details` data sources and refresh the fields so removed columns drop off. The chart and the breakdown table use the columns that remain.
