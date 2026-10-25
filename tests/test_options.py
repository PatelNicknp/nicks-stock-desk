"""Pricing, debit-spread math, and the skip rules. No network."""
import datetime as dt
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from options import bs
from options.check import buyer_score, label_for, price_check
from options.greeks import greeks
from options.ideas import _consider_one, publish, should_fetch, slot_label
from options.spreads import (
    MAX_DEBIT_RATIO,
    build_debit,
    liquidity_grade,
    liquidity_reason,
    pick_expiry,
    quote_ok,
    sizing_text,
    spread_math,
)
from options.sources import _fred_from_csv, _treasury_from_csv, parse_chain


def test_call_price_and_put_call_parity():
    s, k, t, r, vol = 100.0, 100.0, 1.0, 0.04, 0.20
    call = bs.price(s, k, t, r, vol, "call")
    put = bs.price(s, k, t, r, vol, "put")
    # Discounted forward parity: call - put = S - K e^{-rT}
    assert abs((call - put) - (s - k * math.exp(-r * t))) < 1e-8
    assert 7.0 < call < 12.0
    d = bs.delta(s, k, t, r, vol, "call")
    assert 0.5 < d < 0.7
    assert -0.5 < bs.delta(s, k, t, r, vol, "put") < -0.3
    g = greeks(s, k, t, r, vol, "call")
    assert abs(g["delta"] - d) < 1e-8
    assert g["vega"] > 0 and g["gamma"] > 0


def test_iv_round_trip():
    s, k, t, r, vol = 188.5, 180.0, 50 / 365.0, 0.043, 0.28
    for kind in ("call", "put"):
        px = bs.price(s, k, t, r, vol, kind)
        got = bs.implied_vol(px, s, k, t, r, kind)
        assert got is not None
        assert abs(got - vol) < 1e-4
    intrinsic = s - k
    assert bs.implied_vol(intrinsic, s, k, t, r, "call") is None
    assert bs.implied_vol(0.01, s, k, 0, r, "call") is None


def test_spread_payoff_math():
    call = spread_math("call", 95, 105, 3.2, 100)
    assert abs(call["width"] - 10) < 1e-9
    assert abs(call["max_profit"] - 680) < 1e-6
    assert abs(call["max_loss"] - 320) < 1e-6
    assert abs(call["breakeven"] - 98.2) < 1e-9
    assert abs(call["cost"] - 320) < 1e-6
    assert abs(call["move_pct"] - (-1.8)) < 1e-6
    put = spread_math("put", 105, 95, 3.2, 100)
    assert abs(put["breakeven"] - 101.8) < 1e-9
    assert abs(put["max_profit"] - 680) < 1e-6
    assert abs(put["max_loss"] - 320) < 1e-6
    assert " $2k: " in " " + sizing_text(320)
    text = sizing_text(320)
    # 2% of 2000 is $40, which does not buy a $320 debit. 5% of 10000 is $500, one contract.
    assert text.startswith("$2k: 0 to 0")
    assert "$10k: 0 to 1" in text


def test_price_check_labels_follow_the_ratio():
    assert label_for(0.89) == "CHEAP"
    assert label_for(0.9) == "FAIR"
    assert label_for(1.2) == "FAIR"
    assert label_for(1.21) == "OVERPAYING"
    assert buyer_score(1.0) == 50
    assert buyer_score(0.9) == 70
    assert buyer_score(1.2) == 10
    # A fair debit at the model price is FAIR, score 50. Overpaying on the label
    # is not, by itself, a reason to drop the idea.
    s, t, r, vol = 100.0, 50 / 365.0, 0.04, 0.25
    long_k, short_k = 98.0, 108.0
    debit = bs.price(s, long_k, t, r, vol, "call") - bs.price(s, short_k, t, r, vol, "call")
    got = price_check(
        [(1, long_k, "call", vol), (-1, short_k, "call", vol)],
        s, t, r, debit, vol, vol, vol,
    )
    assert got["label"] == "FAIR"
    assert abs(got["ratio"] - 1.0) < 0.02
    assert 45 <= got["score"] <= 55


def test_expiry_window_and_liquidity():
    today = dt.date(2026, 10, 25)
    dates = [today + dt.timedelta(days=d) for d in (20, 40, 52, 70, 90)]
    exp, dte = pick_expiry(dates, today)
    assert dte == 52
    # No 45-60 day expiry, so the 30-75 fallback is used.
    exp, dte = pick_expiry([today + dt.timedelta(days=d) for d in (20, 36, 80)], today)
    assert dte == 36
    assert pick_expiry([today + dt.timedelta(days=20)], today) is None
    assert quote_ok(1.0, 1.05, 1.025, 0.10, 0.10)
    assert not quote_ok(1.0, 1.20, 1.10, 0.10, 0.10)
    # Under $1 the cap is $0.10, not 10% of the mid.
    assert quote_ok(0.40, 0.50, 0.45, 0.10, 0.10)
    assert not quote_ok(0.40, 0.55, 0.475, 0.10, 0.10)
    wide = {"bid": 1.0, "ask": 1.4, "mid": 1.2, "oi": 5000}
    thin = {"bid": 1.0, "ask": 1.02, "mid": 1.01, "oi": 100}
    assert liquidity_reason(wide, thin) == "open interest under 500"
    tight = {"bid": 1.00, "ask": 1.02, "mid": 1.01, "oi": 800}
    assert liquidity_reason(tight, dict(tight)) == ""
    assert liquidity_grade(
        {"bid": 2.0, "ask": 2.04, "mid": 2.02, "oi": 6000},
        {"bid": 1.0, "ask": 1.02, "mid": 1.01, "oi": 6000},
    ) == "A"
    assert liquidity_grade(
        {"bid": 2.0, "ask": 2.04, "mid": 2.02, "oi": 6000},
        {"bid": 1.0, "ask": 1.02, "mid": 1.01, "oi": 800},
    ) == "C"


def _chain(spot, vol, t_years, r, strikes, oi=5000):
    exp = "2026-12-16"
    rows = []
    for kind in ("call", "put"):
        for k in strikes:
            mid = bs.price(spot, k, t_years, r, vol, kind)
            if mid < 0.05:
                continue
            rows.append({
                "exp": exp, "kind": kind, "strike": k,
                "bid": round(mid * 0.98, 2), "ask": round(mid * 1.02, 2), "oi": oi,
            })
    return rows


def test_debit_spread_builds_and_narrows():
    spot, vol, t, r = 100.0, 0.30, 52 / 365.0, 0.04
    strikes = list(range(70, 131, 1))
    quotes = _chain(spot, vol, t, r, strikes)
    built, why = build_debit(quotes, "call", spot, t, r, None, vol)
    assert why == "", why
    assert built["long"]["strike"] < built["short"]["strike"]
    assert 0.50 <= built["long"]["delta"] <= 0.70
    assert built["ratio"] <= MAX_DEBIT_RATIO + 1e-9
    assert built["math"]["max_profit"] > 0
    assert abs(built["math"]["max_loss"] - built["math"]["cost"]) < 1e-6
    # Inflate the natural long so the first pair is too expensive. A nearer long should pass.
    natural = built["long"]["strike"]
    short_k = built["short"]["strike"]
    bumped = []
    for q in quotes:
        row = dict(q)
        if row["kind"] == "call" and abs(row["strike"] - natural) < 1e-9:
            row["bid"] = row["bid"] * 3
            row["ask"] = row["ask"] * 3
        bumped.append(row)
    narrow, why = build_debit(bumped, "call", spot, t, r, short_k, vol)
    assert why == "", why
    assert narrow["narrowed"] is True
    assert natural < narrow["long"]["strike"] < short_k
    assert narrow["ratio"] <= MAX_DEBIT_RATIO + 1e-9
    # Target closer to the spot than the 0.30-delta strike picks the target strike.
    aimed, why = build_debit(quotes, "call", spot, t, r, 105, vol)
    assert why == ""
    assert abs(aimed["short"]["strike"] - 105) <= 1.0
    # A $10 strike grid can miss 0.55 to 0.65. The nearest strike still counts.
    coarse = _chain(spot, vol, t, r, list(range(70, 141, 10)))
    wide_grid, why = build_debit(coarse, "call", spot, t, r, None, vol)
    assert why == "", why
    assert abs(wide_grid["long"]["delta"] - 0.60) <= 0.08


def test_skip_rules_are_one_plain_reason():
    today = dt.date(2026, 10, 25)
    exp = "2026-12-16"
    t = 52 / 365.0
    quotes = _chain(100, 0.25, t, 0.04, list(range(80, 121, 1)))
    chain = {"as_of": "2026-10-23T20:00:00", "quotes": quotes}
    base = dict(ticker="AAA", company="Alpha", side="call", setup="Box READY",
                spot=100.0, avg_volume=2_000_000, rv20=0.22, rv60=0.24, sma50=90.0,
                target=110.0, stop=93.0, market_ok="no", price_as_of="2026-10-23")
    idea, skip = _consider_one(base, chain, 0.04, today, {})
    assert skip is None
    assert idea[0]["education"] == "Education, not financial advice."
    assert idea[0]["direction"] == "Bullish"
    assert "21 days" in idea[0]["exit_plan"]
    assert "+100%" in idea[0]["exit_plan"]
    assert "50-day" in idea[0]["exit_plan"]
    cheap = _consider_one(dict(base, spot=8, avg_volume=5_000), chain, 0.04, today, {})
    assert cheap[0] is None and cheap[1]["reason"] == "price under $10"
    vol = _consider_one(dict(base, avg_volume=400_000), chain, 0.04, today, {})
    assert vol[1]["reason"] == "average volume under 1 million"
    earn = _consider_one(base, chain, 0.04, today, {"AAA": dt.date(2026, 11, 20)})
    assert earn[1]["reason"] == "earnings on 2026-11-20 fall before expiry"
    rich = _consider_one(dict(base, rv20=0.10), chain, 0.04, today, {})
    assert rich[1]["reason"] == "implied vol is more than 1.3 times the 20-day realized vol"
    thin = []
    for q in quotes:
        row = dict(q)
        row["oi"] = 50
        thin.append(row)
    oi = _consider_one(base, {"as_of": "x", "quotes": thin}, 0.04, today, {})
    assert oi[1]["reason"] == "open interest under 500"
    none = _consider_one(base, None, 0.04, today, {})
    assert none[1]["reason"] == "no option quotes"
    put = _consider_one(dict(base, side="put", target=90, stop=98), chain, 0.04, today, {})
    assert put[0] is None or put[0][0]["direction"] == "Bearish"
    if put[0]:
        assert "breakdown level" in put[0][0]["exit_plan"]


def test_refresh_windows_do_not_fetch_hourly_outside_them():
    am = dt.datetime(2026, 10, 26, 10, 30)
    pm = dt.datetime(2026, 10, 26, 15, 30)
    early = dt.datetime(2026, 10, 26, 8, 0)
    assert slot_label(am) == "2026-10-26-am"
    assert slot_label(pm) == "2026-10-26-pm"
    assert slot_label(early) is None
    assert slot_label(dt.datetime(2026, 10, 26, 9, 45)) == "2026-10-26-am"
    assert slot_label(dt.datetime(2026, 10, 26, 9, 44)) is None
    assert should_fetch("offline", am, None) is False
    assert should_fetch("full", early, None) is True
    assert should_fetch("hourly", early, None) is False
    assert should_fetch("hourly", am, None) is True
    assert should_fetch("hourly", am, "2026-10-26-am") is False
    assert should_fetch("hourly", pm, "2026-10-26-am") is True


def test_publish_offline_does_not_call_the_network():
    def boom(ticker):
        raise AssertionError("offline tried a chain request for " + ticker)
    idx = pd.bdate_range("2024-01-02", periods=80)
    close = pd.DataFrame({"AAA": [8.0] * 80}, index=idx)
    vol = pd.DataFrame({"AAA": [2_000_000.0] * 80}, index=idx)
    buy = pd.DataFrame([{
        "ticker": "AAA", "company": "Alpha", "setup_sources": "Box", "best_status": "READY",
        "price": 8, "target1": 10, "stop": 7, "market_ok": "no", "price_as_of": "2026-10-23",
        "data_status": "OK",
    }])
    ideas, skipped, check, logged, stamp = publish(
        close, vol, buy, pd.DataFrame(), pd.DataFrame(),
        cache_dir="/tmp/opt-test-cache", mode="offline",
        now=dt.datetime(2026, 10, 26, 10, 30), stamp=None,
        fetch=boom, sleep=lambda s: None, today=dt.date(2026, 10, 26), rate=0.04,
    )
    assert len(ideas) == 0
    assert skipped.iloc[0]["reason"] == "price under $10"
    assert "offline" in logged[2]
    assert stamp is None


def test_cboe_and_treasury_parsers():
    payload = {
        "timestamp": "2026-10-23T20:00:00",
        "data": {
            "current_price": 100,
            "last_trade_time": "2026-10-23T16:00:00",
            "options": [
                {"option": "AAA261218C00100000", "bid": 2, "ask": 2.1, "open_interest": 2000},
                {"option": "AAA261218P00090000", "bid": 1, "ask": 1.1, "open_interest": 900},
                {"option": "AAA270116C00100000", "bid": 3, "ask": 3.1, "open_interest": 10},
            ],
        },
    }
    got = parse_chain(payload, dt.date(2026, 10, 25), 100)
    assert got["as_of"] == "2026-10-23T16:00:00"
    kinds = {(q["exp"], q["kind"], q["strike"]) for q in got["quotes"]}
    assert ("2026-12-18", "call", 100) in kinds
    assert ("2026-12-18", "put", 90) in kinds
    # January 2027 is outside the compact window for a late-October as-of.
    assert not any(q["exp"].startswith("2027") for q in got["quotes"])
    text = "Date,1 Mo,3 Mo\n10/23/2026,4.1,4.25\n"
    rate, as_of = _treasury_from_csv(text)
    assert abs(rate - 0.0425) < 1e-9 and as_of == "10/23/2026"
    fred = "DATE,DGS3MO\n2026-10-22,.\n2026-10-23,4.30\n"
    rate, as_of = _fred_from_csv(fred)
    assert abs(rate - 0.043) < 1e-9 and as_of == "2026-10-23"


if __name__ == "__main__":
    test_call_price_and_put_call_parity()
    test_iv_round_trip()
    test_spread_payoff_math()
    test_price_check_labels_follow_the_ratio()
    test_expiry_window_and_liquidity()
    test_debit_spread_builds_and_narrows()
    test_skip_rules_are_one_plain_reason()
    test_refresh_windows_do_not_fetch_hourly_outside_them()
    test_publish_offline_does_not_call_the_network()
    test_cboe_and_treasury_parsers()
    print("options ok")
