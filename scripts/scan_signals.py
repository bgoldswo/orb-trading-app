"""CLI: scan delayed data for today's ORB paper signals and log them.

Places NO orders — it fetches recent intraday data, detects the day's ORB
breakouts, and appends timestamped signals to outputs/signals.jsonl.

Usage:
    python scripts/scan_signals.py                 # cfg.symbols, most recent session
    python scripts/scan_signals.py SPY QQQ NVDA    # override symbols
    python scripts/scan_signals.py --asof 2026-05-28
    python scripts/scan_signals.py --lookback 40   # calendar days of data to pull

Intended to be run after the close (data is ~15-min delayed on the free feed).
This is the script the daily scheduled task invokes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

import pandas as pd

from orb.config import ORBConfig
from orb.data import load_intraday
from orb.notify import notify_signals, telegram_configured
from orb.signals import DEFAULT_LOG, log_signals, scan_for_signals

ET = "America/New_York"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scan for ORB paper signals (no orders).")
    p.add_argument("symbols", nargs="*", help="Symbols to scan (default: ORBConfig.symbols).")
    p.add_argument("--asof", default=None, help="Session date YYYY-MM-DD (default: latest available).")
    p.add_argument("--lookback", type=int, default=40, help="Calendar days of data to fetch.")
    p.add_argument("--no-notify", action="store_true", help="Skip Telegram alerts even if configured.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Force UTF-8 output so non-ASCII is safe in the Windows console and when the
    # scheduled task redirects stdout to a log file.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    cfg = ORBConfig()
    symbols = [s.upper() for s in args.symbols] if args.symbols else cfg.symbols
    cfg = ORBConfig(**{**cfg.__dict__, "symbols": symbols})

    end = pd.Timestamp(args.asof) if args.asof else pd.Timestamp.now(tz=ET).normalize()
    start = (end - timedelta(days=args.lookback)).date().isoformat()
    end_str = end.date().isoformat()

    print(f"Scanning {symbols} for ORB signals (data {start} -> {end_str}, no orders placed)...")
    bars: dict[str, pd.DataFrame] = {}
    try:
        for sym in symbols:
            bars[sym] = load_intraday(sym, start, end_str, cfg.bar_minutes)
    except Exception as exc:  # missing keys / network / bad symbol
        print(f"ERROR: could not load data: {exc}", file=sys.stderr)
        print("Set ALPACA_API_KEY / ALPACA_API_SECRET in .env (see .env.example).", file=sys.stderr)
        return 2

    signals = scan_for_signals(bars, cfg, asof=args.asof)
    if not signals:
        print("No ORB signals for the scanned session.")
        return 0

    new = log_signals(signals, DEFAULT_LOG)
    print(f"Found {len(signals)} signal(s); {len(new)} new (logged to {DEFAULT_LOG}).")
    for s in signals:
        tag = "NEW" if s in new else "dup"
        print(
            f"  [{tag}] {s.asof_date} {s.symbol} {s.direction.upper()} "
            f"entry~{s.reference_entry} stop {s.stop_level} target {s.target_level} "
            f"(~{s.suggested_shares} sh) — {s.note}"
        )

    # Alert on NEW signals only (so re-runs don't re-ping you).
    if new and not args.no_notify:
        if telegram_configured():
            sent = notify_signals(new)
            print(f"Telegram: sent {sent}/{len(new)} alert(s).")
        else:
            print("Telegram not configured (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env to get alerts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
