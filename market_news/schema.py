"""Expected desk inputs and the brief JSON shape.

Cursor must verify these paths on the live desk (they matched main as of 2026-11-05).
"""

# Desk files this pack READS (already produced by stock_desk.py — do not re-fetch Yahoo).
INPUT_FILES = {
    "market_today": "data/market_today.csv",       # one-row snapshot (SPY/QQQ/VIX/breadth/PCR)
    "sectors": "data/sectors.csv",                 # sector ETF day % (XLK, XLE, XLP, …)
    "sector_performance": "data/sector_performance.csv",  # equal-weight sector day % (fallback)
    "macro_screener": "data/macro_screener.csv",   # optional past US releases
    "meta": "data/meta.json",                      # price_as_of / updated_pt
}

# Desk files this pack WRITES.
OUTPUT_FILES = {
    "brief": "data/market_brief.json",
    "history": "data/market_brief_history.json",
}

# market_today.csv columns used (others ignored).
# Optional dia_day_pct / dow_day_pct: used in the why line when present; otherwise
# Dow-heavy sector ETFs (XLF + XLI) stand in — never a new Yahoo fetch.
MARKET_TODAY_FIELDS = [
    "spy_price", "spy_day_pct", "qqq_day_pct", "dia_day_pct", "dow_day_pct",
    "breadth_sma20", "breadth_sma50", "breadth_sma100", "breadth_sma200",
    "breadth_sma50_week_ago", "advancers", "decliners", "universe_n",
    "highs_52w", "lows_52w",
    "put_call", "put_call_ma5", "put_call_zone", "put_call_name", "vix",
    "fred_dgs10", "fred_t10y2y", "xly_xlp",
    "updated_pt", "price_as_of", "data_status",
]

# Master switch + one on/off switch per v2 piece (all default on).
FEATURE_FLAG = "market_news"
FEATURE_FLAGS_V2 = (
    "market_news_why_detail",      # (a) 2–3 sentence why line
    "market_news_more_headlines",  # (b) 5–7 ranked headlines
    "market_news_card_layout",     # (d) nicer card layout
    "market_news_tips",            # (e) what-it-means-for-me tips
)

# Cause tags (locked product list).
CAUSE_TAGS = (
    "rates",
    "jobs",
    "oil",
    "election",
    "ai_mood",
    "war",
    "earnings_season",
    "inflation",
)

# Trusted publishers (prefer these; drop duplicates).
TRUSTED_SOURCES = (
    "Federal Reserve",
    "Board of Governors of the Federal Reserve System",
    "U.S. Bureau of Labor Statistics",
    "Bureau of Labor Statistics",
    "BLS",
    "White House",
    "The White House",
    "U.S. Congress",
    "Congress.gov",
    "Reuters",
    "Associated Press",
    "AP",
    "AP News",
    "NPR",
)

DISCLAIMER = (
    "Research only. Not a recommendation to buy or sell. "
    "This desk never places trades. Market-wide news brief only — no single-stock picks."
)

SCHEMA_VERSION = 2
