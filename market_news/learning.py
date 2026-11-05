"""Light learning stubs — correlate cause tags / sources with next-day SPY direction.

No notifications. No trades. Structure only for later reweighting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def stub_from_brief(brief: Dict[str, Any]) -> Dict[str, Any]:
    """One learning row for today's brief (next_day_spy_pct filled in later)."""
    causes = [c.get("cause") for c in (brief.get("causes") or []) if c.get("cause")]
    sources = sorted({
        h.get("source")
        for h in (brief.get("headlines") or [])
        if h.get("source")
    })
    stats = brief.get("stats") or {}
    return {
        "date": brief.get("session") or brief.get("price_as_of"),
        "slot": brief.get("slot"),  # morning_open | evening_close
        "mood": (brief.get("mood") or {}).get("label"),
        "regime": (brief.get("regime") or {}).get("label"),
        "causes": causes,
        "sources": sources,
        "spy_day_pct": stats.get("spy_day_pct"),
        "qqq_day_pct": stats.get("qqq_day_pct"),
        # Filled on the next session when we know how SPY did the following day.
        "next_day_spy_pct": None,
        "next_day_direction": None,  # "up" | "down" | "flat" | None
    }


def backfill_next_day(
    history: List[Dict[str, Any]],
    session: str,
    spy_day_pct: Optional[float],
) -> List[Dict[str, Any]]:
    """When today's SPY day % is known, stamp it onto the prior session's stubs."""
    if spy_day_pct is None or not history:
        return history
    if spy_day_pct > 0.15:
        direction = "up"
    elif spy_day_pct < -0.15:
        direction = "down"
    else:
        direction = "flat"

    out = []
    for row in history:
        row = dict(row)
        # Fill the most recent prior stub that still lacks next_day.
        if (
            row.get("next_day_spy_pct") is None
            and row.get("date")
            and row.get("date") < session
        ):
            # Only fill the latest prior date once per call — mark candidates,
            # then keep the chronologically latest unfinished row.
            out.append(row)
        else:
            out.append(row)

    # Find latest unfinished prior row and fill it.
    unfinished = [
        i for i, r in enumerate(out)
        if r.get("next_day_spy_pct") is None and r.get("date") and r["date"] < session
    ]
    if unfinished:
        i = unfinished[-1]
        out[i] = dict(out[i])
        out[i]["next_day_spy_pct"] = spy_day_pct
        out[i]["next_day_direction"] = direction
    return out


def cause_source_stats(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tiny aggregate for later reweighting. Safe when history is short."""
    cause_hits: Dict[str, Dict[str, int]] = {}
    source_hits: Dict[str, Dict[str, int]] = {}

    def bump(bucket: Dict[str, Dict[str, int]], key: str, direction: str) -> None:
        if not key or not direction:
            return
        cell = bucket.setdefault(key, {"up": 0, "down": 0, "flat": 0, "n": 0})
        cell[direction] = cell.get(direction, 0) + 1
        cell["n"] += 1

    for row in history or []:
        direction = row.get("next_day_direction")
        if not direction:
            continue
        for c in row.get("causes") or []:
            bump(cause_hits, c, direction)
        for s in row.get("sources") or []:
            bump(source_hits, s, direction)

    return {
        "by_cause": cause_hits,
        "by_source": source_hits,
        "n_labeled": sum(1 for r in (history or []) if r.get("next_day_direction")),
        "note": (
            "Counts of next-day SPY direction after each cause/source appeared. "
            "For later reweighting only — not a trading signal."
        ),
    }
