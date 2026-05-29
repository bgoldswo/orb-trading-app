"""Backtest engine. IMPLEMENTED IN PHASE 2.

Given intraday bars and an ORBConfig, simulates ORB day by day applying the
look-ahead and cost rules, and returns (trade_log, equity_curve). Must be
deterministic: identical inputs produce identical outputs.
"""

from __future__ import annotations


def run_backtest(bars_by_symbol, cfg):
    raise NotImplementedError("Implemented in Phase 2.")
