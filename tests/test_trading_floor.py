"""Offline checks for the Trading Floor. Fixed dates and synthetic bars: no clock, no downloads."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tables  # noqa: E402
import trading_floor as tf  # noqa: E402

ASOF = "2026-03-20"
P = tf.config({})


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _stats(**kw):
    base = {"price": 100.0, "prev": 99.0, "day_pct": 1.0, "ma10": 99.0, "ma20": 98.0, "ma50": 95.0,
            "pct_above_ma10": 1.0, "pct_above_ma20": 2.0, "pct_above_ma50": 5.0, "run_pct": 2.0, "up_streak": 1,
            "gap_pct": 0.2, "volume_ratio": 1.0, "volume_streak": 0, "price_as_of": ASOF}
    base.update(kw)
    return base


def _pick(**kw):
    base = {"ticker": "AAA", "company": "Acme Rockets", "entry": 100.0, "stop": 93.0, "target1": 120.0,
            "risk_pct": 7.0, "reward_risk": 2.86, "market_ok": "yes", "pick_source": "Buy setups"}
    base.update(kw)
    return base


def _p(**blocks):
    p = tf.config({})
    for block, values in blocks.items():
        p[block].update(values)
    return p


# ---------------------------------------------------------------- config, settings, help, wiring
def test_config_block_matches_defaults_and_feature_switch():
    cfg = _cfg()
    assert cfg["features"]["trading_floor"] is True
    block = {k: v for k, v in cfg["trading_floor"].items() if not k.startswith("_")}
    assert block == tf.DEFAULTS
    assert 12 <= cfg["trading_floor"]["max_stocks"] <= 15
    assert tables.COLS["trading_floor"] == tf.COLS


def test_settings_and_help_rows():
    cfg = _cfg()
    got = dict(zip(tables.settings_rows(cfg)["setting"], tables.settings_rows(cfg)["value"]))
    assert got["feature.trading_floor"] is True
    assert got["trading_floor.max_stocks"] == 15
    for block in ("news", "scout", "charts", "skeptic", "sentiment", "verdict"):
        for key, value in tf.DEFAULTS[block].items():
            assert got["trading_floor.%s.%s" % (block, key)] == value, (block, key)
    topics = dict(tables.help_rows())
    for t in ("Trading Floor", "Trading Floor scoring", "Trading Floor headlines", "Trading Floor settings"):
        assert t in topics, t
    assert "never places an order" in topics["Trading Floor"]


def test_page_menu_and_switch_wiring():
    sys.path.insert(0, os.path.join(ROOT, "site"))
    import build_pages
    assert ("trading-floor.html", "tradingfloor", "Trading Floor") in build_pages.PAGES
    desk = open(os.path.join(ROOT, "site", "js", "desk.js"), encoding="utf-8").read()
    pages = open(os.path.join(ROOT, "site", "js", "pages.js"), encoding="utf-8").read()
    assert '["Trading Floor", "trading-floor.html", "tradingfloor"]' in desk
    assert 'tradingfloor: "feature.trading_floor"' in desk
    assert 'tradingfloor: { files: ["trading_floor.csv"], render: renderTradingFloor }' in pages
    assert "tradingfloor: \"A short desk debate" in pages
    # A summary page: not a screener, so it stays out of the Technical / Fundamental split.
    assert "tradingfloor" not in _cfg()["scanner_groups"]
    src = open(os.path.join(ROOT, "stock_desk.py"), encoding="utf-8").read()
    assert 'features.get("trading_floor", True)' in src
    assert '"trading_floor": gated(floor, "trading_floor", floor_on' in src
    wf = open(os.path.join(ROOT, ".github", "workflows", "update.yml"), encoding="utf-8").read()
    assert "python tests/test_trading_floor.py" in wf


def test_no_yahoo_and_no_orders_in_module():
    src = open(os.path.join(ROOT, "trading_floor.py"), encoding="utf-8").read().lower()
    assert "yahoo.com" not in src and "yfinance" not in src
    for word in ("place_order", "submit_order", "broker.", "smtp", "webhook", "send_alert"):
        assert word not in src, word


# ---------------------------------------------------------------- picks
def test_pick_stocks_cap_order_and_fill():
    buy = pd.DataFrame([{"ticker": "B%d" % i, "company": "Co %d" % i, "entry": 10.0, "stop": 9.3, "target1": 12.0,
                         "risk_pct": 7.0, "reward_risk": 2.86, "market_ok": "yes", "best_status": "READY"} for i in range(20)])
    picks = tf.pick_stocks(buy, {}, None, _p())
    assert [x["ticker"] for x in picks] == ["B%d" % i for i in range(15)]
    p = tf.config({"trading_floor": {"max_stocks": 12}})
    assert len(tf.pick_stocks(buy, {}, None, p)) == 12
    # Short Buy setups list: fill with stocks READY on 2+ pattern scanners. One scanner is not enough.
    small = buy.head(1)
    rec = lambda t, st="READY": {"ticker": t, "status": st, "pivot": 50.0, "stop": 47.0, "strength": 3, "price": 49.0,
                                 "company": t + " Co", "sector": "Tech", "index_membership": "SP500", "price_as_of": ASOF}
    frames = {"scanner_vcp": pd.DataFrame([rec("XX"), rec("YY"), rec("B0")]),
              "scanner_box": pd.DataFrame([rec("XX", "BROKEN OUT today")]),
              "scanner_canslim": pd.DataFrame([rec("ZZ")])}
    got = tf.pick_stocks(small, frames, None, _p())
    assert [x["ticker"] for x in got] == ["B0", "XX"]
    assert got[1]["pick_source"] == "Cross-scanner" and got[1]["setup_sources"] == "VCP + Box"
    assert got[1]["stop"] is not None and got[1]["target1"] is not None
    off = tf.config({"trading_floor": {"fill_from_scanners": False}})
    assert [x["ticker"] for x in tf.pick_stocks(small, frames, None, off)] == ["B0"]


# ---------------------------------------------------------------- price facts (fixed dates)
def _panel(closes, vols, opens=None):
    idx = pd.bdate_range("2026-01-02", periods=len(closes))
    c = pd.DataFrame({"AAA": closes}, index=idx)
    v = pd.DataFrame({"AAA": vols}, index=idx)
    o = pd.DataFrame({"AAA": opens if opens is not None else closes}, index=idx)
    return c, o, v


def test_price_stats_volume_ratio_streak_gap():
    closes = [100.0] * 60 + [101.0, 102.0, 103.0]
    vols = [1_000_000.0] * 60 + [1_200_000.0, 1_300_000.0, 2_000_000.0]
    opens = closes[:-1] + [108.0]
    c, o, v = _panel(closes, vols, opens)
    st = tf.price_stats("AAA", c, o, v)
    assert abs(st["volume_ratio"] - 2_000_000.0 / np.mean(vols[-51:-1])) < 1e-9
    assert st["volume_streak"] == 3
    assert st["up_streak"] == 3
    assert abs(st["gap_pct"] - (108.0 / 102.0 - 1) * 100) < 1e-9
    assert abs(st["run_pct"] - (103.0 / 100.0 - 1) * 100) < 1e-9
    assert st["price_as_of"] == str(c.index[-1].date())
    assert tf.price_stats("ZZZ", c, o, v)["price"] is None


# ---------------------------------------------------------------- News
def test_news_role():
    p = _p()
    assert tf.role_news([], p) == (0, "No fresh headlines found.")
    up = [{"headline": "Acme Rockets beats estimates and raises guidance", "publisher": "Wire", "link": "", "published": ASOF}]
    down = [{"headline": "Acme Rockets faces probe over accounts", "publisher": "Wire", "link": "", "published": ASOF}]
    flat = [{"headline": "Acme Rockets to present at conference", "publisher": "Wire", "link": "", "published": ASOF}]
    assert tf.role_news(up, p)[0] == 1 and "Acme Rockets beats" in tf.role_news(up, p)[1]
    assert tf.role_news(down, p)[0] == -1
    assert tf.role_news(flat, p)[0] == 0
    # The line quotes the headline that drives the vote, even when it is not the newest.
    pts, line = tf.role_news(flat + down, p)
    assert pts == -1 and "faces probe" in line and tf.lead_headline(flat + down) is down[0]
    assert tf.role_news(up, _p(news={"on": False}))[0] == 0


def test_headlines_fresh_window_name_match_and_desk_first():
    desk = pd.DataFrame([
        {"ticker": "AAA", "headline": "Acme Rockets wins contract", "publisher": "A", "link": "x", "published": "2026-03-19 10:00 PT"},
        {"ticker": "AAA", "headline": "Why Other Corp fell today", "publisher": "B", "link": "y", "published": "2026-03-19 11:00 PT"},
        {"ticker": "AAA", "headline": "AAA old news", "publisher": "C", "link": "z", "published": "2026-03-10 09:00 PT"},
    ])
    google = pd.DataFrame([{"ticker": "AAA", "headline": "Acme Rockets on the move", "publisher": "G", "link": "g",
                            "published": "2026-03-20 08:00 PT", "fetched": ASOF}])
    heads, src = tf.headlines_for("AAA", "Acme Rockets", desk, google, ASOF, _p())
    assert src == "desk" and [h["headline"] for h in heads] == ["Acme Rockets wins contract"]
    # No usable desk headline: the Google News cache is used.
    heads, src = tf.headlines_for("AAA", "Acme Rockets", desk.iloc[1:], google, ASOF, _p())
    assert src == "google" and heads[0]["headline"] == "Acme Rockets on the move"
    # Name check off lets the unrelated desk headline through.
    heads, _ = tf.headlines_for("AAA", "Acme Rockets", desk.iloc[1:], None, ASOF, _p(news={"name_match": False}))
    assert [h["headline"] for h in heads] == ["Why Other Corp fell today"]
    assert tf.headlines_for("AAA", "Acme Rockets", None, None, ASOF, _p()) == ([], "")


def test_google_rss_parse_and_soft_failure():
    xml = """<?xml version="1.0"?><rss><channel>
      <item><title>Acme Rockets jumps on record orders - Big Wire</title><link>https://n/1</link>
        <pubDate>Fri, 20 Mar 2026 15:00:00 GMT</pubDate><source url="https://w">Big Wire</source></item>
      <item><title>Second &amp; story - Other</title><link>https://n/2</link>
        <pubDate>Thu, 19 Mar 2026 15:00:00 GMT</pubDate><source url="https://o">Other</source></item>
    </channel></rss>"""
    rows = tf.parse_rss(xml, "AAA", ASOF, limit=5)
    assert rows[0]["headline"] == "Acme Rockets jumps on record orders" and rows[0]["publisher"] == "Big Wire"
    assert rows[0]["published"] == "2026-03-20 08:00 PT"
    assert rows[1]["headline"] == "Second & story"
    assert tf.parse_rss("not xml", "AAA", ASOF) == []
    junk = xml.replace("Second &amp; story - Other", "Acme Rockets, Inc. (AAA) Stock Price, News, Quote &amp; History - Other")
    assert [r["headline"] for r in tf.parse_rss(junk, "AAA", ASOF)] == ["Acme Rockets jumps on record orders"]

    class R:
        def __init__(self, code, text=""):
            self.status_code, self.text = code, text
    calls = []

    def get(url, params, timeout):
        calls.append(params["q"])
        if "BBB" in params["q"]:
            raise OSError("down")
        if "CCC" in params["q"]:
            return R(503)
        return R(200, xml)
    picks = [{"ticker": "AAA", "company": "Acme Rockets"}, {"ticker": "BBB", "company": ""}, {"ticker": "CCC", "company": ""}]
    got, failed = tf.fetch_google_news(picks, _p(), ASOF, get=get)
    assert len(calls) == 3  # one request per pick, no retries
    assert failed == ["BBB", "CCC"] and {r["ticker"] for r in got} == {"AAA"}
    assert '"Acme Rockets" OR AAA stock when:3d' == calls[0]


def test_news_cache_merge_drops_old_rows():
    old = pd.DataFrame([
        {"ticker": "AAA", "headline": "old a", "publisher": "", "link": "", "published": "", "fetched": "2026-03-19"},
        {"ticker": "BBB", "headline": "keep b", "publisher": "", "link": "", "published": "", "fetched": "2026-03-19"},
        {"ticker": "CCC", "headline": "stale c", "publisher": "", "link": "", "published": "", "fetched": "2026-02-01"},
    ])
    new = [{"ticker": "AAA", "headline": "new a", "publisher": "", "link": "", "published": "", "fetched": ASOF}]
    out = tf.merge_news_cache(old, new, ["AAA"], ASOF, 14)
    assert sorted(out["headline"]) == ["keep b", "new a"]


# ---------------------------------------------------------------- Scout
def test_scout_role():
    p = _p()
    assert tf.role_scout(_stats(volume_ratio=2.0, day_pct=1.5), p)[0] == 1
    assert tf.role_scout(_stats(volume_ratio=2.0, day_pct=-1.5), p)[0] == -1
    assert tf.role_scout(_stats(volume_ratio=0.5), p)[0] == -1
    assert tf.role_scout(_stats(volume_ratio=1.1, volume_streak=3), p)[0] == 1
    assert tf.role_scout(_stats(volume_ratio=1.1, volume_streak=3), _p(scout={"streak_check": False}))[0] == 0
    assert tf.role_scout(_stats(volume_ratio=1.0), p)[0] == 0
    assert tf.role_scout(_stats(volume_ratio=None), p)[0] == 0
    # Edge: exactly hot_ratio counts; exactly thin_ratio does not.
    assert tf.role_scout(_stats(volume_ratio=1.5, day_pct=0.1), p)[0] == 1
    assert tf.role_scout(_stats(volume_ratio=0.7), p)[0] == 0


# ---------------------------------------------------------------- Charts
def test_charts_role_and_veto():
    p = _p()
    pts, line, veto = tf.role_charts(_pick(), _stats(), p)
    assert (pts, veto) == (1, False) and "Entry 100.00, stop 93.00" in line
    assert tf.role_charts(_pick(reward_risk=1.5), _stats(), p)[:3:2] == (0, False)
    assert tf.role_charts(_pick(risk_pct=9.0), _stats(), p)[0] == 0
    for bad in (_pick(entry=None), _pick(stop=None), _pick(target1=None), _pick(stop=101.0), _pick(target1=99.0)):
        pts, line, veto = tf.role_charts(bad, _stats(), p)
        assert (pts, veto) == (-1, True) and "Veto" in line
    assert tf.role_charts(_pick(), _stats(price=92.0), p)[2] is True
    assert tf.role_charts(_pick(), _stats(price=92.0), _p(charts={"veto_below_stop": False}))[2] is False


# ---------------------------------------------------------------- Skeptic
def test_skeptic_role():
    p = _p()
    pts, line, hard, objs = tf.role_skeptic(_pick(), _stats(), 2, "", ASOF, p)
    assert (pts, hard, objs) == (1, False, []) and line == "Nothing serious against it."
    pts, line, hard, objs = tf.role_skeptic(_pick(), _stats(), 0, "", ASOF, p)
    assert (pts, hard) == (0, False) and objs == ["no fresh news to explain a move"]
    pts, _, hard, objs = tf.role_skeptic(_pick(market_ok="no"), _stats(volume_ratio=0.5), 2, "", ASOF, p)
    assert (pts, hard, len(objs)) == (-1, False, 2)
    # Three objections is a hard no.
    pts, line, hard, objs = tf.role_skeptic(_pick(market_ok="no"), _stats(volume_ratio=0.5), 0, "", ASOF, p)
    assert (pts, hard, len(objs)) == (-1, True, 3) and line.endswith("Hard no.")
    # Stretched over MA20, then over MA50 alone.
    assert "20-day" in tf.role_skeptic(_pick(), _stats(pct_above_ma20=10.0), 2, "", ASOF, p)[3][0]
    assert "50-day" in tf.role_skeptic(_pick(), _stats(pct_above_ma50=25.0), 2, "", ASOF, p)[3][0]
    # Over the entry: 5% is an objection, 10% is a hard no on its own.
    _, _, hard, objs = tf.role_skeptic(_pick(), _stats(price=105.0), 2, "", ASOF, p)
    assert hard is False and "chasing" in objs[0]
    assert tf.role_skeptic(_pick(), _stats(price=110.0), 2, "", ASOF, p)[2] is True
    # Earnings within 7 days of the as-of date (fixed dates, no clock).
    assert tf.role_skeptic(_pick(), _stats(), 2, "2026-03-27", ASOF, p)[3] == ["earnings on 2026-03-27"]
    assert tf.role_skeptic(_pick(), _stats(), 2, "2026-03-28", ASOF, p)[3] == []
    assert tf.role_skeptic(_pick(), _stats(), 2, "2026-03-19", ASOF, p)[3] == []
    # Each check has its own switch.
    quiet = _p(skeptic={"no_news_check": False, "market_check": False, "thin_volume_check": False})
    assert tf.role_skeptic(_pick(market_ok="no"), _stats(volume_ratio=0.5), 0, "", ASOF, quiet)[0] == 1
    assert tf.role_skeptic(_pick(), _stats(), 0, "", ASOF, _p(skeptic={"on": False}))[:3] == (0, "Off in Settings.", False)


# ---------------------------------------------------------------- Sentiment
def test_sentiment_role():
    p = _p()
    assert tf.role_sentiment(_stats(), 1, p)[0] == 1
    assert tf.role_sentiment(_stats(run_pct=16.0), 1, p)[0] == 0
    pts, line = tf.role_sentiment(_stats(run_pct=16.0, pct_above_ma10=9.0), 1, p)
    assert pts == -1 and "too hot" in line
    assert tf.role_sentiment(_stats(gap_pct=6.0, up_streak=6), 1, p)[0] == -1
    assert tf.role_sentiment(_stats(pct_above_ma20=12.0), 1, p)[0] == 0
    assert tf.role_sentiment(_stats(), 5, p)[0] == 0  # headline buzz
    assert tf.role_sentiment(_stats(), 5, _p(sentiment={"buzz_check": False}))[0] == 1
    assert tf.role_sentiment(_stats(gap_pct=6.0), 1, _p(sentiment={"gap_check": False}))[0] == 1


# ---------------------------------------------------------------- Chief and the cutoffs
def test_chief_cutoffs():
    p = _p()
    votes = lambda *v: dict(zip(tf.ROLES, v))
    assert tf.chief(votes(1, 1, 0, 0, 0), False, False, p)[:2] == ("BUY", 2)
    assert tf.chief(votes(1, 1, 1, 1, 1), False, False, p)[:2] == ("BUY", 5)
    assert tf.chief(votes(1, 0, 0, 0, 0), False, False, p)[:2] == ("WAIT", 1)
    assert tf.chief(votes(0, 0, 0, 0, 0), False, False, p)[:2] == ("WAIT", 0)
    assert tf.chief(votes(-1, 0, 0, 0, 0), False, False, p)[:2] == ("SKIP", -1)
    # A hard no keeps a +2 or better at WAIT.
    v, total, line = tf.chief(votes(1, 1, 1, -1, 1), False, True, p)
    assert (v, total) == ("WAIT", 3) and "hard no" in line
    # A Charts veto is always SKIP.
    assert tf.chief(votes(1, 1, -1, 1, 1), True, False, p)[0] == "SKIP"
    # Cutoffs come from config.
    strict = _p(verdict={"buy_min_total": 3, "wait_min_total": 1})
    assert tf.chief(votes(1, 1, 0, 0, 0), False, False, strict)[0] == "WAIT"
    assert tf.chief(votes(0, 0, 0, 0, 0), False, False, strict)[0] == "SKIP"


def test_build_floor_end_to_end_and_counts():
    n = 70
    idx = pd.bdate_range("2026-01-02", periods=n)
    calm = [100.0 + 0.05 * i for i in range(n)]
    hot = [100.0] * (n - 5) + [104.0, 108.0, 113.0, 118.0, 124.0]
    close = pd.DataFrame({"AAA": calm, "HOT": hot}, index=idx)
    opn = close.copy()
    vol = pd.DataFrame({"AAA": [1e6] * (n - 1) + [2e6], "HOT": [1e6] * n}, index=idx)
    asof = str(idx[-1].date())
    last = calm[-1]
    picks = [
        _pick(ticker="AAA", entry=last * 1.01, stop=last * 0.94, target1=last * 1.2, risk_pct=7.0, reward_risk=2.9),
        _pick(ticker="HOT", company="Hot Stuff", entry=110.0, stop=102.3, target1=132.0, risk_pct=7.0, reward_risk=2.9),
        _pick(ticker="NOL", company="No Levels", entry=None, stop=None, target1=None),
    ]
    news = pd.DataFrame([{"ticker": "AAA", "headline": "Acme Rockets wins record order", "publisher": "W", "link": "https://x",
                          "published": asof + " 09:00 PT"}])
    out = tf.build_floor(picks, close, opn, vol, news, None, asof, {})
    by = out.set_index("ticker")
    assert by.loc["AAA", "verdict"] == "BUY" and by.loc["AAA", "headline_source"] == "Desk headlines"
    assert by.loc["HOT", "sentiment_pts"] == -1 and by.loc["HOT", "skeptic_hard_no"] == "yes"
    assert by.loc["NOL", "verdict"] == "SKIP" and by.loc["NOL", "charts_veto"] == "yes"
    assert by.loc["NOL", "news_line"] == "No fresh headlines found."
    assert list(out["verdict"]) == sorted(out["verdict"], key=["BUY", "WAIT", "SKIP"].index)
    for r in ("news", "scout", "charts", "skeptic", "sentiment"):
        assert set(out[r + "_pts"]) <= {-1, 0, 1}
    assert (out["total"] == out[[r + "_pts" for r in tf.ROLES]].sum(axis=1)).all()
    assert tf.counts(out) == {"BUY": 1, "WAIT": int((out["verdict"] == "WAIT").sum()), "SKIP": int((out["verdict"] == "SKIP").sum())}
    assert set(out.columns) == set(tf.COLS) - {"disclaimer"}
    assert tf.counts(pd.DataFrame()) == {"BUY": 0, "WAIT": 0, "SKIP": 0}


def test_switch_off_writes_an_empty_file():
    import stock_desk
    df = stock_desk.gated(pd.DataFrame([{"ticker": "AAA"}]), "trading_floor", False, "x")
    assert len(df) == 0 and list(df.columns) == tables.COLS["trading_floor"]


def test_company_name_cleanup_and_name_match():
    assert tf.clean_name("Lilly (Eli)") == "Eli Lilly"
    assert tf.clean_name("Walt Disney Company (The)") == "Walt Disney"
    assert tf.clean_name("Alphabet Inc. (Class A)") == "Alphabet"
    assert tf.clean_name("JPMorgan Chase & Co.") == "JPMorgan Chase"
    assert tf.mentions("Disney beats on parks", "DIS", "Walt Disney Company (The)")
    assert tf.mentions("Why DIS outpaced the market", "DIS", "")
    assert not tf.mentions("Health stocks slide", "CAH", "Cardinal Health")
    assert not tf.mentions("DISH rallies", "DIS", "")
    assert tf.google_query("LLY", "Lilly (Eli)", 3) == '"Eli Lilly" OR LLY stock when:3d'


if __name__ == "__main__":
    names = sorted(k for k, v in list(globals().items()) if k.startswith("test_") and callable(v))
    for name in names:
        globals()[name]()
    print("trading floor ok (%d tests)" % len(names))
