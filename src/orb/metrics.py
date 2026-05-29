"""Performance metrics. IMPLEMENTED IN PHASE 2.

From a trade log and equity curve, computes: total return, win rate, max
drawdown, Sharpe (annualized, with stated risk-free assumption), and a
trade-by-trade summary. Sharpe on a small number of intraday trades is noisy —
report trade count alongside it.
"""

from __future__ import annotations


def performance_summary(trade_log, equity_curve):
    raise NotImplementedError("Implemented in Phase 2.")
