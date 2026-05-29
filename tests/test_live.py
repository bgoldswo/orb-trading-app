"""Live intraday monitor: market-hours gate, poll dedup/alert, run loop (mocked)."""

from __future__ import annotations

import pandas as pd

from orb.config import ORBConfig
from orb.live import is_market_open, poll_once, run_live
from synthetic import ET, flat_day, set_bar, set_opening_range

DATE = "2024-03-04"  # a Monday


def _today_breakout(date=DATE):
    df = flat_day(date, price=100.0)
    set_opening_range(df, date, high=100.0, low=99.0)
    set_bar(df, date, "09:45", c=100.5)  # confirm long
    set_bar(df, date, "09:46", o=100.5)  # entry bar
    return df


def _ts(hhmm, day=DATE):
    return pd.Timestamp(f"{day} {hhmm}", tz=ET)


# --------------------------------------------------------------------------- #
# market-hours gate
# --------------------------------------------------------------------------- #
def test_market_open_only_weekday_rth():
    cfg = ORBConfig()
    assert is_market_open(_ts("10:00"), cfg) is True          # Mon, mid-session
    assert is_market_open(_ts("09:29"), cfg) is False         # before open
    assert is_market_open(_ts("16:00"), cfg) is False         # at close (exclusive)
    assert is_market_open(_ts("10:00", "2024-03-09"), cfg) is False  # Saturday


# --------------------------------------------------------------------------- #
# poll_once
# --------------------------------------------------------------------------- #
def test_poll_emits_then_dedups(tmp_path):
    log = tmp_path / "signals.jsonl"
    fetch = lambda sym, start, end, bm: _today_breakout()  # noqa: E731

    cfg = ORBConfig(**{**ORBConfig().__dict__, "symbols": ["SPY"]})
    first = poll_once(cfg, DATE, fetch=fetch, log_path=log, do_notify=False)
    second = poll_once(cfg, DATE, fetch=fetch, log_path=log, do_notify=False)

    assert len(first) == 1
    assert first[0].symbol == "SPY" and first[0].direction == "long"
    assert second == []  # already alerted today -> no re-ping


# --------------------------------------------------------------------------- #
# run_live loop (fully mocked: clock, sleep, fetch, events)
# --------------------------------------------------------------------------- #
def test_run_live_alerts_once_within_hours(tmp_path):
    log = tmp_path / "signals.jsonl"
    events: list[str] = []
    cfg = ORBConfig(**{**ORBConfig().__dict__, "symbols": ["SPY"]})

    emitted = run_live(
        cfg,
        poll_seconds=0,
        clock=lambda: _ts("10:00"),                       # fixed in-session time
        sleep=lambda s: None,                             # don't actually wait
        fetch=lambda sym, start, end, bm: _today_breakout(),
        log_path=log,
        do_notify=False,
        on_event=events.append,
        max_iterations=2,                                 # two passes
    )
    # Signal emitted on the first pass, deduped on the second.
    assert len(emitted) == 1
    assert any("LIVE SIGNAL" in e for e in events)


def test_run_live_idles_when_market_closed(tmp_path):
    events: list[str] = []
    run_live(
        ORBConfig(),
        poll_seconds=0,
        clock=lambda: _ts("18:00"),     # after close
        sleep=lambda s: None,
        fetch=lambda *a, **k: _today_breakout(),
        log_path=tmp_path / "s.jsonl",
        do_notify=False,
        on_event=events.append,
        max_iterations=1,
    )
    assert any("market closed" in e for e in events)
