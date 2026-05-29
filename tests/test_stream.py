"""Real-time bar stream: message parsing + emit/dedup via an injected source.

No network: a list of bar messages is fed to run_stream, exactly as the Alpaca
websocket would deliver them.
"""

from __future__ import annotations

import pandas as pd

from orb.config import ORBConfig
from orb.stream import bar_message_to_row, run_stream, update_and_detect
from synthetic import ET, flat_day, set_bar, set_opening_range

DATE = "2024-03-04"


def _bar_messages(df: pd.DataFrame, symbol="SPY", upto="09:50"):
    """Turn synthetic day bars into Alpaca-style bar messages, in time order."""
    cutoff = pd.Timestamp(f"{DATE} {upto}", tz=ET)
    msgs = []
    for ts, r in df.loc[df.index <= cutoff].iterrows():
        msgs.append({
            "T": "b", "S": symbol,
            "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume,
            "t": ts.tz_convert("UTC").isoformat(),
        })
    return msgs


def _breakout_day():
    df = flat_day(DATE, price=100.0)
    set_opening_range(df, DATE, high=100.0, low=99.0)
    set_bar(df, DATE, "09:45", c=100.5)  # confirm long
    set_bar(df, DATE, "09:46", o=100.5)  # entry bar
    return df


def test_bar_message_to_row_parses_utc_to_et():
    msg = {"T": "b", "S": "SPY", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100,
           "t": "2024-03-04T14:30:00Z"}  # 14:30 UTC = 09:30 EST
    sym, ts, row = bar_message_to_row(msg)
    assert sym == "SPY"
    assert str(ts.tz) == ET and ts.strftime("%H:%M") == "09:30"
    assert row["open"] == 1.0 and row["close"] == 1.5


def test_stream_emits_signal_then_dedups(tmp_path):
    log = tmp_path / "signals.jsonl"
    msgs = _bar_messages(_breakout_day())
    emitted = run_stream(
        ORBConfig(**{**ORBConfig().__dict__, "symbols": ["SPY"]}),
        seed=False, do_notify=False, log_path=log,
        message_source=msgs, on_event=lambda *_: None,
    )
    assert len(emitted) == 1
    s = emitted[0]
    assert s.symbol == "SPY" and s.direction == "long"
    assert s.reference_entry == 100.5 and s.stop_level == 99.0


def test_update_and_detect_no_signal_before_entry_bar(tmp_path):
    """A breakout that confirms on the last fed bar has no next bar yet -> no signal."""
    log = tmp_path / "s.jsonl"
    df = _breakout_day()
    state: dict = {}
    new = []
    for msg in _bar_messages(df, upto="09:45"):  # stop AT the confirming bar
        new += update_and_detect(state, msg, ORBConfig(), log_path=log, do_notify=False)
    assert new == []  # entry bar (09:46) hasn't arrived
