"""CLI: live intraday ORB monitor — real-time alerts, NO orders.

Run during US market hours; it watches your symbols and Telegram-alerts you the
moment an ORB breakout fires, with a copy-paste Fidelity ticket. You place the
order manually. Stop with Ctrl+C.

Usage:
    python scripts/live_monitor.py                 # cfg.symbols, poll every 60s
    python scripts/live_monitor.py NVDA TSLA --poll 30
    python scripts/live_monitor.py --once          # single pass (testing)

Data note: the free IEX feed is ~15 min delayed, so alerts lag ~15 min. For true
real-time, use a paid feed (set ALPACA_FEED=sip with a subscription).
"""

from __future__ import annotations

import argparse
import sys

from orb.config import ORBConfig
from orb.live import run_live
from orb.notify import telegram_configured


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(description="Live intraday ORB monitor (no orders).")
    p.add_argument("symbols", nargs="*", help="Symbols (default: ORBConfig.symbols).")
    p.add_argument("--poll", type=int, default=60, help="Seconds between polls (REST mode).")
    p.add_argument("--once", action="store_true", help="Single REST pass then exit (testing).")
    p.add_argument("--stream", action="store_true",
                   help="Use the real-time Alpaca websocket feed instead of REST polling.")
    a = p.parse_args(argv if argv is not None else sys.argv[1:])

    cfg = ORBConfig()
    if a.symbols:
        cfg = ORBConfig(**{**cfg.__dict__, "symbols": [s.upper() for s in a.symbols]})

    mode = "real-time websocket" if a.stream else f"REST poll {a.poll}s"
    print(f"Live ORB monitor — symbols {cfg.symbols}, {mode}. NO orders are placed.")
    print(f"Telegram alerts: {'ON' if telegram_configured() else 'OFF (set TELEGRAM_* in .env)'}")
    print("Ctrl+C to stop.\n")
    try:
        if a.stream:
            from orb.stream import run_stream  # imports websocket (the [live] extra)
            run_stream(cfg)
        else:
            run_live(cfg, poll_seconds=a.poll, max_iterations=1 if a.once else None)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
