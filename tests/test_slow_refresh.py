"""Profiles and 13F refresh a slice, and a checkpoint stays off in tests.

No clock and no network. A full run used to ask for every daily name again.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import stock_desk as desk


def test_pool_keeps_missing_names_then_the_stalest_and_stops_at_the_batch():
    tickers = ["C", "A", "D", "B", "E", "F", "G", "H"]
    have = ["A", "B", "E", "F", "G", "H"]
    cycle = {"A": "2026-11-08", "B": "2026-10-26", "G": "2026-10-28", "H": "2026-11-06"}
    pool = desk.slow_refresh_pool(tickers, have, cycle, "2026-11-09", batch=3, every_days=7, already_today=["F"])
    # C and D are not saved yet. E has never been stamped. B and G are older than 7 days.
    # A and H were refreshed inside the window. F was already fetched today.
    assert pool == ["C", "D", "E"]


def test_a_partial_refresh_keeps_rows_it_did_not_touch():
    prior = pd.DataFrame([
        {"ticker": "AAPL", "target_mean": 100},
        {"ticker": "MSFT", "target_mean": 200},
    ])
    merged = desk.merge_ticker_rows(prior, [{"ticker": "AAPL", "target_mean": 110}])
    by_ticker = dict(zip(merged["ticker"], merged["target_mean"]))
    assert by_ticker == {"AAPL": 110, "MSFT": 200}
    assert list(desk.merge_ticker_rows(prior, [])["ticker"]) == ["AAPL", "MSFT"]


def test_hourly_reuses_holders_and_does_not_start_a_batch():
    with tempfile.TemporaryDirectory() as cache:
        pd.DataFrame([{"ticker": "AAPL", "inst_shares": 1}]).to_csv(os.path.join(cache, "holders.csv"), index=False)
        summary, detail = desk.load_holders(["AAPL", "MSFT", "NVDA"], {}, cache, "hourly")
        assert list(summary["ticker"]) == ["AAPL"]
        assert len(detail) == 0
        assert not os.path.exists(os.path.join(cache, "holders_cycle.json"))


def test_checkpoint_is_off_unless_the_workflow_asks():
    os.environ.pop("DESK_CHECKPOINT", None)
    def boom(*_a, **_k):
        raise AssertionError("git should not run")
    old = subprocess.run
    subprocess.run = boom
    try:
        desk.checkpoint_progress("prices")
    finally:
        subprocess.run = old


def test_checkpoint_does_not_raise_when_git_refuses():
    os.environ["DESK_CHECKPOINT"] = "1"

    class Result:
        returncode = 1
        stderr = "not a git checkout"
        stdout = ""

    calls = []
    def fake_run(args, **_k):
        calls.append(list(args))
        return Result()

    old = subprocess.run
    subprocess.run = fake_run
    try:
        desk.checkpoint_progress("prices")
    finally:
        subprocess.run = old
        os.environ.pop("DESK_CHECKPOINT", None)
    assert calls and calls[0][:3] == ["git", "rev-parse", "--is-inside-work-tree"]



def test_ownership_full_lifts_the_cap_only_when_asked():
    settings = {"batch_per_run": 60, "refresh_every_days": 7}
    names = ["T%02d" % i for i in range(80)]
    os.environ.pop("DESK_OWNERSHIP_FULL", None)
    assert desk.holders_batch_per_run(settings, len(names), "full") == 60
    assert desk.holders_batch_per_run(settings, len(names), "hourly", env={"DESK_OWNERSHIP_FULL": "1"}) == 60
    assert desk.holders_batch_per_run(settings, len(names), "full", env={"DESK_OWNERSHIP_FULL": "1"}) == 80
    assert desk.ownership_should_chain(waiting=100, fetched=40, run_index=0, max_runs=8) is True
    assert desk.ownership_should_chain(waiting=0, fetched=40, run_index=0, max_runs=8) is False
    assert desk.ownership_should_chain(waiting=100, fetched=0, run_index=0, max_runs=8) is False
    assert desk.ownership_should_chain(waiting=100, fetched=40, run_index=7, max_runs=8) is False


class _FakeResp:
    def json(self):
        return {"data": {
            "activePositions": {"rows": [{"positions": "Total Institutional Shares Held", "shares": "10", "holders": "3"}]},
            "ownershipSummary": {"SharesOutstandingPCT": {"value": "10%"}, "ShareoutstandingTotal": {"value": "100"}},
            "holdingsTransactions": {"table": {"rows": []}},
            "numberOfTrades": {"rows": []},
        }}


def test_ownership_full_stops_for_the_time_budget_and_resumes():
    """A 13F full fill saves progress and continues later; the default cap stays 60."""
    import netutil
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    cfg = {"rate_limit": {"nasdaq_requests_per_second": 1000, "max_retries": 1}, "slow_sources": {"batch_per_run": 60}}
    seen = []

    def fake_get(_session, url, *a, **k):
        seen.append(url)
        return _FakeResp()

    old_get = netutil.http_get
    old_wait = netutil.RateLimiter.wait
    netutil.http_get = fake_get
    netutil.RateLimiter.wait = lambda self: None
    old_full = os.environ.get("DESK_OWNERSHIP_FULL")
    os.environ["DESK_OWNERSHIP_FULL"] = "1"
    # Clock: first check is the start, then each name sees a later time.
    # Budget 1 means stop once the clock has moved by 1, after the first name.
    times = iter([0, 0, 2, 3, 4, 5])
    try:
        with tempfile.TemporaryDirectory() as cache:
            desk.STAMPS.clear()
            summary, _detail = desk.load_holders(tickers, cfg, cache, "full", clock=lambda: next(times), budget_sec=1)
            assert list(summary["ticker"]) == ["AAA"]
            status = desk.read_ownership_status(cache)
            assert status["stopped_for_budget"] is True
            assert status["fetched_this_run"] == 1
            assert status["waiting"] == 3
            assert status["chain"] is True
            # Names already fetched today are not requested again.
            times2 = iter([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
            summary2, _ = desk.load_holders(tickers, cfg, cache, "full", clock=lambda: next(times2), budget_sec=100)
            got = set(summary2["ticker"])
            assert "AAA" in got and "BBB" in got and "CCC" in got and "DDD" in got
            # AAA's two URLs only from the first run.
            aaa_calls = [u for u in seen if "/AAA/" in u]
            assert len(aaa_calls) == 2
            status2 = desk.read_ownership_status(cache)
            assert status2["waiting"] == 0
            assert status2["chain"] is False
    finally:
        netutil.http_get = old_get
        netutil.RateLimiter.wait = old_wait
        if old_full is None:
            os.environ.pop("DESK_OWNERSHIP_FULL", None)
        else:
            os.environ["DESK_OWNERSHIP_FULL"] = old_full
        desk.STAMPS.clear()


def test_default_holders_run_stays_capped_at_the_usual_slice():
    import netutil
    tickers = ["T%02d" % i for i in range(80)]
    cfg = {"rate_limit": {"nasdaq_requests_per_second": 1000, "max_retries": 1}, "slow_sources": {"batch_per_run": 60}}
    seen = []

    def fake_get(_session, url, *a, **k):
        seen.append(url)
        return _FakeResp()

    old_get = netutil.http_get
    old_wait = netutil.RateLimiter.wait
    netutil.http_get = fake_get
    netutil.RateLimiter.wait = lambda self: None
    os.environ.pop("DESK_OWNERSHIP_FULL", None)
    try:
        with tempfile.TemporaryDirectory() as cache:
            desk.STAMPS.clear()
            summary, _ = desk.load_holders(tickers, cfg, cache, "full", budget_sec=1)
            # Two URLs a name, 60-name cap.
            assert len(seen) == 120
            assert len(summary) == 60
    finally:
        netutil.http_get = old_get
        netutil.RateLimiter.wait = old_wait
        desk.STAMPS.clear()


if __name__ == "__main__":
    test_pool_keeps_missing_names_then_the_stalest_and_stops_at_the_batch()
    test_a_partial_refresh_keeps_rows_it_did_not_touch()
    test_hourly_reuses_holders_and_does_not_start_a_batch()
    test_checkpoint_is_off_unless_the_workflow_asks()
    test_checkpoint_does_not_raise_when_git_refuses()
    test_ownership_full_lifts_the_cap_only_when_asked()
    test_ownership_full_stops_for_the_time_budget_and_resumes()
    test_default_holders_run_stays_capped_at_the_usual_slice()
    print("slow refresh ok")
