"""Streamlit dashboard for the ORB backtester (Phase 3).

Configure parameters in the sidebar, run a backtest, and view the equity curve,
headline metrics, exit-reason breakdown, and the trade-by-trade log.

Run with:  streamlit run streamlit_app.py
(needs the UI extra:  pip install -e ".[ui]")

This is a research/education tool — NOT financial advice, and it places no orders.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import streamlit as st

from .backtest import run_backtest
from .config import ORBConfig
from .data import load_intraday
from .metrics import performance_summary

# Numeric trade-log columns to round for display only.
_MONEY_COLS = ("entry_price", "stop_level", "target_level", "exit_price", "pnl", "equity_before")


@st.cache_data(show_spinner=False)
def _cached_load(symbol: str, start: str, end: str, bar_minutes: int) -> pd.DataFrame:
    """Cache loads within a session so re-running with tweaked params is fast.
    The on-disk cache in data/cache/ already makes the first fetch reusable."""
    return load_intraday(symbol, start, end, bar_minutes)


def _build_config(form: dict) -> ORBConfig:
    """Translate sidebar inputs into an ORBConfig."""
    return ORBConfig(
        symbols=form["symbols"],
        opening_range_minutes=form["opening_range_minutes"],
        direction=form["direction"],
        take_profit_r=form["take_profit_r"],
        risk_per_trade=form["risk_per_trade"],
        starting_equity=form["starting_equity"],
        slippage_bps_entry=form["slippage_bps_entry"],
        slippage_bps_stop=form["slippage_bps_stop"],
        commission_per_share=form["commission_per_share"],
        use_gap_filter=form["use_gap_filter"],
        max_gap_pct=form["max_gap_pct"],
        use_or_width_filter=form["use_or_width_filter"],
        max_or_width_atr=form["max_or_width_atr"],
        atr_period=form["atr_period"],
    )


def _sidebar() -> dict | None:
    """Render the parameter sidebar. Returns the form dict on 'Run', else None."""
    st.sidebar.header("Parameters")
    symbols_raw = st.sidebar.text_input("Symbols (comma-separated)", value="SPY, QQQ")
    today = pd.Timestamp.today().normalize()
    default_start = (today - pd.DateOffset(years=2)).date()
    start = st.sidebar.date_input("Start date", value=default_start)
    end = st.sidebar.date_input("End date", value=(today - pd.Timedelta(days=1)).date())

    st.sidebar.subheader("Strategy")
    or_minutes = st.sidebar.selectbox("Opening-range minutes", [5, 15, 30], index=1)
    direction = st.sidebar.selectbox("Direction", ["long_only", "long_short"], index=0)
    take_profit_r = st.sidebar.number_input("Take-profit (R multiple)", 0.5, 10.0, 2.0, 0.5)

    st.sidebar.subheader("Sizing & costs")
    risk_pct = st.sidebar.number_input("Risk per trade (%)", 0.1, 10.0, 1.0, 0.1)
    starting_equity = st.sidebar.number_input("Starting equity ($)", 1_000.0, 1e8, 100_000.0, 1_000.0)
    slip_entry = st.sidebar.number_input("Entry slippage (bps)", 0.0, 50.0, 2.0, 0.5)
    slip_stop = st.sidebar.number_input("Stop slippage (bps)", 0.0, 50.0, 5.0, 0.5)
    commission = st.sidebar.number_input("Commission per share ($)", 0.0, 1.0, 0.0, 0.001, format="%.3f")

    st.sidebar.subheader("Day filters (opt-in)")
    use_gap = st.sidebar.checkbox("Gap filter", value=False)
    max_gap_pct = st.sidebar.number_input("Max gap (%)", 0.0, 10.0, 0.5, 0.1) / 100.0
    use_or_width = st.sidebar.checkbox("OR-width / ATR filter", value=False)
    max_or_width_atr = st.sidebar.number_input("Max OR width (% of ATR)", 1.0, 200.0, 30.0, 1.0) / 100.0
    atr_period = st.sidebar.number_input("ATR period (days)", 2, 100, 14, 1)

    run = st.sidebar.button("▶ Run backtest", type="primary", use_container_width=True)
    if not run:
        return None

    symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
    return {
        "symbols": symbols,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "opening_range_minutes": int(or_minutes),
        "direction": direction,
        "take_profit_r": float(take_profit_r),
        "risk_per_trade": risk_pct / 100.0,
        "starting_equity": float(starting_equity),
        "slippage_bps_entry": float(slip_entry),
        "slippage_bps_stop": float(slip_stop),
        "commission_per_share": float(commission),
        "use_gap_filter": bool(use_gap),
        "max_gap_pct": float(max_gap_pct),
        "use_or_width_filter": bool(use_or_width),
        "max_or_width_atr": float(max_or_width_atr),
        "atr_period": int(atr_period),
    }


def _run(form: dict) -> dict:
    """Load data + run the backtest. Raises on data/credential errors."""
    cfg = _build_config(form)
    bars: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for sym in cfg.symbols:
        df = _cached_load(sym, form["start"], form["end"], cfg.bar_minutes)
        if df is None or df.empty:
            missing.append(sym)
        else:
            bars[sym] = df
    trade_log, equity_curve = run_backtest(bars, cfg)
    perf = performance_summary(trade_log, equity_curve)
    return {
        "cfg": cfg,
        "bars": {s: len(df) for s, df in bars.items()},
        "missing": missing,
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "perf": perf,
    }


def _render_metrics(perf) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total return", f"{perf.total_return:.2%}")
    c2.metric("Final equity", f"${perf.final_equity:,.0f}")
    c3.metric("Win rate", f"{perf.win_rate:.1%}", help=f"{perf.wins}W / {perf.losses}L")
    c4.metric("Trades", f"{perf.num_trades}")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Max drawdown", f"{perf.max_drawdown:.2%}")
    sharpe = "n/a" if pd.isna(perf.sharpe) else f"{perf.sharpe:.2f}"
    c6.metric("Sharpe (ann.)", sharpe, help=f"rf=0, {perf.sharpe_trading_days} trading days; noisy on few trades")
    c7.metric("Avg R", f"{perf.avg_r_multiple:.2f}")
    pf = "∞" if perf.profit_factor == float("inf") else ("n/a" if pd.isna(perf.profit_factor) else f"{perf.profit_factor:.2f}")
    c8.metric("Profit factor", pf)


def _render_results(res: dict) -> None:
    perf = res["perf"]
    if res["missing"]:
        st.warning(f"No data returned for: {', '.join(res['missing'])} (check symbol/date range).")
    st.caption(
        "Loaded bars — " + ", ".join(f"{s}: {n:,}" for s, n in res["bars"].items())
        if res["bars"] else "No bars loaded."
    )

    _render_metrics(perf)

    trade_log = res["trade_log"]
    if trade_log.empty:
        st.info("No trades were generated for these parameters / window.")
        return

    st.subheader("Equity curve")
    st.line_chart(res["equity_curve"], y_label="Equity ($)")

    left, right = st.columns([1, 2])
    with left:
        st.subheader("Exits")
        counts = trade_log["exit_reason"].value_counts()
        st.bar_chart(counts)
        mean_r = trade_log.groupby("exit_reason")["r_multiple"].mean().round(3)
        st.dataframe(mean_r.rename("mean R"), use_container_width=True)
    with right:
        st.subheader("Trade log")
        display = trade_log.copy()
        for col in _MONEY_COLS:
            if col in display:
                display[col] = display[col].round(2)
        display["r_multiple"] = display["r_multiple"].round(3)
        st.dataframe(display, use_container_width=True, height=360)
        st.download_button(
            "Download trade log (CSV)",
            trade_log.to_csv(index=False).encode("utf-8"),
            file_name="orb_trade_log.csv",
            mime="text/csv",
        )


def main() -> None:
    st.set_page_config(page_title="ORB Backtester", layout="wide")
    st.title("ORB Backtester")
    st.caption(
        "Opening Range Breakout — backtest only, **no orders**. Research/education, "
        "**not financial advice**. Costs (slippage/commission) are modeled."
    )

    form = _sidebar()
    if form is not None:
        if not form["symbols"]:
            st.session_state["error"] = "Enter at least one symbol."
            st.session_state.pop("results", None)
        else:
            try:
                with st.spinner("Loading data and running backtest…"):
                    st.session_state["results"] = _run(form)
                st.session_state.pop("error", None)
            except Exception as exc:  # surface credential/network/data errors cleanly
                st.session_state["error"] = str(exc)
                st.session_state.pop("results", None)

    if st.session_state.get("error"):
        st.error(st.session_state["error"])
        st.info(
            "Data comes from Alpaca. Set `ALPACA_API_KEY` / `ALPACA_API_SECRET` in "
            "`.env` (copy from `.env.example`). First fetch needs network; results "
            "then cache to `data/cache/`."
        )
    elif st.session_state.get("results"):
        _render_results(st.session_state["results"])
    else:
        st.info("Set parameters in the sidebar and click **Run backtest**.")
