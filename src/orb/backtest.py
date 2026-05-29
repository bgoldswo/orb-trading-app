"""Backtest engine.

Given intraday bars and an ORBConfig, simulates ORB day by day applying the
look-ahead and cost rules, and returns (trade_log, equity_curve). Must be
deterministic: identical inputs produce identical outputs.

Modeling choices (documented on purpose — these are where ORB backtests cheat):
- Entry fill: next-bar open moved AGAINST us by ``slippage_bps_entry`` (breakouts
  chase strength), then commission per share.
- Stop fill: the stop LEVEL is the opposite opening-range bound; the FILL is that
  level moved further against us by ``slippage_bps_stop`` (fast reversals fill
  worst). Target fills exactly at the target level (a resting limit).
- Same-bar stop+target: intrabar path is unknown from OHLC, so we assume the STOP
  hit first (conservative). See docs/ORB_RULES.md.
- EOD: any open position is flattened at the open of the first bar at/after
  ``eod_flat_time`` (no extra slippage modeled), else the day's last close.
- Sizing: risk-based off equity at the START of the trading day, so multiple
  symbols on one day don't depend on an arbitrary intraday ordering. Fractional
  shares are allowed to avoid rounding noise on high-priced symbols.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .filters import compute_daily_context, day_is_eligible, filters_enabled
from .strategy import (
    LONG,
    SHORT,
    Signal,
    _parse_time,
    compute_opening_range,
    generate_signals,
)

# Exit reasons recorded in the trade log.
STOP = "stop"
TARGET = "target"
EOD = "eod"


@dataclass(frozen=True)
class Trade:
    date: pd.Timestamp
    symbol: str
    direction: str
    entry_ts: pd.Timestamp
    entry_price: float       # modeled fill, after slippage
    stop_level: float
    target_level: float
    shares: float
    exit_ts: pd.Timestamp
    exit_price: float        # modeled fill, after slippage
    exit_reason: str
    pnl: float               # net of commission
    r_multiple: float        # realized R (pnl per share / risk per share)
    risk_per_share: float
    equity_before: float     # equity used for sizing (start of day)


def _slip(price: float, bps: float, *, worse_is_up: bool) -> float:
    """Move ``price`` by ``bps`` basis points in the adverse direction.

    ``worse_is_up`` True  -> price increases (we buy / cover higher).
    ``worse_is_up`` False -> price decreases (we sell / exit lower).
    """
    factor = 1.0 + (bps / 10_000.0) * (1.0 if worse_is_up else -1.0)
    return price * factor


def _simulate_trade(
    day_bars: pd.DataFrame,
    signal: Signal,
    symbol: str,
    equity_before: float,
    cfg,
) -> Trade | None:
    """Fill a single signal and resolve its exit within one trading day."""
    is_long = signal.direction == LONG

    # --- entry fill (slippage against us) ---
    entry_price = _slip(
        signal.reference_entry, cfg.slippage_bps_entry, worse_is_up=is_long
    )

    # --- stop / target levels ---
    stop_level = signal.stop_level
    risk_per_share = abs(entry_price - stop_level)
    if risk_per_share <= 0:
        # Degenerate: entry already at/through the stop — no tradeable risk.
        return None
    if is_long:
        target_level = entry_price + cfg.take_profit_r * risk_per_share
    else:
        target_level = entry_price - cfg.take_profit_r * risk_per_share

    # --- sizing off start-of-day equity ---
    risk_dollars = cfg.risk_per_trade * equity_before
    shares = risk_dollars / risk_per_share
    if shares <= 0:
        return None

    # --- walk bars from the entry bar to resolve the exit ---
    eod_t = _parse_time(cfg.eod_flat_time)
    trade_bars = day_bars.loc[day_bars.index >= signal.entry_ts]

    exit_ts = None
    exit_price = None
    exit_reason = None

    # itertuples (not iterrows) — much faster on the per-bar walk, which dominates
    # runtime under the optimizer's thousands of backtests. Logic is identical.
    for row in trade_bars.itertuples():
        ts = row.Index
        # Flatten before the close regardless of P&L.
        if ts.time() >= eod_t:
            exit_ts, exit_price, exit_reason = ts, float(row.open), EOD
            break

        hi, lo = float(row.high), float(row.low)
        if is_long:
            hit_stop = lo <= stop_level
            hit_target = hi >= target_level
        else:
            hit_stop = hi >= stop_level
            hit_target = lo <= target_level

        # Same-bar ambiguity -> assume stop first (conservative).
        if hit_stop:
            fill = _slip(stop_level, cfg.slippage_bps_stop, worse_is_up=not is_long)
            exit_ts, exit_price, exit_reason = ts, fill, STOP
            break
        if hit_target:
            exit_ts, exit_price, exit_reason = ts, float(target_level), TARGET
            break

    if exit_ts is None:
        # No stop/target/EOD bar reached — flatten at the day's last close.
        last_ts = trade_bars.index[-1]
        exit_ts = last_ts
        exit_price = float(trade_bars.iloc[-1]["close"])
        exit_reason = EOD

    # --- P&L (net of round-trip commission) ---
    gross_per_share = (
        exit_price - entry_price if is_long else entry_price - exit_price
    )
    commission = cfg.commission_per_share * shares * 2.0
    pnl = gross_per_share * shares - commission
    r_multiple = gross_per_share / risk_per_share

    return Trade(
        date=signal.entry_ts.normalize(),
        symbol=symbol,
        direction=signal.direction,
        entry_ts=signal.entry_ts,
        entry_price=entry_price,
        stop_level=float(stop_level),
        target_level=float(target_level),
        shares=shares,
        exit_ts=exit_ts,
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl=pnl,
        r_multiple=r_multiple,
        risk_per_share=risk_per_share,
        equity_before=equity_before,
    )


def _day_key(bars: pd.DataFrame) -> pd.Series:
    """ET calendar date for each bar, used to group a session."""
    return pd.Series(bars.index.normalize(), index=bars.index)


def run_backtest(bars_by_symbol: dict[str, pd.DataFrame], cfg, signal_fn=generate_signals):
    """Simulate a strategy across symbols and return ``(trade_log, equity_curve)``.

    - ``signal_fn(day_bars, cfg) -> list[Signal]`` is the strategy. Defaults to ORB
      (``generate_signals``); pass another generator to backtest a different
      strategy through the same cost model and exit logic.
    - ``trade_log`` is a DataFrame, one row per trade, sorted by (date, symbol).
    - ``equity_curve`` is a Series of end-of-day equity indexed by date, with a
      leading point at ``starting_equity`` so returns can be computed.

    Determinism: symbols and dates are processed in sorted order, and all of a
    day's trades are sized off the equity recorded at the start of that day.

    The opt-in day filters are ORB-specific (gap / opening-range width); they only
    run when enabled in ``cfg``, so non-ORB strategies simply leave them off.
    """
    # Collect the union of trading dates across all symbols.
    per_symbol_days: dict[str, dict[pd.Timestamp, pd.DataFrame]] = {}
    all_dates: set[pd.Timestamp] = set()
    for symbol, bars in bars_by_symbol.items():
        if bars is None or bars.empty:
            per_symbol_days[symbol] = {}
            continue
        grouped = {day: g for day, g in bars.groupby(_day_key(bars))}
        per_symbol_days[symbol] = grouped
        all_dates.update(grouped.keys())

    # Per-symbol daily context for the opt-in eligibility filters. Computed once
    # over the full intraday history so ATR/prev-close use only prior days.
    use_filters = filters_enabled(cfg)
    daily_ctx: dict[str, pd.DataFrame] = {}
    if use_filters:
        for symbol, bars in bars_by_symbol.items():
            daily_ctx[symbol] = compute_daily_context(bars, cfg)

    equity = float(cfg.starting_equity)
    trades: list[Trade] = []
    curve_dates: list[pd.Timestamp] = []
    curve_equity: list[float] = []

    for day in sorted(all_dates):
        equity_before = equity
        day_pnl = 0.0
        for symbol in sorted(per_symbol_days):
            day_bars = per_symbol_days[symbol].get(day)
            if day_bars is None or day_bars.empty:
                continue
            # Opt-in day filters: skip ineligible sessions before signaling.
            if use_filters and not day_is_eligible(
                day, daily_ctx.get(symbol), compute_opening_range(day_bars, cfg), cfg
            ):
                continue
            for signal in signal_fn(day_bars, cfg):
                trade = _simulate_trade(
                    day_bars, signal, symbol, equity_before, cfg
                )
                if trade is not None:
                    trades.append(trade)
                    day_pnl += trade.pnl
        equity = equity_before + day_pnl
        curve_dates.append(day)
        curve_equity.append(equity)

    # Build outputs. Sort trade log deterministically.
    if trades:
        trade_log = pd.DataFrame([asdict(t) for t in trades])
        trade_log = trade_log.sort_values(["date", "symbol", "entry_ts"]).reset_index(
            drop=True
        )
    else:
        trade_log = pd.DataFrame(columns=[f.name for f in Trade.__dataclass_fields__.values()])

    # Equity curve with a leading starting-equity point.
    start_label = (
        curve_dates[0] - pd.Timedelta(days=1) if curve_dates else pd.Timestamp.min
    )
    equity_curve = pd.Series(
        [float(cfg.starting_equity)] + curve_equity,
        index=[start_label] + curve_dates,
        name="equity",
    )
    return trade_log, equity_curve
