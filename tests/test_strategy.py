"""Opening-range computation, entry timing, and look-ahead safety."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from orb.config import ORBConfig
from orb.strategy import LONG, SHORT, compute_opening_range, generate_signals
from synthetic import ET, flat_day, set_bar, set_opening_range

DATE = "2024-03-04"  # a Monday


def _day_with_or(high=100.0, low=99.0):
    df = flat_day(DATE, price=low)  # post-OR bars sit at OR_low: no accidental breakout
    set_opening_range(df, DATE, high=high, low=low)
    return df


def test_opening_range_uses_only_the_window():
    df = _day_with_or(high=100.0, low=99.0)
    # A post-window spike must NOT change the range.
    set_bar(df, DATE, "10:30", h=200.0, l=1.0)
    rng = compute_opening_range(df, ORBConfig())
    assert rng is not None
    assert rng.high == 100.0
    assert rng.low == 99.0
    # Window closes 15 minutes after the open.
    assert rng.end == pd.Timestamp("09:45").time()


def test_opening_range_respects_configured_minutes():
    df = flat_day(DATE, price=99.0)
    set_opening_range(df, DATE, high=100.0, low=99.0, minutes=5)
    # A higher high arrives in minute 6–15: included only when N=15, not N=5.
    set_bar(df, DATE, "09:40", h=105.0)
    cfg5 = dataclasses.replace(ORBConfig(), opening_range_minutes=5)
    cfg15 = ORBConfig()
    assert compute_opening_range(df, cfg5).high == 100.0
    assert compute_opening_range(df, cfg15).high == 105.0


def test_opening_range_none_when_window_empty():
    # A day that starts after the OR window has no bars in [09:30, 09:45).
    idx = pd.date_range(
        pd.Timestamp(f"{DATE} 10:00", tz=ET),
        pd.Timestamp(f"{DATE} 11:00", tz=ET),
        freq="1min",
        inclusive="left",
    )
    df = pd.DataFrame(
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}, index=idx
    )
    assert compute_opening_range(df, ORBConfig()) is None


def test_entry_is_next_bar_open_after_close_confirmation():
    df = _day_with_or(high=100.0, low=99.0)
    # 09:45 closes above OR_high -> confirmation on that completed bar.
    set_bar(df, DATE, "09:45", o=100.0, h=101.0, l=99.5, c=100.5)
    # 09:46 is the entry bar; its OPEN is the fill reference.
    set_bar(df, DATE, "09:46", o=100.7, h=100.8, l=100.6, c=100.75)

    sigs = generate_signals(df, ORBConfig())
    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == LONG
    assert sig.confirmation_ts == pd.Timestamp(f"{DATE} 09:45", tz=ET)
    assert sig.entry_ts == pd.Timestamp(f"{DATE} 09:46", tz=ET)
    # Look-ahead check: entry uses the NEXT bar's open, never the confirm bar's.
    assert sig.reference_entry == 100.7
    assert sig.entry_ts > sig.confirmation_ts


def test_bar_close_confirmation_ignores_intrabar_wick():
    df = _day_with_or(high=100.0, low=99.0)
    # Price pierces OR_high intrabar (high 101) but closes back inside (99.5).
    set_bar(df, DATE, "09:45", o=99.5, h=101.0, l=99.4, c=99.5)
    # Default bar_close confirmation -> no signal from a mere wick.
    assert generate_signals(df, ORBConfig()) == []
    # Intrabar confirmation -> the wick is enough to trigger.
    cfg = dataclasses.replace(ORBConfig(), breakout_confirmation="intrabar")
    sigs = generate_signals(df, cfg)
    assert len(sigs) == 1
    assert sigs[0].direction == LONG


def test_no_signal_when_confirmation_is_last_bar():
    df = _day_with_or(high=100.0, low=99.0)
    # Confirm on the final bar of the day: there is no next bar to enter on.
    set_bar(df, DATE, "15:59", c=101.0)
    assert generate_signals(df, ORBConfig()) == []


def test_long_only_ignores_downside_breakout():
    df = flat_day(DATE, price=100.0)
    set_opening_range(df, DATE, high=101.0, low=100.0)
    set_bar(df, DATE, "09:45", c=99.0)  # closes below OR_low
    set_bar(df, DATE, "09:46", o=99.0)
    assert generate_signals(df, ORBConfig()) == []  # long_only default
    cfg = dataclasses.replace(ORBConfig(), direction="long_short")
    sigs = generate_signals(df, cfg)
    assert len(sigs) == 1
    assert sigs[0].direction == SHORT


def test_one_trade_per_day_takes_first_breakout_only():
    df = _day_with_or(high=100.0, low=99.0)
    set_bar(df, DATE, "09:45", c=100.5)
    set_bar(df, DATE, "09:46", o=100.5)
    set_bar(df, DATE, "10:00", c=100.9)  # a second, later breakout
    set_bar(df, DATE, "10:01", o=100.9)
    sigs = generate_signals(df, ORBConfig())
    assert len(sigs) == 1
    assert sigs[0].confirmation_ts == pd.Timestamp(f"{DATE} 09:45", tz=ET)


def test_validate_rejects_tz_naive_index():
    df = _day_with_or().tz_localize(None)
    with pytest.raises(ValueError):
        compute_opening_range(df, ORBConfig())
