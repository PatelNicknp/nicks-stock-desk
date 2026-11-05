"""Market News pack — overall-market brief for Nick's Stock Desk.

Research / signals only. Never places trades. Never calls a broker.
Free sources only (RSS / public JSON). No API keys. No extra Yahoo load.
"""

from .brief import build_brief, publish

__all__ = ["build_brief", "publish"]
