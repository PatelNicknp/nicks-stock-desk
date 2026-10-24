"""Offline end-to-end: every page file exists, the score adds up, the wheel page has no contracts."""
import os, sys, json, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import stock_desk
import tables


def _facts_rows(ticker, revenue, eps, equity, debt, ocf, capex, dps, shares):
    rows = []
    for i, year in enumerate((2021, 2022, 2023, 2024)):
        end = "%d-12-31" % year
        filed = "%d-02-01" % (year + 1)
        scale = 1 + i * 0.15
        rows.append({
            "ticker": ticker, "frame": "CY%d" % year, "end": end, "filed": filed,
            "revenue": revenue * scale, "net_income": eps * shares * scale, "eps": eps * scale,
            "gross_profit": revenue * scale * 0.4, "op_income": revenue * scale * 0.2,
            "equity": equity, "debt": debt, "ocf": ocf * scale, "capex": capex,
            "dps": dps, "shares": shares,
        })
    return rows


def build_fixture(root):
    os.makedirs(os.path.join(root, "cache"), exist_ok=True)
    os.makedirs(os.path.join(root, "input"), exist_ok=True)
    shutil.copy(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"), os.path.join(root, "config.json"))
    # shrink the universe switch by replacing config growth and relying on universe cache
    cfg = json.load(open(os.path.join(root, "config.json")))
    cfg["growth_names"] = ["ZZZ"]
    cfg["holdings"] = [{"ticker": "AAA", "shares": 10, "avg_cost": 20, "example": "yes"}]
    cfg["watchlist"] = ["BBB"]
    json.dump(cfg, open(os.path.join(root, "config.json"), "w"))
    dates = pd.bdate_range("2023-01-02", "2025-06-30")
    names = ["AAA", "BBB", "CCC", "SPY", "XLK", "XLY", "XLP", "^VIX"]
    rows = []
    rng = np.random.default_rng(1)
    for t in names:
        px = 100.0
        if t == "AAA":
            px = 30.0
        for d in dates:
            drift = 0.001 if t == "AAA" else (-0.0004 if t == "BBB" else 0.0002)
            px = max(1.0, px * (1 + drift + float(rng.normal(0, 0.005))))
            rows.append({"date": str(d.date()), "ticker": t, "close": round(px, 2),
                         "high": round(px * 1.01, 2), "low": round(px * 0.99, 2), "volume": 2_000_000})
    pd.DataFrame(rows).to_csv(os.path.join(root, "cache", "ohlcv.csv.gz"), index=False, compression="gzip")
    uni = pd.DataFrame([
        {"ticker": "AAA", "company": "Alpha", "sector": "Information Technology", "in_sp500": "yes", "in_growth": "no"},
        {"ticker": "BBB", "company": "Beta", "sector": "Information Technology", "in_sp500": "yes", "in_growth": "no"},
        {"ticker": "CCC", "company": "Gamma", "sector": "Information Technology", "in_sp500": "yes", "in_growth": "no"},
    ])
    uni.to_csv(os.path.join(root, "cache", "universe.csv"), index=False)
    annual = []
    annual += _facts_rows("AAA", 100, 2.0, 80, 10, 30, 5, 0.5, 10)
    annual += _facts_rows("BBB", 100, 1.0, 40, 80, 8, 7, 0.0, 10)
    # CCC has no free cash flow
    annual += _facts_rows("CCC", 100, 1.5, 50, 20, np.nan, np.nan, 0.2, 10)
    pd.DataFrame(annual).to_csv(os.path.join(root, "cache", "annual.csv"), index=False)
    pd.DataFrame(columns=["ticker"]).to_csv(os.path.join(root, "cache", "quarters.csv"), index=False)
    info = pd.DataFrame([
        {"ticker": "AAA", "company": "Alpha", "sector": "Information Technology", "industry": "Software",
         "forward_pe": 12, "analyst_mean": 1.6, "analyst_count": 10, "target_mean": 50, "target_median": 52, "earnings_ts": ""},
        {"ticker": "BBB", "company": "Beta", "sector": "Information Technology", "industry": "Software",
         "forward_pe": 40, "analyst_mean": 4.2, "analyst_count": 8, "target_mean": 15, "target_median": 14, "earnings_ts": ""},
        {"ticker": "CCC", "company": "Gamma", "sector": "Information Technology", "industry": "Software",
         "forward_pe": "", "analyst_mean": "", "analyst_count": "", "target_mean": "", "target_median": "", "earnings_ts": ""},
    ])
    info.to_csv(os.path.join(root, "cache", "yahoo_info.csv"), index=False)
    holders = pd.DataFrame([
        {"ticker": "AAA", "inst_up": 100, "inst_down": 10, "holders": 20, "ownership_pct": 70, "as_of": "2025-03-31", "insider_buys": 2, "insider_sells": 0},
        {"ticker": "BBB", "inst_up": 5, "inst_down": 50, "holders": 10, "ownership_pct": 40, "as_of": "2025-03-31", "insider_buys": 0, "insider_sells": 6},
        {"ticker": "CCC", "inst_up": "", "inst_down": "", "holders": "", "ownership_pct": "", "as_of": "", "insider_buys": "", "insider_sells": ""},
    ])
    holders.to_csv(os.path.join(root, "cache", "holders.csv"), index=False)
    pd.DataFrame(columns=["ticker", "owner"]).to_csv(os.path.join(root, "cache", "holder_rows.csv"), index=False)
    earn = pd.DataFrame([
        {"ticker": "AAA", "earnings_dt": "2025-05-01 16:30:00-04:00", "eps_estimate": 0.5, "eps_actual": 0.6, "surprise_pct": 20},
        {"ticker": "AAA", "earnings_dt": "2025-08-01 16:30:00-04:00", "eps_estimate": 0.55, "eps_actual": "", "surprise_pct": ""},
    ])
    earn.to_csv(os.path.join(root, "cache", "earnings.csv"), index=False)
    stamps = {"sec_facts": "2099-01-01", "yahoo_slow": "2099-01-01", "holders": "2099-01-01",
              "universe": "2099-01-01", "news": "2099-01-01", "option_walls": "2099-01-01",
              "pcr": "2099-01-01", "econ": "2099-01-01"}
    # offline does not consult stamps for fetching, but write them anyway
    json.dump(stamps, open(os.path.join(root, "cache", "stamps.json"), "w"))
    json.dump({"0": {"cik_str": 1, "ticker": "AAA"}}, open(os.path.join(root, "cache", "company_tickers.json"), "w"))
    pd.DataFrame({"ticker": ["AAA"], "shares": [10], "avg_cost": [20], "example": ["yes"]}).to_csv(os.path.join(root, "input", "holdings.csv"), index=False)
    pd.DataFrame({"ticker": ["BBB"], "note": ["watch"]}).to_csv(os.path.join(root, "input", "my_watchlist.csv"), index=False)


def test_offline_job():
    root = tempfile.mkdtemp(prefix="desk-")
    try:
        build_fixture(root)
        os.environ["DESK_ROOT"] = root
        stock_desk.main(["--offline"])
        data = os.path.join(root, "data")
        for name in tables.COLS:
            path = os.path.join(data, name + ".csv")
            assert os.path.exists(path), name
            df = pd.read_csv(path)
            assert list(df.columns) == tables.COLS[name], name
        scores = pd.read_csv(os.path.join(data, "scores.csv"))
        assert set(scores["ticker"]) >= {"AAA", "BBB", "CCC"}
        for _, r in scores.iterrows():
            parts = [r[c] for c in ("pts_tech", "pts_fin", "pts_sent", "pts_earnings", "pts_sector")]
            nums = [p for p in parts if pd.notna(p)]
            if nums:
                assert int(r["score"]) == int(round(sum(nums)))
        ccc = scores[scores.ticker == "CCC"].iloc[0]
        assert pd.isna(ccc["pts_pfcf"])
        assert pd.isna(ccc["pfcf"]) or ccc["pfcf"] == ""
        wheel = pd.read_csv(os.path.join(data, "scanner_wheel.csv"))
        banned = {"strike", "expiry", "premium", "contract", "contractsymbol"}
        assert banned.isdisjoint(set(c.lower() for c in wheel.columns))
        blob = " ".join(wheel["why"].astype(str)).lower() + " " + " ".join(wheel["disclaimer"].astype(str)).lower()
        assert "not an option contract" in blob or "no option contracts" in blob
        aaii = pd.read_csv(os.path.join(data, "aaii_sentiment.csv"))
        assert (aaii["data_status"] == "MISSING").all()
        hpe = pd.read_csv(os.path.join(data, "historical_pe.csv"))
        assert (hpe["official_status"] == "MISSING").any() or (hpe["data_status"] == "MISSING").any()
        log = pd.read_csv(os.path.join(data, "updates_log.csv"))
        assert set(log["status"]) <= {"OK", "CACHED", "MISSING"}
        # no network status that looks like a live fetch of SEC during offline
        sec = log[log["source"].str.contains("SEC EDGAR")]
        assert sec["note"].str.contains("cache|offline|does not call|reused", case=False).all()
        help_df = pd.read_csv(os.path.join(data, "help.csv"))
        assert "upsell" not in " ".join(help_df["plain_english"].astype(str)).lower()
        assert "broker" in " ".join(help_df["plain_english"].astype(str)).lower()
        prices = pd.read_csv(os.path.join(data, "prices.csv"))
        assert "disclaimer" not in prices.columns
        assert prices.groupby("ticker").size().max() <= stock_desk.CHART_BARS
        details = pd.read_csv(os.path.join(data, "score_details.csv"))
        assert "disclaimer" not in details.columns
        assert "plain_english" not in details.columns
        assert set(["ticker", "group_name", "item", "points", "points_label", "now_value", "avg_value", "vs_industry"]) <= set(details.columns)
    finally:
        os.environ.pop("DESK_ROOT", None)
        shutil.rmtree(root, ignore_errors=True)


def test_feature_off_writes_header_only():
    root = tempfile.mkdtemp(prefix="desk-off-")
    try:
        build_fixture(root)
        cfg = json.load(open(os.path.join(root, "config.json")))
        cfg["features"]["scanner_wheel"] = False
        cfg["features"]["aaii_sentiment"] = False
        json.dump(cfg, open(os.path.join(root, "config.json"), "w"))
        os.environ["DESK_ROOT"] = root
        stock_desk.main(["--offline"])
        wheel = pd.read_csv(os.path.join(root, "data", "scanner_wheel.csv"))
        assert len(wheel) == 0
        assert list(wheel.columns) == tables.COLS["scanner_wheel"]
        aaii = pd.read_csv(os.path.join(root, "data", "aaii_sentiment.csv"))
        assert len(aaii) == 0
    finally:
        os.environ.pop("DESK_ROOT", None)
        shutil.rmtree(root, ignore_errors=True)


def test_breadth_holiday_does_not_become_zero():
    dates = pd.bdate_range("2024-01-02", periods=80)
    frame = {("S%d" % i): np.linspace(50 + i, 90 + i, len(dates)) for i in range(25)}
    close = pd.DataFrame(frame, index=dates)
    # A holiday row: stocks are blank, only VIX printed. That used to zero the averages after it.
    close.loc[dates[40], :] = np.nan
    close["^VIX"] = np.nan
    close.loc[dates[40], "^VIX"] = 16.0
    out = tables.breadth_history(close)
    assert dates[40].strftime("%Y-%m-%d") not in set(out["date"])
    after = out[out["date"] > dates[40].strftime("%Y-%m-%d")]
    assert len(after) > 10
    assert after["pct_above_sma20"].notna().all()
    assert (after["pct_above_sma20"] > 0).all()
    sma50 = after["pct_above_sma50"].dropna()
    assert len(sma50) > 0
    assert (sma50 > 0).all()
    assert not (out["pct_above_sma20"].fillna(-1) == 0).any()


def test_breadth_without_enough_days_stays_blank():
    dates = pd.bdate_range("2024-01-02", periods=30)
    close = pd.DataFrame({"S%d" % i: np.linspace(10, 20, len(dates)) for i in range(25)}, index=dates)
    out = tables.breadth_history(close)
    assert out["pct_above_sma20"].notna().all()
    # No 50-day or 200-day reading yet. The column is absent or blank, never 0.
    for col in ("pct_above_sma50", "pct_above_sma200"):
        if col not in out.columns:
            continue
        assert out[col].isna().all()
        assert not (out[col].fillna(-1) == 0).any()


def test_market_row_buy_count_and_qqq():
    dates = pd.bdate_range("2024-06-03", periods=5)
    close = pd.DataFrame({
        "SPY": [100, 102, 101, 103, 104],
        "QQQ": [200, 202, 201, 205, 210],
    }, index=dates)
    scores = pd.DataFrame({
        "verdict": ["BUY", "HOLD", "BUY", "AVOID"],
        "day_pct": [1, -1, 0.5, -2],
        "dist_52w_high_pct": [0, -5, -10, -20],
    })
    breadth = pd.DataFrame([{
        "pct_above_sma20": 60.0, "pct_above_sma50": 55.0,
        "pct_above_sma100": np.nan, "pct_above_sma200": np.nan,
    }])
    row = tables.market_row(close, breadth, None, {}, None, "t", "2024-06-07", 4, scores).iloc[0]
    assert row["qqq_day_pct"] == round((210 / 205 - 1) * 100, 2)
    assert int(row["buy_count"]) == 2
    assert row["breadth_sma50"] == 55.0
    no_qqq = close.drop(columns=["QQQ"])
    blank = tables.market_row(no_qqq, breadth, None, {}, None, "t", "2024-06-07", 4, scores).iloc[0]
    assert "qqq_day_pct" not in blank or pd.isna(blank.get("qqq_day_pct"))


if __name__ == "__main__":
    test_offline_job()
    test_feature_off_writes_header_only()
    test_breadth_holiday_does_not_become_zero()
    test_breadth_without_enough_days_stays_blank()
    test_market_row_buy_count_and_qqq()
    print("job ok")
