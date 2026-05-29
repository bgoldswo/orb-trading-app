"""Walk-forward optimizer: grid, folds, objective guard, determinism, end-to-end."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from orb.config import ORBConfig
from orb.metrics import performance_summary
from orb.optimize import (
    DEFAULT_SEARCH_SPACE,
    _score,
    generate_grid,
    make_folds,
    walk_forward,
)
from orb.backtest import run_backtest
from synthetic import ET, day_index, set_bar, set_opening_range


# --------------------------------------------------------------------------- #
# grid + folds + scoring (pure)
# --------------------------------------------------------------------------- #
def test_generate_grid_covers_full_product():
    grid = generate_grid(DEFAULT_SEARCH_SPACE)
    assert len(grid) == 3 * 4 * 2 * 2 * 2  # 96 combinations
    assert {"opening_range_minutes", "take_profit_r", "direction",
            "use_gap_filter", "use_or_width_filter"} == set(grid[0])
    assert len({tuple(sorted(c.items())) for c in grid}) == len(grid)  # all unique


def test_make_folds_roll_forward():
    folds = make_folds(date(2024, 1, 1), date(2024, 5, 30), is_days=60, oos_days=30)
    # IS=60, OOS=30, step=30 across ~150 days -> several non-overlapping OOS windows.
    assert folds[0][0] == date(2024, 1, 1)
    assert folds[0][1] == date(2024, 3, 1)          # is_end = start + 60d
    assert folds[0][2] == date(2024, 3, 1)          # oos_start == is_end
    # OOS windows step by oos_days and don't overlap.
    assert folds[1][2] == folds[0][2] + (folds[0][3] - folds[0][2])


def test_score_applies_min_trades_guard():
    class P:  # minimal stand-in for Performance
        def __init__(self, n, r):
            self.num_trades, self.avg_r_multiple = n, r
            self.sharpe = self.total_return = self.profit_factor = 0.0
    assert _score(P(5, 2.0), "avg_r", min_trades=10) == float("-inf")  # too few trades
    assert _score(P(20, 2.0), "avg_r", min_trades=10) == 2.0           # qualifies


# --------------------------------------------------------------------------- #
# end-to-end on synthetic months of data
# --------------------------------------------------------------------------- #
def _mini_day(d: str, *, win: bool) -> pd.DataFrame:
    """A compact session: OR 09:30–09:44, breakout at 09:45, resolve by 09:50."""
    idx = day_index(d, end="10:00")  # 30 one-minute bars
    df = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000},
        index=idx,
    )
    df.index.name = "timestamp"
    set_opening_range(df, d, high=100.0, low=99.0)
    set_bar(df, d, "09:45", c=100.5)   # confirm long
    set_bar(df, d, "09:46", o=100.5)   # entry reference
    set_bar(df, d, "09:50", h=104.0 if win else 100.2, l=98.0 if not win else 100.0)
    return df


def _months_of_bars(start: str, periods: int, win: bool) -> pd.DataFrame:
    days = pd.bdate_range(start, periods=periods, tz=ET)
    return pd.concat([_mini_day(d.strftime("%Y-%m-%d"), win=win) for d in days])


# Small space keeps these end-to-end tests fast — the walk-forward machinery is
# identical regardless of grid size (the full 96-combo grid is exercised via the
# real CLI run, not the unit suite).
_SMALL_SPACE = {"opening_range_minutes": [5, 15], "take_profit_r": [2.0]}


def test_walk_forward_runs_and_is_deterministic():
    bars = {"SPY": _months_of_bars("2024-01-01", periods=100, win=True)}
    kw = dict(space=_SMALL_SPACE, is_days=60, oos_days=30, objective="avg_r",
              min_trades=5, workers=1)  # serial keeps the unit test fast
    r1 = walk_forward(bars, ORBConfig(), **kw)
    r2 = walk_forward(bars, ORBConfig(), **kw)

    assert len(r1.folds) >= 2
    # Every fold chose valid params and traded out-of-sample.
    for f in r1.folds:
        assert f.best_params["opening_range_minutes"] in (5, 15, 30)
        assert f.oos_trades > 0
    # Deterministic: same chosen params and OOS curve on a repeat run.
    assert [f.best_params for f in r1.folds] == [f.best_params for f in r2.folds]
    pd.testing.assert_series_equal(r1.oos_equity_curve, r2.oos_equity_curve)


def test_parallel_matches_serial():
    # The parallel in-sample search must yield byte-identical results to serial.
    bars = {"SPY": _months_of_bars("2024-01-01", periods=90, win=True)}
    kw = dict(space=_SMALL_SPACE, is_days=60, oos_days=30, objective="avg_r", min_trades=5)
    serial = walk_forward(bars, ORBConfig(), workers=1, **kw)
    parallel = walk_forward(bars, ORBConfig(), workers=2, **kw)
    assert [f.best_params for f in serial.folds] == [f.best_params for f in parallel.folds]
    pd.testing.assert_series_equal(serial.oos_equity_curve, parallel.oos_equity_curve)


def test_walk_forward_oos_curve_compounds_to_final_equity():
    bars = {"SPY": _months_of_bars("2024-01-01", periods=100, win=True)}
    r = walk_forward(bars, ORBConfig(), space=_SMALL_SPACE, is_days=60, oos_days=30,
                     objective="avg_r", min_trades=5, workers=1)
    # The stitched OOS curve starts at starting_equity and ends above it (winning days).
    assert r.oos_equity_curve.iloc[0] == pytest.approx(ORBConfig().starting_equity)
    assert r.oos_performance.final_equity == pytest.approx(r.oos_equity_curve.iloc[-1])
    assert r.oos_performance.total_return > 0  # this synthetic set always hits target


def test_walk_forward_raises_without_data():
    with pytest.raises(ValueError):
        walk_forward({"SPY": pd.DataFrame()}, ORBConfig())
