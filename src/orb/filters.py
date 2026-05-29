"""Day-eligibility filters (OPT-IN — off by default).

These gate which trading sessions ORB is allowed to trade. They are a separate
layer ON PURPOSE: the look-ahead-safe signal logic in strategy.py stays pure, and
plain ORB remains the default so we can A/B the filters honestly instead of
baking unvalidated thresholds into the baseline (see docs/SPEC.md overfitting
note).

Implemented filters:
- Gap filter: skip days whose RTH open gaps too far from the prior RTH close.
- OR-width filter: skip days whose opening range already spans too much of the
  prior-day ATR ("the move has likely happened").

LOOK-AHEAD SAFETY:
- Daily ATR is true-range based and ``shift(1)``-ed, so a day's eligibility uses
  only PRIOR days' ranges — never its own.
- The gap uses today's open and yesterday's close, both known at the open.
- The OR width is known only after the opening-range window closes, which is
  before the (next-bar) entry. Nothing here peeks past the decision point.

FAIL-CLOSED: if the context needed by an ENABLED filter is missing (e.g. the very
first day has no prior close/ATR), the day is treated as NOT tradeable. A risk
filter that can't be evaluated should suppress the trade, not wave it through.
"""

from __future__ import annotations

import pandas as pd

from .strategy import OpeningRange


def compute_daily_context(bars: pd.DataFrame, cfg) -> pd.DataFrame:
    """Resample one symbol's intraday RTH bars into per-day context.

    Returns a DataFrame indexed by normalized (midnight-ET) day timestamps with
    columns: day_open, day_high, day_low, day_close, prev_close, atr_prev. No
    second data feed needed — daily bars are derived from the intraday frame.
    """
    if bars is None or bars.empty:
        return pd.DataFrame(
            columns=["day_open", "day_high", "day_low", "day_close", "prev_close", "atr_prev"]
        )

    g = bars.groupby(bars.index.normalize())
    daily = pd.DataFrame(
        {
            "day_open": g["open"].first(),
            "day_high": g["high"].max(),
            "day_low": g["low"].min(),
            "day_close": g["close"].last(),
        }
    ).sort_index()

    daily["prev_close"] = daily["day_close"].shift(1)

    # True range = max(H-L, |H-prevC|, |L-prevC|); on day 1 prevC is NaN and the
    # max ignores it, falling back to the H-L range.
    prev_close = daily["prev_close"]
    true_range = pd.concat(
        [
            daily["day_high"] - daily["day_low"],
            (daily["day_high"] - prev_close).abs(),
            (daily["day_low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.ewm(span=cfg.atr_period, adjust=False).mean()
    daily["atr_prev"] = atr.shift(1)  # prior days only -> look-ahead safe
    return daily


def filters_enabled(cfg) -> bool:
    return bool(cfg.use_gap_filter or cfg.use_or_width_filter)


def day_is_eligible(
    day_key: pd.Timestamp,
    daily_ctx: pd.DataFrame,
    opening_range: OpeningRange | None,
    cfg,
) -> bool:
    """Whether ORB may trade ``day_key``. True when no filter is enabled."""
    if not filters_enabled(cfg):
        return True
    if daily_ctx is None or day_key not in daily_ctx.index:
        return False  # fail-closed: no context to validate against
    row = daily_ctx.loc[day_key]

    if cfg.use_gap_filter:
        prev_close = row["prev_close"]
        if pd.isna(prev_close) or prev_close == 0:
            return False
        gap_pct = abs(row["day_open"] - prev_close) / abs(prev_close)
        if gap_pct > cfg.max_gap_pct:
            return False

    if cfg.use_or_width_filter:
        atr_prev = row["atr_prev"]
        if opening_range is None or pd.isna(atr_prev) or atr_prev <= 0:
            return False
        or_width = opening_range.high - opening_range.low
        if or_width > cfg.max_or_width_atr * atr_prev:
            return False

    return True
