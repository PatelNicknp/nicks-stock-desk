"""CANSLIM strict screen (Nick, Nov 2026): one test per rule, the missing-data cases,
the market-correction banner (warning only, never a block), ranking by rs_score,
the dropped soft tier, the switches, and the page wiring. Offline, no downloads."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import setups  # noqa: E402
import tables  # noqa: E402

N = 300
IDX = pd.bdate_range("2025-01-02", periods=N)
OLD_COLS = [
    "ticker", "company", "sector", "index_membership", "status", "pivot", "stop", "target", "strength", "reason",
    "freshness", "price", "price_as_of", "c_quarterly_eps", "c_status", "a_annual_eps", "a_status",
    "n_pct_from_high", "n_status", "s_adv", "s_status", "l_rs_percentile", "l_status", "i_trend", "i_status",
    "m_market", "m_spy", "m_qqq", "m_status", "qualify", "vcp_heuristic", "data_status", "note", "disclaimer",
]


def _ohlc(close, volume):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"close": close, "high": close * 1.005, "low": close * 0.995,
                         "volume": np.asarray(volume, dtype=float)}, index=IDX)


def _climb(rate=0.002, start=50.0):
    return start * ((1 + rate) ** np.arange(N))


def _zigzag(up=0.02, down=0.01, start=50.0):
    """Two steps forward, one back: rising, with half the days down."""
    c = [start]
    for i in range(1, N):
        c.append(c[-1] * (1 + up if i % 2 else 1 - down))
    return np.array(c)


def _flat_vol(v=1_000_000.0):
    return np.full(N, v)


def _spy(rate=0.0004):
    return 100 * ((1 + rate) ** np.arange(N))


def _falling(start=100.0):
    return start * (0.998 ** np.arange(N))


def _good_fund(t, q_eps=(1.0, 1.4), a_eps=(2.0, 2.6), rev=None, ni=None, eq=None):
    """C: CY2025Q3 vs CY2024Q3. A: CY2025 vs CY2024. rev = {frame: revenue}."""
    q = [{"ticker": t, "frame": "CY2024Q3", "eps": q_eps[0]}, {"ticker": t, "frame": "CY2025Q3", "eps": q_eps[1]}]
    if rev:
        frames = {r["frame"]: r for r in q}
        for fr, v in rev.items():
            frames.setdefault(fr, {"ticker": t, "frame": fr, "eps": np.nan})["revenue"] = v
        q = list(frames.values())
    a = [{"ticker": t, "frame": "CY2024", "eps": a_eps[0]}, {"ticker": t, "frame": "CY2025", "eps": a_eps[1],
                                                            "net_income": ni, "equity": eq}]
    return q, a


def _run(stocks, spy=None, qqq=None, rs=None, holders=None, cfg=None, strict=None):
    """stocks: {ticker: (close, volume, quarters_rows, annual_rows)}."""
    frames = {t: _ohlc(c, v) for t, (c, v, _q, _a) in stocks.items()}
    frames["SPY"] = _ohlc(_spy() if spy is None else spy, _flat_vol(1e8))
    if qqq is not None:
        frames["QQQ"] = _ohlc(qqq, _flat_vol(1e8))
    close = pd.DataFrame({t: f["close"] for t, f in frames.items()})
    high = pd.DataFrame({t: f["high"] for t, f in frames.items()})
    low = pd.DataFrame({t: f["low"] for t, f in frames.items()})
    vol = pd.DataFrame({t: f["volume"] for t, f in frames.items()})
    q = pd.DataFrame([r for (_c, _v, qq, _a) in stocks.values() for r in qq])
    a = pd.DataFrame([r for (_c, _v, _q, aa) in stocks.values() for r in aa])
    uni = pd.DataFrame([{"ticker": t, "company": t + " Co", "sector": "Industrials", "index_membership": "SP500"} for t in stocks])
    rs = rs if rs is not None else {t: 90 for t in stocks}
    hold = pd.DataFrame(holders or [], columns=["ticker", "inst_up", "inst_down", "ownership_pct"])
    out, market = setups.scan_canslim(close, high, low, vol, uni, q, a, hold, rs_map=rs, cfg=cfg, strict=strict)
    return out, market


def _stock(close=None, volume=None, **fund):
    q, a = _good_fund("X", **fund)
    return [close if close is not None else _climb(), volume if volume is not None else _flat_vol(), q, a]


def _named(name, rows):
    c, v, q, a = rows
    for r in q + a:
        r["ticker"] = name
    return (c, v, q, a)


def _tickers(out):
    return set(out["ticker"]) if len(out) else set()


def test_good_stock_passes_every_rule_and_keeps_old_columns():
    out, market = _run({"GOOD": _named("GOOD", _stock())})
    assert _tickers(out) == {"GOOD"}
    row = out.iloc[0]
    assert row["status"] == "READY"  # at a new high, but volume is not 1.5x
    assert row["qualify"] == "strict"
    assert row["c_quarterly_eps"] == 40.0 and row["a_annual_eps"] == 30.0
    assert row["stop"] == "" and row["target"] == ""
    assert "Trend check passed" in row["reason"]
    for col in OLD_COLS:
        assert col in tables.COLS["scanner_canslim"], col
    assert "rs_score" in tables.COLS["scanner_canslim"]
    assert set(out.columns) <= set(tables.COLS["scanner_canslim"]) | {"rs"}
    assert market["banner"] == ""


def test_c_quarterly_eps_is_required_at_25_percent():
    out, _ = _run({
        "OK25": _named("OK25", _stock(q_eps=(1.0, 1.25))),
        "LOW": _named("LOW", _stock(q_eps=(1.0, 1.2))),
        "NOQ": ([*_named("NOQ", _stock())[:2], [], _named("NOQ", _stock())[3]]),
    })
    assert _tickers(out) == {"OK25"}


def test_c_sales_checked_only_when_on_file():
    def rev(now, then, p_now=None, p_then=None):
        d = {"CY2025Q3": now, "CY2024Q3": then}
        if p_now is not None:
            d.update({"CY2025Q2": p_now, "CY2024Q2": p_then})
        return d
    out, _ = _run({
        "FAST": _named("FAST", _stock(rev=rev(130, 100))),                  # +30%
        "SLOW": _named("SLOW", _stock(rev=rev(110, 100, 120, 100))),        # +10%, was +20%: slowing
        "ACCEL": _named("ACCEL", _stock(rev=rev(110, 100, 105, 100))),      # +10%, was +5%: speeding up
        "ONLYONE": _named("ONLYONE", _stock(rev=rev(110, 100))),            # +10%, no prior quarter on file
        "NOSALES": _named("NOSALES", _stock()),
    })
    assert _tickers(out) == {"FAST", "ACCEL", "NOSALES"}
    by = out.set_index("ticker")
    assert "speeding up" in by.loc["ACCEL", "c_status"]
    assert "Sales not verified" in by.loc["NOSALES", "c_status"]
    assert "sales not verified" in by.loc["NOSALES", "note"]
    g, prior, now, then = setups._sales_check(pd.DataFrame(_good_fund("Z", rev=rev(130, 100, 105, 100))[0]), "Z")
    assert round(g, 6) == 30.0 and round(prior, 6) == 5.0 and now == 130 and then == 100


def test_a_annual_eps_required_and_roe_only_when_on_file():
    out, _ = _run({
        "LOWA": _named("LOWA", _stock(a_eps=(2.0, 2.4))),               # +20%
        "NOA": (_climb(), _flat_vol(), _good_fund("NOA")[0], []),
        "HIROE": _named("HIROE", _stock(ni=20.0, eq=100.0)),            # 20%
        "LOWROE": _named("LOWROE", _stock(ni=10.0, eq=100.0)),          # 10%
        "NOROE": _named("NOROE", _stock()),
        "NEGEQ": _named("NEGEQ", _stock(ni=10.0, eq=-50.0)),            # ROE has no meaning
    })
    assert _tickers(out) == {"HIROE", "NOROE", "NEGEQ"}
    by = out.set_index("ticker")
    assert "ROE 20.0%" in by.loc["HIROE", "a_status"]
    assert "ROE not verified" in by.loc["NOROE", "a_status"]
    assert "ROE not verified" in by.loc["NEGEQ", "note"]
    assert setups._roe_check(pd.DataFrame(_good_fund("Z", ni=17.0, eq=100.0)[1]), "Z") == 17.0


def test_n_within_15_percent_of_the_high():
    def drop(pct):
        c = _climb(0.01, 5.0)
        c[-3:] = c[-4] * (1 - pct)
        return c
    out, _ = _run({"NEAR": _named("NEAR", _stock(close=drop(0.14))), "FAR": _named("FAR", _stock(close=drop(0.17)))})
    assert _tickers(out) == {"NEAR"}
    assert out.iloc[0]["status"] == "WATCHING"  # more than 5% off the high


def test_s_volume_floor_breakout_and_accumulation():
    big = _flat_vol()
    big[-1] = 1_600_000  # 1.6x the 50-day average on a new high
    up_v = np.where(np.arange(N) % 2 == 1, 600_000.0, 1_500_000.0)  # heavy volume on the down days
    out, _ = _run({
        "BRK": _named("BRK", _stock(volume=big)),
        "THIN": _named("THIN", _stock(volume=_flat_vol(150_000))),
        "DIST": _named("DIST", _stock(close=_zigzag(), volume=up_v)),
        # Same prices as DIST, heavy volume on the up days instead: only accumulation differs.
        "ACC": _named("ACC", _stock(close=_zigzag(), volume=np.where(np.arange(N) % 2 == 1, 1_500_000.0, 600_000.0))),
    })
    assert _tickers(out) == {"BRK", "ACC"}
    by = out.set_index("ticker")
    assert by.loc["BRK", "status"] == "BROKEN OUT today"
    assert "accumulation" in by.loc["ACC", "s_status"]
    ratio, up, down = setups._accumulation(pd.Series(_zigzag()), pd.Series(np.where(np.arange(N) % 2 == 1, 1_500_000.0, 600_000.0)), 50)
    assert round(ratio, 6) == 2.5 and up == 25 * 1_500_000 and down == 25 * 600_000


def test_s_accumulation_missing_volume_is_not_a_fail():
    v = np.full(N, np.nan)
    v[-20:] = 1_000_000  # enough for the 20-day floor, not for 50 sessions
    out, _ = _run({"SHORTVOL": _named("SHORTVOL", _stock(volume=v))})
    assert _tickers(out) == {"SHORTVOL"}
    assert "Accumulation (up-day vs down-day volume) not verified" in out.iloc[0]["s_status"]
    assert "accumulation not verified" in out.iloc[0]["note"]
    assert setups._accumulation(pd.Series(_climb()), pd.Series(v), 50) == (None, None, None)


def test_l_rs_rating_80_and_rank_by_rs_score():
    out, _ = _run({
        "R79": _named("R79", _stock()),
        "R80": _named("R80", _stock(close=_climb(0.002))),
        "FASTER": _named("FASTER", _stock(close=_climb(0.004))),
        "NORS": _named("NORS", _stock()),
    }, rs={"R79": 79, "R80": 80, "FASTER": 85})
    assert list(out["ticker"]) == ["FASTER", "R80"]
    row = out.set_index("ticker").loc["R80"]
    c = pd.Series(_climb(0.002))
    s = pd.Series(_spy())
    rs6 = (c.iloc[-1] / c.iloc[-127] - s.iloc[-1] / s.iloc[-127]) * 100
    rs3 = (c.iloc[-1] / c.iloc[-64] - s.iloc[-1] / s.iloc[-64]) * 100
    assert abs(float(row["rs_score"]) - round(0.6 * rs6 + 0.4 * rs3, 1)) < 1e-9
    assert "RS score" in row["l_status"]


def test_i_holders_flat_or_rising_and_missing_is_not_a_fail():
    out, _ = _run({
        "UP": _named("UP", _stock()), "FLAT": _named("FLAT", _stock()),
        "DOWN": _named("DOWN", _stock()), "NOI": _named("NOI", _stock()),
    }, holders=[
        {"ticker": "UP", "inst_up": 10, "inst_down": 2, "ownership_pct": 60},
        {"ticker": "FLAT", "inst_up": 5, "inst_down": 5, "ownership_pct": 60},
        {"ticker": "DOWN", "inst_up": 2, "inst_down": 10, "ownership_pct": 60},
    ])
    assert _tickers(out) == {"UP", "FLAT", "NOI"}
    by = out.set_index("ticker")
    assert by.loc["FLAT", "i_trend"] == "flat"
    assert by.loc["NOI", "i_trend"] == "not verified"
    assert "I not verified" in by.loc["NOI", "note"]


def test_light_trend_check():
    dip = _climb(0.002)
    dip[-8:] = dip[-9] * 0.93  # under the 50-day, still within 15% of the high
    base = np.concatenate([np.full(100, 60.0), np.full(150, 95.0), np.full(40, 80.0), np.linspace(82, 96, N - 290)])
    out, _ = _run({"DIP": _named("DIP", _stock(close=dip)), "CROSS": _named("CROSS", _stock(close=base)),
                   "OK": _named("OK", _stock())})
    s50 = pd.Series(base).iloc[-50:].mean()
    s200 = pd.Series(base).iloc[-200:].mean()
    assert s50 < s200 < base[-1]  # CROSS: above both averages, but the 50-day is still under the 200-day
    assert _tickers(out) == {"OK"}


def test_market_correction_shows_banner_but_never_blocks_ready():
    stocks = {"GOOD": _named("GOOD", _stock())}
    out, market = _run(stocks, spy=_falling())
    assert _tickers(out) == {"GOOD"} and out.iloc[0]["status"] == "READY"
    assert market["correction"] == "SPY"
    assert "Market in correction: SPY" in market["banner"] and "warning only" in market["banner"]
    assert "Market in correction" in out.iloc[0]["m_status"]
    assert out.iloc[0]["m_spy"].startswith("CORRECTION")
    _out, m2 = _run(stocks, qqq=_falling(300))
    assert m2["correction"] == "QQQ" and "QQQ" in m2["banner"]
    _out, m3 = _run(stocks, spy=_falling(), qqq=_falling(300))
    assert m3["correction"] == "SPY and QQQ"
    _out, m4 = _run(stocks, qqq=_spy())
    assert m4["correction"] == "" and m4["banner"] == ""
    assert setups.canslim_market_correction({}) == ""


def test_soft_tier_is_gone_and_old_screen_is_behind_the_switch():
    # RS 50 and no EPS: the old screen listed it as a soft or strict name. The strict one does not.
    stocks = {"OLD": (_climb(), _flat_vol(), [], [])}
    out, _ = _run(stocks, rs={"OLD": 50})
    assert len(out) == 0
    legacy, _ = _run(stocks, rs={"OLD": 50}, strict=False)
    assert list(legacy["qualify"]) == ["soft"]
    legacy2, _ = _run(stocks, rs={"OLD": 50}, cfg={"features": {"canslim_strict": False}})
    assert list(legacy2["qualify"]) == ["soft"]
    good, _ = _run({"GOOD": _named("GOOD", _stock())})
    assert set(good["qualify"]) == {"strict"}


def test_build_setups_passes_the_switch():
    frames = {"GOOD": _ohlc(_climb(), _flat_vol()), "SPY": _ohlc(_spy(), _flat_vol(1e8))}
    close = pd.DataFrame({t: f["close"] for t, f in frames.items()})
    high = pd.DataFrame({t: f["high"] for t, f in frames.items()})
    low = pd.DataFrame({t: f["low"] for t, f in frames.items()})
    vol = pd.DataFrame({t: f["volume"] for t, f in frames.items()})
    uni = pd.DataFrame([{"ticker": "GOOD", "company": "G", "sector": "", "index_membership": ""}])
    off = {k: False for k in ("scanner_vcp", "scanner_box", "scanner_flag", "scanner_leaders", "scanner_52w", "scanner_breakdown",
                              "scanner_volume", "scanner_qullamaggie", "scanner_marios", "scorecard_canslim")}
    empty = pd.DataFrame()
    strict = setups.build_setups(close, high, low, vol, uni, empty, empty, empty, dict(off, scanner_canslim=True), rs_map={"GOOD": 60})
    assert len(strict["scanner_canslim"]) == 0  # no EPS and RS 60
    legacy = setups.build_setups(close, high, low, vol, uni, empty, empty, empty,
                                 dict(off, scanner_canslim=True, canslim_strict=False), rs_map={"GOOD": 60})
    assert list(legacy["scanner_canslim"]["ticker"]) == ["GOOD"]


def test_config_block_and_switches():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    assert cfg["features"]["canslim_strict"] is True
    assert cfg["features"]["canslim_market_banner"] is True
    block = cfg["canslim"]
    for k, v in setups.CANSLIM_DEFAULTS.items():
        assert float(block[k]) == float(v), k
    assert block["l_rs_min"] == 80 and block["a_roe_min"] == 17 and block["s_accum_sessions"] == 50
    assert "not verified" in block["_note"]
    # A config line moves the screen: RS 75 passes at l_rs_min 70, not at the default 80.
    stocks = {"GOOD": _named("GOOD", _stock())}
    assert len(_run(stocks, rs={"GOOD": 75})[0]) == 0
    assert len(_run(stocks, rs={"GOOD": 75}, cfg={"canslim": {"l_rs_min": 70}})[0]) == 1
    assert setups.canslim_settings({"canslim": {"l_rs_min": "bad"}})["l_rs_min"] == 80.0


def test_missing_values_stay_blank_never_filled():
    out, _ = _run({"GOOD": _named("GOOD", _stock())})
    row = out.iloc[0]
    # No sales, ROE or 13F: blank or not verified, never a made-up number.
    assert "Sales not verified" in row["c_status"]
    assert "ROE not verified" in row["a_status"]
    assert row["i_trend"] == "not verified"
    blob = out.to_csv(index=False)
    assert "nan" not in blob.lower().replace("financ", "")


def test_page_banner_wiring_and_light_theme_classes():
    pages = open(os.path.join(ROOT, "site", "js", "pages.js")).read()
    assert 'D.featureOn("feature.canslim_market_banner")' in pages
    assert "strip: canslimBanner" in pages
    assert 'sort2: "rs_score"' in pages
    assert 'T("rs_score", "RS score vs SPY"' in pages
    assert 'class="banner canslim-banner"' in pages  # the shared .banner style, which follows the light theme
    css = open(os.path.join(ROOT, "site", "css", "desk.css")).read()
    assert ".banner{" in css


def test_page_banner_logic_in_node():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        return
    src = open(os.path.join(ROOT, "site", "js", "pages.js")).read()
    start = src.index("  function canslimCorrection(all)")
    end = src.index("  const canslim = patternPage(")
    code = src[start:end]
    js = (
        "let ON = true; const D = { featureOn: () => ON, esc: (s) => String(s) };\n" + code +
        "\nconst out = [];\n"
        "out.push(canslimBanner([{ m_spy: 'CORRECTION risk (below EMA200)', m_qqq: 'MIXED / x' }]));\n"
        "out.push(canslimBanner([{ m_spy: 'MIXED / x', m_qqq: 'CORRECTION risk (below EMA200)' }]));\n"
        "out.push(canslimBanner([{ m_spy: 'CONFIRMATION / y', m_qqq: 'MIXED / x' }]));\n"
        "out.push(canslimBanner([]));\n"
        "ON = false; out.push(canslimBanner([{ m_spy: 'CORRECTION risk (below EMA200)' }]));\n"
        "console.log(JSON.stringify(out));\n"
    )
    res = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True)
    got = json.loads(res.stdout)
    assert "Market in correction" in got[0] and "SPY" in got[0]
    assert "QQQ" in got[1] and "SPY" not in got[1].replace("SPY and", "")
    assert got[2] == "" and got[3] == "" and got[4] == ""


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("canslim strict ok")
