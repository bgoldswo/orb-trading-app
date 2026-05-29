"""ORB parameter surface. Defaults here are the project's starting assumptions;
all are configurable. See docs/ORB_RULES.md for the rationale."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ORBConfig:
    # --- universe ---
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])

    # --- opening range ---
    opening_range_minutes: int = 15        # 5 / 15 / 30
    bar_minutes: int = 1                   # intraday bar granularity used

    # --- entry (look-ahead-safe defaults) ---
    breakout_confirmation: str = "bar_close"   # "bar_close" | "intrabar"
    entry_timing: str = "next_bar_open"        # enter on bar AFTER confirmation
    direction: str = "long_only"               # "long_only" | "long_short"
    max_trades_per_day: int = 1                # first valid breakout only

    # --- exits ---
    stop_type: str = "opposite_range"          # "opposite_range" | "atr" | "pct"
    take_profit_r: float = 2.0                 # target = R-multiple of risk
    eod_flat_time: str = "15:55"               # flatten before the close (ET)

    # --- sizing & capital ---
    risk_per_trade: float = 0.01               # fraction of equity risked / trade
    starting_equity: float = 100_000.0

    # --- session (US RTH, exchange-local time) ---
    session_open: str = "09:30"
    session_close: str = "16:00"

    # --- cost model (intentionally on from day one) ---
    slippage_bps_entry: float = 2.0            # breakout entries chase
    slippage_bps_stop: float = 5.0             # stop-outs fill worst
    commission_per_share: float = 0.0
