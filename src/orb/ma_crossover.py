"""Intraday EMA-crossover strategy (an alternative to ORB, same engine).

Plain idea: compute a fast and a slow EMA over the day's 1-minute closes. When the
fast EMA crosses *above* the slow one, go long; (optionally) when it crosses below,
go short. Exit via a protective % stop and an R-multiple target — the same exit
machinery the backtester already applies to ORB.

LOOK-AHEAD SAFETY (same contract as ORB):
- EMAs are causal (each bar uses only closes up to and including itself).
- A crossover is detected on a COMPLETED bar; entry is the NEXT bar's open.
- One trade per day (first crossover), respecting ``max_trades_per_day``.

This plugs into ``run_backtest(bars, cfg, signal_fn=generate_ma_signals)`` and the
optimizer, so it gets the identical honest cost model and walk-forward treatment.
"""

from __future__ import annotations

import pandas as pd

from .strategy import LONG, SHORT, Signal, _parse_time, _validate


def generate_ma_signals(bars: pd.DataFrame, cfg) -> list[Signal]:
    """Emit look-ahead-safe EMA-crossover entry signals for one trading day."""
    _validate(bars)
    fast_n, slow_n = int(cfg.fast_ema), int(cfg.slow_ema)
    if fast_n >= slow_n:
        return []  # ill-defined (fast must be faster than slow)
    if len(bars) < slow_n + 2:
        return []  # not enough bars to form the slow EMA and a next bar

    close = bars["close"]
    fast = close.ewm(span=fast_n, adjust=False).mean()
    slow = close.ewm(span=slow_n, adjust=False).mean()
    diff = fast - slow                      # >0 fast above slow
    sign = diff.where(diff != 0).ffill()    # carry sign across exact ties

    allow_short = cfg.direction == "long_short"
    eod_t = _parse_time(cfg.eod_flat_time)

    signals: list[Signal] = []
    # Start once the slow EMA has enough history to be meaningful.
    for i in range(slow_n, len(bars) - 1):
        prev, cur = sign.iloc[i - 1], sign.iloc[i]
        if pd.isna(prev) or pd.isna(cur):
            continue

        crossed_up = prev <= 0 < cur
        crossed_down = prev >= 0 > cur
        direction = None
        if crossed_up:
            direction = LONG
        elif crossed_down and allow_short:
            direction = SHORT
        if direction is None:
            continue

        entry_ts = bars.index[i + 1]
        if entry_ts.time() >= eod_t:        # don't open at/after the EOD flatten
            break
        ref_entry = float(bars["open"].iloc[i + 1])

        # Protective % stop from the entry; target derived via take_profit_r.
        if direction == LONG:
            stop_level = ref_entry * (1.0 - cfg.ma_stop_pct)
        else:
            stop_level = ref_entry * (1.0 + cfg.ma_stop_pct)

        signals.append(
            Signal(
                direction=direction,
                confirmation_ts=bars.index[i],
                entry_ts=entry_ts,
                reference_entry=ref_entry,
                stop_level=float(stop_level),
            )
        )
        if len(signals) >= cfg.max_trades_per_day:
            break

    return signals
