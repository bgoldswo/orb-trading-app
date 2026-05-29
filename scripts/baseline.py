"""Phase 2 baseline run: vanilla ORB vs. opt-in filters on SPY+QQQ.

Honest A/B per docs/SPEC.md — establish the plain-ORB baseline first, then see
whether the gap / OR-width filters actually improve out-of-sample results.

Usage:  python scripts/baseline.py [START END]
First fetch hits Alpaca; subsequent runs use the data/cache/ files.
"""

from __future__ import annotations

import dataclasses
import sys

from orb.backtest import run_backtest
from orb.config import ORBConfig
from orb.data import load_intraday
from orb.metrics import performance_summary

START = sys.argv[1] if len(sys.argv) > 2 else "2024-05-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-05-28"


def fmt(perf) -> str:
    return (
        f"trades={perf.num_trades:>4}  win={perf.win_rate:6.1%}  "
        f"ret={perf.total_return:8.2%}  maxDD={perf.max_drawdown:6.2%}  "
        f"sharpe={perf.sharpe:6.2f}  avgR={perf.avg_r_multiple:6.2f}  "
        f"PF={perf.profit_factor:5.2f}  final=${perf.final_equity:,.0f}"
    )


def main() -> None:
    cfg = ORBConfig()
    print(f"Window: {START} -> {END}   Symbols: {cfg.symbols}\n")

    bars = {}
    for sym in cfg.symbols:
        df = load_intraday(sym, START, END, cfg.bar_minutes)
        bars[sym] = df
        print(f"  loaded {sym}: {len(df):,} bars "
              f"({df.index.min().date()} .. {df.index.max().date()})")
    print()

    runs = {
        "vanilla ORB           ": cfg,
        "+ gap filter          ": dataclasses.replace(cfg, use_gap_filter=True),
        "+ OR-width filter     ": dataclasses.replace(cfg, use_or_width_filter=True),
        "+ both filters        ": dataclasses.replace(
            cfg, use_gap_filter=True, use_or_width_filter=True
        ),
    }
    for label, c in runs.items():
        log, curve = run_backtest(bars, c)
        print(f"{label} {fmt(performance_summary(log, curve))}")


if __name__ == "__main__":
    main()
