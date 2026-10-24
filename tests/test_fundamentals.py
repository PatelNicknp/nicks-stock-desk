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


def test_equity_without_cy_frame_matches_on_period_end():
    """SEC balance-sheet facts usually have no CY#### frame. Match them on the end date."""
    payload = _facts()
    gaap = payload["facts"]["us-gaap"]
    # Drop the annual-frame equity and debt. Keep the same period ends on a 10-K with no frame.
    equity, debt_nc, debt_cur = [], [], []
    for end, filed, eq, nc, cur in (
        ("2022-12-31", "2023-02-01", 50, 20, 5),
        ("2023-12-31", "2024-02-01", 55, 22, 4),
        ("2024-12-31", "2025-02-01", 60, 18, 2),
    ):
        equity.append(_row(eq, "", None, end, filed, "10-K"))
        debt_nc.append(_row(nc, "", None, end, filed, "10-K"))
        debt_cur.append(_row(cur, "", None, end, filed, "10-K"))
    # A full-year flow tagged as equity must not be used. An instant quarter should attach.
    equity.append(_row(999, "", "2024-01-01", "2024-12-31", "2025-02-01", "10-K"))
    equity.append(_row(70, "CY2025Q1I", None, "2025-03-31", "2025-05-01", "10-Q"))
    gaap["StockholdersEquity"] = {"units": {"USD": equity}}
    gaap["LongTermDebtNoncurrent"] = {"units": {"USD": debt_nc}}
    gaap["LongTermDebtCurrent"] = {"units": {"USD": debt_cur}}
    annual, quarters = fund.parse_companyfacts(payload)
    row = annual[annual.frame == "CY2024"].iloc[0]
    assert row["equity"] == 60
    assert row["debt"] == 20  # 18 + 2, and the missing piece is not filled with zero
    q = quarters[quarters.frame == "CY2025Q1"].iloc[0]
    assert q["equity"] == 70
    idx = pd.bdate_range("2022-01-03", "2025-03-01")
    prep = fund.prepare_annual(annual, pd.Series(20.0, index=idx))
    metrics = fund.metrics_asof(prep, "2025-02-02", 20.0)
    assert metrics["roe"] is not None
    assert abs(metrics["roe"] - (18 / 60)) < 1e-9
    assert metrics["de"] is not None


def test_net_income_falls_back_when_a_later_tag_has_the_year():
    payload = _facts()
    gaap = payload["facts"]["us-gaap"]
    # Drop the newest NetIncomeLoss year. ProfitLoss supplies it.
    ni = gaap["NetIncomeLoss"]["units"]["USD"]
    gaap["NetIncomeLoss"]["units"]["USD"] = [r for r in ni if r["frame"] != "CY2024"]
    gaap["ProfitLoss"] = {"units": {"USD": [
        _row(21, "CY2024", "2024-01-01", "2024-12-31", "2025-02-01", "10-K"),
    ]}}
    annual, _ = fund.parse_companyfacts(payload)
    row = annual[annual.frame == "CY2024"].iloc[0]
    assert row["net_income"] == 21
    older = annual[annual.frame == "CY2023"].iloc[0]
    assert older["net_income"] == 14


def test_unframed_fy_fact_fills_net_income_and_does_not_replace_a_framed_value():
    """A 10-K with fp FY and no CY frame is a real year. A framed value for that end stays."""
    payload = _facts()
    gaap = payload["facts"]["us-gaap"]
    ni = []
    for end, filed, val, start in (
        ("2022-12-31", "2023-02-01", 10, "2022-01-01"),
        ("2023-12-31", "2024-02-01", 14, "2023-01-01"),
        ("2024-12-31", "2025-02-01", 18, "2024-01-01"),
        ("2025-01-31", "2025-03-15", 497000000, "2024-02-01"),
    ):
        ni.append(_row(val, "", start, end, filed, "10-K"))
    # A quarterly flow must not be treated as the year.
    ni.append(_row(1, "", "2024-01-01", "2024-03-31", "2024-05-01", "10-Q"))
    gaap["NetIncomeLoss"] = {"units": {"USD": ni}}
    annual, _ = fund.parse_companyfacts(payload)
    row = annual[annual.frame == "CY2024"].iloc[0]
    assert row["revenue"] == 150  # the unframed decoy of 1 does not replace it
    assert row["net_income"] == 18
    extra = annual[annual["end"].astype(str).str.startswith("2025-01-31")]
    assert len(extra) == 1
    assert extra.iloc[0]["net_income"] == 497000000
    assert str(extra.iloc[0]["frame"]).startswith("FY")


def test_split_puts_eps_on_the_adjusted_share_count():
    annual = pd.DataFrame([
        {"ticker": "ORLY", "end": "2022-12-31", "filed": "2025-02-28", "eps": 33.44, "dps": 0.0, "shares": 64962000},
        {"ticker": "ORLY", "end": "2023-12-31", "filed": "2026-02-27", "eps": 2.56, "dps": 0.0, "shares": 914976000},
        {"ticker": "BKNG", "end": "2025-12-31", "filed": "2026-02-18", "eps": 165.57, "dps": 9.60, "shares": 32639000},
    ])
    quarters = pd.DataFrame([
        {"ticker": "ORLY", "end": "2024-03-31", "filed": "2025-05-09", "eps": 9.20, "dps": 0.0, "shares": 59454000},
        {"ticker": "ORLY", "end": "2024-06-30", "filed": "2025-08-08", "eps": 0.70, "dps": 0.0, "shares": 885655000},
        {"ticker": "BKNG", "end": "2025-09-30", "filed": "2025-10-28", "eps": 84.41, "dps": 0.0, "shares": 32558000},
        {"ticker": "BKNG", "end": "2026-03-31", "filed": "2026-04-28", "eps": 1.36, "dps": 0.42, "shares": 794000000},
        {"ticker": "BKNG", "end": "2026-06-30", "filed": "2026-08-04", "eps": 2.53, "dps": 0.0, "shares": 770000000},
    ])
    annual, quarters = fund.adjust_pershare_for_splits(annual, quarters)
    orly = annual[annual.ticker == "ORLY"].set_index("end")
    assert abs(orly.loc["2022-12-31", "eps"] - 33.44 / 15) < 0.01
    assert abs(orly.loc["2023-12-31", "eps"] - 2.56) < 0.01
    assert orly.loc["2022-12-31", "shares"] > 900_000_000
    bk = annual[annual.ticker == "BKNG"].iloc[0]
    assert abs(bk["eps"] - 165.57 / 25) < 0.02
    assert abs(bk["dps"] - 9.60 / 25) < 0.01
    assert bk["shares"] > 700_000_000
    pre_q = quarters[(quarters.ticker == "BKNG") & (quarters.end == "2025-09-30")].iloc[0]
    assert abs(pre_q["eps"] - 84.41 / 25) < 0.02
    post_q = quarters[(quarters.ticker == "BKNG") & (quarters.end == "2026-06-30")].iloc[0]
    assert abs(post_q["eps"] - 2.53) < 0.01
    assert fund.guard_multiple(0.92) is None
    assert fund.guard_yield(0.0616) == 0.0616
    assert fund.guard_yield(0.20) is None
    mcd = pd.DataFrame([
        {"ticker": "MCD", "end": "2020-12-31", "filed": "2021-02-01", "eps": 6.31, "dps": 5.0, "shares": 750100000},
        {"ticker": "MCD", "end": "2025-12-31", "filed": "2026-02-01", "eps": 11.95, "dps": 7.08, "shares": 716.4},
    ])
    nvr = pd.DataFrame([
        {"ticker": "NVR", "end": "2025-12-31", "filed": "2026-02-01", "eps": 400.0, "dps": 0.0, "shares": 2816295},
    ])
    fixed, _ = fund.adjust_pershare_for_splits(pd.concat([mcd, nvr], ignore_index=True), pd.DataFrame())
    mcd_last = fixed[(fixed.ticker == "MCD") & (fixed.end == "2025-12-31")].iloc[0]
    assert abs(mcd_last["shares"] - 716.4 * 1_000_000) < 1
    assert abs(mcd_last["eps"] - 11.95) < 0.01
    nvr_row = fixed[fixed.ticker == "NVR"].iloc[0]
    assert abs(nvr_row["shares"] - 2816295) < 1


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
    test_equity_without_cy_frame_matches_on_period_end()
    test_net_income_falls_back_when_a_later_tag_has_the_year()
    test_unframed_fy_fact_fills_net_income_and_does_not_replace_a_framed_value()
    test_split_puts_eps_on_the_adjusted_share_count()
    test_dividend_zero_is_real_when_concept_absent_from_one_year()
    print("fundamentals ok")
