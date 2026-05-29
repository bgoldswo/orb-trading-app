"""CLI: walk-forward parameter optimization — let the bot pick the parameters.

Optimizes the strategy on rolling in-sample windows and reports the honest
OUT-OF-SAMPLE performance (plus the in-sample-vs-out-of-sample gap, which exposes
overfitting). Places no orders; this is analysis only.

Usage:
    python scripts/optimize.py                       # SPY QQQ, ~2y, defaults
    python scripts/optimize.py NVDA TSLA --start 2023-01-01 --end 2025-12-31
    python scripts/optimize.py --is-days 365 --oos-days 90 --objective avg_r
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from orb.config import ORBConfig
from orb.data import load_intraday
from orb.metrics import performance_summary  # noqa: F401  (kept for parity/debugging)
from orb.optimize import OBJECTIVES, folds_to_frame, walk_forward

ET = "America/New_York"


def _args(argv):
    p = argparse.ArgumentParser(description="Walk-forward ORB optimization (no orders).")
    p.add_argument("symbols", nargs="*", help="Symbols (default: ORBConfig.symbols).")
    today = pd.Timestamp.now(tz=ET).normalize()
    p.add_argument("--start", default=(today - pd.DateOffset(years=2)).date().isoformat())
    p.add_argument("--end", default=(today - pd.Timedelta(days=1)).date().isoformat())
    p.add_argument("--is-days", type=int, default=365, help="In-sample window length (days).")
    p.add_argument("--oos-days", type=int, default=90, help="Out-of-sample window length (days).")
    p.add_argument("--objective", choices=OBJECTIVES, default="avg_r")
    p.add_argument("--min-trades", type=int, default=10, help="Min IS trades for a combo to qualify.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    a = _args(argv if argv is not None else sys.argv[1:])
    cfg = ORBConfig()
    symbols = [s.upper() for s in a.symbols] if a.symbols else cfg.symbols
    cfg = ORBConfig(**{**cfg.__dict__, "symbols": symbols})

    print(f"Walk-forward optimization on {symbols}  ({a.start} -> {a.end})")
    print(f"  IS={a.is_days}d  OOS={a.oos_days}d  objective={a.objective}  min_trades={a.min_trades}")
    try:
        bars = {s: load_intraday(s, a.start, a.end, cfg.bar_minutes) for s in symbols}
    except Exception as exc:
        print(f"ERROR loading data: {exc}", file=sys.stderr)
        return 2

    result = walk_forward(
        bars, cfg, is_days=a.is_days, oos_days=a.oos_days,
        objective=a.objective, min_trades=a.min_trades,
    )
    if not result.folds:
        print("Not enough data for a single IS+OOS fold. Widen the date range or shorten the windows.")
        return 1

    print("\nPer-fold (chosen params + in-sample vs out-of-sample):")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(folds_to_frame(result).to_string(index=False))

    p = result.oos_performance
    print("\nStitched OUT-OF-SAMPLE performance (what 'bot picks' would have delivered):")
    print(f"  trades={p.num_trades}  win={p.win_rate:.1%}  return={p.total_return:.2%}  "
          f"maxDD={p.max_drawdown:.2%}  sharpe={p.sharpe:.2f}  avgR={p.avg_r_multiple:+.3f}  "
          f"PF={p.profit_factor:.2f}")
    print(f"\nOverfitting check ({a.objective}):  IS mean={result.mean_is_objective:.3f}  "
          f"OOS mean={result.mean_oos_objective:.3f}  gap={result.overfitting_gap:+.3f}")
    print("  (A large positive gap = the in-sample 'edge' did not survive out of sample.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
