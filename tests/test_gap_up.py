"""Offline checks for the Gap Up scan. Synthetic bars on fixed dates, no clock, no downloads."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import gap_up  # noqa: E402
import tables  # noqa: E402

START = "2026-01-02"


def _tape(gap_at=-5, gap_bar=(53.0, 54.0, 51.5, 53.5, 2_000_000.0), after_close=53.0, quiet=120, extra=None):
    """Quiet bars near 50 (high 50.5, low 49.5, 1M shares), then one gap bar `gap_at` bars from the end, then
    flat bars closing at after_close. extra: {index from the end: (open, high, low, close, volume)}."""
    n = quiet
    o = [50.0] * n
    h = [50.5] * n
    l = [49.5] * n
    c = [50.0] * n
    v = [1_000_000.0] * n
    g = n + gap_at
    if gap_bar is not None:
        o[g], h[g], l[g], c[g], v[g] = gap_bar
        for k in range(g + 1, n):
            o[k], h[k], l[k], c[k], v[k] = after_close, after_close + 0.5, after_close - 0.5, after_close, 1_000_000.0
    for k, bar in (extra or {}).items():
        i = n + k
        o[i], h[i], l[i], c[i], v[i] = bar
    idx = pd.bdate_range(START, periods=n)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def _scan(frames, cfg=None):
    """frames: {ticker: frame}. SPY sets the panel date (a quiet tape)."""
    frames = dict(frames)
    frames.setdefault("SPY", _tape(gap_bar=None))
    wide = {col: pd.DataFrame({t: f[col] for t, f in frames.items()}) for col in ("open", "high", "low", "close", "volume")}
    uni = pd.DataFrame([{"ticker": t, "company": t + " Co", "sector": "Industrials", "index_membership": "SP500"} for t in frames if t != "SPY"])
    return gap_up.scan_gap_up(wide["close"], wide["high"], wide["low"], wide["volume"], wide["open"], uni, cfg)


def _one(frame, cfg=None):
    out = _scan({"AAA": frame}, cfg)
    assert len(out) == 1, out
    return out.iloc[0]


def test_config_block_and_feature():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["features"]["scanner_gap_up"] is True
    assert cfg["chart_viewer"]["include_gap_up"] is True
    block = cfg["gap_up"]
    for k, v in gap_up.GAP_UP_DEFAULTS.items():
        assert block[k] == v, k
    assert (block["lookback_days"], block["vol_mult"], block["vol_avg_days"], block["min_price"]) == (21, 1.5, 50, 5.0)
    # min_gap_pct is a whole percent, like the other _pct keys: 3.0 means 3%.
    assert block["min_gap_filter"] is True and block["min_gap_pct"] == 3.0
    assert "3%" in block["_note"] and "3%" in topics_text()
    # Same traded-value floor as the Episodic Pivot scan.
    assert block["min_dollar_volume"] == cfg["episodic_pivot"]["min_dollar_volume_50d"]
    got = dict(zip(tables.settings_rows(cfg)["setting"], tables.settings_rows(cfg)["value"]))
    assert got["feature.scanner_gap_up"] is True and got["chart_viewer.include_gap_up"] is True
    for k, v in block.items():
        if not k.startswith("_"):
            assert got["gap_up." + k] == v, k
    topics = dict(tables.help_rows())
    assert "Gap Up" in topics and "Gap Up settings" in topics
    assert "\u2014" not in topics["Gap Up"] and "\u2014" not in block["_note"]


def topics_text():
    return dict(tables.help_rows())["Gap Up"] + " " + dict(tables.help_rows())["Gap Up settings"]


def _gap_of(pct):
    """A tape whose gap-day open is pct% over the prior high of 50.5."""
    op = 50.5 * (1 + pct / 100.0)
    return _tape(gap_bar=(op, op + 1.0, op - 0.2, op + 0.5, 2_000_000.0), after_close=op + 0.5)


def test_min_gap_3_pct():
    assert len(_scan({"AAA": _gap_of(2.9)})) == 0, "2.9% is under the 3% minimum"
    row = _one(_gap_of(3.0))
    assert float(row["gap_pct"]) == 3.0, "exactly 3% is in"
    assert len(_scan({"AAA": _gap_of(3.1)})) == 1
    # Switch off: any true gap counts, as before.
    off = {"gap_up": {"min_gap_filter": False}}
    assert float(_one(_gap_of(1.0), off)["gap_pct"]) == 1.0, "a 1% gap is in with the switch off"
    assert len(_scan({"AAA": _gap_of(2.9)}, off)) == 1
    # The minimum is measured from the prior high, not the prior close: 3.5% over the close but 2.5% over the high is out.
    assert len(_scan({"AAA": _gap_of(2.5)})) == 0 and float(_one(_gap_of(2.5), off)["gap_vs_close_pct"]) > 3.0
    # A high open inside the range never counts, with the switch on or off.
    inside = _tape(gap_bar=(50.4, 53.0, 50.2, 52.5, 3_000_000.0), after_close=52.5)
    assert len(_scan({"AAA": inside})) == 0 and len(_scan({"AAA": inside}, off)) == 0


def test_true_gap_and_gap_pct():
    row = _one(_tape())
    # Prior high 50.5, prior close 50.0, open 53.0.
    assert row["gap_date"] == str(_tape().index[-5].date()) and row["days_ago"] == 4
    assert abs(float(row["gap_pct"]) - round((53.0 / 50.5 - 1) * 100, 2)) < 1e-9
    assert abs(float(row["gap_vs_close_pct"]) - 6.0) < 1e-9
    assert float(row["hold_level"]) == 51.5 and float(row["gap_high"]) == 54.0 and float(row["gap_open"]) == 53.0
    assert row["status"] == gap_up.GAP_HOLDING


def test_open_inside_range_is_not_a_gap():
    # Open 50.4 is above the prior close 50.0 but under the prior high 50.5: a high open inside the range.
    inside = _tape(gap_bar=(50.4, 53.0, 50.2, 52.5, 3_000_000.0), after_close=52.5)
    assert len(_scan({"AAA": inside})) == 0
    # Open exactly at the prior high is not above it.
    at_high = _tape(gap_bar=(50.5, 53.0, 50.4, 52.5, 3_000_000.0), after_close=52.5)
    assert len(_scan({"AAA": at_high})) == 0
    # The switch off measures from the prior close instead, so the inside open counts.
    out = _scan({"AAA": inside}, {"gap_up": {"true_gap_only": False, "min_gap_filter": False}})
    assert len(out) == 1


def test_any_gap_size_counts():
    tiny = _tape(gap_bar=(50.51, 51.0, 50.51, 50.9, 2_000_000.0), after_close=50.8)
    assert len(_scan({"AAA": tiny})) == 0
    row = _one(tiny, {"gap_up": {"min_gap_filter": False}})
    assert 0 < float(row["gap_pct"]) < 0.1


def test_volume_threshold():
    # The 50 sessions before the gap day average 1M shares. 1.5M passes, 1.49M does not.
    assert len(_scan({"AAA": _tape(gap_bar=(53.0, 54.0, 51.5, 53.5, 1_500_000.0))})) == 1
    assert len(_scan({"AAA": _tape(gap_bar=(53.0, 54.0, 51.5, 53.5, 1_490_000.0))})) == 0
    row = _one(_tape(gap_bar=(53.0, 54.0, 51.5, 53.5, 1_500_000.0)))
    assert float(row["volume_mult"]) == 1.5 and int(row["avg_volume_50"]) == 1_000_000
    # The average uses only the days before the gap day: a huge gap-day volume does not lift its own average.
    row = _one(_tape(gap_bar=(53.0, 54.0, 51.5, 53.5, 10_000_000.0)))
    assert float(row["volume_mult"]) == 10.0
    assert len(_scan({"AAA": _tape(gap_bar=(53.0, 54.0, 51.5, 53.5, 1_000_000.0))}, {"gap_up": {"volume_filter": False}})) == 1


def test_hold_rule_and_equal_to_low():
    # A close under the gap-day low (51.5) after the gap day drops it.
    broke = _tape(extra={-2: (52.0, 52.2, 51.0, 51.4, 1_000_000.0)})
    assert len(_scan({"AAA": broke})) == 0
    # A close exactly at the low still holds.
    equal = _tape(extra={-2: (52.0, 52.2, 51.2, 51.5, 1_000_000.0)})
    row = _one(equal)
    assert float(row["lowest_close_since"]) == 51.5
    # An intraday low under the hold level does not matter; only closes count.
    wick = _tape(extra={-2: (52.0, 52.2, 50.0, 52.0, 1_000_000.0)})
    assert len(_scan({"AAA": wick})) == 1
    # Switch off keeps the broken one.
    assert len(_scan({"AAA": broke}, {"gap_up": {"hold_rule": False}})) == 1


def test_21_day_window_includes_today():
    # Gap 20 bars back = 21st trading day counting today: in. 21 bars back: out.
    assert _one(_tape(gap_at=-21))["days_ago"] == 20
    assert len(_scan({"AAA": _tape(gap_at=-22)})) == 0
    today = _one(_tape(gap_at=-1))
    assert today["days_ago"] == 0 and today["status"] == gap_up.GAP_TODAY
    assert len(_scan({"AAA": _tape(gap_at=-22)}, {"gap_up": {"lookback_days": 22}})) == 1


def test_most_recent_holding_gap_per_stock():
    # Older gap at -15 (low 51.5) holds. A newer gap at -5 (open 56.5 over high 54.5, low 55.5) then a close at 55.0 under it.
    old = (53.0, 54.0, 51.5, 53.5, 2_000_000.0)
    frame = _tape(gap_at=-15, gap_bar=old, after_close=54.0,
                  extra={-5: (56.5, 57.0, 55.5, 56.5, 2_000_000.0), -3: (55.2, 55.4, 54.8, 55.0, 1_000_000.0)})
    out = _scan({"AAA": frame})
    assert len(out) == 1
    assert out.iloc[0]["gap_date"] == str(frame.index[-15].date()), "newer gap broke, so the older holding gap is the row"
    # Both hold: the newer gap wins.
    frame2 = _tape(gap_at=-15, gap_bar=old, after_close=54.0, extra={-5: (56.5, 57.0, 55.5, 56.5, 2_000_000.0),
                                                                     -4: (56.0, 56.5, 55.8, 56.0, 1_000_000.0), -3: (56.0, 56.5, 55.8, 56.0, 1_000_000.0),
                                                                     -2: (56.0, 56.5, 55.8, 56.0, 1_000_000.0), -1: (56.0, 56.5, 55.8, 56.0, 1_000_000.0)})
    row = _one(frame2)
    assert row["gap_date"] == str(frame2.index[-5].date()) and float(row["hold_level"]) == 55.5


def test_price_and_liquidity_floor():
    # Scale the whole tape to about $4: under the $5 floor.
    cheap = _tape()
    for col in ("open", "high", "low", "close"):
        cheap[col] = cheap[col] * 0.08
    cheap["volume"] = cheap["volume"] * 50
    assert len(_scan({"AAA": cheap})) == 0
    assert len(_scan({"AAA": cheap}, {"gap_up": {"price_floor": False}})) == 1
    # Last close exactly $5 passes.
    five = _tape(gap_bar=(5.21, 5.4, 4.95, 5.3, 2_000_000.0), after_close=5.0)
    for col in ("open", "high", "low", "close"):
        five.iloc[:-5, five.columns.get_loc(col)] = five[col].iloc[:-5] * 0.1
    five["volume"] = five["volume"] * 10
    assert float(_one(five)["price"]) == 5.0
    # Thin stock: $50 x 20K shares = $1M a day, under $3M.
    thin = _tape()
    thin["volume"] = thin["volume"] * 0.02
    assert len(_scan({"AAA": thin})) == 0
    assert len(_scan({"AAA": thin}, {"gap_up": {"liquidity_floor": False}})) == 1


def test_sorting_newest_first_then_gap_pct():
    frames = {
        "OLD": _tape(gap_at=-10, gap_bar=(60.0, 62.0, 59.0, 61.0, 3_000_000.0), after_close=61.0),
        "BIG": _tape(gap_at=-2, gap_bar=(58.0, 60.0, 57.0, 59.0, 3_000_000.0), after_close=59.0),
        "SML": _tape(gap_at=-2, gap_bar=(52.1, 53.0, 51.9, 52.5, 3_000_000.0), after_close=52.5),
        "AAB": _tape(gap_at=-2, gap_bar=(52.1, 53.0, 51.9, 52.5, 3_000_000.0), after_close=52.5),
    }
    out = _scan(frames)
    assert list(out["ticker"]) == ["BIG", "AAB", "SML", "OLD"]


def test_row_columns_and_other_scanners():
    row = _one(_tape(after_close=53.0))
    assert abs(float(row["pct_above_hold"]) - round((53.0 / 51.5 - 1) * 100, 2)) < 1e-9
    assert float(row["close_pos_pct"]) == 50.0  # close 53.0 in a 52.5 to 53.5 day
    assert row["above_sma50"] == "yes" and row["above_sma200"] == ""  # 120 bars: no 200-day yet
    assert "Gapped up" in row["reason"] and "\u2014" not in row["reason"]
    for col in tables.COLS["scanner_gap_up"]:
        if col not in ("disclaimer",):
            assert col in row.index, col
    gap = _scan({"AAA": _tape(), "BBB": _tape()})
    frames = {
        "scanner_vcp": pd.DataFrame([{"ticker": "AAA", "status": "READY"}, {"ticker": "BBB", "status": "CLOSED"}]),
        "scanner_qullamaggie": pd.DataFrame([{"ticker": "BBB", "status": "CLOSED"}]),
        "scanner_volume": pd.DataFrame([{"ticker": "AAA", "spike": "no", "streak": "yes", "quiet": "no"}]),
        "scanner_growth": pd.DataFrame([{"ticker": "AAA", "passes": "yes"}, {"ticker": "BBB", "passes": "no"}]),
        "scanner_52w": pd.DataFrame([{"ticker": "BBB", "new_high_today": "no", "new_low_today": "no", "near_high": "yes"}]),
    }
    got = gap_up.attach_other_scanners(gap, frames).set_index("ticker")["other_scanners"].to_dict()
    assert got == {"AAA": "VCP, High volume, Growth", "BBB": "52-week"}
    off = gap_up.attach_other_scanners(gap, frames, {"gap_up": {"show_other_scanners": False}})
    assert set(off["other_scanners"]) == {""}


def test_buy_setups_unchanged():
    import setups
    assert "Gap Up" not in setups.BUY_SETUP_ORDER
    src = open(os.path.join(ROOT, "stock_desk.py"), encoding="utf-8").read()
    call = src.split("buy = setups.build_buy_setups(", 1)[1].split(")\n", 1)[0]
    assert "gap" not in call.lower()


if __name__ == "__main__":
    names = sorted(k for k, v in list(globals().items()) if k.startswith("test_") and callable(v))
    for name in names:
        globals()[name]()
    print("gap up ok (%d tests)" % len(names))
