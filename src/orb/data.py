"""Intraday OHLCV loading. IMPLEMENTED IN PHASE 2.

Contract (to be honored by the implementation):
- Returns a tidy DataFrame indexed by timezone-aware ET timestamps with columns
  [open, high, low, close, volume], one row per `bar_minutes` bar, RTH only.
- Splits/dividends handled consistently; no survivorship gaps for the symbols
  requested.
- Source (Alpaca / Polygon / other) is chosen via .env; see docs/SPEC.md.
"""

from __future__ import annotations


def load_intraday(symbol: str, start: str, end: str, bar_minutes: int):
    raise NotImplementedError("Implemented in Phase 2.")
