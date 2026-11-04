"""Paper test of the Trading Floor's BUY calls. FAKE MONEY. Research only.

No real orders, no broker, no alerts. It reads only data the desk already has: the
Trading Floor file of the same run and the cached daily bars (open, high, low, close).

Fill rule: a BUY call made on day D is filled at the OPEN of the next session (D+1),
on the next full run, from that day's daily bar. It is never filled at a price seen
before the call was made.

State lives in committed files that build up day by day:
    data/paper_trades.csv   one row per BUY call (PENDING, OPEN, CLOSED, NOT FILLED, SKIPPED)
    data/paper_equity.csv   one row per trading day since the start
    data/paper_summary.csv  one row: the numbers and the bookmarks last_bar and last_signal_date
Running the same day twice changes nothing (bars up to last_bar are never replayed and
signals for last_signal_date are never added again). Only the full run (and the offline
rebuild) calls this; hourly runs leave the files alone.
"""
import copy
import os

import numpy as np
import pandas as pd

DEFAULTS = {
    "start_cash": 10000.0,
    "position_pct": 10.0,
    "max_open": 10,
    "time_stop_days": 20,
    "fractional_shares": True,
    "share_decimals": 4,
    "skip_if_held": True,
    "skip_gap_past_plan": True,
}

FAKE = "FAKE MONEY. A paper test of the Trading Floor's BUY calls. No real orders, no broker, no alerts."
FILL_RULE = "next session open"

TRADE_COLS = [
    "trade_id", "ticker", "company", "signal_date", "signal_total", "status", "entry_date", "entry_price", "shares", "cost",
    "stop", "target", "last_date", "last_close", "days_held", "exit_date", "exit_price", "exit_reason", "exit_words",
    "pnl", "pnl_pct", "market_value", "note",
]
EQUITY_COLS = ["date", "cash", "invested", "equity", "return_pct", "spy_close", "spy_equity", "spy_return_pct",
               "drawdown_pct", "open_count", "note"]
SUMMARY_COLS = [
    "start_date", "start_cash", "fill_rule", "share_mode", "position_size", "last_bar", "last_signal_date", "cash", "invested",
    "equity", "total_return_pct", "spy_return_pct", "vs_spy_pct", "max_drawdown_pct", "open_count", "pending_count",
    "closed_count", "wins", "losses", "win_rate_pct", "avg_win", "avg_loss", "avg_win_pct", "avg_loss_pct",
    "total_pnl", "skipped_count", "not_filled_count", "note",
]

EXIT_WORDS = {
    "STOP": "Hit the stop, sold at the stop price.",
    "STOP_GAP": "Opened below the stop, sold at the open.",
    "TARGET": "Reached target 1, sold at the target price.",
    "TARGET_GAP": "Opened above target 1, sold at the open.",
    "STOP_SAME_BAR": "Touched the stop and the target on the same day; counted as the stop to stay careful.",
    "TIME": "Time stop: still open after the time limit, sold at the close.",
}


def config(cfg):
    out = copy.deepcopy(DEFAULTS)
    for k, v in ((cfg or {}).get("trading_floor_paper") or {}).items():
        if not str(k).startswith("_"):
            out[k] = v
    return out


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _txt(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _day(ts):
    return str(pd.Timestamp(ts).date())


def size_per_trade(p):
    return float(p["start_cash"]) * float(p["position_pct"]) / 100.0


# ---------------------------------------------------------------- state
def empty_state():
    return {"trades": pd.DataFrame(columns=TRADE_COLS), "equity": pd.DataFrame(columns=EQUITY_COLS), "summary": {}}


def load_state(data_dir):
    st = empty_state()
    for key, name, cols in (("trades", "paper_trades.csv", TRADE_COLS), ("equity", "paper_equity.csv", EQUITY_COLS)):
        path = os.path.join(data_dir, name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            df = pd.read_csv(path, dtype={"trade_id": str, "ticker": str})
            for c in cols:
                if c not in df.columns:
                    df[c] = np.nan
            st[key] = df[cols]
    path = os.path.join(data_dir, "paper_summary.csv")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        df = pd.read_csv(path)
        if len(df):
            st["summary"] = df.iloc[0].to_dict()
    return st


def save_state(st, data_dir):
    st["trades"].reindex(columns=TRADE_COLS).to_csv(os.path.join(data_dir, "paper_trades.csv"), index=False, na_rep="")
    st["equity"].reindex(columns=EQUITY_COLS).to_csv(os.path.join(data_dir, "paper_equity.csv"), index=False, na_rep="")
    pd.DataFrame([st["summary"]]).reindex(columns=SUMMARY_COLS).to_csv(os.path.join(data_dir, "paper_summary.csv"), index=False, na_rep="")


# ---------------------------------------------------------------- one bar
def _bar(bars, ticker, day):
    """(open, high, low, close) for one ticker on one day, or None."""
    out = []
    for k in ("open", "high", "low", "close"):
        frame = bars.get(k)
        if frame is None or ticker not in getattr(frame, "columns", []) or day not in frame.index:
            return None
        out.append(_num(frame.at[day, ticker]))
    if any(v is None for v in out):
        return None
    return tuple(out)


def exit_on_bar(o, h, l, c, stop, target, days_held, time_stop_days):
    """(price, reason) when the trade ends on this bar, else None. Stop first when both are touched."""
    if o <= stop:
        return o, "STOP_GAP"
    if o >= target:
        return o, "TARGET_GAP"
    hit_stop, hit_target = l <= stop, h >= target
    if hit_stop and hit_target:
        return stop, "STOP_SAME_BAR"
    if hit_stop:
        return stop, "STOP"
    if hit_target:
        return target, "TARGET"
    if days_held >= int(time_stop_days):
        return c, "TIME"
    return None


def _close_trade(t, day, price, reason):
    t["status"] = "CLOSED"
    t["exit_date"] = day
    t["exit_price"] = round(price, 4)
    t["exit_reason"] = reason
    t["exit_words"] = EXIT_WORDS[reason]
    t["pnl"] = round((price - t["entry_price"]) * t["shares"], 2)
    t["pnl_pct"] = round((price / t["entry_price"] - 1.0) * 100.0, 2)
    t["market_value"] = 0.0
    return t


def step_day(trades, cash, day, bars, p):
    """Process one trading day: fill PENDING calls at the open, then check exits, then mark to market.
    trades is a list of dicts (changed in place). Returns the new cash."""
    for t in trades:
        if t["status"] != "PENDING" or _txt(t["signal_date"]) >= day:
            continue
        bar = _bar(bars, t["ticker"], day)
        if bar is None:
            # The fill is the next session's open only. No bar that session means no fill.
            t["status"] = "NOT FILLED"
            t["note"] = "No price bar on the next session, so it was not bought."
            continue
        o = bar[0]
        if p.get("skip_gap_past_plan", True) and (o <= t["stop"] or o >= t["target"]):
            t["status"] = "NOT FILLED"
            t["note"] = "Opened at %.2f, already past the stop or target, so it was not bought." % o
            continue
        size = size_per_trade(p)
        shares = size / o if p.get("fractional_shares", True) else float(int(size // o))
        shares = round(shares, int(p.get("share_decimals", 4))) if p.get("fractional_shares", True) else shares
        if shares <= 0 or shares * o > cash + 1e-6:
            t["status"] = "NOT FILLED"
            t["note"] = "Not enough fake cash at the open."
            continue
        t.update({"status": "OPEN", "entry_date": day, "entry_price": round(o, 4), "shares": shares,
                  "cost": round(shares * o, 2), "days_held": 0, "note": "Bought at the open on %s." % day})
        cash -= shares * o
    for t in trades:
        if t["status"] != "OPEN":
            continue
        bar = _bar(bars, t["ticker"], day)
        if bar is None:
            continue
        o, h, l, c = bar
        t["days_held"] = int(_num(t.get("days_held")) or 0) + 1
        t["last_date"], t["last_close"] = day, round(c, 4)
        hit = exit_on_bar(o, h, l, c, t["stop"], t["target"], t["days_held"], p["time_stop_days"])
        if hit:
            _close_trade(t, day, hit[0], hit[1])
            cash += hit[0] * t["shares"]
        else:
            t["market_value"] = round(c * t["shares"], 2)
            t["pnl"] = round((c - t["entry_price"]) * t["shares"], 2)
            t["pnl_pct"] = round((c / t["entry_price"] - 1.0) * 100.0, 2)
    return cash


def add_signals(trades, cash, day, floor, p):
    """New BUY calls from the Trading Floor of day `day` become PENDING (or SKIPPED with the reason)."""
    if floor is None or len(floor) == 0 or "verdict" not in floor.columns:
        return
    held = {t["ticker"] for t in trades if t["status"] in ("OPEN", "PENDING")}
    busy = sum(1 for t in trades if t["status"] in ("OPEN", "PENDING"))
    pending_cash = sum(size_per_trade(p) for t in trades if t["status"] == "PENDING")
    free = cash - pending_cash
    size = size_per_trade(p)
    ids = {t["trade_id"] for t in trades}
    rows = floor[floor["verdict"].astype(str) == "BUY"]
    if "total" in rows.columns:
        rows = rows.assign(_t=pd.to_numeric(rows["total"], errors="coerce")).sort_values("_t", ascending=False, kind="stable")
    for r in rows.to_dict("records"):
        tk = _txt(r.get("ticker")).upper()
        tid = "%s-%s" % (day, tk)
        if not tk or tid in ids:
            continue
        stop, target = _num(r.get("stop")), _num(r.get("target1"))
        t = {c: np.nan for c in TRADE_COLS}
        t.update({"trade_id": tid, "ticker": tk, "company": _txt(r.get("company")), "signal_date": day,
                  "signal_total": _num(r.get("total")), "stop": stop, "target": target, "note": ""})
        reason = ""
        if stop is None or target is None or not stop < target:
            reason = "No usable stop and target."
        elif p.get("skip_if_held", True) and tk in held:
            reason = "Already held."
        elif busy >= int(p["max_open"]):
            reason = "No free slot (max %d open)." % int(p["max_open"])
        elif free < size - 1e-6:
            reason = "Not enough fake cash."
        if reason:
            t["status"], t["note"] = "SKIPPED", reason
        else:
            t["status"] = "PENDING"
            t["note"] = "Buys at the next session's open."
            busy += 1
            free -= size
            held.add(tk)
        trades.append(t)
        ids.add(tid)


# ---------------------------------------------------------------- stats
def stats(trades, equity, p):
    closed = [t for t in trades if t["status"] == "CLOSED"]
    wins = [t for t in closed if (_num(t["pnl"]) or 0) > 0]
    losses = [t for t in closed if (_num(t["pnl"]) or 0) <= 0]
    mean = lambda xs: round(float(np.mean(xs)), 2) if xs else None
    eq = pd.to_numeric(equity["equity"], errors="coerce") if len(equity) else pd.Series(dtype=float)
    dd = None
    if len(eq.dropna()):
        peak = eq.cummax()
        dd = round(float(((eq / peak - 1.0) * 100.0).min()), 2)
    last = equity.iloc[-1].to_dict() if len(equity) else {}
    tot, spy = _num(last.get("return_pct")), _num(last.get("spy_return_pct"))
    return {
        "closed_count": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(closed) * 100.0, 1) if closed else None,
        "avg_win": mean([_num(t["pnl"]) for t in wins]), "avg_loss": mean([_num(t["pnl"]) for t in losses]),
        "avg_win_pct": mean([_num(t["pnl_pct"]) for t in wins]), "avg_loss_pct": mean([_num(t["pnl_pct"]) for t in losses]),
        "total_pnl": round(sum(_num(t["pnl"]) or 0 for t in closed), 2),
        "max_drawdown_pct": dd, "total_return_pct": tot, "spy_return_pct": spy,
        "vs_spy_pct": round(tot - spy, 2) if tot is not None and spy is not None else None,
        "open_count": sum(1 for t in trades if t["status"] == "OPEN"),
        "pending_count": sum(1 for t in trades if t["status"] == "PENDING"),
        "skipped_count": sum(1 for t in trades if t["status"] == "SKIPPED"),
        "not_filled_count": sum(1 for t in trades if t["status"] == "NOT FILLED"),
    }


# ---------------------------------------------------------------- the daily update
def update(state, bars, floor, asof, p, spy="SPY", asof_final=True):
    """Bring the paper test up to `asof`. bars: {"open","high","low","close": wide frames}.
    The first call starts the test on `asof` (no backfill). Returns the new state.
    asof_final=False means the `asof` bar is still a live, unfinished day (a manual run during
    the session): then only the days before it are used and no BUY calls are taken that run."""
    close = bars.get("close")
    if close is None or spy not in getattr(close, "columns", []):
        return state
    spy_close = close[spy].dropna()
    days = [_day(d) for d in spy_close.index]
    if asof not in days:
        return state
    if not asof_final:
        before = [d for d in days if d < asof]
        if not before:
            return state
        asof, floor = before[-1], None
    bars = {k: (v.rename(index=lambda d: _day(d)) if v is not None else None) for k, v in bars.items()}
    spy_by_day = dict(zip(days, spy_close.to_numpy(dtype=float)))
    summ = dict(state.get("summary") or {})
    trades = [dict(r) for r in state["trades"].to_dict("records")] if len(state["trades"]) else []
    for t in trades:
        for k in ("stop", "target", "entry_price", "shares"):
            t[k] = _num(t.get(k))
    equity = state["equity"].copy() if len(state["equity"]) else pd.DataFrame(columns=EQUITY_COLS)
    start = _txt(summ.get("start_date"))
    cash = _num(summ.get("cash"))
    if not start:
        start, cash = asof, float(p["start_cash"])
        summ = {"start_date": start, "start_cash": float(p["start_cash"]), "last_bar": "", "last_signal_date": ""}
    last_bar = _txt(summ.get("last_bar"))
    start_spy = spy_by_day.get(start)
    eq_rows = equity.to_dict("records")
    for day in days:
        if day < start or (last_bar and day <= last_bar) or day > asof:
            continue
        if day > start:
            cash = step_day(trades, cash, day, bars, p)
        invested = sum((_num(t.get("market_value")) or 0) for t in trades if t["status"] == "OPEN")
        equity_now = cash + invested
        spy_now = spy_by_day.get(day)
        spy_eq = float(p["start_cash"]) * spy_now / start_spy if start_spy and spy_now else None
        eq_rows = [r for r in eq_rows if _txt(r.get("date")) != day]
        eq_rows.append({
            "date": day, "cash": round(cash, 2), "invested": round(invested, 2), "equity": round(equity_now, 2),
            "return_pct": round((equity_now / float(p["start_cash"]) - 1) * 100.0, 2),
            "spy_close": round(spy_now, 4) if spy_now else None, "spy_equity": round(spy_eq, 2) if spy_eq else None,
            "spy_return_pct": round((spy_eq / float(p["start_cash"]) - 1) * 100.0, 2) if spy_eq else None,
            "open_count": sum(1 for t in trades if t["status"] == "OPEN"), "note": "",
        })
        last_bar = day
    equity = pd.DataFrame(eq_rows, columns=EQUITY_COLS)
    if len(equity):
        eqv = pd.to_numeric(equity["equity"], errors="coerce")
        equity["drawdown_pct"] = ((eqv / eqv.cummax() - 1.0) * 100.0).round(2)
    if _txt(summ.get("last_signal_date")) != asof and last_bar == asof:
        add_signals(trades, cash, asof, floor, p)
        summ["last_signal_date"] = asof
    st = stats(trades, equity, p)
    invested = sum((_num(t.get("market_value")) or 0) for t in trades if t["status"] == "OPEN")
    summ.update(st)
    summ.update({
        "fill_rule": FILL_RULE, "share_mode": "fractional" if p.get("fractional_shares", True) else "whole",
        "position_size": round(size_per_trade(p), 2), "last_bar": last_bar, "cash": round(cash, 2),
        "invested": round(invested, 2), "equity": round(cash + invested, 2), "note": FAKE,
    })
    tdf = pd.DataFrame(trades, columns=TRADE_COLS)
    return {"trades": tdf, "equity": equity, "summary": summ}
