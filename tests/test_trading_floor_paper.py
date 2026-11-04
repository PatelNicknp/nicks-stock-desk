"""Offline checks for the Trading Floor paper test (FAKE MONEY). Fixed dates and synthetic bars: no clock, no downloads."""
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tables  # noqa: E402
import trading_floor_paper as tp  # noqa: E402

DAYS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09", "2026-03-10",
        "2026-03-11", "2026-03-12", "2026-03-13", "2026-03-16", "2026-03-17", "2026-03-18", "2026-03-19",
        "2026-03-20", "2026-03-23", "2026-03-24", "2026-03-25", "2026-03-26", "2026-03-27", "2026-03-30",
        "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-06"]
D0, D1, D2, D3 = DAYS[0], DAYS[1], DAYS[2], DAYS[3]
P = tp.config({})


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _bars(spec, spy=None):
    """spec: {ticker: {day: (o, h, l, c)}}. Days not given are flat 100 bars. SPY rises 1 a day unless given."""
    idx = pd.to_datetime(DAYS)
    out = {k: pd.DataFrame(index=idx) for k in ("open", "high", "low", "close")}
    for tk, rows in spec.items():
        for j, k in enumerate(("open", "high", "low", "close")):
            vals = []
            for d in DAYS:
                bar = rows.get(d, (100.0, 101.0, 99.0, 100.0))
                vals.append(np.nan if bar is None else bar[j])
            out[k][tk] = vals
    spy_vals = spy or [400.0 + i for i in range(len(DAYS))]
    for k in out:
        out[k]["SPY"] = spy_vals
    return out


def _cut(bars, asof):
    """What the desk would have on the run of `asof`: bars up to that day only."""
    return {k: v.loc[: pd.Timestamp(asof)] for k, v in bars.items()}


def _floor(*rows):
    base = {"ticker": "AAA", "company": "Acme", "verdict": "BUY", "total": 3, "stop": 90.0, "target1": 120.0, "entry": 100.0}
    return pd.DataFrame([dict(base, **r) for r in rows]) if rows else pd.DataFrame(columns=list(base))


def _run(bars, floors, days, p=P, state=None):
    """Run the daily full run on each day in `days`, with the Trading Floor file of that day."""
    st = state or tp.empty_state()
    for d in days:
        st = tp.update(st, _cut(bars, d), floors.get(d, _floor()), d, p)
    return st


def _trade(st, ticker="AAA"):
    rows = st["trades"][st["trades"]["ticker"] == ticker]
    return rows.iloc[-1].to_dict()


def test_defaults_match_config_block_and_switch():
    cfg = _cfg()
    assert cfg["features"]["trading_floor_paper"] is True
    block = {k: v for k, v in cfg["trading_floor_paper"].items() if not k.startswith("_")}
    assert block == tp.DEFAULTS
    assert tp.DEFAULTS == {"start_cash": 10000.0, "position_pct": 10.0, "max_open": 10, "time_stop_days": 20,
                           "fractional_shares": True, "share_decimals": 4, "skip_if_held": True, "skip_gap_past_plan": True}
    assert tp.size_per_trade(P) == 1000.0


def test_start_day_records_cash_and_queues_buy_no_backfill():
    bars = _bars({"AAA": {}})
    st = _run(bars, {D0: _floor({})}, [D0])
    s = st["summary"]
    assert s["start_date"] == D0 and s["last_bar"] == D0 and s["last_signal_date"] == D0
    assert s["equity"] == 10000.0 and s["cash"] == 10000.0 and s["pending_count"] == 1 and s["open_count"] == 0
    assert len(st["equity"]) == 1 and st["equity"].iloc[0]["date"] == D0
    t = _trade(st)
    assert t["status"] == "PENDING" and t["signal_date"] == D0 and t["trade_id"] == D0 + "-AAA"
    # A later start never replays earlier bars.
    st2 = _run(bars, {D2: _floor({})}, [D2])
    assert st2["summary"]["start_date"] == D2 and list(st2["equity"]["date"]) == [D2]


def test_entry_fills_at_next_session_open_fractional():
    bars = _bars({"AAA": {D1: (103.0, 105.0, 101.0, 104.0)}})
    st = _run(bars, {D0: _floor({})}, [D0, D1])
    t = _trade(st)
    assert t["status"] == "OPEN" and t["entry_date"] == D1 and t["entry_price"] == 103.0
    assert t["shares"] == round(1000.0 / 103.0, 4) and t["days_held"] == 1
    assert abs(st["summary"]["cash"] - (10000.0 - t["shares"] * 103.0)) < 0.01
    assert abs(t["market_value"] - t["shares"] * 104.0) < 0.01
    assert st["summary"]["fill_rule"] == "next session open" and st["summary"]["share_mode"] == "fractional"


def test_whole_shares_mode():
    p = dict(P, fractional_shares=False)
    bars = _bars({"AAA": {D1: (103.0, 105.0, 101.0, 104.0)}})
    st = _run(bars, {D0: _floor({})}, [D0, D1], p=p)
    assert _trade(st)["shares"] == 9.0 and st["summary"]["share_mode"] == "whole"


def test_stop_hit_exits_at_stop():
    bars = _bars({"AAA": {D1: (100.0, 102.0, 98.0, 101.0), D2: (99.0, 100.0, 88.0, 89.0)}})
    st = _run(bars, {D0: _floor({})}, [D0, D1, D2])
    t = _trade(st)
    assert t["status"] == "CLOSED" and t["exit_reason"] == "STOP" and t["exit_price"] == 90.0 and t["exit_date"] == D2
    assert t["pnl"] == round((90.0 - 100.0) * 10.0, 2) and t["pnl_pct"] == -10.0
    assert "stop" in t["exit_words"].lower()


def test_gap_under_stop_exits_at_open():
    bars = _bars({"AAA": {D1: (100.0, 102.0, 98.0, 101.0), D2: (85.0, 87.0, 84.0, 86.0)}})
    t = _trade(_run(bars, {D0: _floor({})}, [D0, D1, D2]))
    assert t["exit_reason"] == "STOP_GAP" and t["exit_price"] == 85.0 and t["pnl"] == -150.0
    assert "opened below the stop" in t["exit_words"].lower()


def test_target_hit_and_gap_above_target():
    bars = _bars({"AAA": {D1: (100.0, 121.0, 99.0, 115.0)}})
    t = _trade(_run(bars, {D0: _floor({})}, [D0, D1]))
    assert t["exit_reason"] == "TARGET" and t["exit_price"] == 120.0 and t["pnl"] == 200.0 and t["exit_date"] == D1
    bars = _bars({"AAA": {D1: (100.0, 102.0, 99.0, 101.0), D2: (125.0, 130.0, 124.0, 128.0)}})
    t = _trade(_run(bars, {D0: _floor({})}, [D0, D1, D2]))
    assert t["exit_reason"] == "TARGET_GAP" and t["exit_price"] == 125.0 and t["pnl"] == 250.0


def test_same_bar_stop_and_target_counts_stop():
    bars = _bars({"AAA": {D1: (100.0, 102.0, 99.0, 101.0), D2: (100.0, 125.0, 85.0, 110.0)}})
    t = _trade(_run(bars, {D0: _floor({})}, [D0, D1, D2]))
    assert t["exit_reason"] == "STOP_SAME_BAR" and t["exit_price"] == 90.0 and t["pnl"] == -100.0
    assert tp.exit_on_bar(100, 125, 85, 110, 90, 120, 1, 20) == (90, "STOP_SAME_BAR")
    assert tp.exit_on_bar(100, 101, 99, 100, 90, 120, 19, 20) is None
    assert tp.exit_on_bar(100, 101, 99, 100.5, 90, 120, 20, 20) == (100.5, "TIME")


def test_time_stop_after_20_trading_days_at_close():
    spec = {"AAA": {DAYS[20]: (100.0, 101.0, 99.0, 104.0)}}
    bars = _bars(spec)
    st = _run(bars, {D0: _floor({})}, DAYS[:22])
    t = _trade(st)
    # Bought on DAYS[1] (day 1), so day 20 is DAYS[20].
    assert t["status"] == "CLOSED" and t["exit_reason"] == "TIME" and t["exit_date"] == DAYS[20]
    assert t["exit_price"] == 104.0 and t["days_held"] == 20 and t["pnl"] == 40.0
    assert "time stop" in t["exit_words"].lower()
    st19 = _run(bars, {D0: _floor({})}, DAYS[:20])
    assert _trade(st19)["status"] == "OPEN" and _trade(st19)["days_held"] == 19


def test_stop_and_target_frozen_at_entry():
    bars = _bars({"AAA": {D1: (100.0, 102.0, 99.0, 101.0), D3: (95.0, 96.0, 91.0, 92.0)}})
    # Day 2 floor says BUY again with a higher stop: it is skipped as held and the old stop stays.
    st = _run(bars, {D0: _floor({}), D2: _floor({"stop": 94.0, "target1": 110.0})}, [D0, D1, D2, D3])
    first = st["trades"][st["trades"]["trade_id"] == D0 + "-AAA"].iloc[0]
    second = st["trades"][st["trades"]["trade_id"] == D2 + "-AAA"].iloc[0]
    assert first["stop"] == 90.0 and first["target"] == 120.0 and first["status"] == "OPEN"
    assert second["status"] == "SKIPPED" and second["note"] == "Already held."


def test_max_open_and_cash_limits():
    tickers = ["T%02d" % i for i in range(12)]
    bars = _bars({tk: {} for tk in tickers})
    floor = _floor(*[{"ticker": tk, "total": 12 - i} for i, tk in enumerate(tickers)])
    st = _run(bars, {D0: floor}, [D0, D1])
    status = dict(zip(st["trades"]["ticker"], st["trades"]["status"]))
    assert sum(1 for v in status.values() if v == "OPEN") == 10
    assert status["T10"] == "SKIPPED" and status["T11"] == "SKIPPED"
    notes = dict(zip(st["trades"]["ticker"], st["trades"]["note"]))
    assert notes["T10"].startswith("No free slot")
    # Highest total first: T00..T09 get the slots.
    assert all(status["T%02d" % i] == "OPEN" for i in range(10))
    p = dict(P, max_open=10, start_cash=2500.0, position_pct=40.0)
    st = _run(bars, {D0: _floor({"ticker": "T00", "total": 3}, {"ticker": "T01", "total": 2}, {"ticker": "T02", "total": 1})}, [D0], p=p)
    status = dict(zip(st["trades"]["ticker"], st["trades"]["status"]))
    assert status == {"T00": "PENDING", "T01": "PENDING", "T02": "SKIPPED"}
    assert st["trades"].set_index("ticker").at["T02", "note"] == "Not enough fake cash."


def test_only_buy_rows_and_bad_plans_skipped():
    bars = _bars({"AAA": {}, "BBB": {}, "CCC": {}})
    floor = _floor({"ticker": "AAA"}, {"ticker": "BBB", "verdict": "WAIT"}, {"ticker": "CCC", "stop": np.nan})
    st = _run(bars, {D0: floor}, [D0])
    status = dict(zip(st["trades"]["ticker"], st["trades"]["status"]))
    assert status == {"AAA": "PENDING", "CCC": "SKIPPED"}


def test_gap_past_plan_on_buy_day_is_not_filled():
    bars = _bars({"AAA": {D1: (89.0, 92.0, 88.0, 91.0)}, "BBB": {D1: (121.0, 122.0, 119.0, 120.0)}, "CCC": {D1: None}})
    st = _run(bars, {D0: _floor({"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "CCC"})}, [D0, D1])
    status = dict(zip(st["trades"]["ticker"], st["trades"]["status"]))
    assert status == {"AAA": "NOT FILLED", "BBB": "NOT FILLED", "CCC": "NOT FILLED"}
    assert st["summary"]["cash"] == 10000.0 and st["summary"]["not_filled_count"] == 3


def test_idempotent_same_day_twice_and_through_files():
    bars = _bars({"AAA": {D1: (100.0, 102.0, 99.0, 101.0), D2: (100.0, 121.0, 99.0, 115.0)}, "BBB": {}})
    floors = {D0: _floor({}), D1: _floor({"ticker": "BBB"})}
    once = _run(bars, floors, [D0, D1, D2])
    twice = _run(bars, floors, [D0, D0, D1, D1, D2, D2])
    pd.testing.assert_frame_equal(once["trades"], twice["trades"])
    pd.testing.assert_frame_equal(once["equity"], twice["equity"])
    assert once["summary"] == twice["summary"]
    with tempfile.TemporaryDirectory() as tmp:
        st = tp.empty_state()
        for d in [D0, D1, D1, D2, D2]:
            st = tp.load_state(tmp)
            st = tp.update(st, _cut(bars, d), floors.get(d, _floor()), d, P)
            tp.save_state(st, tmp)
        before = {n: open(os.path.join(tmp, n)).read() for n in ("paper_trades.csv", "paper_equity.csv", "paper_summary.csv")}
        st = tp.update(tp.load_state(tmp), _cut(bars, D2), _floor({"ticker": "CCC"}), D2, P)
        tp.save_state(st, tmp)
        after = {n: open(os.path.join(tmp, n)).read() for n in before}
        assert before == after
        loaded = tp.load_state(tmp)
        assert len(loaded["trades"]) == 2 and list(loaded["equity"]["date"]) == [D0, D1, D2]
        assert _trade(loaded)["exit_reason"] == "TARGET" and _trade(loaded, "BBB")["status"] == "OPEN"


def test_catch_up_after_a_missed_run():
    bars = _bars({"AAA": {D1: (100.0, 102.0, 99.0, 101.0), D2: (99.0, 100.0, 88.0, 89.0)}})
    st = _run(bars, {D0: _floor({})}, [D0, D3])
    assert list(st["equity"]["date"]) == [D0, D1, D2, D3]
    t = _trade(st)
    assert t["entry_date"] == D1 and t["exit_date"] == D2 and t["exit_reason"] == "STOP"


def test_unfinished_day_is_not_used():
    bars = _bars({"AAA": {D1: (100.0, 102.0, 99.0, 101.0), D2: (99.0, 100.0, 88.0, 89.0)}})
    st = _run(bars, {D0: _floor({})}, [D0, D1])
    # A manual run during the D2 session: the half-day bar and that run's calls are not used.
    mid = tp.update(st, _cut(bars, D2), _floor({"ticker": "BBB"}), D2, P, asof_final=False)
    assert mid["summary"]["last_bar"] == D1 and _trade(mid)["status"] == "OPEN" and len(mid["trades"]) == 1
    # The after-close run of D2 then uses the full bar and takes the D2 calls.
    done = tp.update(mid, _cut(bars, D2), _floor({"ticker": "BBB"}), D2, P)
    assert _trade(done)["exit_reason"] == "STOP" and _trade(done, "BBB")["status"] == "PENDING"
    assert done["summary"]["last_bar"] == D2 and done["summary"]["last_signal_date"] == D2


def test_stats_win_rate_averages_drawdown_and_spy():
    spec = {"AAA": {D1: (100.0, 121.0, 99.0, 115.0)},
            "BBB": {D1: (100.0, 102.0, 99.0, 101.0), D2: (99.0, 100.0, 88.0, 89.0)},
            "CCC": {D1: (100.0, 102.0, 99.0, 101.0), D2: (100.0, 112.0, 99.0, 110.0)}}
    spy = [400.0, 404.0, 408.0, 412.0] + [412.0] * (len(DAYS) - 4)
    bars = _bars(spec, spy=spy)
    floor = _floor({"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "CCC", "target1": 110.0})
    st = _run(bars, {D0: floor}, [D0, D1, D2])
    s = st["summary"]
    assert s["closed_count"] == 3 and s["wins"] == 2 and s["losses"] == 1
    assert s["win_rate_pct"] == 66.7 and s["avg_win"] == 150.0 and s["avg_loss"] == -100.0
    assert s["avg_win_pct"] == 15.0 and s["avg_loss_pct"] == -10.0 and s["total_pnl"] == 200.0
    assert s["equity"] == 10200.0 and s["total_return_pct"] == 2.0
    assert s["spy_return_pct"] == 2.0 and s["vs_spy_pct"] == 0.0
    eq = st["equity"].set_index("date")
    assert eq.at[D1, "equity"] == 10000.0 + 200.0 + 10.0 + 10.0  # AAA sold at target, BBB and CCC marked at 101
    assert eq.at[D2, "spy_equity"] == 10200.0
    rows = pd.DataFrame({"equity": [10000.0, 11000.0, 9900.0, 10500.0]})
    assert tp.stats([], rows, P)["max_drawdown_pct"] == -10.0
    assert tp.stats([], rows, P)["win_rate_pct"] is None


def test_page_settings_help_and_wiring():
    df = tables.settings_rows(_cfg())
    rows = dict(zip(df["setting"], df["value"]))
    for k, v in tp.DEFAULTS.items():
        assert rows["trading_floor_paper." + k] == v
    assert rows["feature.trading_floor_paper"] in (True, "true", "True")
    topics = {t: x for t, x in tables.help_rows()}
    for t in ("Paper Test", "Paper Test exits", "Paper Test settings"):
        assert t in topics and "\u2014" not in topics[t]
    assert "FAKE MONEY" in topics["Paper Test"]
    src = open(os.path.join(ROOT, "stock_desk.py"), encoding="utf-8").read()
    assert 'mode in ("full", "offline")' in src and "trading_floor_paper.update(" in src
    desk = open(os.path.join(ROOT, "site", "js", "desk.js"), encoding="utf-8").read()
    assert '["Paper Test", "paper-test.html", "papertest"]' in desk and 'papertest: "feature.trading_floor_paper"' in desk
    assert desk.index('"trading-floor.html"') < desk.index('"paper-test.html"')
    pages = open(os.path.join(ROOT, "site", "js", "pages.js"), encoding="utf-8").read()
    assert "renderPaperTest" in pages and "FAKE MONEY" in pages and 'href="paper-test.html"' in pages
    assert os.path.exists(os.path.join(ROOT, "site", "paper-test.html"))
    assert os.path.exists(os.path.join(ROOT, "docs", "trading_floor_paper_rules.md"))
    wf = open(os.path.join(ROOT, ".github", "workflows", "update.yml"), encoding="utf-8").read()
    assert "python tests/test_trading_floor_paper.py" in wf


def test_paper_module_makes_no_requests():
    src = open(os.path.join(ROOT, "trading_floor_paper.py"), encoding="utf-8").read()
    for bad in ("requests", "urllib", "yfinance", "http", "netutil", "datetime.now", "date.today", "time.time"):
        assert bad not in src, bad


if __name__ == "__main__":
    names = sorted(k for k, v in list(globals().items()) if k.startswith("test_") and callable(v))
    for name in names:
        globals()[name]()
    print("trading floor paper ok (%d tests)" % len(names))
