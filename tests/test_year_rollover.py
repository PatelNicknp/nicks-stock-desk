"""Year change: calendar windows, YTD reset, and off-calendar fiscal years.

Fixed dates only. No clock and no network. Nothing here is tied to 'the current year'
in production code; 2026 and 2027 are just the dates under test.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import fundamentals as fund
import profiles
import stock_desk as desk


def test_nasdaq_calendar_window_crosses_into_january():
    # 45 calendar days starting Dec 20 includes New Year's week in the next year.
    days = profiles.calendar_days("2026-12-20", days_ahead=45, skip_weekends=True)
    # Dec 20, 2026 is a Sunday, so it is skipped and the window starts Monday Dec 21.
    assert "2026-12-20" not in days
    assert days[0] == "2026-12-21"
    assert "2026-12-25" in days  # Christmas weekday is still requested (calendar has no holiday skip)
    assert "2026-12-26" not in days  # Saturday
    assert "2026-12-27" not in days  # Sunday
    assert "2027-01-01" in days  # New Year's Day is a Friday in 2027
    assert "2027-01-04" in days
    assert all(not d.startswith("2025-") for d in days)
    # The last day is within the 45-calendar-day window, not a hardcoded year.
    last = pd.Timestamp(days[-1])
    start = pd.Timestamp("2026-12-20")
    assert last.year == 2027
    assert (last - start).days <= 44


def test_next_earnings_drops_last_years_dates_after_january_1():
    existing = pd.DataFrame([
        {"ticker": "AAPL", "earnings_dt": "2026-12-30", "source": "nasdaq_calendar"},
        {"ticker": "MSFT", "earnings_dt": "2026-10-01", "source": "yahoo"},
    ])
    calendar = pd.DataFrame([
        {"ticker": "AAPL", "earnings_dt": "2027-01-21", "source": "nasdaq_calendar"},
        {"ticker": "MSFT", "earnings_dt": "2027-01-15", "source": "nasdaq_calendar"},
        {"ticker": "NEW", "earnings_dt": "2027-02-02", "source": "nasdaq_calendar"},
    ])
    now = pd.Timestamp("2027-01-02", tz="UTC")
    out = profiles.merge_earnings_dates(existing, calendar, now=now)
    # Dec 30 2026 is no longer a future date, so AAPL gets the January date.
    aapl = out[out.ticker == "AAPL"]
    assert "2027-01-21" in set(aapl["earnings_dt"].astype(str))
    msft_future = out[(out.ticker == "MSFT") & (out.earnings_dt.astype(str) == "2027-01-15")]
    assert len(msft_future) == 1
    assert "NEW" in set(out["ticker"])


def test_ytd_resets_on_the_first_sessions_of_the_new_year():
    # Last two sessions of 2026, then the first sessions of 2027.
    idx = pd.to_datetime([
        "2026-12-30", "2026-12-31", "2027-01-04", "2027-01-05",
    ])
    # 2026 closed at 100, then 110. 2027 opens at 80 and goes to 88 (up 10% this year).
    close = pd.DataFrame({"AAA": [100.0, 110.0, 80.0, 88.0]}, index=idx)
    high = close.copy()
    low = close.copy()
    vol = pd.DataFrame({"AAA": [1_000_000] * 4}, index=idx)
    # Pad so market_features has enough history (it wants 30 bars).
    older = pd.bdate_range("2026-11-01", "2026-12-29")
    pad = pd.DataFrame({
        "AAA": [90.0] * len(older),
    }, index=older)
    close = pd.concat([pad, close])
    high = close.copy()
    low = close.copy()
    vol = pd.DataFrame({"AAA": [1_000_000] * len(close)}, index=close.index)

    asof_2026 = close.loc[: "2026-12-31"]
    mkt_old = desk.market_features(asof_2026, high.loc[asof_2026.index], low.loc[asof_2026.index], vol.loc[asof_2026.index], "AAA", None)
    # YTD through Dec 31 uses 2026 prices only (first 2026 bar in this slice to 110).
    assert mkt_old is not None
    assert mkt_old["asof"] == "2026-12-31"
    first_2026 = float(asof_2026["AAA"][asof_2026.index.year == 2026].iloc[0])
    assert abs(mkt_old["ret_ytd"] - (110.0 / first_2026 - 1)) < 1e-9

    mkt_new = desk.market_features(close, high, low, vol, "AAA", None)
    assert mkt_new["asof"] == "2027-01-05"
    # New year YTD is 88 / 80 - 1 = 0.10, not a number that still includes 2026.
    assert abs(mkt_new["ret_ytd"] - 0.10) < 1e-9
    assert mkt_new["ret_ytd"] != mkt_old["ret_ytd"]


def test_sec_keeps_a_january_fiscal_year_end_on_its_own_year():
    """A filer whose fiscal year ends in January is not dropped when the calendar year changes.

    Period end 2027-01-31 is fiscal 2026 for this company. The frame and the
    unframed FY fallback both have to keep that row.
    """
    def row(val, frame, start, end, filed, form, fp="FY", fy=2026):
        rec = {"val": val, "frame": frame, "end": end, "filed": filed, "form": form, "fp": fp, "fy": fy}
        if start:
            rec["start"] = start
        return rec

    # Framed fiscal year ending 31 Jan 2027 (often tagged CY2026).
    framed = {
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                row(200, "CY2026", "2026-02-01", "2027-01-31", "2027-03-15", "10-K", fy=2026),
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                row(20, "CY2026", "2026-02-01", "2027-01-31", "2027-03-15", "10-K", fy=2026),
            ]}},
        }}
    }
    annual, _ = fund.parse_companyfacts(framed)
    assert len(annual) == 1
    assert str(annual.iloc[0]["end"])[:10] == "2027-01-31"
    assert annual.iloc[0]["revenue"] == 200
    assert annual.iloc[0]["net_income"] == 20

    # Same year-end with no CY frame, which is common on a 10-K. The FY flag
    # and ~365-day duration should still keep it after New Year's.
    unframed = {
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                row(310, "", "2027-02-01", "2028-01-31", "2028-03-15", "10-K", fy=2027),
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                row(31, "", "2027-02-01", "2028-01-31", "2028-03-15", "10-K", fy=2027),
            ]}},
        }}
    }
    annual2, _ = fund.parse_companyfacts(unframed)
    assert len(annual2) == 1
    assert str(annual2.iloc[0]["end"])[:10] == "2028-01-31"
    assert annual2.iloc[0]["revenue"] == 310


def test_calendar_and_ytd_do_not_hardcode_a_year():
    import inspect
    # Production helpers take a start date or read it from the last price bar.
    src = inspect.getsource(profiles.calendar_days)
    assert "2026" not in src and "2027" not in src
    src = inspect.getsource(profiles.merge_earnings_dates)
    assert "2026" not in src and "2027" not in src
    src = inspect.getsource(desk.market_features)
    assert "2026" not in src and "2027" not in src
    # YTD uses the year of the last bar, not a literal.
    assert "c.index[-1].year" in src or "index.year" in src
    src = inspect.getsource(desk.load_nasdaq_earnings)
    assert "2026" not in src and "2027" not in src
    assert "today_et()" in src or "today" in src


if __name__ == "__main__":
    test_nasdaq_calendar_window_crosses_into_january()
    test_next_earnings_drops_last_years_dates_after_january_1()
    test_ytd_resets_on_the_first_sessions_of_the_new_year()
    test_sec_keeps_a_january_fiscal_year_end_on_its_own_year()
    test_calendar_and_ytd_do_not_hardcode_a_year()
    print("year rollover ok")
