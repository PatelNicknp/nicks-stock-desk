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


if __name__ == "__main__":
    test_pool_keeps_missing_names_then_the_stalest_and_stops_at_the_batch()
    test_a_partial_refresh_keeps_rows_it_did_not_touch()
    test_hourly_reuses_holders_and_does_not_start_a_batch()
    test_checkpoint_is_off_unless_the_workflow_asks()
    test_checkpoint_does_not_raise_when_git_refuses()
    print("slow refresh ok")
