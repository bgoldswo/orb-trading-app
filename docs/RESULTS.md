# Backtest Results

A running log of backtest findings. Results are **descriptive, not predictive**
(see the disclaimer in the README). Each entry states its data source, window,
and parameters so a flattering or damning number can be read in context.

---

## Phase 2 baseline — plain ORB on SPY + QQQ

- **Date run:** 2026-05-29
- **Window:** 2024-05-01 → 2026-05-28 (~2 years, in-sample, single window)
- **Universe:** SPY, QQQ
- **Data:** Alpaca free **IEX** feed, 1-min bars (thin volume vs. SIP — see caveats)
- **Params:** defaults (`ORBConfig`): 15-min OR, long-only, opposite-range stop,
  2R target, EOD flat 15:55, risk 1%/trade, entry 2 bps / stop 5 bps slippage.
- **Reproduce:** `python scripts/baseline.py`

### Headline (with the opt-in filters A/B'd)

| Run | Trades | Win% | Return | MaxDD | Sharpe | avg R | PF |
|---|--:|--:|--:|--:|--:|--:|--:|
| **vanilla ORB** | 795 | 45.5% | **−29.0%** | 42.0% | −0.40 | −0.03 | 0.92 |
| + gap filter | 541 | 44.4% | −34.6% | 43.8% | −0.71 | −0.07 | 0.87 |
| + OR-width filter | 588 | 43.4% | −27.4% | 42.8% | −0.44 | −0.04 | 0.91 |
| + both filters | 429 | 42.4% | −30.2% | 40.2% | −0.65 | −0.07 | 0.87 |

**Plain 15-min ORB long-only on SPY/QQQ loses money under realistic costs**, and
the opt-in gap / OR-width filters do not rescue it (gap filtering makes it worse).

### Why it bleeds (vanilla run, exit-reason mix)

| Exit | Count | Share | avg R | avg P&L |
|---|--:|--:|--:|--:|
| stop | 368 | 46% | **−1.18R** | −$988 |
| eod | 306 | 38% | +0.55R | +$441 |
| target | 121 | 15% | +2.00R | +$1,648 |

- Only **15%** of trades reach the 2R target; stops outnumber targets ~3:1.
- The average stop is **−1.18R, not −1.0R** — the extra −0.18R is **stop
  slippage**. Across 368 stops that is ~66R of drag, roughly the gap between a
  losing and a break-even system. A backtest that ignored stop slippage would
  have shown this setup as a *winner*. This is exactly the failure mode named in
  [ORB_RULES.md](ORB_RULES.md) ("stop-out slippage on fast reversals") and the
  reason the SPEC insisted on modeling it from day one.

### Caveats
- **In-sample, single window.** No out-of-sample split; do not tune parameters to
  this sample (SPEC overfitting note).
- **IEX feed is thin.** Free IEX is a fraction of consolidated volume; noisier
  intrabar highs/lows can over-trigger an intraday stop strategy. Worth
  re-checking on SIP before treating the magnitude as final.
- **One parameter set / universe.** Long-only, 15-min OR, 2R, ETFs. ORB is
  regime/volatility dependent; this is a verdict on *this* setup, not all ORB.

### Conclusion
The backtester did its job: it disproved a fragile edge cheaply. Default ORB on
these ETFs has no edge here once costs are honest. Sensible next steps (without
overfitting): verify on SIP data, and/or test a higher-volatility single-name
universe — not parameter-mining this window.
