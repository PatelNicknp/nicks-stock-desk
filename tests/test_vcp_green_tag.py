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
WEAK_ONE = "WATCHING (one pullback)"
DATES = pd.bdate_range("2025-01-02", periods=300)


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _state(score=8, cnt=2, pivot=100.0, close=98.0, breakout=False, big_vol=False, in_trade=False):
    rules = [True] * 8 if score == 8 else [i < score for i in range(8)]
    return {
        "score": score, "rules": rules, "cnt": cnt,
        "depths": [8.0, 5.0, 3.0][:cnt], "highs": [pivot] * cnt,
        "pivot": pivot if cnt else None,
        "is_vcp": bool(cnt >= 2 and score == 8),
        "breakout": breakout, "big_vol": big_vol, "in_trade": in_trade,
        "entry": 101.0 if in_trade else None, "entry_bar": 250 if in_trade else -1,
        "stop": 93.93 if in_trade else None,
        "be_done": False, "part_done": False, "climax_done": False,
        "trail": 97.0, "close": close, "bars": 300, "high52": 105.0,
    }


# One fixed state per ticker. HONA is Nick's example: 0 of 8 with 3 tightening pullbacks.
STATES = {
    "RDY": _state(close=98.0),
    "ATP": _state(close=100.0),  # at the buy line counts as below it
    "BRK": _state(close=103.0, breakout=True, big_vol=True),
    "LOW": _state(close=102.0, big_vol=False),
    "OLD": _state(close=104.0, big_vol=True),  # crossed on an earlier day
    "HONA": _state(score=0, cnt=3, close=90.0),
    "SEV": _state(score=7, cnt=2, close=99.0),
    "ONE": _state(score=8, cnt=1, close=99.0),
    "ONE5": _state(score=5, cnt=1, close=99.0),  # under the old 6/8 floor, never listed
    "NONE": _state(score=8, cnt=0, close=99.0),
}


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
    assert s(STATES["RDY"]) == "READY"
    assert s(STATES["ATP"]) == "READY"
    assert s(STATES["BRK"]) == "BROKEN OUT today"
    assert s(STATES["LOW"]) == "WATCHING"
    assert s(STATES["OLD"]) == "WATCHING"
    for t in ("HONA", "SEV", "ONE", "ONE5", "NONE"):
        assert s(STATES[t]) is None, t
        assert s(STATES[t], False) is None, t
    assert s(STATES["HONA"], True) == WEAK_TREND
    assert s(STATES["SEV"], True) == WEAK_TREND
    assert s(STATES["ONE"], True) == WEAK_ONE
    assert s(STATES["ONE5"], True) is None
    assert s(STATES["NONE"], True) is None
    # A held trade that is not a VCP any more only shows with the switch on.
    held = _state(score=6, cnt=0, close=110.0, in_trade=True)
    assert s(held) is None and s(held, True) == WEAK_TREND
    held8 = _state(score=8, cnt=1, close=110.0, in_trade=True)
    assert s(held8) is None and s(held8, True) == WEAK_ONE


def test_default_scan_lists_only_the_green_tag():
    assert _cfg()["vcp"]["show_weaker_trend"] is False
    for cfg in (None, {}, {"vcp": {}}, _cfg(), {"vcp": {"show_weaker_trend": "yes"}}):
        out = _scan(cfg)
        assert sorted(out.index) == ["ATP", "BRK", "LOW", "OLD", "RDY"], (cfg, list(out.index))
        assert set(out["trend_score"]) == {"8 of 8"}
        assert (out["contractions"].astype(int) >= 2).all()
        assert set(out["status"]) == {"READY", "BROKEN OUT today", "WATCHING"}
    out = _scan()
    assert list(out.index)[0] == "BRK"
    assert out.loc["LOW", "status"] == "WATCHING" and "did not print a buy today" in out.loc["LOW", "reason"]
    assert out.loc["OLD", "status"] == "WATCHING" and "did not cross it today" in out.loc["OLD", "reason"]


def test_switch_brings_weaker_rows_back_labeled():
    out = _scan({"vcp": {"show_weaker_trend": True}})
    assert sorted(out.index) == ["ATP", "BRK", "HONA", "LOW", "OLD", "ONE", "RDY", "SEV"]
    assert out.loc["HONA", "status"] == WEAK_TREND
    assert out.loc["HONA", "trend_score"] == "0 of 8"
    assert int(out.loc["HONA", "contractions"]) == 3
    assert "not 8 of 8" in out.loc["HONA", "reason"] and "never feeds Buy setups" in out.loc["HONA", "reason"]
    assert out.loc["SEV", "status"] == WEAK_TREND and "Still open: rule 8" in out.loc["SEV", "reason"]
    assert out.loc["ONE", "status"] == WEAK_ONE and "only one pullback" in out.loc["ONE", "reason"]
    # Weaker rows sort after every real VCP row.
    ranks = [setups.VCP_STATUS_RANK[x] for x in out["status"]]
    assert ranks == sorted(ranks)
    assert list(out["status"])[-3:] == [WEAK_ONE, WEAK_TREND, WEAK_TREND]


def test_weaker_rows_never_feed_buy_setups_leaders_or_rotation():
    vcp = _scan({"vcp": {"show_weaker_trend": True}}).reset_index()
    names = list(vcp["ticker"])
    scores = pd.DataFrame([{"ticker": t, "company": t, "sector": "Industrials", "index_membership": "SP500",
                            "score": 9, "verdict": "BUY", "above_sma50": "yes", "above_sma200": "yes"} for t in names])
    sma = {t: True for t in names}
    buy = setups.build_buy_setups(vcp, None, None, None, scores, sma_ok=sma, market={"spy": True, "qqq": True})
    got = set(buy["ticker"])
    assert got.isdisjoint({"HONA", "SEV", "ONE", "LOW", "OLD"}), got
    assert {"RDY", "ATP", "BRK"} <= got, got
    leaders = setups.combine_leaders(vcp, pd.DataFrame())
    assert set(leaders["ticker"]) == {"RDY", "ATP", "BRK"}
    live = sector_rotation.resolve_buy_tickers(scores, scanners={"vcp": vcp})
    assert live == {"RDY", "ATP", "BRK"}, live


def test_settings_and_help_carry_the_switch():
    cfg = _cfg()
    rows = tables.settings_rows(cfg)
    got = dict(zip(rows["setting"], rows["value"]))
    assert got["vcp.show_weaker_trend"] is False
    assert "vcp._note" not in got
    help_ = dict(tables.help_rows())
    assert "vcp.show_weaker_trend" in help_["VCP weaker trend switch"]
    assert WEAK_TREND in help_["VCP weaker trend switch"]
    assert "8 of 8" in help_["VCP scanner"] and "two tightening pullbacks" in help_["VCP scanner"]


def test_saved_vcp_file_matches_the_switch():
    path = os.path.join(ROOT, "data", "scanner_vcp.csv")
    if not os.path.exists(path):
        return
    df = pd.read_csv(path)
    df = df[df["ticker"].notna() & (df["ticker"].astype(str).str.strip() != "")]
    if _cfg()["vcp"].get("show_weaker_trend") is True or len(df) == 0:
        return
    assert set(df["trend_score"]) <= {"8 of 8"}, set(df["trend_score"])
    assert (df["contractions"].astype(int) >= 2).all()
    assert set(df["status"]) <= {"READY", "BROKEN OUT today", "WATCHING"}


if __name__ == "__main__":
    test_status_rules_on_fixed_states()
    test_default_scan_lists_only_the_green_tag()
    test_switch_brings_weaker_rows_back_labeled()
    test_weaker_rows_never_feed_buy_setups_leaders_or_rotation()
    test_settings_and_help_carry_the_switch()
    test_saved_vcp_file_matches_the_switch()
    print("vcp green tag ok")
