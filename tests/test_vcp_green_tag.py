"""VCP lists only the green VCP tag: trend template 8 of 8 and at least two tightening pullbacks.

Fixed dates and fixed rows. No clock, no network. Runs under pytest or plain python.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import setups  # noqa: E402
import sector_rotation  # noqa: E402
import tables  # noqa: E402

WEAK_TREND = "WATCHING (trend not 8/8)"
DATES = pd.bdate_range("2025-01-02", periods=300)


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _state(score=8, cnt=2, pivot=100.0, close=98.0, breakout=False, big_vol=False, in_trade=False, entry_score=-1):
    rules = [True] * 8 if score == 8 else [i < score for i in range(8)]
    return {
        "score": score, "rules": rules, "cnt": cnt,
        "depths": [8.0, 5.0, 3.0][:cnt], "highs": [pivot] * cnt,
        "pivot": pivot if cnt else None,
        "is_vcp": bool(cnt >= 2 and score == 8),
        "breakout": breakout, "big_vol": big_vol, "in_trade": in_trade,
        "entry": 101.0 if in_trade else None, "entry_bar": 250 if in_trade else -1,
        "entry_score": entry_score,
        "stop": 93.93 if in_trade else None,
        "be_done": False, "part_done": False, "climax_done": False,
        "trail": 97.0, "close": close, "bars": 300, "high52": 105.0,
    }


# One fixed state per ticker. HONA is Nick's example: 0 of 8 with 3 tightening pullbacks.
STATES = {
    "RDY": _state(close=98.0),
    "ATP": _state(close=100.0),  # at the buy line counts as below it
    "BRK": _state(close=103.0, breakout=True, big_vol=True, in_trade=True, entry_score=8),
    "LOW": _state(close=102.0, big_vol=False),
    "OLD": _state(close=104.0, big_vol=True),  # crossed on an earlier day
    "ONE": _state(score=8, cnt=1, close=99.0),  # one pullback at 8 of 8: plain WATCHING
    "ONEUP": _state(score=8, cnt=1, close=103.0, big_vol=True),  # over the line, still only one pullback
    "HELD": _state(score=6, cnt=0, close=110.0, in_trade=True, entry_score=8),  # bought at 8 of 8, 6 of 8 now
    "HELDV": _state(score=8, cnt=2, close=99.0, in_trade=True, entry_score=8),  # open trade back under the line: WATCHING, not READY
    "HELDO": _state(score=8, cnt=1, close=99.0, in_trade=True, entry_score=8),  # open trade, one pullback now, under the line
    "HELDX": _state(score=7, cnt=0, close=110.0, in_trade=True, entry_score=7),  # buy not at 8 of 8
    "HONA": _state(score=0, cnt=3, close=90.0),
    "SEV": _state(score=7, cnt=2, close=99.0),
    "ONE7": _state(score=7, cnt=1, close=99.0),
    "ONE5": _state(score=5, cnt=1, close=99.0),  # under the 6/8 floor, never listed
    "NONE": _state(score=8, cnt=0, close=99.0),
}
DEFAULT_LISTED = {"ATP": "READY", "BRK": "BROKEN OUT today", "HELD": "WATCHING", "HELDV": "WATCHING", "HELDO": "WATCHING", "LOW": "WATCHING",
                  "OLD": "WATCHING", "ONE": "WATCHING", "ONEUP": "WATCHING", "RDY": "READY"}
WEAK_LISTED = {"HELDX", "HONA", "SEV", "ONE7"}


def _scan(cfg=None):
    names = list(STATES)
    close = pd.DataFrame({t: np.linspace(80, 100, len(DATES)) for t in names + ["SPY"]}, index=DATES)
    high, low, vol = close * 1.01, close * 0.99, close * 0 + 1_000_000
    uni = pd.DataFrame([{"ticker": t, "company": t + " Co", "sector": "Industrials", "index_membership": "SP500"} for t in names])
    real = setups.vcp_last
    order = iter(names)
    try:
        setups.vcp_last = lambda *a, **k: dict(STATES[next(order)])
        out = setups.scan_vcp(close, high, low, vol, uni, cfg)
    finally:
        setups.vcp_last = real
    return out.set_index("ticker")


def test_status_rules_on_fixed_states():
    s = setups._vcp_status
    for t, st in STATES.items():
        assert s(st) == DEFAULT_LISTED.get(t), (t, s(st))
        on = s(st, True)
        if t in DEFAULT_LISTED:
            assert on == DEFAULT_LISTED[t], (t, on)
        elif t in WEAK_LISTED:
            assert on == WEAK_TREND, (t, on)
        else:
            assert on is None, (t, on)


def test_one_pullback_is_never_ready_or_broken_out():
    """READY and BROKEN OUT need is_vcp, which needs two pullbacks. Even a breakout flag cannot lift one pullback."""
    for close in (90.0, 100.0, 103.0):
        for big in (False, True):
            st = _state(score=8, cnt=1, close=close, big_vol=big)
            assert setups._vcp_status(st) == "WATCHING"
            assert setups._vcp_status(st, True) == "WATCHING"
    odd = _state(score=8, cnt=1, close=103.0, breakout=True, big_vol=True)
    assert setups._vcp_status(odd) == "WATCHING"


def test_open_trade_is_never_ready():
    """READY means not bought yet. Any open trade at or under the line is WATCHING."""
    for score, cnt in ((8, 2), (8, 3), (8, 1)):
        for close in (90.0, 99.0, 100.0):
            st = _state(score=score, cnt=cnt, close=close, in_trade=True, entry_score=8)
            assert setups._vcp_status(st) == "WATCHING", (score, cnt, close)
            assert setups._vcp_status(st, True) == "WATCHING", (score, cnt, close)
            assert "dipped back under the buy point" in setups._vcp_reason(st, "WATCHING", DATES)
    # Same setup without a trade is READY.
    assert setups._vcp_status(_state(score=8, cnt=2, close=99.0)) == "READY"


def test_entry_score_is_saved_on_the_buy_day():
    from test_setups import _vcp_tape
    frame, spy, _ = _vcp_tape(True)
    st = setups.vcp_last(frame["high"], frame["low"], frame["close"], frame["volume"], spy.to_numpy())
    assert st["breakout"] and st["in_trade"]
    assert st["entry_score"] == 8
    frame, spy, _ = _vcp_tape(False)
    st = setups.vcp_last(frame["high"], frame["low"], frame["close"], frame["volume"], spy.to_numpy())
    assert not st["in_trade"] and st["entry_score"] == -1


def test_default_scan_lists_only_8_of_8():
    assert _cfg()["vcp"]["show_weaker_trend"] is False
    for cfg in (None, {}, {"vcp": {}}, _cfg(), {"vcp": {"show_weaker_trend": "yes"}}):
        out = _scan(cfg)
        assert dict(out["status"]) == DEFAULT_LISTED, (cfg, dict(out["status"]))
    out = _scan()
    # Every listed row is 8 of 8 today, except an open trade bought at 8 of 8.
    assert set(out.drop(index="HELD")["trend_score"]) == {"8 of 8"}
    assert out.loc["HELD", "trend_score"] == "6 of 8"
    assert "was 8 of 8 on the buy day. It is 6 of 8 today." in out.loc["HELD", "reason"]
    assert "A trade is still open" in out.loc["HELD", "reason"]
    assert "was 8 of 8 on the buy day" not in out.loc["HELDV", "reason"]
    for t in ("HELDV", "HELDO"):
        assert out.loc[t, "status"] == "WATCHING" and out.loc[t, "in_trade"] == "yes"
        assert "open trade that has dipped back under the buy point" in out.loc[t, "reason"]
    for t in ("HELD", "LOW", "OLD", "ONE"):
        assert "dipped back under" not in out.loc[t, "reason"]
    assert list(out.index)[0] == "BRK"
    assert "one pullback so far" in out.loc["ONE", "reason"]
    assert "cannot be READY or BROKEN OUT" in out.loc["ONE", "reason"]
    assert "one pullback so far" in out.loc["ONEUP", "reason"]
    assert out.loc["LOW", "status"] == "WATCHING" and "did not print a buy today" in out.loc["LOW", "reason"]
    assert out.loc["OLD", "status"] == "WATCHING" and "did not cross it today" in out.loc["OLD", "reason"]
    assert "WATCHING (one pullback)" not in set(out["status"])


def test_switch_brings_back_only_rows_under_8_of_8_last():
    out = _scan({"vcp": {"show_weaker_trend": True}})
    assert set(out.index) == set(DEFAULT_LISTED) | WEAK_LISTED
    weak = out[out["status"] == WEAK_TREND]
    assert set(weak.index) == WEAK_LISTED
    assert not (weak["trend_score"] == "8 of 8").any()
    assert out.loc["HONA", "trend_score"] == "0 of 8" and int(out.loc["HONA", "contractions"]) == 3
    assert "not 8 of 8" in out.loc["HONA", "reason"] and "never feeds Buy setups" in out.loc["HONA", "reason"]
    assert "Still open: rule 8" in out.loc["SEV", "reason"]
    # The weaker rows are listed last, after every 8 of 8 row.
    statuses = list(out["status"])
    first_weak = statuses.index(WEAK_TREND)
    assert all(x == WEAK_TREND for x in statuses[first_weak:])
    assert len(statuses) - first_weak == len(WEAK_LISTED)
    assert set(out["status"]) == {"READY", "BROKEN OUT today", "WATCHING", WEAK_TREND}


def test_weaker_and_one_pullback_rows_never_feed_buy_setups_leaders_or_rotation():
    vcp = _scan({"vcp": {"show_weaker_trend": True}}).reset_index()
    names = list(vcp["ticker"])
    scores = pd.DataFrame([{"ticker": t, "company": t, "sector": "Industrials", "index_membership": "SP500",
                            "score": 9, "verdict": "BUY", "above_sma50": "yes", "above_sma200": "yes"} for t in names])
    sma = {t: True for t in names}
    buy = setups.build_buy_setups(vcp, None, None, None, scores, sma_ok=sma, market={"spy": True, "qqq": True})
    live = {"RDY", "ATP", "BRK"}
    # An open trade that dipped under its buy line is WATCHING, so it is not a READY buy setup.
    assert "HELDV" not in set(buy["ticker"]) and "HELDO" not in set(buy["ticker"])
    assert set(buy["ticker"]) == live, set(buy["ticker"])
    leaders = setups.combine_leaders(vcp, pd.DataFrame())
    assert set(leaders["ticker"]) == live
    assert sector_rotation.resolve_buy_tickers(scores, scanners={"vcp": vcp}) == live


def test_settings_and_help_carry_the_switch():
    cfg = _cfg()
    rows = tables.settings_rows(cfg)
    got = dict(zip(rows["setting"], rows["value"]))
    assert got["vcp.show_weaker_trend"] is False
    assert "vcp._note" not in got
    help_ = dict(tables.help_rows())
    assert "vcp.show_weaker_trend" in help_["VCP weaker trend switch"]
    assert WEAK_TREND in help_["VCP weaker trend switch"]
    assert "WATCHING (one pullback)" not in " ".join(help_.values())
    assert "one pullback so far" in help_["VCP scanner"]
    assert "8 of 8" in help_["VCP scanner"] and "two tightening pullbacks" in help_["VCP scanner"]


def test_saved_vcp_file_matches_the_switch():
    path = os.path.join(ROOT, "data", "scanner_vcp.csv")
    if not os.path.exists(path):
        return
    df = pd.read_csv(path)
    df = df[df["ticker"].notna() & (df["ticker"].astype(str).str.strip() != "")]
    if _cfg()["vcp"].get("show_weaker_trend") is True or len(df) == 0:
        return
    held = df["in_trade"].astype(str) == "yes"
    assert set(df.loc[~held, "trend_score"]) <= {"8 of 8"}, set(df["trend_score"])
    assert set(df["status"]) <= {"READY", "BROKEN OUT today", "WATCHING"}
    live = df["status"].isin(["READY", "BROKEN OUT today"])
    assert (df.loc[live, "contractions"].astype(int) >= 2).all()
    assert (df.loc[live, "trend_score"] == "8 of 8").all()
    assert not ((df["status"] == "READY") & held).any()


if __name__ == "__main__":
    test_status_rules_on_fixed_states()
    test_one_pullback_is_never_ready_or_broken_out()
    test_open_trade_is_never_ready()
    test_entry_score_is_saved_on_the_buy_day()
    test_default_scan_lists_only_8_of_8()
    test_switch_brings_back_only_rows_under_8_of_8_last()
    test_weaker_and_one_pullback_rows_never_feed_buy_setups_leaders_or_rotation()
    test_settings_and_help_carry_the_switch()
    test_saved_vcp_file_matches_the_switch()
    print("vcp green tag ok")
