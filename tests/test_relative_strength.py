"""RS Rating (MarketSmith style): the formula, the 1 to 99 rank, the blank year, and the switch."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import relative_strength as rs


def _path(start, *steps):
    """Closes that hit each step at the quarter boundaries, then hold the last price."""
    prices = [float(start)]
    for step in steps:
        prices.append(prices[-1] * (1.0 + step))
    # 253 closes: index 0, 63, 126, 189, 252 are the five points. Fill flat inside each quarter.
    out = np.empty(rs.MIN_BARS, dtype=float)
    marks = [0, 63, 126, 189, 252]
    for i, price in enumerate(prices):
        end = marks[i + 1] if i + 1 < len(marks) else marks[-1]
        out[marks[i]: end + (0 if i + 1 < len(marks) else 1)] = price
    out[-1] = prices[-1]
    return out


def test_quarter_endpoints_and_weights():
    # Q4 +10%, Q3 +10%, Q2 +10%, Q1 +20%. Latest quarter is weighted 0.4.
    closes = _path(100, 0.10, 0.10, 0.10, 0.20)
    quarters = rs.quarter_returns(closes, 63)
    assert quarters is not None
    q1, q2, q3, q4 = quarters
    assert abs(q4 - 0.10) < 1e-9
    assert abs(q3 - 0.10) < 1e-9
    assert abs(q2 - 0.10) < 1e-9
    assert abs(q1 - 0.20) < 1e-9
    raw = rs.raw_score(quarters)
    assert abs(raw - (0.4 * 0.20 + 0.2 * 0.10 + 0.2 * 0.10 + 0.2 * 0.10)) < 1e-12
    assert abs(raw - 0.14) < 1e-12


def test_latest_quarter_counts_double():
    only_recent = rs.raw_score((0.10, 0.0, 0.0, 0.0))
    only_old = rs.raw_score((0.0, 0.0, 0.0, 0.10))
    assert abs(only_recent - 0.04) < 1e-12
    assert abs(only_old - 0.02) < 1e-12
    assert only_recent > only_old


def test_rank_ends_are_1_and_99_and_ties_share():
    raw = pd.Series({"WEAK": -0.20, "MID_A": 0.05, "MID_B": 0.05, "BEST": 0.40})
    ranks = rs.rank_1_to_99(raw)
    assert int(ranks["WEAK"]) == 1
    assert int(ranks["BEST"]) == 99
    assert int(ranks["MID_A"]) == int(ranks["MID_B"]) == 50
    # One scored name is the strongest by itself.
    assert int(rs.rank_1_to_99(pd.Series({"ONLY": 0.01}))["ONLY"]) == 99
    assert len(rs.rank_1_to_99(pd.Series(dtype=float))) == 0
    # A blank raw score is not in the count, so it cannot pull the best name off 99.
    with_blank = pd.Series({"BEST": 0.4, "NEW": np.nan, "WEAK": -0.2})
    ranked = rs.rank_1_to_99(with_blank)
    assert "NEW" not in ranked.index
    assert int(ranked["BEST"]) == 99
    assert int(ranked["WEAK"]) == 1


def test_short_history_is_blank_and_not_ranked():
    dates = pd.bdate_range("2024-01-02", periods=400)
    full = _path(100, 0.05, 0.05, 0.05, 0.05)
    # A listing with 200 closes, about nine months, must not get a partial score.
    short = np.linspace(50, 80, 200)
    close = pd.DataFrame({
        "FULL": np.nan,
        "NEW": np.nan,
        "ZERO": np.nan,
    }, index=dates)
    close.iloc[-len(full):, 0] = full
    close.iloc[-len(short):, 1] = short
    zero = full.copy()
    zero[0] = 0.0
    close["ZERO"] = np.nan
    close.iloc[-len(zero):, 2] = zero
    table = rs.build(close, ["FULL", "NEW", "ZERO", "FULL"], as_of="2025-07-15")
    assert list(table["ticker"]) == ["FULL", "NEW", "ZERO"]
    full_row = table.set_index("ticker").loc["FULL"]
    new_row = table.set_index("ticker").loc["NEW"]
    zero_row = table.set_index("ticker").loc["ZERO"]
    assert int(full_row["rs"]) == 99
    assert full_row["rs_label"] == "RS 99: beat 99% of stocks over the past year"
    assert new_row["rs"] == ""
    assert new_row["rs_raw"] == ""
    assert new_row["rs_note"] == rs.SHORT_NOTE
    assert int(new_row["bars"]) == 200
    assert zero_row["rs"] == ""
    assert zero_row["rs_note"] == rs.GAP_NOTE
    # The new name was not treated as a zero and did not change the rank.
    assert "0" not in str(new_row["rs"])


def test_label_uses_the_rank_as_the_percent():
    assert rs.label_for(85) == "RS 85: beat 85% of stocks over the past year"
    assert rs.label_for(1) == "RS 1: beat 1% of stocks over the past year"
    assert rs.label_for(99) == "RS 99: beat 99% of stocks over the past year"
    assert rs.label_for(None) == ""
    assert rs.label_for("") == ""
    assert "\u2014" not in rs.label_for(85)
    assert "\u2014" not in rs.SHORT_NOTE


def test_attach_copies_the_rank_and_leaves_unknown_names_blank():
    ratings = rs.build(
        pd.DataFrame({"AAA": _path(10, 0.1, 0.0, 0.0, 0.2), "BBB": _path(10, 0.0, 0.0, 0.0, 0.0)}),
        ["AAA", "BBB"],
    )
    frame = pd.DataFrame({"ticker": ["BBB", "AAA", "CCC"], "status": ["READY", "READY", "WATCHING"]})
    out = rs.attach(frame, ratings)
    assert list(out["ticker"]) == ["BBB", "AAA", "CCC"]
    assert out.loc[out.ticker == "CCC", "rs"].iloc[0] == ""
    assert out.loc[out.ticker == "CCC", "rs_label"].iloc[0] == ""
    aaa = int(out.loc[out.ticker == "AAA", "rs"].iloc[0])
    bbb = int(out.loc[out.ticker == "BBB", "rs"].iloc[0])
    assert aaa == 99 and bbb == 1
    assert "beat 99%" in out.loc[out.ticker == "AAA", "rs_label"].iloc[0]
    # No ticker column: leave the frame alone (the highs and lows history file).
    history = pd.DataFrame({"date": ["2024-01-02"], "new_highs": [3]})
    assert rs.attach(history, ratings) is history or "rs" not in rs.attach(history, ratings).columns


def test_config_switch_defaults_on_and_weights_are_readable():
    assert rs.feature_on({}) is True
    assert rs.feature_on({"features": {}}) is True
    assert rs.feature_on({"features": {"rs_rank": False}}) is False
    spec = rs.settings_from({
        "relative_strength": {"quarter_sessions": 63, "weight_q1": 0.4, "min_bars": 100, "leader_min": 70},
    })
    # A shorter min_bars cannot rank a stock that does not have all four quarters.
    assert spec["min_bars"] == 253
    assert spec["weights"][0] == 0.4
    assert spec["leader_min"] == 70
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import json
    cfg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8"))
    assert cfg["features"]["rs_rank"] is True
    block = cfg["relative_strength"]
    assert block["quarter_sessions"] == 63
    assert [block["weight_q1"], block["weight_q2"], block["weight_q3"], block["weight_q4"]] == [0.4, 0.2, 0.2, 0.2]
    assert block["min_bars"] == 253
    assert block["leader_min"] == 70
    assert "\u2014" not in block["_note"]


def test_help_and_page_copy_are_plain():
    import tables
    topics = dict(tables.help_rows())
    text = topics["Relative strength"]
    assert "RS 85" in text or "beat 85%" in text
    assert "feature.rs_rank" in text
    assert "63" in text
    assert "left blank" in text
    assert "MarketSmith" in text and "every stock" in text
    assert "not against SPY" in text and "rule 8" in text and "rs_spy_3m" in text
    assert "\u2014" not in text
    pages = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "site", "js", "pages.js"), encoding="utf-8").read()
    desk = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "site", "js", "desk.js"), encoding="utf-8").read()
    assert "70 or higher" in pages or "or higher" in desk
    assert "beat 85% of stocks over the past year" in desk or "beat %d%% of stocks" in open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "relative_strength.py"), encoding="utf-8").read()
    assert 'featureOn("feature.rs_rank")' in desk
    assert "rsmin" in pages
    assert "withRs(" in pages


def test_scores_and_scanner_tables_carry_the_rs_column():
    import tables
    for name in ("scores", "scanner_vcp", "scanner_canslim", "scanner_leaders", "buy_setups", "trends", "scanner_52w"):
        cols = tables.COLS[name]
        assert "rs" in cols and cols.index("rs") < cols.index("data_status"), name
    # The old L header stays for the Sheet and holds the same RS Rating.
    assert "l_rs_percentile" in tables.COLS["scanner_canslim"]
    assert tables.COLS["rs_ratings"][:2] == ["ticker", "rs"]


if __name__ == "__main__":
    import inspect
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn) and not inspect.signature(_fn).parameters:
            _fn()
    print("relative strength ok")
