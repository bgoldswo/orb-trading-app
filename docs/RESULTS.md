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

---

## Phase 4.5 — walk-forward optimization on SPY + QQQ ("let the bot pick")

- **Date run:** 2026-05-29
- **Window:** 2024-05-29 → 2026-05-28; IS=365d, OOS=90d (rolling)
- **Search space:** OR-minutes {5,15,30} × take-profit R {1.5,2,2.5,3} × direction
  {long_only, long_short} × gap filter {off,on} × OR-width filter {off,on} = 96 combos
- **Objective:** Avg R (expectancy), min 10 in-sample trades to qualify
- **Reproduce:** `python scripts/optimize.py SPY QQQ --is-days 365 --oos-days 90 --objective avg_r`

The optimizer chose parameters per fold on in-sample data, then was scored on the
next unseen out-of-sample window:

| OOS window | chosen params | IS avg R | OOS avg R | OOS return |
|---|---|--:|--:|--:|
| 2025-05→08 | OR30, 3R, L/S, gap+width | +0.100 | −0.191 | −8.7% |
| 2025-08→11 | OR15, 1.5R, L/S, width | +0.034 | −0.107 | −8.5% |
| 2025-11→02 | OR15, 3R, L/S, gap+width | +0.034 | +0.213 | +10.1% |
| 2026-02→05 | OR15, 3R, L/S, gap+width | +0.043 | −0.416 | −22.1% |
| 2026-05 (partial) | OR30, 3R, L/S | −0.036 | +0.340 | +2.0% |

**Stitched out-of-sample:** 232 trades, win 40.1%, **return −26.9%**, maxDD 32.2%,
Sharpe −1.19, avg R −0.123, PF 0.80.

**Overfitting check (avg R):** IS mean **+0.035** vs OOS mean **−0.032**
(gap **+0.067**). The in-sample "edge" *flipped to a loss out of sample*.

### Conclusion
Letting the machine choose parameters — done honestly via walk-forward — **confirms
there is no robust ORB edge on SPY/QQQ**. The optimizer did find slightly positive
*in-sample* expectancy each fold, but it did not survive out of sample (it inverted).
This is exactly why we built it walk-forward: a naive grid search would have
reported the +0.035 in-sample figure and called it a winner. The honest answer is
the opposite. To actually find an edge, change the **universe** (e.g. volatile
single names), not the parameter search on these ETFs.

---

## Phase 4.5 — walk-forward on volatile single names (NVDA + TSLA + AMD)

Testing the hypothesis that ORB's momentum premise works better on high-volatility
single names than on ETFs.

- **Date run:** 2026-05-29 · **Window:** 2024-05-29 → 2026-05-28 · IS=365d / OOS=90d
- **Data:** Alpaca free IEX, 1-min · same 96-combo space, objective Avg R, min 10 IS trades
- **Reproduce:** `python scripts/optimize.py NVDA TSLA AMD --is-days 365 --oos-days 90`

**Stitched out-of-sample:** 583 trades, win 39.6%, **return −34.9%**, maxDD 35.7%,
Sharpe −1.20, avg R −0.065, PF 0.86.

**Overfitting check (avg R):** IS mean **+0.014** vs OOS mean **−0.194**
(gap **+0.208** — a *larger* collapse than the ETFs).

### Conclusion
The hypothesis did not hold: walk-forward on volatile single names is **worse**, not
better, and the in-sample-to-out-of-sample degradation is bigger. Across every test
run so far — vanilla ORB, filtered ORB, bot-optimized ETFs, and bot-optimized single
names — **no configuration shows a robust out-of-sample edge** once costs are honest.
Caveat: the free IEX feed is thin (especially for single names), which can over-trigger
intraday stops; the *magnitude* may differ on SIP data, but the *direction* (no robust
edge) has been consistent across four independent tests.

> Methodology note: the optimizer now parallelizes the per-fold in-sample search
> across CPU cores (`--workers`, default auto), verified to produce identical
> results to the serial path.

---

## A different strategy — intraday EMA crossover on SPY + QQQ

The engine is now strategy-agnostic; this is a *different* strategy (fast/slow EMA
cross, % stop + R-multiple target) run through the identical walk-forward + cost
model — testing whether changing the *strategy* (not the universe) finds an edge.

- **Date run:** 2026-05-29 · **Window:** 2024-05-29 → 2026-05-28 · IS=365d / OOS=90d
- **Search space:** fast EMA {5,9,12} × slow EMA {20,30,50} × R {1.5,2,3} × direction
- **Reproduce:** `python scripts/optimize.py --strategy ma SPY QQQ`

**Stitched out-of-sample:** 502 trades, win 44.6%, **return −41.5%**, maxDD 50.4%,
Sharpe −1.81, avg R −0.099, PF 0.73.

**Overfitting check (avg R):** IS mean **−0.061** vs OOS mean **−0.084** (gap +0.024).

### Conclusion
EMA crossover is the **clearest loser yet** — and tellingly, its in-sample avg R was
**already negative** (−0.061). The optimizer couldn't find a profitable parameter set
even *in hindsight* on the training data, so there was no in-sample "edge" to overfit
(hence the tiny gap). It just loses, consistently.

**The pattern across all tests is now unmistakable:** plain ORB, filtered ORB,
bot-optimized ORB (ETFs and volatile names), and bot-optimized EMA crossover — **none
show a robust out-of-sample edge** on liquid US equities once realistic costs are
modeled. This matches the well-documented reality that simple intraday
technical-analysis edges are largely arbitraged away and/or eaten by costs. The
honest verdict: **don't trade these with real money.** The value delivered is the
*disproof* — cheaply, before any capital was at risk.
