"""Performance metrics.

From a trade log and equity curve, computes: total return, win rate, max
drawdown, Sharpe (annualized, with stated risk-free assumption), and a
trade-by-trade summary. Sharpe on a small number of intraday trades is noisy —
``num_trades`` is reported alongside it so a flattering ratio on five trades is
not mistaken for an edge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Trading days per year for annualizing a daily-sampled Sharpe.
TRADING_DAYS = 252
# Risk-free rate assumption baked into Sharpe (stated, not hidden).
RISK_FREE_RATE = 0.0


@dataclass(frozen=True)
class Performance:
    num_trades: int
    wins: int
    losses: int
    win_rate: float           # fraction in [0, 1]
    total_return: float       # fraction over the whole curve
    starting_equity: float
    final_equity: float
    max_drawdown: float       # fraction in [0, 1], reported as a positive number
    sharpe: float             # annualized, rf=RISK_FREE_RATE; NaN if undefined
    sharpe_trading_days: int  # = TRADING_DAYS, so the annualization is explicit
    avg_r_multiple: float     # mean realized R across trades
    profit_factor: float      # gross profit / gross loss; inf if no losers

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve is None or len(equity_curve) < 2:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return abs(float(drawdown.min()))  # min is <= 0; report magnitude (no -0.0)


def _sharpe(equity_curve: pd.Series) -> float:
    if equity_curve is None or len(equity_curve) < 3:
        return math.nan
    returns = equity_curve.pct_change().dropna()
    if returns.empty:
        return math.nan
    std = returns.std(ddof=1)
    if std == 0 or np.isnan(std):
        return math.nan
    excess = returns.mean() - RISK_FREE_RATE / TRADING_DAYS
    return float(excess / std * math.sqrt(TRADING_DAYS))


def performance_summary(trade_log: pd.DataFrame, equity_curve: pd.Series) -> Performance:
    """Summarize a backtest run. Robust to an empty trade log (flat curve)."""
    starting_equity = float(equity_curve.iloc[0]) if len(equity_curve) else 0.0
    final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) else 0.0
    total_return = (
        final_equity / starting_equity - 1.0 if starting_equity else 0.0
    )

    num_trades = int(len(trade_log))
    if num_trades:
        pnl = trade_log["pnl"]
        wins = int((pnl > 0).sum())
        losses = int((pnl < 0).sum())
        win_rate = wins / num_trades
        avg_r = float(trade_log["r_multiple"].mean())
        gross_profit = float(pnl[pnl > 0].sum())
        gross_loss = float(-pnl[pnl < 0].sum())
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else math.inf
        )
    else:
        wins = losses = 0
        win_rate = 0.0
        avg_r = 0.0
        profit_factor = math.nan

    return Performance(
        num_trades=num_trades,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_return=total_return,
        starting_equity=starting_equity,
        final_equity=final_equity,
        max_drawdown=_max_drawdown(equity_curve),
        sharpe=_sharpe(equity_curve),
        sharpe_trading_days=TRADING_DAYS,
        avg_r_multiple=avg_r,
        profit_factor=profit_factor,
    )
