"""Performance metrics: return, win rate, drawdown, Sharpe, profit factor."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from orb.metrics import TRADING_DAYS, performance_summary


def _curve(values):
    idx = pd.date_range("2024-03-01", periods=len(values), freq="D")
    return pd.Series([float(v) for v in values], index=idx, name="equity")


def test_summary_on_a_known_run():
    curve = _curve([100_000, 110_000, 99_000, 108_900])
    trades = pd.DataFrame(
        {"pnl": [10_000.0, -11_000.0, 9_900.0], "r_multiple": [2.0, -1.1, 1.98]}
    )
    perf = performance_summary(trades, curve)

    assert perf.num_trades == 3
    assert perf.wins == 2 and perf.losses == 1
    assert perf.win_rate == pytest.approx(2 / 3)
    assert perf.total_return == pytest.approx(0.089, abs=1e-9)
    assert perf.starting_equity == 100_000 and perf.final_equity == 108_900
    # Peak 110k -> trough 99k is a 10% drawdown.
    assert perf.max_drawdown == pytest.approx(0.10, abs=1e-9)
    assert perf.profit_factor == pytest.approx(19_900 / 11_000, abs=1e-9)
    assert perf.avg_r_multiple == pytest.approx((2.0 - 1.1 + 1.98) / 3)
    assert perf.sharpe_trading_days == TRADING_DAYS
    assert math.isfinite(perf.sharpe) and perf.sharpe > 0


def test_profit_factor_infinite_when_no_losers():
    curve = _curve([100_000, 101_000, 102_000])
    trades = pd.DataFrame({"pnl": [1_000.0, 1_000.0], "r_multiple": [1.0, 1.0]})
    perf = performance_summary(trades, curve)
    assert perf.losses == 0
    assert math.isinf(perf.profit_factor)


def test_empty_trade_log_is_flat_and_safe():
    curve = _curve([100_000, 100_000])
    trades = pd.DataFrame(columns=["pnl", "r_multiple"])
    perf = performance_summary(trades, curve)
    assert perf.num_trades == 0
    assert perf.win_rate == 0.0
    assert perf.total_return == pytest.approx(0.0)
    assert perf.max_drawdown == pytest.approx(0.0)
    assert math.isnan(perf.profit_factor)
    assert math.isnan(perf.sharpe)  # undefined with no return dispersion


def test_max_drawdown_is_reported_as_positive_fraction():
    curve = _curve([100_000, 120_000, 60_000, 90_000])
    perf = performance_summary(pd.DataFrame({"pnl": [], "r_multiple": []}), curve)
    # Peak 120k -> trough 60k = 50% drawdown.
    assert perf.max_drawdown == pytest.approx(0.5, abs=1e-9)
