"""Opt-in day-eligibility filters: daily context, gap filter, OR-width filter.

These are OFF by default, so the first job is proving they don't change baseline
behavior, then proving each one gates the right days when switched on.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from orb.backtest import run_backtest
from orb.config import ORBConfig
from orb.filters import compute_daily_context, day_is_eligible
from orb.strategy import compute_opening_range
from synthetic import ET, flat_day, set_bar, set_opening_range

D1, D2 = "2024-03-04", "2024-03-05"


def breakout_day(date, *, or_high=100.0, or_low=99.0, open_override=None):
    """A long-breakout day that hits the 2R target (1 trade when eligible)."""
    df = flat_day(date, price=100.0)
    set_opening_range(df, date, high=or_high, low=or_low)
    set_bar(df, date, "09:45", c=100.5)
    set_bar(df, date, "09:46", o=100.5)
    set_bar(df, date, "09:50", h=104.0)
    if open_override is not None:  # force a gap at the 09:30 open
        set_bar(df, date, "09:30", o=open_override)
    return df


# --------------------------------------------------------------------------- #
# daily context
# --------------------------------------------------------------------------- #
def test_daily_context_prev_close_and_atr_are_lookahead_safe():
    day1 = flat_day(D1, price=100.0)
    set_bar(day1, D1, "11:00", h=110.0, l=90.0)  # day-1 range = 20
    day2 = flat_day(D2, price=101.0)
    ctx = compute_daily_context(pd.concat([day1, day2]), ORBConfig())

    k1 = pd.Timestamp(f"{D1} 00:00", tz=ET)
    k2 = pd.Timestamp(f"{D2} 00:00", tz=ET)
    # Prev close is yesterday's last bar; day 1 has none.
    assert pd.isna(ctx.loc[k1, "prev_close"])
    assert ctx.loc[k2, "prev_close"] == pytest.approx(100.0)
    # ATR is shifted: day 1 has no prior ATR; day 2 sees only day 1's range (20).
    assert pd.isna(ctx.loc[k1, "atr_prev"])
    assert ctx.loc[k2, "atr_prev"] == pytest.approx(20.0)


# --------------------------------------------------------------------------- #
# defaults: filters off => baseline unchanged
# --------------------------------------------------------------------------- #
def test_filters_off_by_default_takes_the_trade():
    bars = {"SPY": breakout_day(D1, open_override=110.0)}  # huge gap, but...
    log, _ = run_backtest(bars, ORBConfig())  # ...defaults don't filter
    assert len(log) == 1


# --------------------------------------------------------------------------- #
# gap filter
# --------------------------------------------------------------------------- #
def test_gap_filter_skips_large_gap_day():
    # Day 1 seeds prev_close=100; day 2 opens at 110 -> a 10% gap.
    bars = {"SPY": pd.concat([flat_day(D1, price=100.0), breakout_day(D2, open_override=110.0)])}
    cfg_on = dataclasses.replace(ORBConfig(), use_gap_filter=True)
    cfg_off = dataclasses.replace(ORBConfig(), use_gap_filter=False)
    assert len(run_backtest(bars, cfg_off)[0]) == 1   # day 2 trades
    assert len(run_backtest(bars, cfg_on)[0]) == 0     # day 2 filtered out


def test_gap_filter_allows_small_gap_day():
    # Day 2 opens at 100.3 vs prev close 100 -> 0.3% gap, under the 0.5% cap.
    bars = {"SPY": pd.concat([flat_day(D1, price=100.0), breakout_day(D2, open_override=100.3)])}
    cfg_on = dataclasses.replace(ORBConfig(), use_gap_filter=True)
    assert len(run_backtest(bars, cfg_on)[0]) == 1


def test_gap_filter_fails_closed_on_first_day():
    # No prior close to validate the gap against -> day is not tradeable.
    bars = {"SPY": breakout_day(D1)}
    cfg_on = dataclasses.replace(ORBConfig(), use_gap_filter=True)
    assert len(run_backtest(bars, cfg_on)[0]) == 0


# --------------------------------------------------------------------------- #
# OR-width / ATR filter
# --------------------------------------------------------------------------- #
def test_or_width_filter_skips_wide_range_day():
    # Day 1 establishes a daily range of 20 (ATR_prev for day 2 = 20).
    day1 = flat_day(D1, price=100.0)
    set_bar(day1, D1, "11:00", h=110.0, l=90.0)
    # Day 2's opening range is 10 wide (100..90) > 30% * 20 = 6 -> filtered.
    day2 = breakout_day(D2, or_high=100.0, or_low=90.0)
    bars = {"SPY": pd.concat([day1, day2])}

    cfg_off = dataclasses.replace(ORBConfig(), use_or_width_filter=False)
    cfg_on = dataclasses.replace(ORBConfig(), use_or_width_filter=True)
    assert len(run_backtest(bars, cfg_off)[0]) == 1
    assert len(run_backtest(bars, cfg_on)[0]) == 0


def test_or_width_filter_allows_narrow_range_day():
    day1 = flat_day(D1, price=100.0)
    set_bar(day1, D1, "11:00", h=110.0, l=90.0)  # ATR_prev = 20
    day2 = breakout_day(D2, or_high=100.0, or_low=99.0)  # OR width 1 < 6
    bars = {"SPY": pd.concat([day1, day2])}
    cfg_on = dataclasses.replace(ORBConfig(), use_or_width_filter=True)
    assert len(run_backtest(bars, cfg_on)[0]) == 1


def test_day_is_eligible_true_when_no_filter_enabled():
    df = breakout_day(D1)
    rng = compute_opening_range(df, ORBConfig())
    ctx = compute_daily_context(df, ORBConfig())
    key = pd.Timestamp(f"{D1} 00:00", tz=ET)
    # With both filters off, every day is eligible regardless of context.
    assert day_is_eligible(key, ctx, rng, ORBConfig()) is True
