# Set up Nick's Stock Desk

You do this once. After that, the files update themselves and you open the report.

This desk is research only. It will not place a trade, and it does not connect to a broker.

## 1. Turn on the automatic update

1. Open the GitHub repo `PatelNicknp/nicks-stock-desk` on your computer or iPad browser.
2. Tap **Actions**.
3. If GitHub asks you to enable Actions, tap the green button to enable them.
4. On the left, click **Update Nick's Stock Desk**.
5. Click **Run workflow**, leave the branch on `main`, and click the green **Run workflow** button.
6. Wait until the yellow dot turns green. The first run is the long one. It can take most of an hour because it reads filings for the whole S&P 500. Later runs during the day are shorter.

The schedule after that:

- A few times during the market day, prices refresh.
- Once after the close, the slow facts refresh (filings, analyst data, 13F, insiders, option walls).

If you do not see the workflow in the list, GitHub sometimes hides a workflow that was added in a pull request until it is on `main`. After the pull request is merged, look again. If it is still missing:

1. On GitHub, go to **Add file** > **Create new file**.
2. Name the file `.github/workflows/update.yml`.
3. Open `workflow_copy/update.yml` in the repo and copy the whole thing into the new file.
4. Commit it on `main`.
5. Come back to **Actions** and run it once by hand.

## 2. Make the Google Sheet

You only need one sheet. If you already uploaded the starter workbook, keep that file. You do not have to upload it again.

If you are starting fresh:

1. On your iPad or computer, open [Google Drive](https://drive.google.com).
2. Download `data/Nick_Stock_Desk_Starter.xlsx` from the repo (tap the file, then the download arrow).
3. In Drive, tap **New** > **File upload** and choose that workbook.
4. Double-tap it and choose **Open with Google Sheets**.
5. If Sheets asks, let it convert the file. You should see a tab named Setup and one tab for each page. The tabs only have headers until you run the refresh in the next step.

A blank Google Sheet also works. The refresh creates any tab that is missing.

## 3. Add the refresh menu

The sheet does not use IMPORTDATA. A script copies each file from GitHub into the tab with the same name. That avoids the "allow access" message and the size error on the price file.

1. In the sheet, tap **Extensions** > **Apps Script**. If you do not see Extensions, tap the three dots and look for it. On iPad, open the sheet in the browser (Safari or Chrome), not only the Sheets app, if the menu is missing.
2. Delete any code that is already in the editor, including an older copy of this script.
3. Open `apps_script/Refresh.gs` in the repo and paste the whole file in.
4. Tap the save icon. Name the project `Nick Stock Desk` if it asks.
5. Close the script tab and reload the sheet.
6. You should see a **Desk** menu. Tap **Desk** > **Refresh data now**.
7. The first time, Google asks you to allow the script. Review the prompt and tap **Allow**. It reads the public files on GitHub and writes this sheet. It does not send mail and it does not place a trade.
8. Wait until the Setup tab says the refresh finished. A big sheet can take a few minutes. If it pauses, leave it open. The script continues on its own. The time of the last refresh is in cell B6 on Setup. The sentence next to it is the status.
9. Empty cells mean the number was missing. They are not zeros.

To reload later, tap **Desk** > **Refresh data now** again. Then in Looker, tap the refresh icon on the report.

Optional: **Desk** > **Install hourly auto-refresh** reloads the sheet about once an hour. **Desk** > **Remove auto-refresh** turns that off. The GitHub files still update on their own either way.

If a tab says a file was not found, the pull request is not on `main` yet, or that run has not finished. Wait until the Action is green, then refresh again.

## 4. Put your real holdings in

The portfolio starts with example rows so the page is not blank. They are marked `example=yes`. Replace them.

1. On GitHub, open `input/holdings.csv`.
2. Tap the pencil to edit.
3. One row per stock you own. Columns are `ticker`, `shares`, `avg_cost`, `example`.
4. Use `no` in the example column for your real rows. Delete the sample rows when you are ready.
5. Commit the change. The next run picks it up. Nothing is sent to a broker.

The watchlist is `input/my_watchlist.csv`. One ticker per line is enough. A short note in the second column is optional.

Growth names that are not already in the S&P 500 or the Nasdaq-100 live in `config.json` under `growth_names`. Add a ticker there the same way if you want it scored every day.

The Nasdaq-100 is included already. In `config.json`, the `indexes` block turns each list on or off: `sp500`, `ndx100`, and `growth`. Set one to `false` and the next full run stops scoring names that are only in that list. On the Top stocks page, filter `index_membership` with Contains (`SP500`, `NDX100`, or `Growth`). A stock in two lists appears once, with both tags.

## 5. Build the Looker report

Do this on a computer if you can. Looker Studio is awkward on an iPad.

1. Open [Looker Studio](https://lookerstudio.google.com/).
2. **Create** > **Report**.
3. Choose **Google Sheets** and pick the sheet from step 2.
4. Add each tab as its own data source when a page needs it. The tab name matches the page in `LOOKER_SPEC.md`.
5. Follow `LOOKER_SPEC.md` from the top. Theme first, then the left navigation, then one page at a time. The VCP, CANSLIM, box, flag, and leaders pages are in that list. Each one has an on/off switch in `config.json`. Turning one off leaves the tab in place with headers only.
6. On every page, add a text box with this line: `Research only. Not a recommendation to buy or sell. This desk never places trades.`
7. When a cell is blank, leave it blank. Do not replace blanks with zero. The spec shows the color rules for the -2 to +2 score cells.

## 6. How to know it worked

Open the `updates_log` tab.

- **OK** means that source answered.
- **CACHED** means this run failed and the previous copy was used. The page is still usable. Check again after the next day.
- **MISSING** means there is no copy. Read the note. A few feeds are missing on purpose (AAII, the official S&P 500 P/E). The help tab explains those in plain English.

Then open the `scores` tab. You should see one row per stock, a score, a BUY / HOLD / AVOID label, and an entry zone. Stocks with thin data have a lower confidence and blank cells where a number was not available.

## 7. If a page looks wrong

1. Check `updates_log` for that source.
2. In the sheet, **Desk** > **Refresh data now**. When Setup says the refresh finished, in Looker tap the refresh icon on the report.
3. If the whole Action run is red, open the run and read the last lines. You do not need to fix code. Tell the assistant what the red text says.
