"""Dashboard glue: the sidebar form -> ORBConfig mapping.

The Streamlit rendering itself is verified by booting the app; here we guard the
error-prone part that has no UI runtime — that every form field lands on the
right ORBConfig field with the right type. Skips cleanly if the UI extra
(streamlit) isn't installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from orb.backtest import run_backtest
from orb.config import ORBConfig
from orb.webapp import _build_config, _equity_drawdown_fig, _exit_fig, _style_trade_log
from synthetic import flat_day, set_bar, set_opening_range


def _form(**overrides):
    form = {
        "symbols": ["SPY", "QQQ"],
        "start": "2024-01-01",
        "end": "2024-12-31",
        "opening_range_minutes": 15,
        "direction": "long_only",
        "take_profit_r": 2.0,
        "risk_per_trade": 0.01,        # already a fraction (sidebar converts %)
        "starting_equity": 100_000.0,
        "slippage_bps_entry": 2.0,
        "slippage_bps_stop": 5.0,
        "commission_per_share": 0.0,
        "use_gap_filter": False,
        "max_gap_pct": 0.005,
        "use_or_width_filter": False,
        "max_or_width_atr": 0.30,
        "atr_period": 14,
    }
    form.update(overrides)
    return form


def test_build_config_defaults_match_orbconfig():
    cfg = _build_config(_form())
    default = ORBConfig()
    assert cfg.symbols == ["SPY", "QQQ"]
    assert cfg.opening_range_minutes == default.opening_range_minutes
    assert cfg.take_profit_r == default.take_profit_r
    assert cfg.risk_per_trade == default.risk_per_trade
    assert cfg.slippage_bps_stop == default.slippage_bps_stop
    # Filters default off, matching the engine default.
    assert cfg.use_gap_filter is False and cfg.use_or_width_filter is False


def test_build_config_threads_overrides_through():
    cfg = _build_config(
        _form(
            symbols=["NVDA"],
            opening_range_minutes=5,
            direction="long_short",
            take_profit_r=3.0,
            risk_per_trade=0.02,
            use_gap_filter=True,
            max_gap_pct=0.01,
            use_or_width_filter=True,
            max_or_width_atr=0.5,
            atr_period=20,
        )
    )
    assert cfg.symbols == ["NVDA"]
    assert cfg.opening_range_minutes == 5
    assert cfg.direction == "long_short"
    assert cfg.take_profit_r == 3.0
    assert cfg.risk_per_trade == 0.02
    assert cfg.use_gap_filter and cfg.max_gap_pct == 0.01
    assert cfg.use_or_width_filter and cfg.max_or_width_atr == 0.5
    assert cfg.atr_period == 20


def _sample_result():
    """A one-trade backtest so the render helpers get realistic shapes."""
    d = "2024-03-04"
    df = flat_day(d, 100.0)
    set_opening_range(df, d, 100.0, 99.0)
    set_bar(df, d, "09:45", c=100.5)
    set_bar(df, d, "09:46", o=100.5)
    set_bar(df, d, "09:50", h=104.0)  # hits the 2R target
    return run_backtest({"SPY": df}, ORBConfig())


def test_chart_and_table_builders_run_without_error():
    trade_log, equity_curve = _sample_result()
    assert not trade_log.empty
    # Figures build (Plotly) — would raise on a bad trace/axis spec.
    assert _equity_drawdown_fig(equity_curve).data
    assert _exit_fig(trade_log).data
    # Styler renders fully (catches format/column-name drift).
    html = _style_trade_log(trade_log).to_html()
    assert "P&L" in html and "Symbol" in html
