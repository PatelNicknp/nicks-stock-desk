"""Fast history backfill. Fixed rows, no clock and no network."""
import json
import os
import shutil
import subprocess
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

    def _fake_download(tickers, cfg, start, threads, period, outcomes=None):
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
        assert float(saved.loc[saved["ticker"] == "AAA", "close"].iloc[0]) == 10
        code = desk.run_history_backfill(cfg)
        assert code == 0
        assert seen["tickers"] == ["CCC"]
        saved = pd.read_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"))
        assert set(saved["ticker"]) == {"AAA", "BBB", "CCC"}
        assert float(saved.loc[saved["ticker"] == "AAA", "close"].iloc[0]) == 10
    finally:
        desk.build_price_tickers = old_build
        desk._download_long = old_dl
        desk.ROOT = old_root
        desk.STAMPS.clear()
        shutil.rmtree(tmp)


NOV5_LOG = (
    "HTTP Error 404: Quote not found for symbol: CWEN-A\n"
    "[OK] Universe size 1720 1720 names after S&P 400, S&P 600, and liquid additions\n"
    "BACKFILL enabled=1 fetched=599 waiting=598 cap=600 concurrency=2 universe=1720\n"
    "Backfill saved 599 new histories (598 still waiting, cap 600, 2 at a time). "
    "Cache only. No profiles, filings, news, or options.\n"
)


def _followup_child(log_path, output_path, run_index):
    """The workflow's second process: a fresh interpreter, ROOT still None."""
    env = os.environ.copy()
    env.pop("DESK_ROOT", None)
    env["BACKFILL_RUN_INDEX"] = str(run_index)
    env["GITHUB_OUTPUT"] = output_path
    script = (
        "import os, stock_desk as desk\n"
        "assert desk.ROOT is None\n"
        "chain, status = desk.write_backfill_followup(\n"
        "    %r, os.environ.get('BACKFILL_RUN_INDEX'), os.environ.get('GITHUB_OUTPUT'))\n"
        "print('chain', chain, 'fetched', status.get('fetched'), 'waiting', status.get('waiting'))\n"
    ) % log_path
    return subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True,
    )


def test_followup_loads_config_without_calling_main():
    """The Nov 5 job saved histories, then crashed here and never committed them."""
    tmp = tempfile.mkdtemp()
    try:
        log_path = os.path.join(tmp, "backfill.log")
        out_path = os.path.join(tmp, "github_output.txt")
        cache_path = os.path.join(tmp, "ohlcv.csv.gz")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(NOV5_LOG)
        with open(cache_path, "wb") as handle:
            handle.write(b"cached-bytes-must-stay")
        before = open(cache_path, "rb").read()
        done = _followup_child(log_path, out_path, 0)
        assert done.returncode == 0, done.stdout + done.stderr
        assert "ROOT None" not in done.stderr
        assert open(cache_path, "rb").read() == before
        text = open(out_path, encoding="utf-8").read()
        assert "chain=true\n" in text
        assert "waiting=598\n" in text
        assert "fetched=599\n" in text
        assert "chain True fetched 599 waiting 598" in done.stdout
    finally:
        shutil.rmtree(tmp)


def test_followup_does_not_chain_a_failed_or_final_chunk():
    tmp = tempfile.mkdtemp()
    old = desk.ROOT
    old_env = os.environ.get("DESK_ROOT")
    desk.ROOT = None
    os.environ.pop("DESK_ROOT", None)
    try:
        stuck = os.path.join(tmp, "stuck.log")
        with open(stuck, "w", encoding="utf-8") as handle:
            handle.write("BACKFILL enabled=1 fetched=0 waiting=1122 cap=600 concurrency=2 universe=1725\n")
        out = os.path.join(tmp, "out.txt")
        chain, status = desk.write_backfill_followup(stuck, "0", out)
        assert chain is False and status["fetched"] == 0 and status["waiting"] == 1122
        assert "chain=false\n" in open(out, encoding="utf-8").read()
        last = os.path.join(tmp, "last.log")
        with open(last, "w", encoding="utf-8") as handle:
            handle.write("BACKFILL enabled=1 fetched=522 waiting=1 cap=600 concurrency=2 universe=1725\n")
        chain, _status = desk.write_backfill_followup(last, "3", None)
        assert chain is False
        missing = os.path.join(tmp, "empty.log")
        with open(missing, "w", encoding="utf-8") as handle:
            handle.write("no status line\n")
        try:
            desk.write_backfill_followup(missing, "0", None)
        except SystemExit as exc:
            assert "no BACKFILL line" in str(exc)
        else:
            raise AssertionError("missing BACKFILL line should stop the step")
    finally:
        desk.ROOT = old
        if old_env is None:
            os.environ.pop("DESK_ROOT", None)
        else:
            os.environ["DESK_ROOT"] = old_env
        shutil.rmtree(tmp)


def test_unset_root_uses_desk_root_before_the_repo():
    tmp = tempfile.mkdtemp()
    old_root = desk.ROOT
    old_env = os.environ.get("DESK_ROOT")
    desk.ROOT = None
    try:
        with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as handle:
            json.dump({"incremental_prices": {"fast_backfill_max_runs": 7, "fast_backfill_per_run": 600}}, handle)
        os.environ["DESK_ROOT"] = tmp
        assert desk.root() == tmp
        settings = desk.incremental_price_settings(desk.load_cfg())
        assert settings["fast_backfill_max_runs"] == 7
        assert settings["fast_backfill_per_run"] == 600
    finally:
        desk.ROOT = old_root
        if old_env is None:
            os.environ.pop("DESK_ROOT", None)
        else:
            os.environ["DESK_ROOT"] = old_env
        shutil.rmtree(tmp)


def _bars(ticker, close, n=40):
    import pandas as pd
    rows = []
    for i in range(n):
        rows.append({
            "date": str(pd.Timestamp("2024-01-02") + pd.Timedelta(days=i))[:10],
            "ticker": ticker, "close": close, "high": close + 1, "low": close - 1, "volume": 100, "open": close,
        })
    return rows


def test_unavailable_symbol_is_recorded_and_not_retried():
    import pandas as pd
    tmp = tempfile.mkdtemp()
    old_root = desk.ROOT
    desk.ROOT = tmp
    desk.STAMPS.clear()
    os.makedirs(os.path.join(tmp, "cache"))
    os.makedirs(os.path.join(tmp, "data"))
    pd.DataFrame(_bars("AAA", 10)).to_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"), index=False, compression="gzip")
    before = open(os.path.join(tmp, "cache", "ohlcv.csv.gz"), "rb").read()
    calls = []

    def _fetch(symbols):
        calls.append(list(symbols))
        outcomes = [{"symbol": "NOPE", "kind": "unavailable", "detail": "no daily bars returned"}]
        return pd.DataFrame(columns=["date", "ticker", "close", "high", "low", "volume", "open"]), outcomes

    cfg = {
        "features": {"fast_history_backfill": True, "incremental_prices": True, "universe": True},
        "incremental_prices": {"fast_backfill_per_run": 5, "chart_concurrency": 2, "history_period": "5y", "repair_below_bars": 126},
    }

    def _universe(cfg, cache, mode, hold, watch):
        return pd.DataFrame({"ticker": ["AAA", "NOPE"]}), ["AAA", "NOPE"]

    old_build = desk.build_price_tickers
    desk.build_price_tickers = _universe
    try:
        code = desk.run_history_backfill(cfg, fetcher=_fetch, today="2026-11-07")
        assert code == 0
        assert calls == [["NOPE"]]
        assert open(os.path.join(tmp, "cache", "ohlcv.csv.gz"), "rb").read() == before
        gaps = json.load(open(os.path.join(tmp, "cache", "price_gaps.json")))
        assert gaps["NOPE"]["kind"] == "unavailable"
        assert "delisted" not in gaps["NOPE"]["reason"]
        assert gaps["NOPE"]["recheck_after"] > "2026-11-07"
        calls.clear()
        code = desk.run_history_backfill(cfg, fetcher=_fetch, today="2026-11-08")
        assert code == 0 and calls == []
    finally:
        desk.build_price_tickers = old_build
        desk.ROOT = old_root
        desk.STAMPS.clear()
        shutil.rmtree(tmp)


def test_rate_limit_keeps_saved_bars_and_does_not_mark_unavailable():
    import pandas as pd
    tmp = tempfile.mkdtemp()
    old_root = desk.ROOT
    desk.ROOT = tmp
    desk.STAMPS.clear()
    os.makedirs(os.path.join(tmp, "cache"))
    pd.DataFrame(_bars("AAA", 10, 40)).to_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"), index=False, compression="gzip")

    def _fetch(symbols):
        frames = []
        outcomes = []
        for symbol in symbols:
            if symbol == "WAIT":
                outcomes.append({"symbol": symbol, "kind": "transient", "detail": "429 too many requests"})
            else:
                frames.append(pd.DataFrame(_bars(symbol, 5, 40)))
        fresh = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return fresh, outcomes

    cfg = {
        "features": {"fast_history_backfill": True, "incremental_prices": True, "universe": True},
        "incremental_prices": {"fast_backfill_per_run": 5, "chart_concurrency": 2, "history_period": "5y", "repair_below_bars": 126},
    }

    def _universe(cfg, cache, mode, hold, watch):
        return pd.DataFrame({"ticker": ["AAA", "BBB", "WAIT"]}), ["AAA", "BBB", "WAIT"]

    old_build = desk.build_price_tickers
    desk.build_price_tickers = _universe
    try:
        code = desk.run_history_backfill(cfg, fetcher=_fetch, today="2026-11-07")
        assert code == 2
        saved = pd.read_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"))
        assert set(saved["ticker"]) >= {"AAA", "BBB"}
        assert "WAIT" not in set(saved["ticker"])
        assert float(saved.loc[saved["ticker"] == "AAA", "close"].iloc[0]) == 10
        assert not os.path.exists(os.path.join(tmp, "cache", "price_gaps.json")) or "WAIT" not in json.load(open(os.path.join(tmp, "cache", "price_gaps.json")))
        status = {"enabled": 1, "fetched": 1, "waiting": 1, "outcome": 1}
        assert desk.backfill_should_chain(status, 0, 4)
        assert not desk.backfill_should_chain({"enabled": 1, "fetched": 0, "waiting": 1, "outcome": 2}, 0, 4)
        assert not desk.backfill_should_chain({"enabled": 1, "fetched": 0, "waiting": 0, "outcome": 3}, 0, 4)
    finally:
        desk.build_price_tickers = old_build
        desk.ROOT = old_root
        desk.STAMPS.clear()
        shutil.rmtree(tmp)


def test_restart_downloads_only_what_is_still_missing():
    import pandas as pd
    tmp = tempfile.mkdtemp()
    old_root = desk.ROOT
    desk.ROOT = tmp
    desk.STAMPS.clear()
    os.makedirs(os.path.join(tmp, "cache"))
    pd.DataFrame(_bars("AAA", 10, 40)).to_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"), index=False, compression="gzip")
    seen = []

    def _fetch(symbols):
        seen.append(list(symbols))
        return pd.DataFrame(_bars(symbols[0], 7, 40)), []

    cfg = {
        "features": {"fast_history_backfill": True, "incremental_prices": True, "universe": True},
        "incremental_prices": {"fast_backfill_per_run": 1, "chart_concurrency": 2, "history_period": "5y", "repair_below_bars": 126},
    }

    def _universe(cfg, cache, mode, hold, watch):
        return pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"]}), ["AAA", "BBB", "CCC"]

    old_build = desk.build_price_tickers
    desk.build_price_tickers = _universe
    try:
        assert desk.run_history_backfill(cfg, fetcher=_fetch, today="2026-11-07") == 0
        assert seen == [["BBB"]]
        assert desk.run_history_backfill(cfg, fetcher=_fetch, today="2026-11-07") == 0
        assert seen[1] == ["CCC"]
        saved = pd.read_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"))
        assert set(saved["ticker"]) == {"AAA", "BBB", "CCC"}
        assert float(saved.loc[saved["ticker"] == "AAA", "close"].iloc[0]) == 10
    finally:
        desk.build_price_tickers = old_build
        desk.ROOT = old_root
        desk.STAMPS.clear()
        shutil.rmtree(tmp)


def test_export_uses_cache_dates_and_skips_short_history():
    import pandas as pd
    tmp = tempfile.mkdtemp()
    old_root = desk.ROOT
    desk.ROOT = tmp
    os.makedirs(os.path.join(tmp, "cache"))
    os.makedirs(os.path.join(tmp, "data"))
    rows = _bars("LONG", 12, 40) + _bars("SHORT", 3, 4) + _bars("SPY", 20, 80)
    pd.DataFrame(rows).to_csv(os.path.join(tmp, "cache", "ohlcv.csv.gz"), index=False, compression="gzip")
    pd.DataFrame([
        {"ticker": "LONG", "company": "Long Co", "sector": "Health Care", "index_membership": "SP500",
         "in_sp500": "yes", "in_sp400": "no", "in_sp600": "no", "in_ndx100": "no", "in_growth": "no", "in_liquid": "no"},
        {"ticker": "SHORT", "company": "Short Co", "sector": "Health Care", "index_membership": "SP500",
         "in_sp500": "yes", "in_sp400": "no", "in_sp600": "no", "in_ndx100": "no", "in_growth": "no", "in_liquid": "no"},
    ]).to_csv(os.path.join(tmp, "data", "universe.csv"), index=False)
    cache_bytes = open(os.path.join(tmp, "cache", "ohlcv.csv.gz"), "rb").read()
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    try:
        report = desk.export_cached_scores(os.path.join(tmp, "data"), os.path.join(tmp, "cache"), cfg)
        assert report["scored"] == 1
        assert report["short"] == 1
        assert report["kept"] == 0
        assert open(os.path.join(tmp, "cache", "ohlcv.csv.gz"), "rb").read() == cache_bytes
        scores = pd.read_csv(os.path.join(tmp, "data", "scores.csv"))
        assert list(scores["ticker"]) == ["LONG"]
        assert str(scores["price_as_of"].iloc[0])[:10] == report["price_as_of"]
        candles = pd.read_csv(os.path.join(tmp, "data", "ohlc", "LONG.csv"))
        assert str(candles["date"].iloc[-1])[:10] == str(scores["price_as_of"].iloc[0])[:10]
        assert not os.path.exists(os.path.join(tmp, "data", "ohlc", "SHORT.csv"))
    finally:
        desk.ROOT = old_root
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
    test_followup_loads_config_without_calling_main()
    test_followup_does_not_chain_a_failed_or_final_chunk()
    test_unset_root_uses_desk_root_before_the_repo()
    test_unavailable_symbol_is_recorded_and_not_retried()
    test_rate_limit_keeps_saved_bars_and_does_not_mark_unavailable()
    test_restart_downloads_only_what_is_still_missing()
    test_export_uses_cache_dates_and_skips_short_history()
    test_settings_and_help()
    print("fast backfill ok")
