"""Real-time bar streaming via Alpaca's IEX websocket (free) — no orders.

Upgrades the live monitor from REST polling to a genuine real-time feed: it
subscribes to 1-minute bars and re-evaluates ORB on each completed bar, alerting
the instant a breakout confirms.

Correctness detail: if you start mid-session you'd miss the opening-range bars, so
``run_stream`` **seeds** today's bars via REST first, then streams updates on top.

Data caveat (unchanged): the free IEX feed is one venue (~2-3% of volume), so its
highs/lows can miss true extremes — fine for paper/learning, shaky for real
trading. Swap to SIP (paid) by setting ALPACA_FEED=sip. Still places NO orders.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Callable, Iterable

import pandas as pd

from .config import ORBConfig
from .data import _load_dotenv, load_intraday
from .notify import notify_signals
from .signals import DEFAULT_LOG, PaperSignal, log_signals, scan_for_signals

ET = "America/New_York"
_STREAM_URL = "wss://stream.data.alpaca.markets/v2/{feed}"
_COLS = ("open", "high", "low", "close", "volume")


def bar_message_to_row(item: dict) -> tuple[str, pd.Timestamp, dict]:
    """Alpaca bar message -> (symbol, ET timestamp, OHLCV row dict)."""
    ts = pd.Timestamp(item["t"]).tz_convert(ET)  # Alpaca 't' is RFC3339 UTC
    row = {
        "open": float(item["o"]), "high": float(item["h"]), "low": float(item["l"]),
        "close": float(item["c"]), "volume": float(item.get("v", 0)),
    }
    return item["S"], ts, row


def update_and_detect(
    state: dict[str, pd.DataFrame],
    item: dict,
    cfg: ORBConfig,
    *,
    log_path=DEFAULT_LOG,
    do_notify: bool = True,
) -> list[PaperSignal]:
    """Fold one bar into ``state`` and emit/alert any NEW ORB signal for it.

    ``state`` maps symbol -> accumulated ET-indexed OHLCV DataFrame. Dedup is via
    the persistent signal log, so a signal alerts at most once per day+symbol."""
    sym, ts, row = bar_message_to_row(item)
    new_row = pd.DataFrame([row], index=pd.DatetimeIndex([ts], name="timestamp"))[list(_COLS)]
    prev = state.get(sym)
    df = pd.concat([prev, new_row]) if prev is not None and not prev.empty else new_row
    state[sym] = df[~df.index.duplicated(keep="last")].sort_index()

    signals = scan_for_signals({sym: state[sym]}, cfg, asof=ts.date().isoformat())
    new = log_signals(signals, log_path)
    if new and do_notify:
        notify_signals(new)
    return new


def _seed_state(cfg: ORBConfig, asof_date: str, lookback_days: int) -> dict[str, pd.DataFrame]:
    """Pre-load today's (and recent) bars via REST so the opening range isn't
    missed when starting mid-session."""
    end = pd.Timestamp(asof_date)
    start = (end - timedelta(days=lookback_days)).date().isoformat()
    state: dict[str, pd.DataFrame] = {}
    for sym in cfg.symbols:
        try:
            df = load_intraday(sym, start, asof_date, cfg.bar_minutes, force_refresh=True)
        except Exception:
            df = None
        if df is not None and not df.empty:
            state[sym] = df
    return state


def _alpaca_bar_stream(cfg: ORBConfig, feed: str | None = None) -> Iterable[dict]:
    """Connect to Alpaca's websocket and yield 1-minute bar messages."""
    import websocket  # lazy: only needed for the real feed (optional [live] extra)

    _load_dotenv()
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not set (see .env.example).")
    feed = feed or os.environ.get("ALPACA_FEED", "iex")

    ws = websocket.create_connection(_STREAM_URL.format(feed=feed), timeout=30)
    try:
        ws.recv()  # {"T":"success","msg":"connected"}
        ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
        ws.recv()  # authenticated
        ws.send(json.dumps({"action": "subscribe", "bars": list(cfg.symbols)}))
        ws.recv()  # subscription confirmation
        while True:
            for item in json.loads(ws.recv()):
                if item.get("T") == "b":  # a completed bar
                    yield item
    finally:
        ws.close()


def run_stream(
    cfg: ORBConfig | None = None,
    *,
    seed: bool = True,
    lookback_days: int = 20,
    feed: str | None = None,
    log_path=DEFAULT_LOG,
    do_notify: bool = True,
    on_event: Callable[[str], None] = print,
    message_source: Iterable[dict] | None = None,
    max_messages: int | None = None,
) -> list[PaperSignal]:
    """Stream real-time bars and alert ORB signals live. Places NO orders.

    ``message_source`` is injectable (an iterable of bar messages) so the loop is
    fully testable offline; default connects to Alpaca's IEX websocket.
    """
    cfg = cfg or ORBConfig()
    asof = pd.Timestamp.now(tz=ET).date().isoformat()
    state = _seed_state(cfg, asof, lookback_days) if seed else {}
    source = message_source if message_source is not None else _alpaca_bar_stream(cfg, feed)

    emitted: list[PaperSignal] = []
    count = 0
    for item in source:
        for s in update_and_detect(state, item, cfg, log_path=log_path, do_notify=do_notify):
            emitted.append(s)
            on_event(
                f"🔔 LIVE SIGNAL {s.asof_date} {s.symbol} {s.direction.upper()} "
                f"entry~{s.reference_entry} stop {s.stop_level} target {s.target_level} "
                f"(~{s.suggested_shares} sh) — alert sent, NO order placed"
            )
        count += 1
        if max_messages is not None and count >= max_messages:
            break
    return emitted
