"""Intraday OHLCV loading (Alpaca Market Data v2, with a local cache).

Contract honored by the implementation:
- Returns a tidy DataFrame indexed by timezone-aware ET timestamps with columns
  [open, high, low, close, volume], one row per ``bar_minutes`` bar, RTH only
  (09:30–16:00 ET).
- Bars are Alpaca's split-adjusted feed; we request ``adjustment=all``.
- Fetched data is cached to ``data/cache/`` (git-ignored) so repeat backtests run
  offline and deterministically. The engine and tests never need the network —
  only first-time fetches do.

Credentials come from the environment (``ALPACA_API_KEY`` / ``ALPACA_API_SECRET``);
copy ``.env.example`` to ``.env``. ``.env`` is loaded if present, but no extra
dependency is required.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

_ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
_ET = "America/New_York"
_RTH_OPEN = "09:30"
_RTH_CLOSE = "16:00"  # inclusive of bars up to but not at the close
_DEFAULT_CACHE = Path("data") / "cache"


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader: populates os.environ for keys not already set.
    Avoids a python-dotenv dependency; ignores malformed lines."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _cache_path(symbol: str, start: str, end: str, bar_minutes: int, cache_dir: Path) -> Path:
    name = f"{symbol.upper()}_{bar_minutes}m_{start}_{end}.csv"
    return cache_dir / name


def _timeframe(bar_minutes: int) -> str:
    """Map a minute granularity to an Alpaca timeframe string."""
    if bar_minutes % 60 == 0:
        hours = bar_minutes // 60
        return f"{hours}Hour"
    return f"{bar_minutes}Min"


def _fetch_alpaca(symbol: str, start: str, end: str, bar_minutes: int) -> pd.DataFrame:
    _load_dotenv()
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "ALPACA_API_KEY / ALPACA_API_SECRET not set. Copy .env.example to "
            ".env and fill them in (see docs/SPEC.md)."
        )

    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    base = _ALPACA_BARS_URL.format(symbol=urllib.parse.quote(symbol.upper()))
    rows: list[dict] = []
    page_token: str | None = None

    while True:
        params = {
            "timeframe": _timeframe(bar_minutes),
            "start": start,
            "end": end,
            "adjustment": "all",
            "feed": "iex",  # free tier; override via ALPACA_FEED for sip
            "limit": 10_000,
        }
        if os.environ.get("ALPACA_FEED"):
            params["feed"] = os.environ["ALPACA_FEED"]
        if page_token:
            params["page_token"] = page_token

        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (trusted host)
            payload = json.loads(resp.read().decode("utf-8"))

        rows.extend(payload.get("bars") or [])
        page_token = payload.get("next_page_token")
        if not page_token:
            break

    if not rows:
        return _empty_frame()

    df = pd.DataFrame(rows)
    # Alpaca columns: t,o,h,l,c,v,n,vw -> our schema.
    df = df.rename(
        columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def _empty_frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz=_ET, name="timestamp")
    return pd.DataFrame(
        {c: pd.Series(dtype="float64") for c in ("open", "high", "low", "close", "volume")},
        index=idx,
    )


def _to_et_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a UTC-indexed frame to ET and keep only regular-hours bars."""
    if df.empty:
        return _empty_frame()
    if df.index.tz is None:
        df = df.tz_localize("UTC")
    df = df.tz_convert(_ET).sort_index()
    # RTH: bars stamped in [09:30, 16:00) ET.
    tod = df.index.time
    open_t = pd.Timestamp(_RTH_OPEN).time()
    close_t = pd.Timestamp(_RTH_CLOSE).time()
    return df.loc[(tod >= open_t) & (tod < close_t)]


def load_intraday(
    symbol: str,
    start: str,
    end: str,
    bar_minutes: int = 1,
    *,
    cache_dir: str | os.PathLike | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Load intraday OHLCV for one symbol over ``[start, end]`` (ISO dates).

    Reads from the local cache when present; otherwise fetches from Alpaca and
    caches the result. Returns RTH-only bars indexed by tz-aware ET timestamps.
    """
    cache_root = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE
    path = _cache_path(symbol, start, end, bar_minutes, cache_root)

    if path.exists() and not force_refresh:
        df = pd.read_csv(path, index_col="timestamp", parse_dates=["timestamp"])
        # Cached timestamps are stored in UTC ISO form; normalize to ET.
        if df.index.tz is None:
            df.index = pd.to_datetime(df.index, utc=True)
        return _to_et_rth(df)

    raw = _fetch_alpaca(symbol, start, end, bar_minutes)
    df = _to_et_rth(raw)

    cache_root.mkdir(parents=True, exist_ok=True)
    # Persist in UTC so the cache file is tz-unambiguous across machines.
    to_save = df.tz_convert("UTC") if not df.empty else df
    to_save.to_csv(path)
    return df
