"""Plain 'what it means for me' tips — research only, overall market.

Never names a single stock. Never tells anyone to buy or sell a ticker.
Built from regime + breadth + VIX (+ mood) only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_tips(
    mood: Dict[str, Any],
    regime: Dict[str, Any],
    breadth: Dict[str, Any],
    stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return 2–3 very plain research-only lines."""
    stats = stats or {}
    vix = _f((mood or {}).get("vix"))
    if vix is None:
        vix = _f(stats.get("vix"))
    mood_label = (mood or {}).get("label") or "Mixed"
    regime_label = (regime or {}).get("label") or "unknown"
    flag = (breadth or {}).get("flag")

    lines: List[str] = []

    # Line 1 — tape feel from mood + VIX
    if mood_label == "Fear" or (vix is not None and vix >= 25):
        lines.append(
            "Fear is high today. Big swings are more common — go slow with new buys."
        )
    elif vix is not None and vix >= 20:
        lines.append(
            "The market is jumpy (VIX is firm). Small moves are normal; be patient with new buys."
        )
    elif mood_label == "Calm" and (vix is None or vix < 16):
        lines.append(
            "The tape looks calm. No rush — stick to your usual plan."
        )
    else:
        lines.append(
            "Choppy day, small moves are normal; be patient with new buys."
        )

    # Line 2 — breadth / how wide the move was
    if flag == "broad_decline":
        lines.append(
            "Most stocks fell with the indexes. Keep new buys small until more names join an up day."
        )
    elif flag == "broad_advance":
        lines.append(
            "Most stocks rose with the indexes. Strength is shared, not just a few names."
        )
    elif flag == "index_up_stocks_down":
        lines.append(
            "The index is up, but most stocks are not. Be careful chasing strength that only a few names show."
        )
    elif flag == "index_down_stocks_up":
        lines.append(
            "The index is down, but most stocks held up. The weak print may be narrow."
        )
    elif flag == "flat_or_mixed":
        lines.append(
            "Index and breadth are mixed. Wait for a clearer day before sizing up."
        )

    # Line 3 — regime context
    if regime_label == "uptrend":
        lines.append(
            "The bigger trend is still up on the desk's 50-day and 200-day checks — one rough day does not flip that by itself."
        )
    elif regime_label == "selloff":
        lines.append(
            "Breadth looks weak on the 50-day check. Treat rallies as research time, not a green light."
        )
    elif regime_label == "chop":
        lines.append(
            "The desk is in chop — not a clean uptrend or selloff. Expect back-and-forth days."
        )

    # Cap at 3; always at least 2 when we have any signal.
    lines = [ln for ln in lines if ln][:3]
    if len(lines) < 2:
        lines.append("Research only — this box never picks a single stock or places a trade.")

    return {
        "title": "What it means for me",
        "lines": lines,
        "disclaimer": "Research only. Not advice to buy or sell any stock.",
    }
