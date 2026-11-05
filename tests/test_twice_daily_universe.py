"""Twice-daily schedule, the wider universe, SEC mapping, and a gradual backfill.

Fixed dates and made-up rows. No clock and no network.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import watchdog as w
import stock_desk as desk
import tables

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UTC = dt.timezone.utc


def desk_slots(day):
    return [(t.strftime("%H:%M"), m) for t, m in w.slots_for_day(dt.date.fromisoformat(day), twice_daily=True)]


def test_twice_daily_keeps_open_and_close_only():
    # Monday 2 Nov 2026 is EST. 10:15 ET is 15:15 UTC. 18:30 ET is 23:30 UTC.
    assert desk_slots("2026-11-02") == [("15:15", "hourly"), ("23:30", "full")]
    # Friday 30 Oct 2026 is EDT. 10:15 ET is 14:15 UTC. 18:30 ET is 22:30 UTC.
    assert desk_slots("2026-10-30") == [("14:15", "hourly"), ("22:30", "full")]
    assert desk_slots("2026-11-01") == []
    # The hourly calendar is still there when the switch is off.
    hourly = [(t.strftime("%H:%M"), m) for t, m in w.slots_for_day(dt.date(2026, 11, 2), twice_daily=False)]
    assert len(hourly) == 9 and hourly[0] == ("15:15", "hourly") and hourly[-1] == ("23:30", "full")
    assert w.apply_schedule({}) is True
    assert w.apply_schedule({"features": {"twice_daily_schedule": False}}) is False
    w.TWICE_DAILY = False


def test_gate_skips_the_midday_crons_when_twice_daily():
    old = w.TWICE_DAILY
    w.TWICE_DAILY = True
    try:
        # 16:15 UTC on 30 Oct 2026 is 12:15 ET. That hourly cron must not run.
        go, mode, _ = w.schedule_gate("15 14-22 * * 1-5", dt.datetime(2026, 10, 30, 16, 18, tzinfo=UTC))
        assert go is False
        # 14:15 UTC is 10:15 ET and stays the open run.
        go, mode, _ = w.schedule_gate("15 14-22 * * 1-5", dt.datetime(2026, 10, 30, 14, 18, tzinfo=UTC))
        assert go is True and mode == "hourly"
        go, mode, _ = w.schedule_gate("30 22,23 * * 1-5", dt.datetime(2026, 10, 30, 22, 33, tzinfo=UTC))
        assert go is True and mode == "full"
    finally:
        w.TWICE_DAILY = old


def test_xom_override_and_rolling_slice():
    mapped = desk.resolve_cik({"XOM": "0002115436", "HONA": "0002089271"}, {"XOM": "34088"})
    assert mapped["XOM"] == "0000034088"
    assert mapped["HONA"] == "0002089271"
    pool = desk.rolling_sec_pool(
        ["AAPL", "MID1", "MID2", "MID3"],
        core=["AAPL"],
        cycle={"MID2": "2026-11-04"},
        today="2026-11-05",
        batch=1,
        every_days=7,
        already_today=[],
    )
    # AAPL is daily. MID2 was fetched yesterday, so it waits. MID1 and MID3 have
    # never been fetched; the slice keeps one of them.
    assert pool[0] == "AAPL"
    assert pool[1:] == ["MID1"]
    assert "MID2" not in pool


def test_backfill_is_capped():
    settings = desk.incremental_price_settings({"incremental_prices": {"backfill_per_run": 1}})
    plan = desk.classify_price_fetches(["BBB", "AAA", "CCC"], None, settings, True)
    assert plan["AAA"]["reason"] == "new" and plan["AAA"]["kind"] == "full"
    assert plan["BBB"]["reason"] == "waiting" and plan["BBB"]["kind"] == "skip"
    assert plan["CCC"]["reason"] == "waiting"


def test_liquid_names_skip_etfs_and_names_already_held():
    listed_nas = "\n".join([
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
        "AAPL|Apple Inc. Common Stock|Q|N|N|100|N|N",
        "PREF|Some Preferred Stock|Q|N|N|100|N|N",
        "SPY|SPDR S&P 500 ETF|G|N|N|100|Y|N",
    ])
    listed_oth = "\n".join([
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
        "BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK.B|N|40|N|BRK.B",
    ])
    good = desk.parse_listed_common(listed_nas, listed_oth)
    assert good == {"AAPL", "BRK-B"}
    rows = [
        {"symbol": "AAPL", "marketCap": "3000000000000"},
        {"symbol": "NEW", "marketCap": "20000000000"},
        {"symbol": "TINY", "marketCap": "1000000000"},
        {"symbol": "BRK.B", "marketCap": "900000000000"},
    ]
    # NEW is not on the symbol file, so it is dropped. BRK-B is already in the desk.
    assert desk.select_liquid_names(rows, good, ["AAPL", "BRK-B"], 10_000_000_000, 10) == []
    good.add("NEW")
    assert desk.select_liquid_names(rows, good, ["AAPL", "BRK-B"], 10_000_000_000, 1) == ["NEW"]


def test_core_list_stays_on_the_original_names():
    import pandas as pd
    universe = pd.DataFrame([
        {"ticker": "AAPL", "in_sp500": "yes", "in_ndx100": "yes", "in_growth": "no", "in_sp400": "no", "in_sp600": "no"},
        {"ticker": "MID", "in_sp500": "no", "in_ndx100": "no", "in_growth": "no", "in_sp400": "yes", "in_sp600": "no"},
    ])
    assert desk.core_tickers(universe, ["HELD"], ["WATCH"]) == ["AAPL", "HELD", "WATCH"]


def test_settings_and_help():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    assert cfg["features"]["twice_daily_schedule"] is True
    assert cfg["features"]["sec_rolling"] is True
    assert cfg["features"]["liquid_names"] is True
    assert cfg["sec_facts"]["cik_overrides"]["XOM"] == "0000034088"
    assert cfg["incremental_prices"]["backfill_per_run"] == 40
    rows = dict(zip(tables.settings_rows(cfg)["setting"].astype(str), tables.settings_rows(cfg)["value"].astype(str)))
    assert rows["feature.twice_daily_schedule"] == "True"
    assert rows["index.sp400"] == "True" and rows["index.sp600"] == "True"
    assert rows["sec_facts.cik_overrides.XOM"] == "0000034088"
    assert rows["incremental_prices.backfill_per_run"] == "40"
    assert rows["liquid_names.min_market_cap"] == "10000000000"
    help_rows = dict(tables.help_rows())
    for topic in ("Twice a day", "Wider universe", "SEC filings for the wider list"):
        assert topic in help_rows
    assert "10:15" in help_rows["Twice a day"] and "18:30" in help_rows["Twice a day"]
    assert "0000034088" in help_rows["SEC filings for the wider list"]
    assert "have not filed a 10-K" in help_rows["SEC filings for the wider list"]
    published = open(os.path.join(ROOT, "data", "help.csv"), encoding="utf-8").read()
    assert "\nTwice a day," in published
    assert "\nWider universe," in published
    settings = open(os.path.join(ROOT, "data", "settings.csv"), encoding="utf-8").read()
    assert "\nfeature.twice_daily_schedule,True\n" in settings
    assert "\nindex.sp400,True\n" in settings


if __name__ == "__main__":
    test_twice_daily_keeps_open_and_close_only()
    test_gate_skips_the_midday_crons_when_twice_daily()
    test_xom_override_and_rolling_slice()
    test_backfill_is_capped()
    test_liquid_names_skip_etfs_and_names_already_held()
    test_core_list_stays_on_the_original_names()
    test_settings_and_help()
    print("twice daily universe ok")
