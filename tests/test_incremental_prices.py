"""Incremental daily prices: merge, no shrink, adjustment refetch, and the switch.

Fixed dates and made-up bars. No clock and no network.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

import stock_desk
import tables

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _settings(**overrides):
    raw = {
        "repair": True,
        "refresh": True,
        "refresh_mode": "weekly",
        "refresh_every_days": 7,
        "refresh_slices": 8,
        "overlap_days": 5,
        "adjust_tolerance_pct": 0.05,
        "adjust_tolerance_dollars": 0.02,
        "chart_concurrency": 2,
        "repair_below_bars": 126,
        "history_period": "5y",
    }
    raw.update(overrides)
    return stock_desk.incremental_price_settings({"incremental_prices": raw})


def _bars(ticker, dates, close, volume=1000):
    rows = []
    for i, day in enumerate(dates):
        px = close[i] if isinstance(close, (list, tuple)) else close
        rows.append({
            "date": day, "ticker": ticker, "close": px,
            "high": px + 1, "low": px - 1, "volume": volume, "open": px,
        })
    return pd.DataFrame(rows)


def _closes(frame, ticker):
    sub = frame[frame["ticker"] == ticker]
    return dict(zip(sub["date"], sub["close"]))


def test_merge_replaces_overlap_and_appends():
    cached = _bars("AAA", ["2024-01-02", "2024-01-03", "2024-01-04"], [10, 11, 12])
    fresh = _bars("AAA", ["2024-01-04", "2024-01-05"], [12.01, 13])
    merged, bad = stock_desk.merge_price_rows(cached, fresh, _settings())
    assert bad == []
    got = _closes(merged, "AAA")
    assert got["2024-01-02"] == 10
    assert got["2024-01-03"] == 11
    assert abs(got["2024-01-04"] - 12.01) < 1e-9
    assert got["2024-01-05"] == 13
    assert len(merged) == 4


def test_short_download_does_not_shrink_history():
    cached = _bars("AAA", ["2020-01-02", "2024-01-03", "2024-01-04"], [10, 11, 12])
    fresh = _bars("AAA", ["2024-01-04"], [12.5])
    merged, bad = stock_desk.merge_price_rows(cached, fresh, _settings())
    assert bad == []
    got = _closes(merged, "AAA")
    assert set(got) == {"2020-01-02", "2024-01-03", "2024-01-04"}
    assert got["2020-01-02"] == 10
    assert got["2024-01-03"] == 11
    assert got["2024-01-04"] == 12.5
    # A symbol the download did not mention keeps every saved bar.
    both = pd.concat([cached, _bars("BBB", ["2024-01-03", "2024-01-04"], [20, 21])], ignore_index=True)
    kept, _bad = stock_desk.merge_price_rows(both, fresh, _settings())
    assert set(kept[kept.ticker == "BBB"]["date"]) == {"2024-01-03", "2024-01-04"}


def test_forming_bar_is_not_an_adjustment():
    cached = _bars("AAA", ["2024-01-03", "2024-01-04"], [100, 100])
    fresh = _bars("AAA", ["2024-01-03", "2024-01-04"], [100, 140])
    merged, bad = stock_desk.merge_price_rows(cached, fresh, _settings())
    assert bad == []
    got = _closes(merged, "AAA")
    assert got["2024-01-03"] == 100
    assert got["2024-01-04"] == 140


def test_overlap_mismatch_flags_refetch_and_does_not_mix():
    cached = _bars("AAA", ["2019-06-03", "2024-01-02", "2024-01-03", "2024-01-04"], [80, 100, 100, 100])
    fresh = _bars("AAA", ["2024-01-03", "2024-01-04"], [50, 50])
    merged, bad = stock_desk.merge_price_rows(cached, fresh, _settings())
    assert bad == ["AAA"]
    got = _closes(merged, "AAA")
    assert got["2019-06-03"] == 80
    assert got["2024-01-03"] == 100
    assert got["2024-01-04"] == 100
    # The full refetch replaces the overlap and still keeps a day the refetch did not return.
    full = _bars("AAA", ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], [40, 50, 50, 51])
    applied, again = stock_desk.merge_price_rows(merged, full, _settings(), hold_back=[])
    assert again == []
    got = _closes(applied, "AAA")
    assert got["2019-06-03"] == 80
    assert got["2024-01-02"] == 40
    assert got["2024-01-03"] == 50
    assert got["2024-01-05"] == 51


def test_tolerance_ignores_pennies_and_catches_a_split():
    assert stock_desk.close_mismatch(100, 100.02, 0.05, 0.02) is False
    assert stock_desk.close_mismatch(10, 10.01, 0.05, 0.02) is False
    assert stock_desk.close_mismatch(10, 10.03, 0.05, 0.02) is True
    assert stock_desk.close_mismatch(100, 50, 0.05, 0.02) is True
    # Exactly on the band is not beyond it.
    assert stock_desk.close_mismatch(10, 10.02, 0.05, 0.02) is False


def test_switch_off_plans_a_full_replace():
    cached = _bars("AAA", ["2020-01-02", "2024-01-04"], [10, 12])
    fresh = _bars("AAA", ["2024-01-04"], [12])
    replaced, bad = stock_desk.combine_downloaded_prices(cached, fresh, False, _settings())
    assert bad == []
    assert list(replaced["date"]) == ["2024-01-04"]
    assert len(replaced) == 1
    plan = stock_desk.classify_price_fetches(["AAA"], cached, _settings(), enabled=False)
    assert plan["AAA"]["kind"] == "full"
    assert plan["AAA"]["reason"] == "switched_off"
    kept, _bad = stock_desk.combine_downloaded_prices(cached, fresh, True, _settings())
    assert set(kept["date"]) == {"2020-01-02", "2024-01-04"}


def test_short_history_is_repaired_once_and_then_updated():
    stub = _bars("KVUE", ["2026-11-03"], [17])
    settings = _settings()
    plan = stock_desk.classify_price_fetches(["KVUE"], stub, settings, True, repairs={})
    assert plan["KVUE"]["kind"] == "full"
    assert plan["KVUE"]["reason"] == "repair"
    done = stock_desk.classify_price_fetches(["KVUE"], stub, settings, True, repairs={"KVUE": {"bars": 1}})
    assert done["KVUE"]["reason"] == "update"
    assert done["KVUE"]["start"] == "2026-10-29"
    # A history that shrank below the recorded full fetch is repaired again.
    shrunk = stock_desk.classify_price_fetches(["KVUE"], stub, settings, True, repairs={"KVUE": {"bars": 800}})
    assert shrunk["KVUE"]["reason"] == "repair"
    # A one-bar answer is not treated as a finished repair, so the next run asks again.
    remembered = stock_desk.note_price_repairs({}, stub, stub, ["KVUE"], settings["repair_below_bars"])
    assert "KVUE" not in remembered
    listing_dates = list(pd.bdate_range("2026-09-01", periods=24).strftime("%Y-%m-%d"))
    listing = _bars("VYLR", listing_dates, 8)
    remembered = stock_desk.note_price_repairs({}, listing, listing, ["VYLR"], settings["repair_below_bars"])
    assert remembered["VYLR"]["bars"] == 24


def test_incremental_start_weekly_refresh_and_slice():
    dates = list(pd.bdate_range("2024-01-02", periods=200).strftime("%Y-%m-%d"))
    cached = _bars("AAPL", dates, 100)
    settings = _settings()
    plan = stock_desk.classify_price_fetches(["AAPL"], cached, settings, True)
    assert plan["AAPL"]["reason"] == "update"
    assert plan["AAPL"]["kind"] == "incremental"
    expect = (pd.Timestamp(dates[-1]) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    assert plan["AAPL"]["start"] == expect
    assert stock_desk.weekly_refresh_due(None, "2026-11-04", 7) is False
    assert stock_desk.weekly_refresh_due("2026-11-01", "2026-11-07", 7) is False
    assert stock_desk.weekly_refresh_due("2026-10-28", "2026-11-04", 7) is True
    weekly = stock_desk.classify_price_fetches(["AAPL"], cached, settings, True, refresh_all=True)
    assert weekly["AAPL"]["reason"] == "refresh"
    assert weekly["AAPL"]["kind"] == "full"
    sliced = _settings(refresh_mode="slice", repair_below_bars=10)
    index = stock_desk.refresh_slice_index("2026-11-04", 8)
    assert index == stock_desk.refresh_slice_index("2026-11-04", 8)
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    book = pd.concat([_bars(s, dates, 20) for s in symbols], ignore_index=True)
    plan = stock_desk.classify_price_fetches(symbols, book, sliced, True, slice_index=index)
    for symbol in symbols:
        reason = "refresh" if stock_desk.ticker_in_slice(symbol, 8, index) else "update"
        assert plan[symbol]["reason"] == reason
    quiet = _settings(refresh=False, refresh_mode="slice", repair_below_bars=10)
    off = stock_desk.classify_price_fetches(symbols, book, quiet, True, slice_index=index)
    assert {item["reason"] for item in off.values()} == {"update"}


def test_new_symbol_is_a_full_fetch():
    cached = _bars("AAA", ["2024-01-02", "2024-01-03"], [10, 11])
    plan = stock_desk.classify_price_fetches(["AAA", "NEW"], cached, _settings(repair_below_bars=2), True)
    assert plan["AAA"]["reason"] == "update"
    assert plan["NEW"]["kind"] == "full"
    assert plan["NEW"]["reason"] == "new"


def test_settings_and_help_rows():
    with open(os.path.join(ROOT, "config.json")) as fh:
        cfg = json.load(fh)
    assert cfg["features"]["incremental_prices"] is True
    block = cfg["incremental_prices"]
    assert block["repair"] is True and block["refresh"] is True
    assert block["chart_concurrency"] == 2
    assert block["overlap_days"] == 5
    assert block["refresh_mode"] == "weekly"
    rows = dict(zip(tables.settings_rows(cfg)["setting"].astype(str), tables.settings_rows(cfg)["value"].astype(str)))
    assert rows["feature.incremental_prices"] == "True"
    for key in (
        "repair", "refresh", "refresh_mode", "refresh_every_days", "refresh_slices",
        "overlap_days", "adjust_tolerance_pct", "adjust_tolerance_dollars",
        "chart_concurrency", "repair_below_bars", "history_period",
    ):
        assert rows["incremental_prices." + key] == str(block[key]), key
    help_rows = dict(tables.help_rows())
    assert "few days of overlap" in help_rows["Incremental prices"]
    assert "cannot erase" in help_rows["Incremental prices"]
    assert "features.incremental_prices" in help_rows["Incremental price settings"]
    assert "0.05 means 0.05 percent" in help_rows["Incremental price settings"]
    assert "one or two chart calls" in help_rows["Rate limits"]
    published_help = open(os.path.join(ROOT, "data", "help.csv"), encoding="utf-8").read()
    assert "\nIncremental prices," in published_help
    assert "\nIncremental price settings," in published_help
    published = open(os.path.join(ROOT, "data", "settings.csv"), encoding="utf-8").read()
    assert "\nfeature.incremental_prices,True\n" in published
    assert "\nincremental_prices.chart_concurrency,2\n" in published
    assert "\nincremental_prices.overlap_days,5\n" in published
    assert 'period="5y"' in open(os.path.join(ROOT, "stock_desk.py"), encoding="utf-8").read()
    clamped = stock_desk.incremental_price_settings({"incremental_prices": {"chart_concurrency": 99, "refresh_mode": "nope"}})
    assert clamped["chart_concurrency"] == 8
    assert clamped["refresh_mode"] == "weekly"


if __name__ == "__main__":
    test_merge_replaces_overlap_and_appends()
    test_short_download_does_not_shrink_history()
    test_forming_bar_is_not_an_adjustment()
    test_overlap_mismatch_flags_refetch_and_does_not_mix()
    test_tolerance_ignores_pennies_and_catches_a_split()
    test_switch_off_plans_a_full_replace()
    test_short_history_is_repaired_once_and_then_updated()
    test_incremental_start_weekly_refresh_and_slice()
    test_new_symbol_is_a_full_fetch()
    test_settings_and_help_rows()
    print("incremental prices ok")
