"""Backtest engine: fills, stop/target resolution, cost model, determinism."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from orb.backtest import EOD, STOP, TARGET, run_backtest
from orb.config import ORBConfig
from synthetic import ET, flat_day, set_bar, set_opening_range

DATE = "2024-03-04"


def trade_day(date=DATE, *, confirm_close=100.5, entry_open=100.5):
    """A day that confirms a long at 09:45 and enters at 09:46. Post-OR baseline
    sits at 100 (inside OR_high) so nothing triggers until a bar we set."""
    df = flat_day(date, price=100.0)
    set_opening_range(df, date, high=100.0, low=99.0)
    set_bar(df, date, "09:45", c=confirm_close)
    set_bar(df, date, "09:46", o=entry_open)
    return df


def only_trade(trade_log: pd.DataFrame):
    assert len(trade_log) == 1
    return trade_log.iloc[0]


def test_target_hit_yields_clean_2r():
    df = trade_day()
    set_bar(df, DATE, "09:50", h=104.0)  # reaches the 2R target
    log, curve = run_backtest({"SPY": df}, ORBConfig())
    t = only_trade(log)
    assert t["exit_reason"] == TARGET
    # Risk-based sizing => a +2R win is +2 * (risk_per_trade * equity).
    assert t["r_multiple"] == pytest.approx(2.0, abs=1e-9)
    assert t["pnl"] == pytest.approx(2000.0, abs=1e-6)
    assert curve.iloc[-1] == pytest.approx(102000.0, abs=1e-6)


def test_stop_hit_loses_more_than_1r_from_slippage():
    df = trade_day()
    set_bar(df, DATE, "09:50", l=98.0)  # pierces the opposite-range stop
    log, _ = run_backtest({"SPY": df}, ORBConfig())
    t = only_trade(log)
    assert t["exit_reason"] == STOP
    # Stop slippage makes the realized loss WORSE than a textbook -1R.
    assert t["r_multiple"] < -1.0
    assert t["pnl"] < -1000.0


def test_zero_stop_slippage_is_exactly_minus_1r():
    df = trade_day()
    set_bar(df, DATE, "09:50", l=98.0)
    cfg = dataclasses.replace(ORBConfig(), slippage_bps_entry=0.0, slippage_bps_stop=0.0)
    log, _ = run_backtest({"SPY": df}, cfg)
    t = only_trade(log)
    assert t["r_multiple"] == pytest.approx(-1.0, abs=1e-9)
    assert t["pnl"] == pytest.approx(-1000.0, abs=1e-6)


def test_same_bar_stop_and_target_resolves_to_stop():
    df = trade_day()
    # One bar spans BOTH the stop and the target — path unknown from OHLC.
    set_bar(df, DATE, "09:50", h=104.0, l=98.0)
    log, _ = run_backtest({"SPY": df}, ORBConfig())
    t = only_trade(log)
    assert t["exit_reason"] == STOP  # conservative tie-break


def test_eod_flatten_when_neither_level_hit():
    df = trade_day()  # nothing set to hit stop/target; rides flat to the close
    log, _ = run_backtest({"SPY": df}, ORBConfig())
    t = only_trade(log)
    assert t["exit_reason"] == EOD
    assert t["exit_ts"] == pd.Timestamp(f"{DATE} 15:55", tz=ET)


def test_entry_fill_reflects_slippage():
    df = trade_day(entry_open=100.5)
    log, _ = run_backtest({"SPY": df}, ORBConfig())
    t = only_trade(log)
    # Long entry filled ABOVE the next-bar open by 2 bps (chasing strength).
    assert t["entry_price"] == pytest.approx(100.5 * 1.0002, abs=1e-9)

    log0, _ = run_backtest(
        {"SPY": df}, dataclasses.replace(ORBConfig(), slippage_bps_entry=0.0)
    )
    assert only_trade(log0)["entry_price"] == pytest.approx(100.5, abs=1e-9)


def test_commission_reduces_pnl():
    df = trade_day()
    set_bar(df, DATE, "09:50", h=104.0)
    cfg = dataclasses.replace(ORBConfig(), commission_per_share=0.01)
    log, _ = run_backtest({"SPY": df}, cfg)
    t = only_trade(log)
    # Round-trip commission = 0.01 * shares * 2; pnl falls below the 2000 gross.
    assert t["pnl"] < 2000.0
    assert t["pnl"] == pytest.approx(2000.0 - 0.01 * t["shares"] * 2.0, abs=1e-6)


def test_sizing_uses_start_of_day_equity_and_compounds():
    d1, d2 = "2024-03-04", "2024-03-05"
    day1 = trade_day(d1)
    set_bar(day1, d1, "09:50", h=104.0)  # +2R win, +2000
    day2 = trade_day(d2)
    set_bar(day2, d2, "09:50", h=104.0)
    log, curve = run_backtest({"SPY": pd.concat([day1, day2])}, ORBConfig())
    assert len(log) == 2
    first, second = log.iloc[0], log.iloc[1]
    assert first["equity_before"] == pytest.approx(100_000.0)
    # Day 2 sizes off the compounded equity from day 1's win, so its +2R is
    # worth 2% of 102k = 2040, not a flat 2000.
    assert second["equity_before"] == pytest.approx(102_000.0)
    assert curve.iloc[-1] == pytest.approx(104_040.0, abs=1e-6)


def test_multi_symbol_same_day_shares_start_of_day_equity():
    df_spy = trade_day()
    set_bar(df_spy, DATE, "09:50", h=104.0)
    df_qqq = trade_day()
    set_bar(df_qqq, DATE, "09:50", h=104.0)
    log, _ = run_backtest({"SPY": df_spy, "QQQ": df_qqq}, ORBConfig())
    assert len(log) == 2
    # Both trades on the same day are sized off the same start-of-day equity.
    assert (log["equity_before"] == 100_000.0).all()
    assert sorted(log["symbol"]) == ["QQQ", "SPY"]


def test_determinism_identical_inputs_identical_outputs():
    df = trade_day()
    set_bar(df, DATE, "09:50", h=104.0)
    bars = {"SPY": df}
    log_a, curve_a = run_backtest(bars, ORBConfig())
    log_b, curve_b = run_backtest(bars, ORBConfig())
    pd.testing.assert_frame_equal(log_a, log_b)
    pd.testing.assert_series_equal(curve_a, curve_b)


def test_no_signal_day_produces_no_trades_and_flat_curve():
    df = flat_day(DATE, price=100.0)
    set_opening_range(df, DATE, high=100.0, low=99.0)  # never breaks out
    log, curve = run_backtest({"SPY": df}, ORBConfig())
    assert log.empty
    assert curve.iloc[-1] == pytest.approx(100_000.0)
