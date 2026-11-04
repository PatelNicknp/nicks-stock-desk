# Trading Floor paper test rules (FAKE MONEY)

The Paper Test page (`paper-test.html`) follows the Trading Floor's BUY calls with a pretend
account, to see if the calls would have made or lost money. **It is fake money.** No real
order is ever placed, no broker is connected, no alert or notification is sent, and nothing
new is downloaded. It reads only what the daily full run already has: the Trading Floor file
of that run (`data/trading_floor.csv`) and the saved daily bars (open, high, low, close).
US desk only.

Code: `trading_floor_paper.py`. Tests: `tests/test_trading_floor_paper.py`.
Switch: `features.trading_floor_paper` (on). Settings: the `trading_floor_paper` block in `config.json`.

## Settings (all values)

| Setting | Value | Meaning |
|---|---|---|
| `start_cash` | 10000.0 | Fake dollars at the start. |
| `position_pct` | 10.0 | Each position is 10% of the starting cash: $1,000. |
| `max_open` | 10 | At most 10 positions open or waiting at once. |
| `time_stop_days` | 20 | Sell at the close of the 20th trading day held (the entry day is day 1). |
| `fractional_shares` | true | Buy fractional shares ($1,000 / open). Off buys whole shares only. |
| `share_decimals` | 4 | Fractional shares are rounded to 4 decimals. |
| `skip_if_held` | true | A BUY call is skipped when the stock is already held or waiting. |
| `skip_gap_past_plan` | true | A stock that opens at or under its stop, or at or over target 1, on the buy day is not bought. |

## Start

The test started with the first full run that had it: **Nov 3, 2026**, with $10,000 of fake
cash and SPY's Nov 3 close as the SPY starting point. It only moves forward. Nothing before the
start is replayed or backfilled.

## Entries (fill rule: next session's open)

1. Each daily full run (after the close) reads that day's Trading Floor. Every **BUY** row
   becomes a call, highest total first.
2. The call is skipped (with the reason shown on the page) when: it has no usable stop and
   target 1; the stock is already held or waiting; 10 positions are already open or waiting;
   or free fake cash (cash minus cash set aside for waiting calls) is under $1,000.
3. Otherwise it waits overnight. On the **next full run**, it is bought at **the next
   session's open**, read from that session's daily bar. It is never filled at a price that
   was known before the call was made.
4. If that open is already at or under the stop, or at or over target 1, it is **not
   filled**. If the stock has no bar on that session, it is not filled.
5. Shares = $1,000 / open, rounded to 4 decimals.

## Exits (checked on every daily bar from the entry day on)

Stop and target 1 are the Trading Floor's, **frozen on the day of the call**. Later calls do not
move them. The checks run in this order on each bar:

1. Opened at or under the stop: sold **at the open** ("Opened below the stop").
2. Opened at or over target 1: sold **at the open** ("Opened above target 1").
3. Touched both the stop and target 1 on the same bar: counted as **the stop**, sold at the stop
   price. A daily bar cannot say which came first, so the careful answer is used.
4. Touched the stop: sold at the stop price.
5. Touched target 1: sold at target 1.
6. Held 20 trading days (the entry day is day 1): sold **at that day's close** ("Time stop").

## Numbers

* Per trade: P&L in dollars and percent.
* Win rate: closed trades with a gain, over all closed trades. A trade with no gain counts as a loss.
* Average win and average loss, in dollars and percent.
* Total return of the fake account vs SPY buy-and-hold: the same $10,000 put into SPY at the
  start day's close.
* Max drawdown: the biggest drop of the fake account from its own high, on daily closes.
* A daily equity curve: cash plus open positions marked at each day's close.

## State and runs

* State is saved in `data/paper_trades.csv` (one row per call), `data/paper_equity.csv`
  (one row per trading day), and `data/paper_summary.csv` (the numbers and the bookmarks
  `last_bar` and `last_signal_date`).
* Only the daily full run (and the offline rebuild, which uses only saved data) changes them.
  Hourly runs leave them alone.
* A day's bar counts only after that session is over (after 16:15 ET). A manual full run
  during the session uses only the finished days before it and takes no BUY calls; the
  after-close run of that day does the rest.
* Running the same day twice changes nothing: bars up to `last_bar` are never processed
  again, and calls for `last_signal_date` are never added again.
* If a full run is missed, the next one catches up every missed trading day from the saved
  bars. The calls of a missed day are not recreated.
* Turning `features.trading_floor_paper` off hides the page, removes it from the menu, and
  stops the daily update. The saved files are left as they were.
* Changing `start_cash` after the start does not restart the test. To restart, delete the three
  paper files; the next full run starts again on its own day.
