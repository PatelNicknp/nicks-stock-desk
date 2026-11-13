"""EPS fill: SEC EPS history for the EPS Rating (features.eps_fill)."""
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import eps_inputs as ei  # noqa: E402
import ms_screens as ms  # noqa: E402
import profiles  # noqa: E402
import stock_desk  # noqa: E402


def _fact(start, end, val, form="10-Q", filed="2026-01-01", accn="a"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "accn": accn}


def _payload(us=None, ifrs=None, dei=None):
    facts = {}
    if us:
        facts["us-gaap"] = us
    if ifrs:
        facts["ifrs-full"] = ifrs
    if dei:
        facts["dei"] = dei
    return {"facts": facts}


def _eps(rows, unit="USD/shares"):
    return {"units": {unit: rows}}


def _hist(payload):
    h = ei.parse_eps_history(payload, "T")
    return {(r.kind, r.frame): (round(r.eps, 4), r.source) for r in h.itertuples()}


def test_fiscal_q4_is_full_year_minus_nine_months():
    rows = [
        _fact("2025-01-01", "2025-03-31", 1.0),
        _fact("2025-04-01", "2025-06-30", 1.1),
        _fact("2025-07-01", "2025-09-30", 1.2),
        _fact("2025-01-01", "2025-09-30", 3.3),
        _fact("2025-01-01", "2025-12-31", 4.8, form="10-K", filed="2026-02-20"),
    ]
    got = _hist(_payload(us={"EarningsPerShareDiluted": _eps(rows)}))
    assert got[("Q", "CY2025Q4")] == (1.5, "derived")
    assert got[("Q", "CY2025Q3")] == (1.2, "sec")
    assert got[("A", "CY2025")] == (4.8, "sec")


def test_q4_from_three_quarters_when_no_ytd_and_off_calendar_year():
    # A fiscal year ending late January (NVDA style) is labeled by the SEC midpoint rule.
    rows = [
        _fact("2025-01-27", "2025-04-27", 0.76),
        _fact("2025-04-28", "2025-07-27", 1.08),
        _fact("2025-07-28", "2025-10-26", 1.30),
        _fact("2025-01-27", "2026-01-25", 4.90, form="10-K"),
    ]
    got = _hist(_payload(us={"EarningsPerShareDiluted": _eps(rows)}))
    assert got[("Q", "CY2025Q4")] == (1.76, "derived")
    assert got[("Q", "CY2025Q1")][0] == 0.76
    assert ("A", "CY2026") in got  # yearly label from the end date, consistent year to year


def test_later_tag_fills_periods_the_first_tag_stopped_covering():
    # MNST style: EarningsPerShareDiluted stopped in 2011, the company moved to another tag.
    old = [_fact("2011-01-01", "2011-03-31", 0.5)]
    new = [_fact("2026-04-01", "2026-06-30", 0.30), _fact("2025-04-01", "2025-06-30", 0.25)]
    got = _hist(_payload(us={
        "EarningsPerShareDiluted": _eps(old),
        "IncomeLossFromContinuingOperationsPerDilutedShare": _eps(new),
    }))
    assert got[("Q", "CY2026Q2")] == (0.3, "sec")
    assert got[("Q", "CY2011Q1")] == (0.5, "sec")


def test_ifrs_foreign_filer_annual_eps_in_own_currency():
    rows = [_fact("2024-01-01", "2024-12-31", 19.24, form="20-F"), _fact("2025-01-01", "2025-12-31", 24.71, form="20-F")]
    got = _hist(_payload(ifrs={"DilutedEarningsLossPerShare": _eps(rows, "EUR/shares")}))
    assert got[("A", "CY2025")] == (24.71, "sec")


def test_net_income_over_diluted_shares_when_no_eps_tag():
    ni = [_fact("2026-07-01", "2026-09-30", 50_000_000.0)]
    sh = [_fact("2026-07-01", "2026-09-30", 100_000_000.0)]
    got = _hist(_payload(us={
        "NetIncomeLoss": {"units": {"USD": ni}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": sh}},
    }))
    assert got[("Q", "CY2026Q3")] == (0.5, "ni_shares")


def test_net_income_over_cover_shares_is_last_resort():
    ni = [_fact("2026-07-01", "2026-09-30", 30.0, accn="X1")]
    cover = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-10-20", "val": 40.0, "accn": "X1"}, {"end": "2026-10-20", "val": 20.0, "accn": "X1"}]}}}
    got = _hist(_payload(us={"NetIncomeLoss": {"units": {"USD": ni}}}, dei=cover))
    assert got[("Q", "CY2026Q3")] == (0.5, "ni_cover_shares")  # two share classes add up


def test_split_restatements_scale_old_values():
    # A 4:1 split: two periods restated in a 2021 filing. A 2016 value never restated is scaled.
    rows = [
        _fact("2016-01-01", "2016-12-31", 8.0, form="10-K", filed="2017-02-01"),
        _fact("2019-01-01", "2019-12-31", 12.0, form="10-K", filed="2020-02-01"),
        _fact("2020-01-01", "2020-12-31", 14.0, form="10-K", filed="2020-10-30"),
        _fact("2019-01-01", "2019-12-31", 3.0, form="10-K", filed="2021-02-01"),
        _fact("2020-01-01", "2020-12-31", 3.5, form="10-K", filed="2021-02-01"),
        _fact("2021-01-01", "2021-12-31", 4.0, form="10-K", filed="2022-02-01"),
    ]
    got = _hist(_payload(us={"EarningsPerShareDiluted": _eps(rows)}))
    assert got[("A", "CY2016")][0] == 2.0
    assert got[("A", "CY2019")][0] == 3.0
    assert got[("A", "CY2021")][0] == 4.0


def test_one_restatement_is_not_a_split():
    rows = [
        _fact("2019-01-01", "2019-12-31", 2.0, form="10-K", filed="2020-02-01"),
        _fact("2019-01-01", "2019-12-31", 1.0, form="10-K/A", filed="2020-06-01"),
        _fact("2018-01-01", "2018-12-31", 1.8, form="10-K", filed="2019-02-01"),
    ]
    got = _hist(_payload(us={"EarningsPerShareDiluted": _eps(rows)}))
    assert got[("A", "CY2018")][0] == 1.8


def test_nasdaq_surprise_page_and_label():
    payload = {"data": {"earningsSurpriseTable": {"rows": [
        {"fiscalQtrEnd": "Sep 2026", "dateReported": "10/14/2026", "eps": 14.89},
        {"fiscalQtrEnd": "Jan 2026", "dateReported": "2/25/2026", "eps": "1.76"},
        {"fiscalQtrEnd": "bad", "eps": 1},
    ]}}}
    df = ei.parse_nasdaq_surprise(payload, "ASML")
    assert list(df["frame"]) == ["CY2026Q3", "CY2025Q4"]
    merged = ei.merge_saved(df, ei.parse_nasdaq_surprise({"data": {"earningsSurpriseTable": {"rows": [
        {"fiscalQtrEnd": "Sep 2026", "eps": 15.0}]}}}, "ASML"), "nasdaq")
    assert len(merged) == 2 and float(merged[merged.frame == "CY2026Q3"]["eps"].iloc[0]) == 15.0


def test_other_source_only_replaces_missing_or_stale_sec_quarters():
    asof = pd.Timestamp("2026-11-12")

    def q(t, frames, src):
        return pd.DataFrame([{"ticker": t, "frame": f, "kind": "Q", "eps": 1.0, "start": "", "end": "", "filed": "", "source": src} for f in frames])
    good = ["CY2025Q3", "CY2025Q4", "CY2026Q1", "CY2026Q2", "CY2026Q3"]
    sec = pd.concat([q("US", good, "sec"), q("OLD", ["CY2014Q1", "CY2015Q1"], "sec")], ignore_index=True)
    other = pd.concat([q("US", good, "yahoo"), q("OLD", good, "yahoo"), q("FOR", good, "yahoo"), q("THIN", good[-3:], "yahoo")], ignore_index=True)
    hist, replaced = ei.combine(sec, [other], asof=asof)
    assert replaced == {"OLD": "yahoo", "FOR": "yahoo"}
    assert set(hist[hist.ticker == "US"]["source"]) == {"sec"}
    assert set(hist[hist.ticker == "OLD"]["source"]) == {"yahoo"}  # never mixed with the stale SEC quarters
    assert "THIN" not in set(hist["ticker"])


def test_yahoo_report_dates_map_to_the_reported_quarter():
    e = pd.DataFrame({"ticker": ["A", "A", "A"], "earnings_dt": ["2026-10-14 06:00:00-04:00", "2026-03-21", "2026-11-19"],
                      "eps_actual": [1.0, 2.0, 3.0]})
    got = ei.yahoo_quarters(e)
    assert sorted(got["frame"]) == ["CY2025Q4", "CY2026Q3"] or sorted(got["frame"]) == ["CY2025Q4", "CY2026Q3", "CY2026Q3"]
    assert got[got.frame == "CY2025Q4"]["eps"].iloc[0] == 2.0


def _amap(d):
    return {(y, 0): v for y, v in d.items()}


def test_shorter_span_skips_a_loss_at_the_start_only_when_switched_on():
    amap = _amap({2020: -1.0, 2021: 1.0, 2022: 1.2, 2023: 1.5, 2024: 1.8, 2025: 2.0})
    assert ms.annual_growth(amap) == (None, 5)  # PR68 rule unchanged when off
    g, yrs = ms.annual_growth(amap, skip_loss_start=True)
    assert yrs == 4 and abs(g - ((2.0 / 1.0) ** 0.25 - 1) * 100) < 1e-9
    # A loss in the latest year never gets a growth rate.
    assert ms.annual_growth(_amap({2020: 1.0, 2025: -1.0}), skip_loss_start=True)[0] is None


def test_loss_rank_key_is_below_every_growth_rate_and_orders_losses():
    shrink = ms.loss_rank_key(_amap({2022: -2.0, 2025: -0.5}))
    widen = ms.loss_rank_key(_amap({2022: -0.5, 2025: -2.0}))
    assert shrink < -100 and widen < -100 and shrink > widen
    assert ms.loss_rank_key(_amap({2024: 1.0, 2025: 2.0})) is None


def _frames(spec):
    q, a = [], []
    for t, (qs, ys) in spec.items():
        for f, v in qs.items():
            q.append({"ticker": t, "frame": f, "eps": v})
        for y, v in ys.items():
            a.append({"ticker": t, "frame": "CY%d" % y, "eps": v})
    return pd.DataFrame(q), pd.DataFrame(a)


def test_eps_ratings_fill_rates_loss_makers_low_and_skips_stale_quarters():
    qs_good = {"CY2025Q3": 1.0, "CY2026Q3": 2.0, "CY2025Q2": 1.0, "CY2026Q2": 1.5}
    spec = {
        "GROW": (qs_good, {2020: 1.0, 2025: 3.0}),
        "SLOW": ({"CY2025Q3": 1.0, "CY2026Q3": 1.1}, {2020: 1.0, 2025: 1.2}),
        "LOSS": (qs_good, {2020: -1.0, 2025: -0.2}),
        "STALE": ({"CY2014Q1": 1.0, "CY2015Q1": 2.0}, {2020: 1.0, 2025: 3.0}),
    }
    q, a = _frames(spec)
    off = ms.eps_ratings(q, a, list(spec), {}).set_index("ticker")
    assert np.isnan(off.loc["LOSS", "eps_rating"]) and not np.isnan(off.loc["STALE", "eps_rating"])
    on = ms.eps_ratings(q, a, list(spec), {}, fill=True, asof="2026-11-12").set_index("ticker")
    assert on.loc["LOSS", "eps_annual_basis"] == "loss" and not np.isnan(on.loc["LOSS", "eps_rating"])
    assert np.isnan(on.loc["LOSS", "eps_annual_growth"])
    assert np.isnan(on.loc["STALE", "eps_rating"]) and bool(on.loc["STALE", "eps_quarter_stale"])
    assert on.loc["GROW", "eps_rating"] > on.loc["LOSS", "eps_rating"]


def test_highest_eps_and_rs_still_needs_real_growth():
    table = pd.DataFrame([
        {"ticker": "LOSS", "eps_q_yoy": 500.0, "eps_prev_q_yoy": 400.0, "eps_annual_growth": np.nan, "eps_growth_years": np.nan,
         "latest_quarter": "CY2026Q3", "eps_rating": 95.0, "eps_parts": 3.0, "eps_annual_basis": "loss"},
    ])
    idx = pd.bdate_range("2025-01-01", periods=80)
    close = pd.DataFrame({"LOSS": np.linspace(100, 105, 80)}, index=idx)
    uni = pd.DataFrame({"ticker": ["LOSS"], "company": ["L"], "sector": [""], "index_membership": [""]})
    rows, cnt = ms.build_eps_rs(close, uni, table, {"LOSS": 99})
    assert len(rows) == 0


def test_zip_hook_sees_each_payload_once():
    import zipfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "companyfacts.zip")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("CIK0000000001.json", json.dumps(_payload(us={"EarningsPerShareDiluted": _eps([
                _fact("2026-07-01", "2026-09-30", 1.0)])})))
        seen = []
        a, q, found, missing = profiles.parse_companyfacts_from_zip(
            path, {"AAA": "0000000001", "BBB": "0000000002"}, lambda p: (pd.DataFrame(), pd.DataFrame()),
            on_payload=lambda t, p: seen.append(t))
        assert seen == ["AAA"] and missing == ["BBB"]


def test_save_eps_history_replaces_only_given_tickers():
    with tempfile.TemporaryDirectory() as d:
        a = ei.parse_eps_history(_payload(us={"EarningsPerShareDiluted": _eps([_fact("2026-07-01", "2026-09-30", 1.0)])}), "AAA")
        b = ei.parse_eps_history(_payload(us={"EarningsPerShareDiluted": _eps([_fact("2026-07-01", "2026-09-30", 2.0)])}), "BBB")
        stock_desk.save_eps_history(d, [a, b])
        a2 = ei.parse_eps_history(_payload(us={"EarningsPerShareDiluted": _eps([_fact("2026-07-01", "2026-09-30", 3.0)])}), "AAA")
        stock_desk.save_eps_history(d, [a2])
        got = pd.read_csv(os.path.join(d, stock_desk.EPS_HISTORY_FILE))
        assert dict(zip(got["ticker"], got["eps"])) == {"AAA": 3.0, "BBB": 2.0}


def test_eps_fill_switch_off_returns_nothing():
    with tempfile.TemporaryDirectory() as d:
        uni = pd.DataFrame({"ticker": ["AAA"]})
        hist, info = stock_desk.load_eps_inputs(uni, {"features": {"eps_fill": False}}, d, "offline")
        assert hist is None and info["on"] is False
        hist, info = stock_desk.load_eps_inputs(uni, {"features": {"eps_fill": True}}, d, "offline")
        assert hist is None and "next full run" in info["note"]


def test_nasdaq_eps_does_not_fetch_off_full_run_or_when_switched_off():
    with tempfile.TemporaryDirectory() as d:
        cfg = {"features": {"eps_fill_nasdaq": True}, "rate_limit": {"nasdaq_requests_per_second": 3, "max_retries": 1}}
        assert len(stock_desk.load_nasdaq_eps(["ASML"], cfg, d, "hourly")) == 0
        cfg["features"]["eps_fill_nasdaq"] = False
        assert len(stock_desk.load_nasdaq_eps(["ASML"], cfg, d, "full")) == 0


def test_share_class_borrows_base_cik_only_when_missing():
    got = stock_desk.share_class_ciks({"CWEN": "1", "BRK-B": "2"}, ["CWEN-A", "BRK-B", "XYZ-A", "CWEN"])
    assert got["CWEN-A"] == "1" and got["BRK-B"] == "2" and "XYZ-A" not in got
    assert "CWEN-A" not in stock_desk.share_class_ciks({"CWEN": "1"}, ["CWEN-A"], on=False)


def test_names_missing_from_history_keep_plain_sec_rows():
    eq = pd.DataFrame([{"ticker": "NEW", "frame": "CY2026Q3", "eps": 1.0}])
    ea = pd.DataFrame([{"ticker": "NEW", "frame": "CY2025", "eps": 1.0}])
    quarters = pd.DataFrame([{"ticker": "OLD", "frame": "CY2026Q3", "eps": 2.0}, {"ticker": "NEW", "frame": "CY2026Q3", "eps": 9.0},
                             {"ticker": "OLD", "frame": "FY2026", "eps": 5.0}])
    annual = pd.DataFrame([{"ticker": "OLD", "frame": "CY2025", "eps": 3.0}])
    q, a = ei.add_plain_rows(eq, ea, quarters, annual, ["NEW", "OLD"])
    assert dict(zip(q["ticker"], q["eps"])) == {"NEW": 1.0, "OLD": 2.0}
    assert len(a) == 2


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("eps fill ok")
