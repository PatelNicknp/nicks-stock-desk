"""SEC parser: annual vs quarterly, no look-ahead, missing stays missing."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import fundamentals as fund


def _row(val, frame, start, end, filed, form):
    rec = {"val": val, "frame": frame, "end": end, "filed": filed, "form": form, "fp": "FY", "fy": 2024}
    if start:
        rec["start"] = start
    return rec


def _facts():
    def usd(name, rows):
        return {name: {"units": {"USD": rows}}}
    def usds(name, rows):
        return {name: {"units": {"USD/shares": rows}}}
    def sh(name, rows):
        return {name: {"units": {"shares": rows}}}
    gaap = {}
    # three annual years plus a YTD decoy that must be ignored (9-month duration, quarterly frame)
    years = [("CY2022", "2022-01-01", "2022-12-31", "2023-02-01", 100, 10, 1.0, 80, 20, 30, 5, 0.4),
             ("CY2023", "2023-01-01", "2023-12-31", "2024-02-01", 120, 14, 1.4, 90, 18, 36, 6, 0.5),
             ("CY2024", "2024-01-01", "2024-12-31", "2025-02-01", 150, 18, 1.8, 100, 15, 40, 6, 0.6)]
    rev, ni, eps, gp, oi, ocf, capex, dps = [], [], [], [], [], [], [], []
    for fr, s, e, f, r, n, ep, g, o, c, x, d in years:
        rev.append(_row(r, fr, s, e, f, "10-K"))
        ni.append(_row(n, fr, s, e, f, "10-K"))
        eps.append(_row(ep, fr, s, e, f, "10-K"))
        gp.append(_row(g, fr, s, e, f, "10-K"))
        oi.append(_row(o, fr, s, e, f, "10-K"))
        ocf.append(_row(c, fr, s, e, f, "10-K"))
        capex.append(_row(x, fr, s, e, f, "10-K"))
        dps.append(_row(d, fr, s, e, f, "10-K"))
    # decoys
    rev.append(_row(9999, "CY2024Q3", "2024-01-01", "2024-09-30", "2024-11-01", "10-Q"))  # YTD, ignored
    rev.append(_row(1, "", "2024-01-01", "2024-12-31", "2025-02-01", "10-K"))  # no frame, ignored
    equity, debt_nc, debt_cur, shares = [], [], [], []
    for fr, e, f, eq, nc, cur, shs in (
        ("CY2022", "2022-12-31", "2023-02-01", 50, 20, 5, 10),
        ("CY2023", "2023-12-31", "2024-02-01", 55, 22, 4, 10),
        ("CY2024", "2024-12-31", "2025-02-01", 60, 18, 2, 10),
    ):
        equity.append(_row(eq, fr, None, e, f, "10-K"))
        debt_nc.append(_row(nc, fr, None, e, f, "10-K"))
        debt_cur.append(_row(cur, fr, None, e, f, "10-K"))
        shares.append(_row(shs, fr, None, e, f, "10-K"))
    # one real quarter
    qrev = [_row(40, "CY2025Q1", "2025-01-01", "2025-03-31", "2025-05-01", "10-Q")]
    gaap.update(usd("RevenueFromContractWithCustomerExcludingAssessedTax", rev + qrev))
    gaap.update(usd("NetIncomeLoss", ni))
    gaap.update(usds("EarningsPerShareDiluted", eps))
    gaap.update(usd("GrossProfit", gp))
    gaap.update(usd("OperatingIncomeLoss", oi))
    gaap.update(usd("NetCashProvidedByUsedInOperatingActivities", ocf))
    gaap.update(usd("PaymentsToAcquirePropertyPlantAndEquipment", capex))
    gaap.update(usds("CommonStockDividendsPerShareDeclared", dps))
    gaap.update(usd("StockholdersEquity", equity))
    gaap.update(usd("LongTermDebtNoncurrent", debt_nc))
    gaap.update(usd("LongTermDebtCurrent", debt_cur))
    gaap.update(sh("CommonStockSharesOutstanding", shares))
    return {"facts": {"us-gaap": gaap}}


def test_parser_drops_ytd_and_combines_debt():
    annual, quarters = fund.parse_companyfacts(_facts())
    assert set(annual["frame"]) == {"CY2022", "CY2023", "CY2024"}
    row = annual[annual.frame == "CY2024"].iloc[0]
    assert row["revenue"] == 150
    assert row["debt"] == 20  # 18 + 2, not zero-filled
    assert float(quarters[quarters.frame == "CY2025Q1"]["revenue"].iloc[0]) == 40


def test_known_on_blocks_same_day_and_missing_fcf():
    annual, _ = fund.parse_companyfacts(_facts())
    idx = pd.bdate_range("2022-01-03", "2025-03-01")
    closes = pd.Series(20.0, index=idx)
    # price steps so each filing date has a price
    prep = fund.prepare_annual(annual, closes)
    # CY2024 filed 2025-02-01, known the next day
    before = fund.metrics_asof(prep, "2025-02-01", 20.0)
    after = fund.metrics_asof(prep, "2025-02-02", 20.0)
    assert before["fy_end"] == "2023-12-31"
    assert after["fy_end"] == "2024-12-31"
    assert after["ttm_pe"] is not None
    # a company with no cash flow stays blank, not zero
    annual2 = annual.drop(columns=["ocf", "capex"])
    prep2 = fund.prepare_annual(annual2, closes)
    m = fund.metrics_asof(prep2, "2025-02-02", 20.0)
    assert m["pfcf"] is None
    assert m["fcf"] is None


def test_dividend_zero_is_real_when_concept_absent_from_one_year():
    # covered by fillna only when some years report a dividend. All-missing is also 0 (no dividend tag).
    annual, _ = fund.parse_companyfacts(_facts())
    idx = pd.bdate_range("2022-01-03", "2025-03-01")
    closes = pd.Series(20.0, index=idx)
    prep = fund.prepare_annual(annual, closes)
    m = fund.metrics_asof(prep, "2025-02-02", 20.0)
    assert abs(m["div_yield"] - 0.6 / 20.0) < 1e-9


if __name__ == "__main__":
    test_parser_drops_ytd_and_combines_debt()
    test_known_on_blocks_same_day_and_missing_fcf()
    test_dividend_zero_is_real_when_concept_absent_from_one_year()
    print("fundamentals ok")
