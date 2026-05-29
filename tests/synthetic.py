"""Synthetic intraday bar builders for deterministic Phase 2 tests.

No network, no provider — just hand-built OHLCV days so each ORB rule can be
exercised in isolation. All timestamps are tz-aware ET, matching the data
contract in src/orb/data.py.
"""

from __future__ import annotations

import pandas as pd

ET = "America/New_York"


def day_index(date_str: str, start: str = "09:30", end: str = "16:00") -> pd.DatetimeIndex:
    """1-minute RTH timestamps for one day: [09:30, 16:00) -> 390 bars."""
    start_ts = pd.Timestamp(f"{date_str} {start}", tz=ET)
    end_ts = pd.Timestamp(f"{date_str} {end}", tz=ET)
    return pd.date_range(start_ts, end_ts, freq="1min", inclusive="left")


def flat_day(date_str: str, price: float = 100.0, volume: float = 1000.0) -> pd.DataFrame:
    """A full RTH day where every bar is flat at ``price`` (no signals on its own)."""
    idx = day_index(date_str)
    df = pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": volume},
        index=idx,
    )
    df.index.name = "timestamp"
    return df


def set_opening_range(
    df: pd.DataFrame, date_str: str, high: float, low: float, minutes: int = 15
) -> pd.DataFrame:
    """Overwrite the first ``minutes`` bars so OR_high=high, OR_low=low."""
    mid = (high + low) / 2.0
    for ts in day_index(date_str)[:minutes]:
        df.loc[ts, ["open", "high", "low", "close"]] = [mid, high, low, mid]
    return df


def set_bar(
    df: pd.DataFrame,
    date_str: str,
    hhmm: str,
    *,
    o: float | None = None,
    h: float | None = None,
    l: float | None = None,
    c: float | None = None,
    v: float | None = None,
) -> pd.DataFrame:
    """Overwrite individual OHLCV fields of a single bar (others left as-is)."""
    ts = pd.Timestamp(f"{date_str} {hhmm}", tz=ET)
    for col, val in (("open", o), ("high", h), ("low", l), ("close", c), ("volume", v)):
        if val is not None:
            df.loc[ts, col] = val
    return df
