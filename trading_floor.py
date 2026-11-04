"""Trading Floor: six desk roles talk through today's top picks.

Research only. It never places a trade, never calls a broker, and sends no alerts.

Inputs are things the desk already has: the Buy setups list (or the top cross-scanner
picks when that list is short), the cached daily bars (close, open, volume), the
headlines the desk already stores, and one small cache of free Google News RSS
headlines. No Yahoo request is added here.

Every role gives +1, 0, or -1. The Chief adds them up:
    Charts veto (no valid levels)            -> SKIP
    total >= buy_min_total and no hard no     -> BUY
    total >= wait_min_total                   -> WAIT
    otherwise                                 -> SKIP
Every number lives in the trading_floor block of config.json. The rules are written
out in plain words in docs/trading_floor_rules.md.
"""
import copy
import datetime as dt
import html
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

import setups

PT = "America/Los_Angeles"

DEFAULTS = {
    "max_stocks": 15,
    "fill_from_scanners": True,
    "fill_min_scanners": 2,
    "news": {
        "on": True,
        "fresh_days": 3,
        "max_headlines": 5,
        "name_match": True,
        "google_news": True,
        "google_per_second": 1,
        "google_timeout_s": 15,
        "keep_days": 14,
    },
    "scout": {
        "on": True,
        "avg_days": 50,
        "hot_ratio": 1.5,
        "thin_ratio": 0.7,
        "streak_check": True,
        "streak_days": 3,
    },
    "charts": {
        "on": True,
        "min_reward_risk": 2.0,
        "max_risk_pct": 8.0,
        "veto_below_stop": True,
    },
    "skeptic": {
        "on": True,
        "no_news_check": True,
        "thin_volume_check": True,
        "thin_volume_ratio": 0.8,
        "extended_ma_check": True,
        "max_above_ma20_pct": 10.0,
        "max_above_ma50_pct": 25.0,
        "extended_entry_check": True,
        "max_above_entry_pct": 5.0,
        "market_check": True,
        "earnings_check": True,
        "earnings_days": 7,
        "hard_no_objections": 3,
        "hard_no_above_entry_pct": 10.0,
    },
    "sentiment": {
        "on": True,
        "run_check": True,
        "run_days": 5,
        "run_pct": 15.0,
        "ma10_check": True,
        "max_above_ma10_pct": 8.0,
        "ma20_check": True,
        "max_above_ma20_pct": 12.0,
        "gap_check": True,
        "gap_pct": 5.0,
        "streak_check": True,
        "up_streak_days": 6,
        "buzz_check": True,
        "buzz_headlines": 5,
        "hot_flags": 2,
    },
    "verdict": {
        "buy_min_total": 2,
        "wait_min_total": 0,
    },
}

ROLES = ("news", "scout", "charts", "skeptic", "sentiment")
ROLE_LABEL = {"chief": "Chief", "news": "News", "scout": "Scout", "charts": "Charts", "skeptic": "Skeptic", "sentiment": "Sentiment"}
NOTE = "Research only. A desk debate, not a recommendation. This desk never places trades, never calls a broker, and sends no alerts."

COLS = [
    "rank", "ticker", "company", "sector", "pick_source", "setup_sources", "best_status", "price", "price_as_of", "day_pct",
    "entry", "stop", "target1", "risk_pct", "reward_risk", "dist_to_entry_pct",
    "volume_ratio", "volume_streak", "ma10", "ma20", "ma50", "pct_above_ma10", "pct_above_ma20", "pct_above_ma50",
    "run_pct", "up_streak", "gap_pct", "headline_count", "headline", "headline_link", "headline_source",
    "news_pts", "news_line", "scout_pts", "scout_line", "charts_pts", "charts_line", "charts_veto",
    "skeptic_pts", "skeptic_line", "skeptic_objections", "skeptic_hard_no", "sentiment_pts", "sentiment_line",
    "total", "verdict", "chief_line", "data_status", "note", "disclaimer",
]
NEWS_COLS = ["ticker", "headline", "publisher", "link", "published", "fetched"]


def config(cfg):
    """The trading_floor block over the defaults. Keys starting with _ are notes."""
    out = copy.deepcopy(DEFAULTS)
    block = (cfg or {}).get("trading_floor") or {}
    for k, v in block.items():
        if str(k).startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            for k2, v2 in v.items():
                if not str(k2).startswith("_"):
                    out[k][k2] = v2
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- small helpers
def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and not np.isfinite(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def _pct(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None or b <= 0:
        return None
    return (a / b - 1.0) * 100.0


def _fmt(v, nd=2):
    return "" if v is None else ("%." + str(nd) + "f") % v


def _date(value):
    """First YYYY-MM-DD in a value, as a date. None when there is none."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", _txt(value))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _points(n):
    return "+1" if n > 0 else ("-1" if n < 0 else "0")


# ---------------------------------------------------------------- picks
def _rows(df):
    if df is None or len(getattr(df, "index", [])) == 0 or "ticker" not in getattr(df, "columns", []):
        return []
    return [r for r in df.to_dict("records") if _txt(r.get("ticker"))]


def pick_stocks(buy, frames=None, close=None, p=None):
    """Today's picks, at most max_stocks.

    First the Buy setups rows in that page's own order (broken out first, then the most scanners agreeing).
    When fill_from_scanners is on and that list is short, the rest are stocks that are READY or BROKEN OUT
    today on at least fill_min_scanners of the pattern scanners, with levels from setups.buy_levels.
    """
    p = p or config({})
    cap = int(p.get("max_stocks") or 0)
    picks, seen = [], set()
    for r in _rows(buy):
        if len(picks) >= cap:
            break
        t = _txt(r["ticker"]).upper()
        if t in seen:
            continue
        seen.add(t)
        picks.append({
            "ticker": t, "company": _txt(r.get("company")), "sector": _txt(r.get("sector")), "pick_source": "Buy setups",
            "setup_sources": _txt(r.get("setup_sources")), "best_status": _txt(r.get("best_status")),
            "entry": _num(r.get("entry")), "stop": _num(r.get("stop")), "target1": _num(r.get("target1")),
            "risk_pct": _num(r.get("risk_pct")), "reward_risk": _num(r.get("reward_risk")),
            "market_ok": _txt(r.get("market_ok")).lower(),
        })
    if len(picks) >= cap or not p.get("fill_from_scanners") or not frames:
        return picks
    market = ""
    if buy is not None and len(buy) and "market_ok" in buy.columns:
        market = _txt(buy.iloc[0].get("market_ok")).lower()
    grouped = {}
    sources = (("VCP", "scanner_vcp"), ("Box", "scanner_box"), ("Flag", "scanner_flag"), ("Qullamaggie", "scanner_qullamaggie"),
               ("Marios", "scanner_marios"), ("EP", "scanner_ep"), ("CANSLIM", "scanner_canslim"))
    for name, key in sources:
        frame = frames.get(key)
        if name == "EP":
            frame = setups._ep_buy_rows(frame)
        for rec in setups._setup_records(frame, name):
            grouped.setdefault(rec["ticker"].upper(), []).append(rec)
    order = {name: i for i, (name, _) in enumerate(sources)}
    extra = []
    for t, recs in grouped.items():
        if t in seen:
            continue
        names = sorted({rec["source"] for rec in recs}, key=lambda s: order[s])
        if len(names) < int(p.get("fill_min_scanners") or 1):
            continue
        usable = [rec for rec in recs if rec["pivot"] is not None and rec["pivot"] > 0]
        usable.sort(key=lambda rec: (0 if rec["status"] == "BROKEN OUT today" else 1,
                                     -(rec["strength"] if rec["strength"] is not None else -1), order[rec["source"]]))
        best = usable[0] if usable else recs[0]
        price = best.get("price")
        if close is not None and t in getattr(close, "columns", []):
            s = close[t].dropna()
            if len(s):
                price = float(s.iloc[-1])
        broken = best["status"] == "BROKEN OUT today"
        levels = setups.buy_levels(best.get("pivot"), best.get("stop"), price, broken) if usable else None
        extra.append({
            "ticker": t, "company": best.get("company") or "", "sector": best.get("sector") or "", "pick_source": "Cross-scanner",
            "setup_sources": " + ".join(names), "best_status": best["status"],
            "entry": best.get("pivot"), "stop": levels["stop"] if levels else None,
            "target1": levels["target1"] if levels else None, "risk_pct": levels["risk_pct"] if levels else None,
            "reward_risk": levels["reward_risk"] if levels else None, "market_ok": market,
            "_k": (0 if broken else 1, -len(names), -(best["strength"] or 0), t),
        })
    extra.sort(key=lambda r: r["_k"])
    for r in extra:
        if len(picks) >= cap:
            break
        r.pop("_k", None)
        picks.append(r)
    return picks


# ---------------------------------------------------------------- price and volume facts
def price_stats(ticker, close, opn=None, vol=None, avg_days=50, run_days=5):
    """Facts from the cached daily bars only. Missing pieces stay None."""
    out = {k: None for k in ("price", "prev", "day_pct", "ma10", "ma20", "ma50", "pct_above_ma10", "pct_above_ma20",
                             "pct_above_ma50", "run_pct", "up_streak", "gap_pct", "volume_ratio", "volume_streak", "price_as_of")}
    if close is None or ticker not in getattr(close, "columns", []):
        return out
    c = close[ticker].dropna()
    if len(c) < 2:
        return out
    arr = c.to_numpy(dtype=float)
    last, prev = float(arr[-1]), float(arr[-2])
    out["price"], out["prev"] = last, prev
    out["price_as_of"] = str(pd.Timestamp(c.index[-1]).date())
    out["day_pct"] = _pct(last, prev)
    for n in (10, 20, 50):
        if len(arr) >= n:
            ma = float(np.mean(arr[-n:]))
            out["ma%d" % n] = ma
            out["pct_above_ma%d" % n] = _pct(last, ma)
    if len(arr) > run_days:
        out["run_pct"] = _pct(last, arr[-1 - run_days])
    streak = 0
    for i in range(len(arr) - 1, 0, -1):
        if arr[i] > arr[i - 1]:
            streak += 1
        else:
            break
    out["up_streak"] = streak
    if opn is not None and ticker in getattr(opn, "columns", []):
        o = opn[ticker].reindex(c.index)
        today_open = _num(o.iloc[-1])
        if today_open is not None:
            out["gap_pct"] = _pct(today_open, prev)
    if vol is not None and ticker in getattr(vol, "columns", []):
        v = vol[ticker].reindex(c.index).to_numpy(dtype=float)
        n = len(v)
        # Same 50-day average the High volume page uses: the sessions before the day being checked.
        avg = setups._prior_avg(v, n - 1, avg_days)
        if avg is not None and np.isfinite(v[-1]):
            out["volume_ratio"] = float(v[-1]) / avg
            vs, i = 0, n - 1
            while i >= avg_days:
                a = setups._prior_avg(v, i, avg_days)
                if a is None or not np.isfinite(v[i]) or v[i] <= a:
                    break
                vs += 1
                i -= 1
            out["volume_streak"] = vs
    return out


# ---------------------------------------------------------------- headlines
GENERIC = {
    "inc", "corp", "corporation", "company", "co", "the", "group", "holdings", "holding", "plc", "ltd", "class", "and", "of",
    "international", "technologies", "technology", "solutions", "systems", "financial", "services", "health", "energy",
    "bank", "capital", "global", "american", "national", "general", "first", "united", "power", "resources", "brands",
    "industries", "motors", "partners", "properties", "realty", "trust", "pharmaceuticals", "therapeutics", "labs",
    "communications", "networks", "entertainment", "products", "foods", "materials", "insurance", "electric", "airlines",
}


def clean_name(company):
    """A company name as people write it: 'Lilly (Eli)' -> 'Eli Lilly', 'Walt Disney Company (The)' -> 'Walt Disney'."""
    name = _txt(company)
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", name)
    if m:
        inner = m.group(2).strip()
        keep = inner.lower() not in ("the", "") and not inner.lower().startswith("class")
        name = (inner + " " + m.group(1).strip()) if keep else m.group(1).strip()
    name = re.sub(r"[,.]?\s+(Inc|Incorporated|Corp|Corporation|Company|Co|Plc|Ltd|N\.?V|S\.?A|Holdings|Group)\.?$", "", name, flags=re.I)
    name = re.sub(r"[,.]?\s+(Inc|Corp|Company|Co)\.?$", "", name, flags=re.I)
    return name.strip(" ,.&")


def _name_words(company):
    """Distinctive words from a company name, for the headline name check."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", clean_name(company)) if w]
    return [w for w in words if w.lower() not in GENERIC and len(w) >= 3][:2]


def mentions(headline, ticker, company):
    """True when the headline names the ticker (as a word) or a distinctive word of the company name."""
    text = _txt(headline)
    if not text:
        return False
    if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(_txt(ticker).upper()), text):
        return True
    low = text.lower()
    return any(re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(w.lower()), low) for w in _name_words(company))


def headlines_for(ticker, company, desk_news, floor_news, asof, p):
    """Fresh headlines for one stock, newest first. The desk's own stored headlines win; the
    Trading Floor cache (Google News RSS) is used only when the desk has none for this stock."""
    n = p["news"]
    asof_d = _date(asof)
    if asof_d is None:
        return [], ""

    def fresh(frame, src):
        out = []
        for r in _rows(frame):
            if _txt(r.get("ticker")).upper() != ticker:
                continue
            day = _date(r.get("published"))
            if day is None or (asof_d - day).days > int(n["fresh_days"]) or day > asof_d + dt.timedelta(days=1):
                continue
            title = _txt(r.get("headline"))
            if not title or (n.get("name_match") and not mentions(title, ticker, company)):
                continue
            out.append({"headline": title, "publisher": _txt(r.get("publisher")), "link": _txt(r.get("link")),
                        "published": _txt(r.get("published")), "source": src})
        out.sort(key=lambda h: h["published"], reverse=True)
        return out[: int(n["max_headlines"])]

    got = fresh(desk_news, "desk")
    if got:
        return got, "desk"
    got = fresh(floor_news, "google")
    return got, ("google" if got else "")


def headline_tone(title):
    import scoring
    return scoring.headline_tone(title)[0]


def lead_headline(heads):
    """The newest headline that points the same way as the total tone, so the News line explains its vote."""
    if not heads:
        return None
    tones = [headline_tone(h["headline"]) for h in heads]
    tone = sum(tones)
    lead = [h for h, t in zip(heads, tones) if (t > 0) == (tone > 0) and (t < 0) == (tone < 0)]
    return (lead or heads)[0]


# ---------------------------------------------------------------- the five voting roles
def role_news(heads, p):
    """+1 when the fresh headlines lean positive, -1 when they lean negative, 0 otherwise or when there are none."""
    if not p["news"].get("on", True):
        return 0, "Off in Settings."
    if not heads:
        return 0, "No fresh headlines found."
    tone = sum(headline_tone(h["headline"]) for h in heads)
    top = lead_headline(heads)
    src = (" (" + top["publisher"] + ")") if top.get("publisher") else ""
    more = "" if len(heads) == 1 else " %d fresh headlines." % len(heads)
    if tone > 0:
        return 1, "Moving on: \u201c%s\u201d%s. Headlines lean positive.%s" % (top["headline"], src, more)
    if tone < 0:
        return -1, "Moving on: \u201c%s\u201d%s. Headlines lean negative.%s" % (top["headline"], src, more)
    return 0, "Latest: \u201c%s\u201d%s. No clear good or bad news.%s" % (top["headline"], src, more)


def role_scout(stats, p):
    """Volume against the 50-day normal. +1 heavy buying or a volume streak, -1 heavy selling or thin volume."""
    s = p["scout"]
    if not s.get("on", True):
        return 0, "Off in Settings."
    ratio = stats.get("volume_ratio")
    if ratio is None:
        return 0, "No volume on file to compare."
    day = stats.get("day_pct") or 0.0
    words = "%.1f\u00d7 its normal volume" % ratio
    if ratio >= s["hot_ratio"] and day > 0:
        return 1, "Unusual volume: %s on an up day. Buyers are showing up." % words
    if ratio >= s["hot_ratio"] and day <= 0:
        return -1, "Unusual volume: %s on a down day. That looks like selling." % words
    if ratio < s["thin_ratio"]:
        return -1, "Thin: only %s. Not much interest today." % words
    streak = stats.get("volume_streak") or 0
    if s.get("streak_check", True) and streak >= int(s["streak_days"]):
        return 1, "Volume above normal %d days in a row (%s today)." % (streak, words)
    return 0, "Normal volume: %s." % words


def role_charts(pick, stats, p):
    """Entry, stop and target from the levels the desk already computed. Returns (pts, line, veto)."""
    c = p["charts"]
    entry, stop, target = pick.get("entry"), pick.get("stop"), pick.get("target1")
    if not c.get("on", True):
        return 0, "Off in Settings.", False
    if entry is None or stop is None or target is None or not (stop < entry < target):
        return -1, "No valid entry, stop and target on file. Veto.", True
    price = stats.get("price")
    risk = pick.get("risk_pct")
    if risk is None:
        risk = (entry - stop) / entry * 100.0
    rr = pick.get("reward_risk")
    if rr is None:
        rr = (target - entry) / (entry - stop)
    plan = "Entry %s, stop %s (-%.1f%%), target %s, reward/risk %.1f." % (_fmt(entry), _fmt(stop), risk, _fmt(target), rr)
    if c.get("veto_below_stop", True) and price is not None and price <= stop:
        return -1, "Price %s is at or under the stop %s. The setup is broken. Veto." % (_fmt(price), _fmt(stop)), True
    if rr >= c["min_reward_risk"] and risk <= c["max_risk_pct"]:
        return 1, plan + " Clean plan.", False
    return 0, plan + " Plan is weak (reward/risk under %s or risk over %s%%)." % (_fmt(c["min_reward_risk"], 1), _fmt(c["max_risk_pct"], 1)), False


def role_skeptic(pick, stats, n_fresh, earnings_date, asof, p):
    """Counts objections. 0 -> +1, 1 -> 0, 2 or more -> -1. Returns (pts, line, hard_no, objections)."""
    k = p["skeptic"]
    if not k.get("on", True):
        return 0, "Off in Settings.", False, []
    objs = []
    hard = False
    if k.get("no_news_check", True) and p["news"].get("on", True) and n_fresh == 0:
        objs.append("no fresh news to explain a move")
    ratio = stats.get("volume_ratio")
    if k.get("thin_volume_check", True) and ratio is not None and ratio < k["thin_volume_ratio"]:
        objs.append("thin volume (%.1f\u00d7 normal)" % ratio)
    if k.get("extended_ma_check", True):
        a20, a50 = stats.get("pct_above_ma20"), stats.get("pct_above_ma50")
        if a20 is not None and a20 >= k["max_above_ma20_pct"]:
            objs.append("stretched %.1f%% over its 20-day average" % a20)
        elif a50 is not None and a50 >= k["max_above_ma50_pct"]:
            objs.append("stretched %.1f%% over its 50-day average" % a50)
    entry, price = pick.get("entry"), stats.get("price")
    over = _pct(price, entry)
    if k.get("extended_entry_check", True) and over is not None and over >= k["max_above_entry_pct"]:
        objs.append("already %.1f%% over the entry (chasing)" % over)
        if over >= k["hard_no_above_entry_pct"]:
            hard = True
    if k.get("market_check", True) and pick.get("market_ok") == "no":
        objs.append("SPY is not in an uptrend")
    if k.get("earnings_check", True):
        e, a = _date(earnings_date), _date(asof)
        if e is not None and a is not None and 0 <= (e - a).days <= int(k["earnings_days"]):
            objs.append("earnings on %s" % e.isoformat())
    if len(objs) >= int(k["hard_no_objections"]):
        hard = True
    pts = 1 if not objs else (0 if len(objs) == 1 else -1)
    if not objs:
        line = "Nothing serious against it."
    else:
        line = "Against: " + "; ".join(objs) + "."
    if hard:
        line += " Hard no."
    return pts, line, hard, objs


def role_sentiment(stats, n_fresh, p):
    """Is the crowd too hot? 0 hot flags -> +1, 1 -> 0, hot_flags or more -> -1."""
    s = p["sentiment"]
    if not s.get("on", True):
        return 0, "Off in Settings."
    flags = []
    run = stats.get("run_pct")
    if s.get("run_check", True) and run is not None and run >= s["run_pct"]:
        flags.append("up %.1f%% in %d days" % (run, int(s["run_days"])))
    a10, a20 = stats.get("pct_above_ma10"), stats.get("pct_above_ma20")
    if s.get("ma10_check", True) and a10 is not None and a10 >= s["max_above_ma10_pct"]:
        flags.append("%.1f%% over MA10" % a10)
    if s.get("ma20_check", True) and a20 is not None and a20 >= s["max_above_ma20_pct"]:
        flags.append("%.1f%% over MA20" % a20)
    gap = stats.get("gap_pct")
    if s.get("gap_check", True) and gap is not None and gap >= s["gap_pct"]:
        flags.append("gapped up %.1f%% today" % gap)
    streak = stats.get("up_streak") or 0
    if s.get("streak_check", True) and streak >= int(s["up_streak_days"]):
        flags.append("%d up days in a row" % streak)
    if s.get("buzz_check", True) and n_fresh >= int(s["buzz_headlines"]):
        flags.append("%d fresh headlines" % n_fresh)
    if not flags:
        bits = []
        if run is not None:
            bits.append("%+.1f%% in %d days" % (run, int(s["run_days"])))
        if a10 is not None:
            bits.append("%+.1f%% vs MA10" % a10)
        return 1, "Crowd is calm" + (" (" + ", ".join(bits) + ")." if bits else ".")
    if len(flags) >= int(s["hot_flags"]):
        return -1, "Crowd is too hot: " + ", ".join(flags) + "."
    return 0, "Crowd is warming up: " + ", ".join(flags) + "."


def chief(pts, veto, hard_no, p):
    """Sum the five votes and apply the cutoffs. Returns (verdict, total, line)."""
    v = p["verdict"]
    total = int(sum(pts.get(r, 0) for r in ROLES))
    pros = [ROLE_LABEL[r] for r in ROLES if pts.get(r, 0) > 0]
    cons = [ROLE_LABEL[r] for r in ROLES if pts.get(r, 0) < 0]
    tail = []
    if pros:
        tail.append("for: " + ", ".join(pros))
    if cons:
        tail.append("against: " + ", ".join(cons))
    why = ("; ".join(tail) + ".") if tail else "nobody feels strongly."
    if veto:
        return "SKIP", total, "SKIP. Charts vetoed it: no usable entry, stop and target."
    if total >= int(v["buy_min_total"]) and not hard_no:
        return "BUY", total, "BUY (total %+d). %s" % (total, why[0].upper() + why[1:])
    if total >= int(v["wait_min_total"]):
        extra = " The Skeptic's hard no keeps it from a BUY." if (hard_no and total >= int(v["buy_min_total"])) else ""
        return "WAIT", total, "WAIT (total %+d). %s%s" % (total, why[0].upper() + why[1:], extra)
    return "SKIP", total, "SKIP (total %+d). %s" % (total, why[0].upper() + why[1:])


# ---------------------------------------------------------------- the whole floor
def build_floor(picks, close, opn, vol, desk_news, floor_news, asof, cfg=None, earnings=None):
    """One row per pick with every role's line and points. earnings: {ticker: next earnings date}."""
    p = config(cfg)
    earnings = earnings or {}
    rows = []
    for i, pick in enumerate(picks):
        t = pick["ticker"]
        st = price_stats(t, close, opn, vol, int(p["scout"]["avg_days"]), int(p["sentiment"]["run_days"]))
        heads, src = headlines_for(t, pick.get("company"), desk_news, floor_news, asof, p) if p["news"].get("on", True) else ([], "")
        n_fresh = len(heads)
        pts = {}
        lines = {}
        pts["news"], lines["news"] = role_news(heads, p)
        pts["scout"], lines["scout"] = role_scout(st, p)
        pts["charts"], lines["charts"], veto = role_charts(pick, st, p)
        pts["skeptic"], lines["skeptic"], hard, objs = role_skeptic(pick, st, n_fresh, earnings.get(t), asof, p)
        pts["sentiment"], lines["sentiment"] = role_sentiment(st, n_fresh, p)
        verdict, total, cline = chief(pts, veto, hard, p)
        lead = lead_headline(heads)
        entry = pick.get("entry")
        rows.append({
            "rank": i + 1, "ticker": t, "company": pick.get("company"), "sector": pick.get("sector"),
            "pick_source": pick.get("pick_source"), "setup_sources": pick.get("setup_sources"), "best_status": pick.get("best_status"),
            "price": _r(st["price"]), "price_as_of": st["price_as_of"] or asof, "day_pct": _r(st["day_pct"]),
            "entry": _r(entry), "stop": _r(pick.get("stop")), "target1": _r(pick.get("target1")),
            "risk_pct": _r(pick.get("risk_pct")), "reward_risk": _r(pick.get("reward_risk")),
            "dist_to_entry_pct": _r(_pct(st["price"], entry)),
            "volume_ratio": _r(st["volume_ratio"]), "volume_streak": st["volume_streak"],
            "ma10": _r(st["ma10"]), "ma20": _r(st["ma20"]), "ma50": _r(st["ma50"]),
            "pct_above_ma10": _r(st["pct_above_ma10"]), "pct_above_ma20": _r(st["pct_above_ma20"]), "pct_above_ma50": _r(st["pct_above_ma50"]),
            "run_pct": _r(st["run_pct"]), "up_streak": st["up_streak"], "gap_pct": _r(st["gap_pct"]),
            "headline_count": n_fresh,
            "headline": lead["headline"] if lead else "", "headline_link": lead["link"] if lead else "",
            "headline_source": {"desk": "Desk headlines", "google": "Google News"}.get(src, "None"),
            "news_pts": pts["news"], "news_line": lines["news"],
            "scout_pts": pts["scout"], "scout_line": lines["scout"],
            "charts_pts": pts["charts"], "charts_line": lines["charts"], "charts_veto": "yes" if veto else "no",
            "skeptic_pts": pts["skeptic"], "skeptic_line": lines["skeptic"], "skeptic_objections": len(objs),
            "skeptic_hard_no": "yes" if hard else "no",
            "sentiment_pts": pts["sentiment"], "sentiment_line": lines["sentiment"],
            "total": total, "verdict": verdict, "chief_line": cline,
            "data_status": "OK", "note": NOTE,
        })
    out = pd.DataFrame(rows, columns=[c for c in COLS if c != "disclaimer"])
    if len(out) == 0:
        return out
    rank = {"BUY": 0, "WAIT": 1, "SKIP": 2}
    out["_v"] = out["verdict"].map(rank)
    out = out.sort_values(["_v", "total", "rank"], ascending=[True, False, True]).drop(columns="_v").reset_index(drop=True)
    return out


def counts(frame):
    if frame is None or len(frame) == 0 or "verdict" not in frame.columns:
        return {"BUY": 0, "WAIT": 0, "SKIP": 0}
    v = frame["verdict"].astype(str)
    return {k: int((v == k).sum()) for k in ("BUY", "WAIT", "SKIP")}


# ---------------------------------------------------------------- Google News RSS (free, no key)
GOOGLE_RSS = "https://news.google.com/rss/search"


def google_query(ticker, company, fresh_days):
    name = clean_name(company)
    base = ('"%s" OR %s stock' % (name, ticker)) if name else ("%s stock" % ticker)
    return "%s when:%dd" % (base, int(fresh_days))


# Quote and option-chain pages are not news. They are skipped.
QUOTE_PAGE = re.compile(r"stock price, news, quote|quote & history|quotes & news|options? chain|\([A-Z]{1,5}\d{6}[CP]\d+\)", re.I)


def parse_rss(text, ticker, fetched, limit=5):
    """Items from a Google News RSS reply. Bad XML gives an empty list (a soft failure)."""
    rows = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return rows
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        src = item.find("source")
        publisher = (src.text or "").strip() if src is not None and src.text else ""
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(" - " + publisher)].strip()
        published = ""
        when = item.findtext("pubDate") or ""
        try:
            published = pd.Timestamp(pd.to_datetime(when, utc=True)).tz_convert(PT).strftime("%Y-%m-%d %H:%M PT")
        except Exception:
            published = ""
        if title and not QUOTE_PAGE.search(title):
            rows.append({"ticker": ticker, "headline": title, "publisher": publisher, "link": (item.findtext("link") or "").strip(),
                         "published": published, "fetched": fetched})
        if len(rows) >= limit:
            break
    return rows


def fetch_google_news(picks, p, fetched, get=None, wait=None):
    """One RSS request per stock in picks (already capped). Returns (rows, failed_tickers).
    get(url, params, timeout) returns an object with status_code and text. Failures are soft."""
    import requests
    get = get or (lambda url, params, timeout: requests.get(url, params=params, timeout=timeout,
                                                            headers={"User-Agent": "Mozilla/5.0 (compatible; NickStockDesk/1.0; research)"}))
    n = p["news"]
    rows, failed = [], []
    for pick in picks:
        t = pick["ticker"]
        if wait:
            wait()
        try:
            params = {"q": google_query(t, pick.get("company"), n["fresh_days"]), "hl": "en-US", "gl": "US", "ceid": "US:en"}
            resp = get(GOOGLE_RSS, params, float(n["google_timeout_s"]))
            if getattr(resp, "status_code", 0) != 200:
                failed.append(t)
                continue
            rows.extend(parse_rss(resp.text, t, fetched, int(n["max_headlines"])))
        except Exception:
            failed.append(t)
    return rows, failed


def merge_news_cache(old, new_rows, refreshed, today, keep_days):
    """New rows replace the refreshed tickers. Rows fetched more than keep_days ago are dropped."""
    old = old if old is not None and len(old) else pd.DataFrame(columns=NEWS_COLS)
    for c in NEWS_COLS:
        if c not in old.columns:
            old[c] = ""
    keep = old[~old["ticker"].astype(str).isin(set(refreshed))]
    out = pd.concat([keep[NEWS_COLS], pd.DataFrame(new_rows, columns=NEWS_COLS)], ignore_index=True)
    day = _date(today)
    if day is not None:
        ok = out["fetched"].map(lambda v: _date(v) is not None and (day - _date(v)).days <= int(keep_days))
        out = out[ok]
    return out.reset_index(drop=True)
