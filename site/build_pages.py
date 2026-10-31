"""Write the static page shells. Data and layout live in site/js."""
import os

PAGES = [
    ("index.html", "today", "Today"),
    ("top-stocks.html", "top", "Top stocks"),
    ("buy-setups.html", "buysetups", "Buy setups"),
    ("scorecard.html", "scorecard", "Stock scorecard"),
    ("watchlist.html", "watchlist", "Watchlist and portfolio"),
    ("alerts.html", "alerts", "Alerts"),
    ("backtest.html", "backtest", "Backtest"),
    ("growth.html", "growth", "Growth"),
    ("quality.html", "quality", "Quality"),
    ("dividend.html", "dividend", "Dividend"),
    ("wheel.html", "wheel", "Wheel (stocks only)"),
    ("vcp.html", "vcp", "VCP"),
    ("canslim.html", "canslim", "CANSLIM"),
    ("box.html", "box", "Box breakout"),
    ("flag.html", "flag", "Flag breakout"),
    ("qullamaggie.html", "qullamaggie", "Qullamaggie breakout"),
    ("marios.html", "marios", "Marios breakout"),
    ("breakdowns.html", "breakdowns", "Breakdowns"),
    ("volume.html", "volume", "High volume"),
    ("leaders.html", "leaders", "Leaders"),
    ("52-week.html", "week52", "52-week"),
    ("options.html", "options", "Debit spreads"),
    ("earnings-calendar.html", "calendar", "Calendar"),
    ("earnings-heatmap.html", "heatmap", "Strength heatmap"),
    ("earnings-cards.html", "cards", "Report cards"),
    ("put-call.html", "putcall", "Put/call ratio"),
    ("walls.html", "walls", "Put and call walls"),
    ("analysts.html", "analysts", "Analyst ratings"),
    ("thirteen-f.html", "thirteen", "13F tracker"),
    ("aaii.html", "aaii", "AAII"),
    ("insiders.html", "insiders", "Insider trading"),
    ("headlines.html", "headlines", "Headline sentiment"),
    ("xly-xlp.html", "xly", "XLY/XLP"),
    ("financials.html", "financials", "Summary"),
    ("earnings-tracker.html", "tracker", "Earnings tracker"),
    ("company-financials.html", "company", "Company financials"),
    ("dividend-fundamentals.html", "divfund", "Dividend fundamentals"),
    ("sector-rotation.html", "rotation", "Sector rotation"),
    ("macro.html", "macro", "Macro screener"),
    ("sector-macro.html", "secmacro", "Sector macro scores"),
    ("historical-pe.html", "histpe", "Historical P/E"),
    ("breakouts.html", "breakouts", "52-week breakouts"),
    ("trends.html", "trends", "Trends"),
    ("pullbacks.html", "pullbacks", "Pullbacks"),
    ("gainers.html", "gainers", "Gainers and losers"),
    ("breadth.html", "breadth", "Breadth"),
    ("sector-performance.html", "secperf", "Sector performance"),
    ("heatmaps.html", "heatmaps", "Heatmaps"),
    ("updates.html", "updates", "Data updates"),
    ("help.html", "help", "Help"),
]

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0B0F17">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Nick's Stock Desk">
<title>{title} · Nick's Stock Desk</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 22 22'%3E%3Crect rx='6' width='22' height='22' fill='%237C9CFF'/%3E%3C/svg%3E">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<link rel="stylesheet" href="css/desk.css">
</head>
<body data-page="{pid}">
<div id="app"></div>
<script src="vendor/papaparse.min.js"></script>
<script src="vendor/chart.umd.min.js"></script>
<script src="js/desk.js"></script>
<script src="js/pages.js"></script>
</body>
</html>
"""

def main():
    root = os.path.dirname(os.path.abspath(__file__))
    for filename, pid, title in PAGES:
        path = os.path.join(root, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE.format(title=title, pid=pid))
    print(len(PAGES), "pages")

if __name__ == "__main__":
    main()
