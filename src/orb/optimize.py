"""Walk-forward parameter optimization (Phase 4.5).

The point: let the *machine* choose the strategy parameters — honestly. A naive
grid search over all history would overfit and lie. Walk-forward optimization
avoids that:

    1. Optimize parameters on an IN-SAMPLE window.
    2. Apply the chosen parameters to the NEXT, unseen OUT-OF-SAMPLE window.
    3. Roll forward and repeat.
    4. Stitch the out-of-sample slices into one equity curve — that curve is the
       honest estimate of what "let the bot pick" would actually have delivered.

The gap between in-sample and out-of-sample scores is the overfitting tell: if
OOS is much worse than IS, the "edge" was curve-fitting. This module reports both
so the result can't flatter itself.

Optimization cannot create an edge that isn't in the data — if ORB has none on a
universe, walk-forward will show that plainly. That's a feature.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .backtest import run_backtest
from .config import ORBConfig
from .metrics import Performance, performance_summary

ET = "America/New_York"

# Full search space (every knob the bot may choose).
DEFAULT_SEARCH_SPACE: dict[str, list] = {
    "opening_range_minutes": [5, 15, 30],
    "take_profit_r": [1.5, 2.0, 2.5, 3.0],
    "direction": ["long_only", "long_short"],
    "use_gap_filter": [False, True],
    "use_or_width_filter": [False, True],
}

OBJECTIVES = ("avg_r", "sharpe", "total_return", "profit_factor")


# --------------------------------------------------------------------------- #
# grid + scoring
# --------------------------------------------------------------------------- #
def generate_grid(space: dict[str, list]) -> list[dict]:
    """All parameter combinations as a deterministic list of override dicts."""
    keys = list(space)
    return [dict(zip(keys, values)) for values in itertools.product(*(space[k] for k in keys))]


def _metric(perf: Performance, objective: str) -> float:
    """Raw objective value (may be nan/inf); no trade-count guard applied."""
    value = {
        "avg_r": perf.avg_r_multiple,
        "sharpe": perf.sharpe,
        "total_return": perf.total_return,
        "profit_factor": perf.profit_factor,
    }.get(objective)
    if value is None:
        raise ValueError(f"unknown objective: {objective!r} (choose from {OBJECTIVES})")
    return float(value)


def _score(perf: Performance, objective: str, min_trades: int) -> float:
    """Objective value with a minimum-trades guard so a 2-trade fluke can't win."""
    if perf.num_trades < min_trades:
        return float("-inf")
    value = _metric(perf, objective)
    if math.isnan(value):
        return float("-inf")
    return value


# --------------------------------------------------------------------------- #
# windows
# --------------------------------------------------------------------------- #
def make_folds(
    data_start: date, data_end: date, is_days: int, oos_days: int, step_days: int | None = None
) -> list[tuple[date, date, date, date]]:
    """Rolling (is_start, is_end, oos_start, oos_end) windows; end is exclusive.

    The final OOS window may be shorter if the data runs out — it still uses all
    available data rather than discarding the tail.
    """
    step_days = step_days or oos_days
    one = timedelta(days=1)
    folds: list[tuple[date, date, date, date]] = []
    t = data_start
    while True:
        is_end = t + timedelta(days=is_days)
        oos_start = is_end
        if oos_start > data_end:
            break
        oos_end = min(oos_start + timedelta(days=oos_days), data_end + one)
        folds.append((t, is_end, oos_start, oos_end))
        t = t + timedelta(days=step_days)
    return folds


def _ts(d: date) -> pd.Timestamp:
    return pd.Timestamp(d).tz_localize(ET)


def _slice(bars_by_symbol: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Bars with timestamp in [start, end). Symbols with no bars are dropped."""
    out = {}
    for sym, df in bars_by_symbol.items():
        if df is None or df.empty:
            continue
        sub = df.loc[(df.index >= start) & (df.index < end)]
        if not sub.empty:
            out[sym] = sub
    return out


def _data_bounds(bars_by_symbol: dict[str, pd.DataFrame]) -> tuple[date | None, date | None]:
    lo = hi = None
    for df in bars_by_symbol.values():
        if df is None or df.empty:
            continue
        d0, d1 = df.index.min().date(), df.index.max().date()
        lo = d0 if lo is None or d0 < lo else lo
        hi = d1 if hi is None or d1 > hi else hi
    return lo, hi


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
@dataclass
class Fold:
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    best_params: dict
    is_objective: float   # chosen metric, in-sample (what optimization saw)
    is_trades: int
    oos_objective: float  # SAME metric, out-of-sample (the honest check)
    oos_trades: int
    oos_return: float


@dataclass
class WalkForwardResult:
    objective: str
    folds: list[Fold]
    oos_equity_curve: pd.Series
    oos_trade_log: pd.DataFrame
    oos_performance: Performance        # over the stitched OOS curve
    mean_is_objective: float
    mean_oos_objective: float

    @property
    def overfitting_gap(self) -> float:
        """IS minus OOS objective (positive = OOS worse = curve-fitting)."""
        return self.mean_is_objective - self.mean_oos_objective


def optimize_window(is_bars: dict, base_cfg, grid: list[dict], objective: str, min_trades: int):
    """Grid-search one in-sample window; return (best_params, best_score, best_perf)."""
    best_params = None
    best_score = float("-inf")
    best_perf = None
    for combo in grid:  # deterministic order; strict > keeps the first on ties
        cfg = dataclasses.replace(base_cfg, **combo)
        log, curve = run_backtest(is_bars, cfg)
        perf = performance_summary(log, curve)
        score = _score(perf, objective, min_trades)
        if score > best_score:
            best_score, best_params, best_perf = score, combo, perf
    return best_params, best_score, best_perf


def walk_forward(
    bars_by_symbol: dict[str, pd.DataFrame],
    base_cfg: ORBConfig | None = None,
    space: dict[str, list] | None = None,
    *,
    is_days: int = 365,
    oos_days: int = 90,
    step_days: int | None = None,
    objective: str = "avg_r",
    min_trades: int = 10,
) -> WalkForwardResult:
    """Run walk-forward optimization and return per-fold + stitched OOS results.

    Deterministic: identical inputs produce identical outputs. OOS equity
    compounds across folds (each fold starts from the prior fold's ending equity),
    so the stitched curve reads like one continuous account.
    """
    base_cfg = base_cfg or ORBConfig()
    space = space or DEFAULT_SEARCH_SPACE
    grid = generate_grid(space)

    data_start, data_end = _data_bounds(bars_by_symbol)
    if data_start is None:
        raise ValueError("no data to optimize over")

    running = float(base_cfg.starting_equity)
    folds: list[Fold] = []
    oos_logs: list[pd.DataFrame] = []
    curve_index: list[pd.Timestamp] = []
    curve_vals: list[float] = []
    first_oos_date: date | None = None

    for is_s, is_e, oos_s, oos_e in make_folds(data_start, data_end, is_days, oos_days, step_days):
        is_bars = _slice(bars_by_symbol, _ts(is_s), _ts(is_e))
        if not is_bars:
            continue
        best, is_score, is_perf = optimize_window(is_bars, base_cfg, grid, objective, min_trades)
        if best is None:
            continue

        oos_bars = _slice(bars_by_symbol, _ts(oos_s), _ts(oos_e))
        oos_cfg = dataclasses.replace(base_cfg, starting_equity=running, **best)
        log, curve = run_backtest(oos_bars, oos_cfg)
        oos_perf = performance_summary(log, curve)

        daily = curve.iloc[1:]  # drop the synthetic leading point
        curve_index.extend(daily.index)
        curve_vals.extend(float(v) for v in daily.values)
        if not daily.empty:
            running = float(daily.iloc[-1])
        if first_oos_date is None:
            first_oos_date = oos_s
        oos_logs.append(log)

        folds.append(
            Fold(
                is_start=is_s.isoformat(), is_end=is_e.isoformat(),
                oos_start=oos_s.isoformat(), oos_end=oos_e.isoformat(),
                best_params=best,
                is_objective=round(is_score, 4),
                is_trades=is_perf.num_trades,
                oos_objective=round(_metric(oos_perf, objective), 4) if oos_perf.num_trades else float("nan"),
                oos_trades=oos_perf.num_trades,
                oos_return=round(oos_perf.total_return, 6),
            )
        )

    lead = (_ts(first_oos_date) - pd.Timedelta(days=1)) if first_oos_date else pd.Timestamp.min
    oos_curve = pd.Series(
        [float(base_cfg.starting_equity)] + curve_vals, index=[lead] + curve_index, name="equity"
    )
    oos_log = pd.concat(oos_logs, ignore_index=True) if oos_logs else pd.DataFrame()
    oos_perf_total = performance_summary(oos_log, oos_curve)

    finite_is = [f.is_objective for f in folds if math.isfinite(f.is_objective)]
    finite_oos = [f.oos_objective for f in folds if math.isfinite(f.oos_objective)]
    mean_is = sum(finite_is) / len(finite_is) if finite_is else float("nan")
    mean_oos = sum(finite_oos) / len(finite_oos) if finite_oos else float("nan")

    return WalkForwardResult(
        objective=objective,
        folds=folds,
        oos_equity_curve=oos_curve,
        oos_trade_log=oos_log,
        oos_performance=oos_perf_total,
        mean_is_objective=mean_is,
        mean_oos_objective=mean_oos,
    )


def folds_to_frame(result: WalkForwardResult) -> pd.DataFrame:
    """Per-fold summary as a DataFrame (handy for printing or the dashboard)."""
    rows = []
    for f in result.folds:
        row = {"oos_window": f"{f.oos_start}→{f.oos_end}", **f.best_params,
               f"IS_{result.objective}": f.is_objective, "IS_trades": f.is_trades,
               f"OOS_{result.objective}": f.oos_objective, "OOS_trades": f.oos_trades,
               "OOS_return": f.oos_return}
        rows.append(row)
    return pd.DataFrame(rows)
