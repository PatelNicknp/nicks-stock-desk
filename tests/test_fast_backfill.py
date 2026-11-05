"""Fast history backfill. Fixed rows, no clock and no network."""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_desk as desk
import tables
import watchdog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg(**over):
    features = {"fast_history_backfill": True, "incremental_prices": True}
    features.update(over.pop("features", {}))
    prices = {"backfill_per_run": 40, "fast_backfill_per_run": 600, "chart_concurrency": 2, "fast_backfill_max_runs": 4}
    prices.update(over.pop("prices", {}))
    return {"features": features, "incremental_prices": prices}


def test_regular_runs_stay_at_40_and_two_wide():
    cfg = _cfg()
    hourly = desk.price_settings_for(cfg, "hourly")
    full = desk.price_settings_for(cfg, "full")
    assert hourly["backfill_per_run"] == 40 and full["backfill_per_run"] == 40
    assert hourly["chart_concurrency"] == 2 and full["chart_concurrency"] == 2
    catch = desk.price_settings_for(cfg, "backfill")
    assert catch["backfill_per_run"] == 600
    assert catch["chart_concurrency"] == 2
    assert catch["fast_backfill_per_run"] == 600
    off = _cfg(features={"fast_history_backfill": False})
    assert desk.price_settings_for(off, "backfill")["backfill_per_run"] == 40
    # A typo cannot ask for tens of thousands of charts in one chunk.
    huge = desk.incremental_price_settings({"incremental_prices": {"fast_backfill_per_run": 99999, "chart_concurrency": 2}})
    assert huge["fast_backfill_per_run"] == 2500
    assert huge["chart_concurrency"] == 2


def test_catch_up_ignores_names_that_already_have_bars():
    import pandas as pd
    cached = pd.DataFrame([
        {"date": "2024-01-02", "ticker": "AAA", "close": 10, "high": 11, "low": 9, "volume": 100, "open": 10},
        {"date": "2024-01-03", "ticker": "AAA", "close": 11, "high": 12, "low": 10, "volume": 100, "open": 11},
    ])
    settings = desk.price_settings_for(_cfg(prices={"fast_backfill_per_run": 1, "repair_below_bars": 1}), "backfill")
    plan = desk.classify_price_fetches(["CCC", "AAA", "BBB"], cached, settings, True)
    new, waiting = desk.backfill_symbols(plan)
    assert plan["AAA"]["reason"] == "update"
    assert new == ["BBB"]
    assert waiting == ["CCC"]
    assert "AAA" not in new and "AAA" not in waiting


def test_chain_stops_when_done_stuck_or_out_of_runs():
    moving = {"enabled": 1, "fetched": 600, "waiting": 600}
    assert desk.backfill_should_chain(moving, 0, 4)
    assert desk.backfill_should_chain(moving, "1", 4)
    assert not desk.backfill_should_chain({"enabled": 1, "fetched": 600, "waiting": 0}, 0, 4)
    assert not desk.backfill_should_chain({"enabled": 1, "fetched": 0, "waiting": 600}, 0, 4)
    assert not desk.backfill_should_chain({"enabled": 0, "fetched": 10, "waiting": 10}, 0, 4)
    assert not desk.backfill_should_chain(moving, 3, 4)
    assert desk.backfill_should_chain(moving, 2, 4)
    body = watchdog.backfill_dispatch_body("main", "0")
    assert body == {"ref": "main", "inputs": {"run_index": "1"}}
    assert watchdog.backfill_dispatch_body("", "bad")["inputs"]["run_index"] == "1"


def test_switch_off_makes_no_download():
    tmp = tempfile.mkdtemp()
    old_root = desk.ROOT
    desk.ROOT = tmp
    desk.STAMPS.clear()
    called = []
    old_dl = desk._download_long

    def _boom(*args, **kwargs):
        called.append(args)
        raise AssertionError("download")

    desk._download_long = _boom
    try:
        code = desk.run_history_backfill({"features": {"fast_history_backfill": False, "incremental_prices": True}, "incremental_prices": {}})
        assert code == 0 and called == []
    finally:
        desk._download_long = old_dl
        desk.ROOT = old_root
        desk.STAMPS.clear()
        shutil.rmtree(tmp)


def test_chunk_downloads_only_the_capped_new_names():
    tmp = tempfile.mkdtemp()
    old_root = desk.ROOT
    desk.ROOT = tmp
    desk.STAMPS.clear()
    import pandas as pd
    os.makedirs(os.path.join(tmp, "cache"))
    cached = pd.DataFrame([
        {"date": "2024-01-02", "ticker": "AAA", "close": 10, "high": 11, "low": 9, "volume": 100, "open": 10},
    ])
    cached.to_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"), index=False, compression="gzip")
    seen = {}

    def _fake_universe(cfg, cache, mode, hold, watch):
        return pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"]}), ["AAA", "BBB", "CCC"]

    def _fake_download(tickers, cfg, start, threads, period):
        seen["tickers"] = list(tickers)
        seen["start"] = start
        seen["threads"] = threads
        seen["period"] = period
        return pd.DataFrame([
            {"date": "2024-01-02", "ticker": tickers[0], "close": 5, "high": 6, "low": 4, "volume": 50, "open": 5},
            {"date": "2021-01-04", "ticker": tickers[0], "close": 4, "high": 4, "low": 4, "volume": 50, "open": 4},
        ])

    old_build, old_dl = desk.build_price_tickers, desk._download_long
    desk.build_price_tickers = _fake_universe
    desk._download_long = _fake_download
    cfg = {
        "features": {"fast_history_backfill": True, "incremental_prices": True, "universe": True},
        "incremental_prices": {"fast_backfill_per_run": 1, "chart_concurrency": 2, "history_period": "5y", "repair_below_bars": 1},
    }
    try:
        code = desk.run_history_backfill(cfg)
        assert code == 0
        assert seen["tickers"] == ["BBB"]
        assert seen["threads"] == 2 and seen["period"] == "5y" and seen["start"] is None
        saved = pd.read_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"))
        assert set(saved["ticker"]) == {"AAA", "BBB"}
    finally:
        desk.build_price_tickers = old_build
        desk._download_long = old_dl
        desk.ROOT = old_root
        desk.STAMPS.clear()
        shutil.rmtree(tmp)


def test_settings_and_help():
    with open(os.path.join(ROOT, "config.json")) as fh:
        cfg = json.load(fh)
    assert cfg["features"]["fast_history_backfill"] is True
    assert cfg["incremental_prices"]["backfill_per_run"] == 40
    assert cfg["incremental_prices"]["fast_backfill_per_run"] == 600
    assert cfg["incremental_prices"]["fast_backfill_max_runs"] == 4
    assert cfg["incremental_prices"]["chart_concurrency"] == 2
    rows = dict(zip(tables.settings_rows(cfg)["setting"].astype(str), tables.settings_rows(cfg)["value"].astype(str)))
    assert rows["feature.fast_history_backfill"] == "True"
    assert rows["incremental_prices.backfill_per_run"] == "40"
    assert rows["incremental_prices.fast_backfill_per_run"] == "600"
    assert rows["incremental_prices.fast_backfill_max_runs"] == "4"
    help_rows = dict(tables.help_rows())
    text = help_rows["Fast history backfill"]
    assert "600" in text and "40" in text and "two chart calls" in text
    assert "features.fast_history_backfill" in text
    assert "fast_backfill_per_run" in help_rows["Incremental price settings"]
    published = open(os.path.join(ROOT, "data", "help.csv"), encoding="utf-8").read()
    assert "\nFast history backfill," in published
    settings = open(os.path.join(ROOT, "data", "settings.csv"), encoding="utf-8").read()
    assert "\nfeature.fast_history_backfill,True\n" in settings
    assert "\nincremental_prices.fast_backfill_per_run,600\n" in settings
    assert "\nincremental_prices.backfill_per_run,40\n" in settings


if __name__ == "__main__":
    test_regular_runs_stay_at_40_and_two_wide()
    test_catch_up_ignores_names_that_already_have_bars()
    test_chain_stops_when_done_stuck_or_out_of_runs()
    test_switch_off_makes_no_download()
    test_chunk_downloads_only_the_capped_new_names()
    test_settings_and_help()
    print("fast backfill ok")
