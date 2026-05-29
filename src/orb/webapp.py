"""Streamlit dashboard for the ORB backtester (Phase 3).

Configure parameters in the sidebar, run a backtest, and view the equity curve
(with drawdown), headline metrics, exit-reason breakdown, and the trade log.
Every input has an inline explanation, and an in-app guide explains the strategy.

Run with:  streamlit run streamlit_app.py
(needs the UI extra:  pip install -e ".[ui]")

This is a research/education tool — NOT financial advice, and it places no orders.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .backtest import EOD, STOP, TARGET, run_backtest
from .config import ORBConfig
from .data import load_intraday
from .metrics import performance_summary
from .optimize import STRATEGIES, folds_to_frame, walk_forward
from .signals import DEFAULT_LOG, load_signal_log, log_signals, scan_for_signals
from .strategy import compute_opening_range

# Exit-reason colors used across charts/labels.
_EXIT_COLORS = {TARGET: "#16a34a", STOP: "#dc2626", EOD: "#64748b"}


# --------------------------------------------------------------------------- #
# data + config glue
# --------------------------------------------------------------------------- #
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
    return {
        "cfg": cfg,
        "bars": {s: len(df) for s, df in bars.items()},
        "missing": missing,
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "perf": performance_summary(trade_log, equity_curve),
        "start": form["start"],
        "end": form["end"],
    }


# --------------------------------------------------------------------------- #
# guide / help text
# --------------------------------------------------------------------------- #
_GUIDE = """
**What is this?** It backtests the **Opening Range Breakout (ORB)** strategy on
historical stock data — so you can see how it *would have* performed, costs included.

**How ORB works (plain English):**
1. After the 9:30 ET open, watch the first **N minutes** (the *opening range*) and
   note its **high** and **low**.
2. If price later **closes above that high**, the strategy **buys** (a "breakout").
3. It sets a **stop-loss** (exit if price falls to the range low) and a
   **profit target** (a multiple of what it's risking), and closes any open trade
   by 15:55 ET.

**Using the app — 3 steps:**
1. In the **sidebar**, pick **symbols** and a **date range** (the defaults are a fine
   starting point — you can just hit Run).
2. Optionally tweak the strategy/cost settings. **Hover the ❔ next to any field**
   for what it means.
3. Click **▶ Run backtest** and read the results. The first run downloads data
   (~30–60s for a couple of years); after that it's cached and instant.

> ⚠️ Research/education only. This places **no orders** and is **not financial advice**.
> Backtested results don't predict the future.
"""

_GLOSSARY = """
- **Total return** — overall % change of the account over the period.
- **Win rate** — share of trades that ended in profit. (A high win rate can still
  lose money if the losses are bigger than the wins — check *Avg R*.)
- **Max drawdown** — the worst peak-to-trough drop in the account. Smaller is better.
- **Sharpe** — return per unit of risk, annualized (risk-free rate = 0). Noisy when
  there aren't many trades, so read it next to the trade count.
- **Avg R** — average result per trade measured in units of risk. **Positive means
  an edge**; e.g. +0.2 means each trade made 0.2× what it risked, on average.
- **Profit factor** — gross profit ÷ gross loss. Above 1.0 means winners outweigh losers.
- **Exit reasons** — 🟢 **target** (hit the profit target), 🔴 **stop** (hit the
  stop-loss), ⚪ **eod** (closed at 15:55 with neither hit).
"""


# --------------------------------------------------------------------------- #
# sidebar
# --------------------------------------------------------------------------- #
def _sidebar() -> dict | None:
    """Render the parameter sidebar. Returns the form dict on 'Run', else None."""
    st.sidebar.header("⚙️ Parameters")
    st.sidebar.caption("Hover the ❔ on any field for an explanation.")

    symbols_raw = st.sidebar.text_input(
        "Symbols", value="SPY, QQQ",
        help="Tickers to test, comma-separated (e.g. SPY, QQQ, AAPL). Liquid US "
             "stocks/ETFs work best.",
    )
    today = pd.Timestamp.today().normalize()
    default_start = (today - pd.DateOffset(years=2)).date()
    start = st.sidebar.date_input(
        "Start date", value=default_start,
        help="Beginning of the backtest window. A longer window means more trades "
             "but a slower first data download.",
    )
    end = st.sidebar.date_input(
        "End date", value=(today - pd.Timedelta(days=1)).date(),
        help="End of the backtest window.",
    )

    st.sidebar.subheader("Strategy")
    or_minutes = st.sidebar.selectbox(
        "Opening-range minutes", [5, 15, 30], index=1,
        help="How many minutes after 9:30 ET define the breakout high/low. "
             "15 is the classic default; shorter reacts faster but is noisier.",
    )
    direction = st.sidebar.selectbox(
        "Direction", ["long_only", "long_short"], index=0,
        help="long_only buys upside breakouts only (simpler, safer). long_short "
             "also short-sells downside breakouts.",
    )
    take_profit_r = st.sidebar.number_input(
        "Take-profit (R multiple)", 0.5, 10.0, 2.0, 0.5,
        help="Profit target as a multiple of risk (R). 2.0 = aim to make twice "
             "what you'd lose if the stop is hit.",
    )

    st.sidebar.subheader("Sizing & costs")
    risk_pct = st.sidebar.number_input(
        "Risk per trade (%)", 0.1, 10.0, 1.0, 0.1,
        help="Fraction of the account risked per trade. This sets the position "
             "size. 1% is a common, conservative choice.",
    )
    starting_equity = st.sidebar.number_input(
        "Starting equity ($)", 1_000.0, 1e8, 100_000.0, 1_000.0,
        help="Hypothetical starting capital for the simulation.",
    )
    slip_entry = st.sidebar.number_input(
        "Entry slippage (bps)", 0.0, 50.0, 2.0, 0.5,
        help="Assumed worse fill when entering a breakout (you chase strength). "
             "1 bp = 0.01%. Higher = more pessimistic / realistic.",
    )
    slip_stop = st.sidebar.number_input(
        "Stop slippage (bps)", 0.0, 50.0, 5.0, 0.5,
        help="Assumed worse fill when a stop triggers during a fast move. ORB is "
             "very sensitive to this — keep it on.",
    )
    commission = st.sidebar.number_input(
        "Commission per share ($)", 0.0, 1.0, 0.0, 0.001, format="%.3f",
        help="Per-share commission. 0 is fine for most modern brokers.",
    )

    st.sidebar.subheader("Day filters (optional)")
    st.sidebar.caption("Off by default — turn on to skip certain days.")
    use_gap = st.sidebar.checkbox(
        "Gap filter", value=False,
        help="Skip days that open far from the prior day's close. Gappy days "
             "behave differently and can hurt ORB.",
    )
    max_gap_pct = st.sidebar.number_input(
        "…max gap (%)", 0.0, 10.0, 0.5, 0.1,
        help="Used only if the Gap filter is on: skip the day if the open is more "
             "than this % away from yesterday's close.",
    ) / 100.0
    use_or_width = st.sidebar.checkbox(
        "OR-width / ATR filter", value=False,
        help="Skip days whose opening range is already wide vs recent volatility "
             "(the big move may have already happened).",
    )
    max_or_width_atr = st.sidebar.number_input(
        "…max OR width (% of ATR)", 1.0, 200.0, 30.0, 1.0,
        help="Used only if the OR-width filter is on: skip the day if the opening "
             "range is wider than this % of the prior-day ATR (a volatility gauge).",
    ) / 100.0
    atr_period = st.sidebar.number_input(
        "…ATR period (days)", 2, 100, 14, 1,
        help="How many prior days of volatility (ATR) the OR-width filter uses.",
    )

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


# --------------------------------------------------------------------------- #
# charts
# --------------------------------------------------------------------------- #
def _equity_drawdown_fig(equity_curve: pd.Series) -> go.Figure:
    """Equity curve (top) with an underwater drawdown panel (bottom)."""
    drawdown = equity_curve / equity_curve.cummax() - 1.0
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
        vertical_spacing=0.06,
        subplot_titles=("Equity", "Drawdown"),
    )
    fig.add_trace(
        go.Scatter(
            x=equity_curve.index, y=equity_curve.values, mode="lines",
            line=dict(color="#2563eb", width=2), fill="tozeroy",
            fillcolor="rgba(37,99,235,0.08)", name="Equity",
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=drawdown.index, y=drawdown.values, mode="lines",
            line=dict(color="#dc2626", width=1), fill="tozeroy",
            fillcolor="rgba(220,38,38,0.12)", name="Drawdown",
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1%}<extra></extra>",
        ),
        row=2, col=1,
    )
    fig.update_yaxes(title_text="$", tickformat="$,.0f", row=1, col=1)
    fig.update_yaxes(title_text="%", tickformat=".0%", row=2, col=1)
    fig.update_layout(
        height=460, margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False, hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _exit_fig(trade_log: pd.DataFrame) -> go.Figure:
    """Bar chart of exit-reason counts, colored by reason."""
    counts = trade_log["exit_reason"].value_counts()
    fig = go.Figure(
        go.Bar(
            x=counts.index, y=counts.values,
            marker_color=[_EXIT_COLORS.get(r, "#94a3b8") for r in counts.index],
            text=counts.values, textposition="outside",
            hovertemplate="%{x}: %{y} trades<extra></extra>",
        )
    )
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="trades", plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _trade_chart_fig(day_bars: pd.DataFrame, trade: dict, cfg) -> go.Figure:
    """Candlestick of one session with OR levels and the trade's entry/stop/
    target/exit drawn on top — so you can *see* what the strategy did."""
    rng = compute_opening_range(day_bars, cfg)
    fig = go.Figure(
        go.Candlestick(
            x=day_bars.index, open=day_bars["open"], high=day_bars["high"],
            low=day_bars["low"], close=day_bars["close"], name="price",
            increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        )
    )
    # Opening-range band.
    if rng is not None:
        fig.add_hline(y=rng.high, line=dict(color="#2563eb", dash="dot", width=1),
                      annotation_text="OR high", annotation_position="right")
        fig.add_hline(y=rng.low, line=dict(color="#2563eb", dash="dot", width=1),
                      annotation_text="OR low", annotation_position="right")

    # Stop / target levels.
    fig.add_hline(y=trade["stop_level"], line=dict(color="#dc2626", dash="dash", width=1),
                  annotation_text="stop", annotation_position="left")
    fig.add_hline(y=trade["target_level"], line=dict(color="#16a34a", dash="dash", width=1),
                  annotation_text="target", annotation_position="left")

    # Entry + exit markers.
    is_long = trade["direction"] == "long"
    fig.add_trace(go.Scatter(
        x=[trade["entry_ts"]], y=[trade["entry_price"]], mode="markers", name="entry",
        marker=dict(symbol="triangle-up" if is_long else "triangle-down", size=14,
                    color="#2563eb", line=dict(width=1, color="white")),
    ))
    exit_color = {TARGET: "#16a34a", STOP: "#dc2626", EOD: "#64748b"}.get(trade["exit_reason"], "#64748b")
    fig.add_trace(go.Scatter(
        x=[trade["exit_ts"]], y=[trade["exit_price"]], mode="markers",
        name=f"exit ({trade['exit_reason']})",
        marker=dict(symbol="x", size=13, color=exit_color, line=dict(width=1)),
    ))
    fig.update_layout(
        height=460, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _style_trade_log(trade_log: pd.DataFrame):
    """A compact, formatted, color-coded view of the trade log."""
    df = trade_log.copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["entry_ts"] = df["entry_ts"].dt.strftime("%H:%M")
    df["exit_ts"] = df["exit_ts"].dt.strftime("%H:%M")
    cols = {
        "date": "Date", "symbol": "Symbol", "direction": "Side",
        "entry_ts": "In", "entry_price": "Entry", "exit_ts": "Out",
        "exit_price": "Exit", "exit_reason": "Exit reason", "shares": "Shares",
        "pnl": "P&L ($)", "r_multiple": "R",
    }
    df = df[list(cols)].rename(columns=cols)

    def _sign_color(v):
        return f"color: {'#16a34a' if v > 0 else '#dc2626' if v < 0 else '#64748b'}"

    return (
        df.style
        .format({"Entry": "{:,.2f}", "Exit": "{:,.2f}", "Shares": "{:,.0f}",
                 "P&L ($)": "{:+,.0f}", "R": "{:+.2f}"})
        .map(_sign_color, subset=["P&L ($)", "R"])
    )


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
def _render_metrics(perf) -> None:
    start_eq = perf.starting_equity
    net = perf.final_equity - start_eq
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total return", f"{perf.total_return:.1%}",
              delta=f"{net:+,.0f} $", delta_color="normal")
    c2.metric("Final equity", f"${perf.final_equity:,.0f}")
    c3.metric("Win rate", f"{perf.win_rate:.0%}", help=f"{perf.wins} wins / {perf.losses} losses")
    c4.metric("Trades", f"{perf.num_trades}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Max drawdown", f"{perf.max_drawdown:.1%}")
    sharpe = "n/a" if pd.isna(perf.sharpe) else f"{perf.sharpe:.2f}"
    c6.metric("Sharpe (ann.)", sharpe, help="rf=0; noisy on few trades — read with trade count")
    c7.metric("Avg R", f"{perf.avg_r_multiple:+.2f}", help="Avg result per trade in units of risk. Positive = edge.")
    if perf.profit_factor == float("inf"):
        pf = "∞"
    elif pd.isna(perf.profit_factor):
        pf = "n/a"
    else:
        pf = f"{perf.profit_factor:.2f}"
    c8.metric("Profit factor", pf, help="Gross profit ÷ gross loss. >1 is good.")


def _render_results(res: dict) -> None:
    perf = res["perf"]
    if res["missing"]:
        st.warning(f"No data returned for: {', '.join(res['missing'])} (check the symbol or date range).")
    if res["bars"]:
        st.caption("Loaded bars — " + ", ".join(f"{s}: {n:,}" for s, n in res["bars"].items()))

    _render_metrics(perf)

    trade_log = res["trade_log"]
    if trade_log.empty:
        st.info("No trades were generated for these parameters / window. Try a longer window or different settings.")
        return

    tab_overview, tab_chart, tab_equity, tab_trades, tab_guide = st.tabs(
        ["📈 Equity & drawdown", "🔍 Trade chart", "🎯 Exits", "📋 Trade log", "❓ What do these mean?"]
    )
    with tab_overview:
        st.plotly_chart(_equity_drawdown_fig(res["equity_curve"]), use_container_width=True)
    with tab_chart:
        _render_trade_chart(res)
    with tab_equity:
        left, right = st.columns([2, 1])
        with left:
            st.plotly_chart(_exit_fig(trade_log), use_container_width=True)
        with right:
            st.caption("Average R by exit reason")
            mean_r = trade_log.groupby("exit_reason")["r_multiple"].mean().round(2)
            st.dataframe(mean_r.rename("avg R"), use_container_width=True)
    with tab_trades:
        st.dataframe(_style_trade_log(trade_log), use_container_width=True, height=420)
        st.download_button(
            "⬇ Download trade log (CSV)",
            trade_log.to_csv(index=False).encode("utf-8"),
            file_name="orb_trade_log.csv", mime="text/csv",
        )
    with tab_guide:
        st.markdown(_GLOSSARY)


def _render_trade_chart(res: dict) -> None:
    """Pick a trade and draw its session: candlesticks + OR + entry/stop/target/exit."""
    trade_log = res["trade_log"]
    cfg = res["cfg"]
    st.caption("See exactly what a trade did — opening range, breakout, and the entry/stop/target/exit.")

    syms = sorted(trade_log["symbol"].unique())
    c1, c2 = st.columns(2)
    sym = c1.selectbox("Symbol", syms)
    sym_log = trade_log[trade_log["symbol"] == sym]
    dates = [d.strftime("%Y-%m-%d") for d in sym_log["date"]]
    picked = c2.selectbox("Trade date", dates)

    trade = sym_log[sym_log["date"].dt.strftime("%Y-%m-%d") == picked].iloc[0].to_dict()
    try:
        bars = _cached_load(sym, res["start"], res["end"], cfg.bar_minutes)
        day_bars = bars[bars.index.strftime("%Y-%m-%d") == picked]
        if day_bars.empty:
            st.info("No bars cached for that day.")
            return
        st.plotly_chart(_trade_chart_fig(day_bars, trade, cfg), use_container_width=True)
        st.caption(
            f"{sym} {picked} — {trade['direction'].upper()} entry {trade['entry_price']:.2f} → "
            f"exit {trade['exit_price']:.2f} ({trade['exit_reason']}), "
            f"P&L ${trade['pnl']:+,.0f}, {trade['r_multiple']:+.2f}R"
        )
    except Exception as exc:
        st.warning(f"Could not load bars for the chart: {exc}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def backtest_page() -> None:
    st.title("📈 ORB Backtester")
    st.caption(
        "Opening Range Breakout — backtest only, **no orders**. "
        "Research/education, **not financial advice**. Trading costs are modeled."
    )

    with st.expander("📖 New here? How this works & how to use it", expanded=True):
        st.markdown(_GUIDE)

    form = _sidebar()
    if form is not None:
        if not form["symbols"]:
            st.session_state["error"] = "Please enter at least one symbol."
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
            "a `.env` file (copy from `.env.example`). The first fetch needs "
            "internet; results then cache to `data/cache/`."
        )
    elif st.session_state.get("results"):
        _render_results(st.session_state["results"])
    else:
        st.info("👈 Set your parameters in the sidebar, then click **▶ Run backtest**.")


# --------------------------------------------------------------------------- #
# paper signals page
# --------------------------------------------------------------------------- #
_SIGNAL_GUIDE = """
This page scans **recent / delayed** market data for the day's ORB breakout
signals and logs them. It is **paper only** — it places **no orders** and is not
financial advice. Each signal shows the intended entry, stop, target, and a
risk-based suggested size, plus a timestamp of when it was detected.

Run it **after the close** (the free data feed is ~15 minutes delayed). A daily
scheduled task can do this automatically; this page lets you scan on demand and
review the running log.
"""

_SIGNAL_COLS = {
    "asof_date": "Date", "symbol": "Symbol", "direction": "Side",
    "reference_entry": "Entry", "stop_level": "Stop", "target_level": "Target",
    "suggested_shares": "Shares", "emitted_at": "Detected (UTC)",
}


def signals_page() -> None:
    st.title("📡 Paper signals")
    st.caption("ORB breakout signals on delayed data — **no orders placed**. Not financial advice.")
    with st.expander("ℹ️ What is this?", expanded=True):
        st.markdown(_SIGNAL_GUIDE)

    cfg = ORBConfig()
    symbols_raw = st.text_input("Symbols", value=", ".join(cfg.symbols))
    lookback = st.slider("Data lookback (calendar days)", 5, 90, 40,
                         help="How much recent data to pull (more is needed if day filters use a long ATR).")
    scan = st.button("📡 Scan latest session", type="primary")

    if scan:
        symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
        if not symbols:
            st.error("Enter at least one symbol.")
        else:
            run_cfg = ORBConfig(**{**cfg.__dict__, "symbols": symbols})
            end = pd.Timestamp.now(tz="America/New_York").normalize()
            start = (end - pd.Timedelta(days=lookback)).date().isoformat()
            try:
                with st.spinner("Fetching delayed data and scanning…"):
                    bars = {s: _cached_load(s, start, end.date().isoformat(), run_cfg.bar_minutes) for s in symbols}
                    found = scan_for_signals(bars, run_cfg)
                    new = log_signals(found, DEFAULT_LOG)
                if found:
                    st.success(f"{len(found)} signal(s) for the latest session — {len(new)} new, logged to {DEFAULT_LOG}.")
                    df = pd.DataFrame(s.to_record() for s in found)
                    st.dataframe(df[list(_SIGNAL_COLS)].rename(columns=_SIGNAL_COLS),
                                 use_container_width=True, hide_index=True)
                else:
                    st.info("No ORB signals for the latest available session.")
            except Exception as exc:
                st.error(str(exc))
                st.info("Data comes from Alpaca — set `ALPACA_API_KEY` / `ALPACA_API_SECRET` in `.env`.")

    st.subheader("Signal log")
    log_df = load_signal_log(DEFAULT_LOG)
    if log_df.empty:
        st.caption("No signals logged yet. Scan a session above (or let the daily task run).")
    else:
        show = [c for c in _SIGNAL_COLS if c in log_df.columns]
        st.dataframe(log_df[show].rename(columns=_SIGNAL_COLS).iloc[::-1],
                     use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download signal log (CSV)",
            log_df.to_csv(index=False).encode("utf-8"),
            file_name="orb_signals.csv", mime="text/csv",
        )


# --------------------------------------------------------------------------- #
# optimizer page (walk-forward)
# --------------------------------------------------------------------------- #
_OPT_GUIDE = """
Let the *machine* pick the parameters — honestly. This runs **walk-forward**
optimization: it tunes on an in-sample window, then scores on the next *unseen*
out-of-sample window and rolls forward. The **out-of-sample** result is the honest
estimate; a big in-sample-minus-out-of-sample gap means the 'edge' was overfitting.

Heads-up: a full run does many backtests and can take a few minutes here. For big
sweeps the CLI is faster (it parallelizes across cores): `python scripts/optimize.py`.
"""


def optimizer_page() -> None:
    st.title("🧪 Walk-forward optimizer")
    st.caption("The bot chooses parameters; the **out-of-sample** number is the honest one. No orders.")
    with st.expander("ℹ️ What is this?", expanded=True):
        st.markdown(_OPT_GUIDE)

    today = pd.Timestamp.today().normalize()
    c1, c2, c3 = st.columns(3)
    symbols_raw = c1.text_input("Symbols", value="SPY, QQQ")
    strategy = c2.selectbox("Strategy", list(STRATEGIES),
                            format_func=lambda s: {"orb": "ORB", "ma": "EMA crossover"}.get(s, s))
    objective = c3.selectbox("Objective", ["avg_r", "sharpe", "total_return", "profit_factor"])
    c4, c5, c6 = st.columns(3)
    start = c4.date_input("Start", value=(today - pd.DateOffset(years=2)).date())
    is_days = c5.number_input("In-sample days", 60, 1095, 365, 5)
    oos_days = c6.number_input("Out-of-sample days", 30, 365, 90, 5)
    end = (today - pd.Timedelta(days=1)).date()

    if st.button("🧪 Run walk-forward", type="primary"):
        symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
        if not symbols:
            st.error("Enter at least one symbol.")
            return
        signal_fn, space = STRATEGIES[strategy]
        cfg = ORBConfig(**{**ORBConfig().__dict__, "symbols": symbols})
        try:
            with st.spinner("Loading data and running walk-forward (this can take a few minutes)…"):
                bars = {s: _cached_load(s, start.isoformat(), end.isoformat(), cfg.bar_minutes)
                        for s in symbols}
                result = walk_forward(
                    bars, cfg, space=space, is_days=int(is_days), oos_days=int(oos_days),
                    objective=objective, workers=1, signal_fn=signal_fn,  # serial: robust in-app
                )
            st.session_state["opt_result"] = result
            st.session_state.pop("opt_error", None)
        except Exception as exc:
            st.session_state["opt_error"] = str(exc)
            st.session_state.pop("opt_result", None)

    if st.session_state.get("opt_error"):
        st.error(st.session_state["opt_error"])
        return
    result = st.session_state.get("opt_result")
    if result is None:
        st.info("Set the universe + windows above and click **Run walk-forward**.")
        return
    if not result.folds:
        st.warning("Not enough data for a single in-sample + out-of-sample fold. Widen the date range.")
        return

    gap = result.overfitting_gap
    g1, g2, g3 = st.columns(3)
    g1.metric(f"In-sample {result.objective}", f"{result.mean_is_objective:+.3f}")
    g2.metric(f"Out-of-sample {result.objective}", f"{result.mean_oos_objective:+.3f}")
    g3.metric("Overfitting gap", f"{gap:+.3f}", help="In-sample minus out-of-sample. Large positive = the edge didn't survive.")
    if gap > 0.05:
        st.warning("Large positive gap — the in-sample 'edge' largely did **not** survive out of sample (overfitting).")

    st.subheader("Stitched out-of-sample equity")
    st.plotly_chart(_equity_drawdown_fig(result.oos_equity_curve), use_container_width=True)
    _render_metrics(result.oos_performance)

    st.subheader("Per fold — chosen params & in-sample vs out-of-sample")
    st.dataframe(folds_to_frame(result), use_container_width=True, hide_index=True)
