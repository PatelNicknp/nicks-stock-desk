"""SEC profiles, approximate SIC sectors, Nasdaq calendar, and zip parsing.

Fixed dates and made-up files. No clock and no network.
"""
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import fundamentals as fund
import profiles


def test_sic_to_sector_is_approximate_and_covers_common_groups():
    assert profiles.sic_to_sector("2834") == "Health Care"  # pharma
    assert profiles.sic_to_sector("7372") == "Information Technology"  # prepackaged software
    assert profiles.sic_to_sector("1311") == "Energy"
    assert profiles.sic_to_sector("6021") == "Financials"
    assert profiles.sic_to_sector("6798") == "Real Estate"
    assert profiles.sic_to_sector("2086") == "Consumer Staples"  # CCEP-style soft drinks
    assert profiles.sic_to_sector("4813") == "Communication Services"
    assert profiles.sic_to_sector("4911") == "Utilities"
    assert profiles.sic_to_sector("3711") == "Consumer Discretionary"
    assert profiles.sic_to_sector("") == ""
    assert profiles.sic_to_sector("xxxx") == ""


def test_submissions_profile_reads_name_country_exchange_and_sic():
    ry = {
        "cik": "1000275",
        "name": "ROYAL BANK OF CANADA",
        "sic": "6022",
        "sicDescription": "COMMERCIAL BANKS, NEC",
        "tickers": ["RY"],
        "exchanges": ["NYSE"],
        "stateOfIncorporation": "A6",
        "stateOfIncorporationDescription": "ONTARIO, CANADA",
        "addresses": {
            "business": {
                "stateOrCountry": "A6",
                "stateOrCountryDescription": "Ontario, Canada",
                "isForeignLocation": 1,
            }
        },
    }
    row = profiles.parse_submissions_profile(ry, ticker="RY")
    assert row["ticker"] == "RY"
    assert row["company"] == "ROYAL BANK OF CANADA"
    assert "Canada" in row["country"]
    assert row["exchange"] == "NYSE"
    assert row["sic"] == "6022"
    assert row["industry"] == "COMMERCIAL BANKS, NEC"
    assert row["sector"] == "Financials"
    assert row["sector_source"] == profiles.SECTOR_SOURCE_SIC

    us = {
        "name": "Apple Inc.",
        "sic": "3571",
        "sicDescription": "ELECTRONIC COMPUTERS",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "stateOfIncorporation": "CA",
        "stateOfIncorporationDescription": "CA",
        "addresses": {"business": {"stateOrCountry": "CA", "stateOrCountryDescription": "CA", "isForeignLocation": 0}},
    }
    aapl = profiles.parse_submissions_profile(us, ticker="AAPL")
    assert aapl["country"] == "United States"
    assert aapl["sector"] == "Information Technology"


def test_profiles_never_overwrite_a_filled_sector_or_name():
    universe = pd.DataFrame([
        {"ticker": "AAPL", "company": "Apple", "sector": "Information Technology"},
        {"ticker": "NEW", "company": "", "sector": ""},
        {"ticker": "PART", "company": "Already Named", "sector": ""},
    ])
    prof = pd.DataFrame([
        {"ticker": "AAPL", "company": "APPLE INC WRONG", "sector": "Industrials",
         "industry": "ELECTRONIC COMPUTERS", "country": "United States", "exchange": "Nasdaq",
         "website": "", "sector_source": "sic_approx"},
        {"ticker": "NEW", "company": "New Co", "sector": "Health Care",
         "industry": "PHARMACEUTICAL PREPARATIONS", "country": "United States", "exchange": "NYSE",
         "website": "", "sector_source": "sic_approx"},
        {"ticker": "PART", "company": "Should Not Win", "sector": "Financials",
         "industry": "BANKS", "country": "Canada", "exchange": "NYSE",
         "website": "", "sector_source": "sic_approx"},
    ])
    out = profiles.apply_profiles_to_universe(universe, prof)
    aapl = out[out.ticker == "AAPL"].iloc[0]
    assert aapl["company"] == "Apple"
    assert aapl["sector"] == "Information Technology"
    assert aapl.get("sector_source", "") != "sic_approx"
    new = out[out.ticker == "NEW"].iloc[0]
    assert new["company"] == "New Co"
    assert new["sector"] == "Health Care"
    assert new["industry"] == "PHARMACEUTICAL PREPARATIONS"
    assert new["sector_source"] == "sic_approx"
    part = out[out.ticker == "PART"].iloc[0]
    assert part["company"] == "Already Named"
    assert part["sector"] == "Financials"
    assert part["country"] == "Canada"


def test_calendar_days_skip_weekends_inside_the_window():
    days = profiles.calendar_days("2026-11-11", days_ahead=10, skip_weekends=True)
    # 11 Wed through 20 Fri is 10 calendar days, minus Sat 14 and Sun 15.
    assert days[0] == "2026-11-11"
    assert "2026-11-14" not in days
    assert "2026-11-15" not in days
    assert days[-1] == "2026-11-20"
    assert len(days) == 8


def test_nasdaq_calendar_parses_rows_and_keeps_saved_on_failure():
    payload = {"data": {"rows": [
        {"symbol": "AAPL", "time": "After Close", "epsForecast": "2.10"},
        {"symbol": "BRK.B", "time": "Time-Not-Supplied", "epsForecast": "4.00"},
        {"symbol": "", "time": "Before Open"},
    ]}}
    rows = profiles.parse_nasdaq_earnings_payload(payload, "2026-11-20")
    by = {r["ticker"]: r for r in rows}
    assert by["AAPL"]["earnings_dt"] == "2026-11-20"
    assert by["AAPL"]["source"] == "nasdaq_calendar"
    assert by["BRK-B"]["eps_estimate"] == "4.00"
    assert "" not in by

    prior = pd.DataFrame([
        {"ticker": "MSFT", "earnings_dt": "2026-11-18", "source": "nasdaq_calendar"},
        {"ticker": "OLD", "earnings_dt": "2026-11-20", "source": "nasdaq_calendar"},
    ])
    fresh = pd.DataFrame(rows)
    merged = profiles.keep_calendar_on_failure(prior, fresh, failed=False)
    assert "AAPL" in set(merged["ticker"])
    assert "MSFT" in set(merged["ticker"])  # other dates stay
    # 2026-11-20 was refreshed, so OLD is replaced.
    assert "OLD" not in set(merged["ticker"])

    kept = profiles.keep_calendar_on_failure(prior, pd.DataFrame(), failed=True)
    assert list(kept["ticker"]) == ["MSFT", "OLD"]
    empty = profiles.keep_calendar_on_failure(prior, None, failed=True)
    assert list(empty["ticker"]) == ["MSFT", "OLD"]


def test_merge_earnings_dates_only_fills_names_still_missing_a_future_date():
    existing = pd.DataFrame([
        {"ticker": "AAPL", "earnings_dt": "2026-11-20", "source": "yahoo"},
        {"ticker": "MSFT", "earnings_dt": "2026-10-01", "source": "yahoo"},
    ])
    calendar = pd.DataFrame([
        {"ticker": "AAPL", "earnings_dt": "2026-11-21", "source": "nasdaq_calendar"},
        {"ticker": "MSFT", "earnings_dt": "2026-12-01", "source": "nasdaq_calendar"},
        {"ticker": "NEW", "earnings_dt": "2026-12-02", "source": "nasdaq_calendar"},
    ])
    now = pd.Timestamp("2026-11-10", tz="UTC")
    out = profiles.merge_earnings_dates(existing, calendar, now=now)
    aapl = out[out.ticker == "AAPL"]
    # AAPL already has a future date; the Nasdaq row is not added.
    assert list(aapl["earnings_dt"]) == ["2026-11-20"]
    msft = out[(out.ticker == "MSFT") & (out.earnings_dt == "2026-12-01")]
    assert len(msft) == 1
    assert "NEW" in set(out["ticker"])
    # Empty calendar leaves existing alone (self-heal).
    same = profiles.merge_earnings_dates(existing, pd.DataFrame(), now=now)
    assert list(same["ticker"]) == ["AAPL", "MSFT"]


def test_companyfacts_and_submissions_zips_parse_known_members():
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"val": 150, "frame": "CY2024", "start": "2024-01-01", "end": "2024-12-31",
                     "filed": "2025-02-01", "form": "10-K", "fp": "FY", "fy": 2024}
                ]}},
                "NetIncomeLoss": {"units": {"USD": [
                    {"val": 18, "frame": "CY2024", "start": "2024-01-01", "end": "2024-12-31",
                     "filed": "2025-02-01", "form": "10-K", "fp": "FY", "fy": 2024}
                ]}},
            }
        }
    }
    sub = {
        "name": "Apple Inc.",
        "sic": "3571",
        "sicDescription": "ELECTRONIC COMPUTERS",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "stateOfIncorporation": "CA",
        "addresses": {"business": {"stateOrCountry": "CA", "isForeignLocation": 0}},
    }
    facts_buf = io.BytesIO()
    with zipfile.ZipFile(facts_buf, "w") as zf:
        zf.writestr("CIK0000320193.json", json.dumps(facts))
        zf.writestr("CIK0000999999.json", json.dumps({"facts": {}}))
    facts_buf.seek(0)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        facts_path = os.path.join(tmp, "companyfacts.zip")
        sub_path = os.path.join(tmp, "submissions.zip")
        open(facts_path, "wb").write(facts_buf.getvalue())
        with zipfile.ZipFile(sub_path, "w") as zf:
            zf.writestr("CIK0000320193.json", json.dumps(sub))
        annual, quarters, found, missing = profiles.parse_companyfacts_from_zip(
            facts_path, {"AAPL": "0000320193", "GONE": "0000000001"}, fund.parse_companyfacts
        )
        assert found == ["AAPL"]
        assert missing == ["GONE"]
        assert float(annual[annual.ticker == "AAPL"]["revenue"].iloc[0]) == 150
        prof = profiles.parse_submissions_from_zip(sub_path, {"AAPL": "0000320193"})
        assert list(prof["ticker"]) == ["AAPL"]
        assert prof.iloc[0]["company"] == "Apple Inc."
        assert prof.iloc[0]["sector"] == "Information Technology"


def test_finnhub_is_skipped_when_the_key_is_missing():
    old = os.environ.pop("FINNHUB_API_KEY", None)
    try:
        assert profiles.finnhub_api_key() == ""
        os.environ["FINNHUB_API_KEY"] = "  demo  "
        assert profiles.finnhub_api_key() == "demo"
        row = profiles.parse_finnhub_profile({"weburl": "https://example.com", "country": "US", "finnhubIndustry": "Tech"}, "aapl")
        assert row["ticker"] == "AAPL"
        assert row["website"] == "https://example.com"
    finally:
        if old is None:
            os.environ.pop("FINNHUB_API_KEY", None)
        else:
            os.environ["FINNHUB_API_KEY"] = old




def test_mixed_yahoo_and_nasdaq_dates_still_parse():
    # Yahoo history is tz-aware; the Nasdaq calendar is a date only. Parsing
    # the two together must not turn the calendar date into NaT.
    mixed = pd.Series([
        "2026-10-22 16:00:00-04:00",
        "2026-12-16",
        "2027-02-04 16:00:00-05:00",
    ])
    dts = profiles.parse_earnings_dt(mixed)
    assert dts.notna().all()
    assert str(dts.iloc[1].date()) == "2026-12-16"
    existing = pd.DataFrame([
        {"ticker": "MSFT", "earnings_dt": "2026-10-22 16:00:00-04:00", "source": "yahoo"},
    ])
    calendar = pd.DataFrame([
        {"ticker": "MSFT", "earnings_dt": "2026-12-16", "source": "nasdaq_calendar"},
        {"ticker": "ABM", "earnings_dt": "2026-12-16", "source": "nasdaq_calendar"},
    ])
    now = pd.Timestamp("2026-11-10 17:00", tz="UTC")
    out = profiles.merge_earnings_dates(existing, calendar, now=now)
    dts = profiles.parse_earnings_dt(out["earnings_dt"])
    future = out[dts.notna() & (dts > now)]
    assert "MSFT" in set(future["ticker"])
    assert "ABM" in set(future["ticker"])
    msft_dates = set(profiles.parse_earnings_dt(out.loc[out.ticker=="MSFT", "earnings_dt"]).dt.strftime("%Y-%m-%d"))
    assert "2026-12-16" in msft_dates

if __name__ == "__main__":
    test_sic_to_sector_is_approximate_and_covers_common_groups()
    test_submissions_profile_reads_name_country_exchange_and_sic()
    test_profiles_never_overwrite_a_filled_sector_or_name()
    test_calendar_days_skip_weekends_inside_the_window()
    test_nasdaq_calendar_parses_rows_and_keeps_saved_on_failure()
    test_merge_earnings_dates_only_fills_names_still_missing_a_future_date()
    test_companyfacts_and_submissions_zips_parse_known_members()
    test_finnhub_is_skipped_when_the_key_is_missing()
    test_mixed_yahoo_and_nasdaq_dates_still_parse()
    print("profiles ok")
