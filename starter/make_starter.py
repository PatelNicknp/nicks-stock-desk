"""Build the Google-Sheet starter workbook. Formulas only. No live data inside the file."""
import os
import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://raw.githubusercontent.com/PatelNicknp/nicks-stock-desk/main/data/"
TABS = [
    "scores", "score_details", "market_today", "sectors", "breadth_history",
    "alerts", "score_changes", "portfolio", "portfolio_summary", "watchlist",
    "prices", "news", "scanner_growth", "scanner_quality", "scanner_dividend", "scanner_wheel",
    "scanner_vcp", "scanner_canslim", "scanner_box", "scanner_flag", "scanner_leaders",
    "earnings_calendar", "earnings_heatmap", "earnings_cards", "earnings_history",
    "put_call", "option_walls", "analyst_ratings", "institutional_13f", "aaii_sentiment",
    "insider_trading", "headline_sentiment", "xly_xlp",
    "financials_summary", "earnings_tracker", "company_financials", "dividend_scanner",
    "macro_screener", "sector_macro", "historical_pe",
    "breakouts", "trends", "pullbacks", "gainers_losers", "sector_performance", "heatmaps",
    "freshness", "updates_log", "help", "settings", "universe",
    "backtest_summary", "backtest_buckets", "backtest_equity", "backtest_yearly", "backtest_notes",
]

def main():
    wb = openpyxl.Workbook()
    setup = wb.active
    setup.title = "Setup"
    setup["A1"] = "Nick's Stock Desk"
    setup["A2"] = "Research only. This workbook does not place trades."
    setup["A3"] = "Each tab loads one CSV with IMPORTDATA. After you upload the file to Google Sheets, use Extensions > Apps Script and paste apps_script/Refresh.gs so the Desk menu can reload them."
    setup["A4"] = "Base URL"
    setup["B4"] = BASE
    setup["A5"] = "If a tab says the resource was not found, the files are not on the main branch yet. Wait until the pull request is merged."
    for name in TABS:
        ws = wb.create_sheet(name)
        ws["A1"] = '=IMPORTDATA("%s%s.csv")' % (BASE, name)
    out = os.path.join(ROOT, "data", "Nick_Stock_Desk_Starter.xlsx")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    wb.save(out)
    print(out)

if __name__ == "__main__":
    main()
