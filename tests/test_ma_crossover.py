"""EMA-crossover strategy: signal generation, look-ahead safety, engine wiring."""

from __future__ import annotations

import dataclasses

import pandas as pd

from orb.backtest import run_backtest
from orb.config import ORBConfig
from orb.ma_crossover import generate_ma_signals
from orb.strategy import LONG
from synthetic import ET, day_index

DATE = "2024-03-04"


def _day_from_closes(closes: list[float]) -> pd.DataFrame:
    """Build a day where each bar's OHLC == the given close (clean for EMA tests)."""
    idx = day_index(DATE)[: len(closes)]
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0},
        index=idx,
    )
    df.index.name = "timestamp"
    return df


def _cfg(**kw):
    defaults = {"fast_ema": 3, "slow_ema": 6, "ma_stop_pct": 0.01}
    return dataclasses.replace(ORBConfig(), **{**defaults, **kw})


def test_no_signal_without_a_crossover():
    # Monotonically rising: fast stays above slow the whole time -> no cross.
    df = _day_from_closes([100 + i * 0.1 for i in range(60)])
    assert generate_ma_signals(df, _cfg()) == []


def test_detects_upward_crossover_and_enters_next_bar():
    # Down for a while (fast below slow), then a sharp sustained rally -> fast
    # crosses above slow; signal should fire and enter on the NEXT bar's open.
    closes = [100 - i * 0.2 for i in range(20)] + [96 + i * 0.5 for i in range(20)]
    df = _day_from_closes(closes)
    sigs = generate_ma_signals(df, _cfg())
    assert len(sigs) == 1
    s = sigs[0]
    assert s.direction == LONG
    assert s.entry_ts > s.confirmation_ts                       # next-bar entry
    assert s.reference_entry == df["open"].loc[s.entry_ts]      # the next bar's open
    assert s.stop_level == s.reference_entry * (1 - 0.01)       # % stop below entry


def test_long_only_default_ignores_downward_cross():
    closes = [100 + i * 0.2 for i in range(20)] + [104 - i * 0.5 for i in range(20)]
    df = _day_from_closes(closes)
    assert generate_ma_signals(df, _cfg(direction="long_only")) == []
    short = generate_ma_signals(df, _cfg(direction="long_short"))
    assert len(short) == 1 and short[0].direction == "short"


def test_fast_not_faster_than_slow_yields_nothing():
    df = _day_from_closes([100 + i for i in range(30)])
    assert generate_ma_signals(df, _cfg(fast_ema=20, slow_ema=10)) == []


def test_runs_through_backtest_via_signal_fn():
    # A rally day that crosses up then runs into the target; the engine should
    # produce exactly one trade using the injected MA signal generator.
    closes = [100 - i * 0.2 for i in range(15)] + [97 + i * 0.6 for i in range(40)]
    df = _day_from_closes(closes)
    log, curve = run_backtest({"SPY": df}, _cfg(), signal_fn=generate_ma_signals)
    assert len(log) == 1
    assert log.iloc[0]["direction"] == "long"
