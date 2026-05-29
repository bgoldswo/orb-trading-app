"""Paper-trading signal engine (Phase 4).

Scans recent/delayed intraday data for the day's ORB breakout signals and logs
them, **timestamped, with no orders placed**. This is the same look-ahead-safe
logic the backtester uses — a signal is only emitted once the confirming bar has
closed and the next bar's open (the intended entry) is known.

NOTHING here connects to a broker. Every emitted record carries
``placed_order = False``; this module's only side effect is appending to a log
file. Live order execution is an explicitly-gated future phase (see docs/SPEC.md).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .filters import compute_daily_context, day_is_eligible, filters_enabled
from .strategy import LONG, compute_opening_range, generate_signals

# Default log location (outputs/ is git-ignored).
DEFAULT_LOG = Path("outputs") / "signals.jsonl"


@dataclass(frozen=True)
class PaperSignal:
    """A single emitted paper signal. Prices are the strategy's *intended* plan
    (no slippage modeled — this is a signal, not a fill)."""

    emitted_at: str        # UTC ISO timestamp: when the scan produced this record
    asof_date: str         # trading day scanned (ET date, YYYY-MM-DD)
    symbol: str
    direction: str         # "long" | "short"
    or_high: float
    or_low: float
    confirmation_ts: str   # ET ISO: bar whose CLOSE confirmed the breakout
    entry_ts: str          # ET ISO: next bar (intended entry)
    reference_entry: float  # next bar's open — the intended entry price
    stop_level: float
    target_level: float
    risk_per_share: float
    suggested_shares: int  # risk-based size off the configured paper equity
    placed_order: bool = False                 # ALWAYS False — paper only
    note: str = "PAPER SIGNAL — no order placed"

    def to_record(self) -> dict:
        return asdict(self)


def _build(sig, symbol: str, asof_date: str, cfg, emitted_at: str) -> PaperSignal | None:
    """Turn an engine Signal into a sized paper signal, or None if untradeable."""
    is_long = sig.direction == LONG
    stop_level = sig.or_low if is_long else sig.or_high
    risk_per_share = abs(sig.reference_entry - stop_level)
    if risk_per_share <= 0:
        return None
    target_level = (
        sig.reference_entry + cfg.take_profit_r * risk_per_share
        if is_long
        else sig.reference_entry - cfg.take_profit_r * risk_per_share
    )
    risk_dollars = cfg.risk_per_trade * cfg.starting_equity
    suggested_shares = int(risk_dollars // risk_per_share)  # whole shares, floored
    return PaperSignal(
        emitted_at=emitted_at,
        asof_date=asof_date,
        symbol=symbol,
        direction=sig.direction,
        or_high=round(float(sig.or_high), 4),
        or_low=round(float(sig.or_low), 4),
        confirmation_ts=sig.confirmation_ts.isoformat(),
        entry_ts=sig.entry_ts.isoformat(),
        reference_entry=round(float(sig.reference_entry), 4),
        stop_level=round(float(stop_level), 4),
        target_level=round(float(target_level), 4),
        risk_per_share=round(float(risk_per_share), 4),
        suggested_shares=suggested_shares,
    )


def _select_day(bars: pd.DataFrame, asof: str | None):
    """Return (day_bars, asof_date_str) for the chosen session, or (None, None)."""
    dates = sorted({ts.date() for ts in bars.index})
    if not dates:
        return None, None
    if asof is not None:
        target = pd.Timestamp(asof).date()
        if target not in dates:
            return None, None
    else:
        target = dates[-1]  # most recent available session
    day_bars = bars[[ts.date() == target for ts in bars.index]]
    return day_bars, target.isoformat()


def scan_for_signals(
    bars_by_symbol: dict[str, pd.DataFrame],
    cfg,
    asof: str | None = None,
    emitted_at: str | None = None,
) -> list[PaperSignal]:
    """Emit paper signals for the as-of session (default: most recent available).

    Applies the same opt-in day filters as the backtest, so what the scanner
    surfaces matches what the strategy would actually have taken.
    """
    emitted_at = emitted_at or datetime.now(timezone.utc).isoformat()
    use_filters = filters_enabled(cfg)
    out: list[PaperSignal] = []

    for symbol in sorted(bars_by_symbol):
        bars = bars_by_symbol[symbol]
        if bars is None or bars.empty:
            continue
        day_bars, asof_date = _select_day(bars, asof)
        if day_bars is None or day_bars.empty:
            continue

        if use_filters:
            ctx = compute_daily_context(bars, cfg)
            day_key = day_bars.index.normalize()[0]
            if not day_is_eligible(day_key, ctx, compute_opening_range(day_bars, cfg), cfg):
                continue

        for sig in generate_signals(day_bars, cfg):
            rec = _build(sig, symbol, asof_date, cfg, emitted_at)
            if rec is not None:
                out.append(rec)
    return out


def _existing_keys(path: Path) -> set[tuple[str, str]]:
    """(asof_date, symbol) pairs already in the log, for idempotent appends."""
    keys: set[tuple[str, str]] = set()
    if not path.exists():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            keys.add((d.get("asof_date"), d.get("symbol")))
        except json.JSONDecodeError:
            continue
    return keys


def log_signals(records: list[PaperSignal], path: str | Path = DEFAULT_LOG) -> list[PaperSignal]:
    """Append new signals to the JSONL log. Idempotent per (asof_date, symbol):
    re-scanning the same day won't duplicate rows. Returns the newly-written ones."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_keys(path)
    new = [r for r in records if (r.asof_date, r.symbol) not in existing]
    if new:
        with path.open("a", encoding="utf-8") as fh:
            for rec in new:
                fh.write(json.dumps(rec.to_record()) + "\n")
    return new


def load_signal_log(path: str | Path = DEFAULT_LOG) -> pd.DataFrame:
    """Read the signal log into a DataFrame (empty if no log yet)."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return pd.DataFrame(rows)
