# ORB — Precise Rules (US Equities, Regular Trading Hours)

## Session
Regular trading hours, 09:30–16:00 ET. All logic uses exchange-local time.

## Opening range
- OR window = first **N** minutes from 09:30 (N ∈ {5, 15, 30}; default 15).
- `OR_high` = highest high over the window; `OR_low` = lowest low.
- The range is fixed only **after** the window closes.

## Breakout & entry
- **Long** when price breaks above `OR_high`; **short** when below `OR_low`
  (default: long only).
- **Confirmation:** bar **close** beyond the level (default) — reduces false
  breakouts at the cost of a slightly later entry.
- **Entry:** at the **next** bar's open after confirmation. This is the
  look-ahead-safe convention — we never assume a fill at a price the bar had not
  yet traded through at decision time.
- **One trade per symbol per day** (first valid breakout only).

## Stops & targets
- **Stop (default):** opposite side of the opening range (`OR_low` for a long).
  Alternatives: ATR multiple, or fixed %.
- **Target (default):** R-multiple, where `R = |entry − stop|`; default **2R**.
  Alternatives: trailing stop, or no fixed target (exit only at EOD/stop).
- **End of day:** flatten all positions at **15:55 ET** regardless of P&L.
- **Same-bar ambiguity:** if one bar touches both stop and target, the intrabar
  path is unknown from OHLC — assume the **stop** hit first (conservative).

## Position sizing
- Risk-based: `risk_$ = risk_per_trade × equity` (default 1%);
  `shares = risk_$ / |entry − stop|`.

## Cost model (on from day one — on purpose)
- Entry slippage (breakouts chase strength): default 2 bps.
- Stop slippage (worst fills, fast reversals): default 5 bps.
- Commission: configurable per share (default 0).
- Backtests that ignore stop slippage overstate ORB; this one will not.

## Known failure modes
- **False breakouts / whipsaw** on choppy days — the dominant losing pattern.
- **Stop-out slippage** on fast reversals.
- **Poor entry fills** inherent to chasing breakouts.
- **Regime dependence** — better in trending / high-volatility conditions; bleeds
  in low-vol, range-bound markets.
- **Gap-through-open days** where the opening auction blows past levels.
- **Overfitting** N and the R-multiple to a single historical sample.

## Literature (treat as a pointer, not a target)
ORB is a conventional intraday construction. An often-cited study
(Zarattini & Aziz, 2023) examined a 5-minute ORB on QQQ. Treat any specific
performance figures from it (or any source) as **unverified** until we pull the
source directly — we do **not** design to its numbers, and reported results
typically assume cost/leverage choices that must be checked.
