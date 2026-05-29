"""ORB signal logic.

LOOK-AHEAD SAFETY CONTRACT (do not violate when implementing):
- OR_high / OR_low are fixed only AFTER the opening-range window closes. No bar
  inside or after the window may use information from later bars.
- A breakout is detected on a COMPLETED bar (bar_close confirmation). The entry
  is executed at the NEXT bar's open. We never assume a fill at a price the bar
  had not yet traded through at the moment of the decision.
- If a single bar's range spans BOTH the stop and the target, the intrabar path
  is unknown from OHLC alone — resolve conservatively (assume the stop hit
  first). This is the easiest place to accidentally inflate results. (Resolved
  in backtest.py; this module only emits look-ahead-safe entry signals.)

This module is pure: it takes one trading day's bars + an ORBConfig and returns
opening-range levels and entry signals. It does not size, fill, or apply costs —
that is the backtest engine's job. Cost-free separation keeps the look-ahead
contract easy to audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

import pandas as pd

# Direction labels used across strategy/backtest.
LONG = "long"
SHORT = "short"

# Required OHLC columns for any bars frame passed in.
_OHLC = ("open", "high", "low", "close")


@dataclass(frozen=True)
class OpeningRange:
    """Levels fixed once the opening-range window has closed."""

    high: float
    low: float
    start: pd.Timestamp  # first bar timestamp inside the window
    end: time            # window close (time-of-day); bars at/after this are post-OR


@dataclass(frozen=True)
class Signal:
    """A look-ahead-safe entry signal. Prices here are pre-cost reference prices;
    the backtest applies slippage/commission when filling."""

    direction: str               # LONG | SHORT
    confirmation_ts: pd.Timestamp  # bar whose CLOSE confirmed the breakout
    entry_ts: pd.Timestamp         # NEXT bar — where the entry is actually filled
    reference_entry: float         # that next bar's open (pre-cost)
    or_high: float
    or_low: float


def _parse_time(value: str) -> time:
    """'09:30' -> datetime.time(9, 30)."""
    return time.fromisoformat(value)


def _or_end_time(cfg) -> time:
    """Time-of-day at which the opening-range window closes (exclusive)."""
    open_t = _parse_time(cfg.session_open)
    end_dt = datetime.combine(datetime.min, open_t) + timedelta(
        minutes=cfg.opening_range_minutes
    )
    return end_dt.time()


def _validate(bars: pd.DataFrame) -> None:
    missing = [c for c in _OHLC if c not in bars.columns]
    if missing:
        raise ValueError(f"bars missing required columns: {missing}")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must be indexed by a tz-aware DatetimeIndex")
    if bars.index.tz is None:
        raise ValueError("bars index must be timezone-aware (exchange-local ET)")
    if not bars.index.is_monotonic_increasing:
        raise ValueError("bars index must be sorted ascending")


def compute_opening_range(bars: pd.DataFrame, cfg) -> OpeningRange | None:
    """Compute OR_high/OR_low from the first ``opening_range_minutes`` of one
    trading day's bars.

    Returns ``None`` if there are no bars inside the window (e.g. a half day or
    missing data). The range is intentionally derived ONLY from bars whose
    timestamp falls in ``[session_open, session_open + N)`` — never later bars.
    """
    _validate(bars)
    if bars.empty:
        return None

    open_t = _parse_time(cfg.session_open)
    end_t = _or_end_time(cfg)
    tod = bars.index.time

    in_window = (tod >= open_t) & (tod < end_t)
    window = bars.loc[in_window]
    if window.empty:
        return None

    return OpeningRange(
        high=float(window["high"].max()),
        low=float(window["low"].min()),
        start=window.index[0],
        end=end_t,
    )


def generate_signals(bars: pd.DataFrame, cfg) -> list[Signal]:
    """Emit look-ahead-safe entry signals for one trading day.

    - Confirmation: a COMPLETED post-OR bar closes beyond the OR level
      (``bar_close``, default) or trades beyond it (``intrabar``).
    - Entry: the OPEN of the NEXT bar after the confirming bar. A confirmation on
      the day's last bar yields no signal (no next bar to enter on).
    - Direction: ``long_only`` takes only upside breakouts; ``long_short`` takes
      whichever side confirms first.
    - At most ``max_trades_per_day`` signals (default 1 = first valid breakout).
    """
    _validate(bars)
    rng = compute_opening_range(bars, cfg)
    if rng is None:
        return []

    end_t = rng.end
    eod_t = _parse_time(cfg.eod_flat_time)
    tod = bars.index.time

    # Post-OR bars only. Breakouts before the window closes are not real signals.
    post_or = bars.loc[tod >= end_t]
    if len(post_or) < 2:  # need a confirming bar AND a next bar to enter on
        return []

    allow_short = cfg.direction == "long_short"
    intrabar = cfg.breakout_confirmation == "intrabar"

    signals: list[Signal] = []
    # Iterate every bar except the last: each must have a NEXT bar for entry.
    for i in range(len(post_or) - 1):
        bar = post_or.iloc[i]
        nxt = post_or.iloc[i + 1]
        entry_ts = post_or.index[i + 1]

        # Don't open a position at/after the EOD flatten time.
        if entry_ts.time() >= eod_t:
            break

        long_break = (
            bar["high"] > rng.high if intrabar else bar["close"] > rng.high
        )
        short_break = (
            bar["low"] < rng.low if intrabar else bar["close"] < rng.low
        )

        direction = None
        if long_break:
            direction = LONG
        elif short_break and allow_short:
            direction = SHORT

        if direction is None:
            continue

        signals.append(
            Signal(
                direction=direction,
                confirmation_ts=post_or.index[i],
                entry_ts=entry_ts,
                reference_entry=float(nxt["open"]),
                or_high=rng.high,
                or_low=rng.low,
            )
        )
        if len(signals) >= cfg.max_trades_per_day:
            break

    return signals
