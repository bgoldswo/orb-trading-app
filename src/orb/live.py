"""Live intraday monitor (real-time-ish ORB alerts).

During market hours this polls each symbol's bars-so-far, detects the day's ORB
breakout *as it forms*, and fires a one-time alert (Telegram) with the Fidelity
order ticket. It places **NO orders** — execution is manual, by design.

Data caveat: on the free IEX feed bars are ~15 minutes delayed, so alerts are
~15 minutes late — fine for building/testing, but genuine real-time entry needs a
paid real-time feed (Alpaca SIP / Polygon). The loop is feed-agnostic; only the
fetch function changes.

Dedup is via the persistent signal log, so each (date, symbol) alerts at most
once — re-polling the same session won't re-ping you.
"""

from __future__ import annotations

import time as _time
from datetime import timedelta
from typing import Callable

import pandas as pd

from .config import ORBConfig
from .data import load_intraday
from .notify import notify_signals
from .signals import DEFAULT_LOG, PaperSignal, log_signals, scan_for_signals
from .strategy import _parse_time

ET = "America/New_York"


def _default_fetch(symbol: str, start: str, end: str, bar_minutes: int) -> pd.DataFrame:
    # force_refresh so an in-progress session isn't served stale from disk cache.
    return load_intraday(symbol, start, end, bar_minutes, force_refresh=True)


def is_market_open(now_et: pd.Timestamp, cfg: ORBConfig) -> bool:
    """True if ``now_et`` is a weekday within [session_open, session_close).
    (Exchange holidays aren't modeled — on a holiday there's simply no data.)"""
    if now_et.weekday() >= 5:  # Sat/Sun
        return False
    tod = now_et.time()
    return _parse_time(cfg.session_open) <= tod < _parse_time(cfg.session_close)


def poll_once(
    cfg: ORBConfig,
    asof_date: str,
    *,
    fetch: Callable = _default_fetch,
    lookback_days: int = 40,
    log_path=DEFAULT_LOG,
    do_notify: bool = True,
) -> list[PaperSignal]:
    """One pass: fetch today's bars, detect signals, log+alert the NEW ones.

    Returns the newly-emitted signals (empty if none or already alerted today).
    """
    end = pd.Timestamp(asof_date)
    start = (end - timedelta(days=lookback_days)).date().isoformat()
    bars = {}
    for sym in cfg.symbols:
        df = fetch(sym, start, asof_date, cfg.bar_minutes)
        if df is not None and not df.empty:
            bars[sym] = df

    signals = scan_for_signals(bars, cfg, asof=asof_date)
    new = log_signals(signals, log_path)
    if new and do_notify:
        notify_signals(new)
    return new


def run_live(
    cfg: ORBConfig | None = None,
    *,
    poll_seconds: int = 60,
    clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz=ET),
    sleep: Callable[[float], None] = _time.sleep,
    fetch: Callable = _default_fetch,
    log_path=DEFAULT_LOG,
    do_notify: bool = True,
    on_event: Callable[[str], None] = print,
    max_iterations: int | None = None,
) -> list[PaperSignal]:
    """Poll for live ORB signals during market hours until stopped.

    Pure dependencies (``clock``, ``sleep``, ``fetch``, ``on_event``,
    ``max_iterations``) are injectable so the loop is fully testable offline.
    Returns all signals emitted during the run.
    """
    cfg = cfg or ORBConfig()
    emitted: list[PaperSignal] = []
    iterations = 0
    while True:
        now = clock()
        if is_market_open(now, cfg):
            new = poll_once(cfg, now.date().isoformat(), fetch=fetch,
                            log_path=log_path, do_notify=do_notify)
            for s in new:
                emitted.append(s)
                on_event(
                    f"🔔 LIVE SIGNAL {s.asof_date} {s.symbol} {s.direction.upper()} "
                    f"entry~{s.reference_entry} stop {s.stop_level} target {s.target_level} "
                    f"(~{s.suggested_shares} sh) — alert sent, NO order placed"
                )
            if not new:
                on_event(f"{now:%H:%M} ET — watching {cfg.symbols}, no new breakout")
        else:
            on_event(f"{now:%Y-%m-%d %H:%M} ET — market closed, idling")

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        sleep(poll_seconds)
    return emitted
