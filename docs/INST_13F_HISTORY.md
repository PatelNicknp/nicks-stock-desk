# 13F fund-holder history (CANSLIM I)

CANSLIM's I wants more funds owning a stock each quarter. The desk now keeps a
per-stock, per-quarter count of 13F filers so that trend is on file.

## Data

Free SEC data only: the quarterly **Form 13F data sets**
(https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets). Each ZIP
holds every 13F filed in a date range (about one quarter of filing dates).
Requests send the desk's SEC User-Agent from `config.json` (`rate_limits.sec_user_agent`)
and run one at a time with a pause, far under the SEC's 10-requests-a-second limit.
Raw ZIPs go to `cache/bulk/13f/`, which is git-ignored; they are never committed.

Stored in the repo (`data/`):

| File | What |
| --- | --- |
| `inst_13f_history.csv` | `ticker, period, holders, shares, cusips, complete`. One row per universe stock per quarter. `holders` = distinct 13F filers (CIK) with a long share position; `shares` = total shares they report (put/call rows and bond principal left out). |
| `inst_13f_cusip_map.csv` | Every CUSIP looked up and the US ticker OpenFIGI gave (blank = no US listing found), so no CUSIP is asked twice. |
| `inst_13f_sets.json` | Which SEC ZIPs are already in the history. |

Which filing counts for a filer and quarter: the newest original 13F-HR or
RESTATEMENT amendment; NEW HOLDINGS amendments filed after it add positions;
13F notices are skipped. A quarter is `complete` when the ingested ZIPs cover the
45 days after quarter end (the 13F deadline). Only complete quarters are used.

## CUSIP to ticker

The free OpenFIGI mapping API (no key: 25 requests a minute, 10 CUSIPs each).
Every CUSIP held by at least 20 filers in some quarter is looked up with
`exchCode=US`; non-US issuers use CINS numbers (first character a letter, e.g.
Accenture `G1151C101`) and get a second pass as `ID_CINS` on any exchange,
keeping only US listings. Share classes come back as `BRK-B` style to match `universe.csv`.

Two free fallbacks fill the gaps OpenFIGI leaves:

- **Retired CUSIPs (continuity).** OpenFIGI does not map a CUSIP once it is retired,
  but many filers keep reporting it (Exxon's old `30231G102` still had about 3,900
  filers in June 2026 against 397 on the new `30233Q108`). An unmapped equity CUSIP is
  tied to a universe ticker when exactly one ticker shares its 6-character issuer code,
  or else its 13F issuer name, unless both were live in more than two of the same
  quarters or it never had a quarter of the ticker's holders. Holders are counted
  once across both CUSIPs.
- **Company name.** For a universe stock with no mapped CUSIP at all (OpenFIGI answered
  ONEOK and Qorvo with foreign listings only), the unmapped equity CUSIP whose 13F issuer
  name matches the universe company name is used.

### Match quality (backfill run Nov 15, 2026, universe of 2,500)

- 9,465 CUSIPs looked up (every CUSIP with 20+ filers in a quarter); 8,549 have a
  US ticker: 7,360 first pass, 1,145 CINS / any-exchange second pass, 27 retired CUSIPs
  (continuity), 17 by company name.
- 2,464 of 2,500 universe stocks have holder counts (2,463 in the June 2026 quarter).
  The 36 without are mostly recent IPOs, small or OTC-like names, and a few CUSIPs the
  free mapper does not know.
- Trend for the I check (2026Q1 to 2026Q2): 2,393 stocks (96%) have one (1,669 rising,
  256 flat, 468 falling); 34 are not verified because the count moved more than 50%
  (CUSIP changes and new listings); 73 lack two complete quarters.
- Check against the Nasdaq institutional-holder counts the desk already caches (520
  stocks): correlation 0.997 on a log scale, SEC count a median 12% lower (Nasdaq also
  counts non-13F holders), 98.8% within 25%.

## The I rule

`features.canslim_i_13f_trend` (on): I passes when `holders` in the newest complete
quarter is at least the quarter before, or has dropped by no more than
`canslim.i_flat_tolerance_pct` (2%). A bigger drop fails. A move of more than
`canslim.i_max_jump_pct` (50%) either way is "not verified": that is almost always a
CUSIP change (OpenFIGI does not map retired CUSIPs; Carnival went from about 1,000
holders on its old CUSIP to 988 on its new one, which would look like a 30x jump). Fewer than two back-to-back
complete quarters on file is "not verified" and does not fail the stock.
Off gives back the old Nasdaq bought-vs-sold check.

## Keeping it current

No new schedule or workflow. With `features.inst_13f_history` on, the normal
full update (stock_desk.py full mode) checks the SEC page once a day. Only when the
SEC has published a ZIP that is not in `inst_13f_sets.json` (about once a quarter,
a few weeks after each quarter's filing window) it downloads that ZIP plus the one
before it (late filers), adds the new quarter, maps any new CUSIPs, and the normal
commit saves the files. A failure keeps the saved files and is logged.

Manual steps, from the repo root (same results):

    python inst_history.py --update        # add the newest SEC ZIP if it is new
    python inst_history.py --backfill 6    # rebuild from the newest 6 ZIPs (new universe names, repairs)

Then commit `data/inst_13f_*`.

Timing note: the 13F deadline is 45 days after quarter end, and the SEC posts the
data set for each three-month filing window after it closes. So the newest
complete quarter usually lags by one quarter (on Nov 13, 2026 it is June 30, 2026;
the Sept 30 quarter arrives with the Sep to Nov 2026 ZIP, expected in December).
