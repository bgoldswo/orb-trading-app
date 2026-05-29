# ORB Trading App — Specification

## Objective
A single deployable app to backtest, and later emit paper-trading **signals**
for, the Opening Range Breakout strategy on liquid US equities. The backtest's
primary job is to test the edge honestly under realistic costs — to disprove a
fragile edge cheaply — not to confirm one.

## In scope
- Historical intraday backtesting of ORB.
- Configurable parameters (range period, exits, sizing, costs).
- Results: equity curve, total return, win rate, max drawdown, Sharpe, and a
  trade-by-trade log.
- Web dashboard (Phase 3).
- Paper / delayed live signals, **no orders** (Phase 4).

## Out of scope (unless explicitly approved)
- Live order execution / broker integration.
- Anything that constitutes financial advice.

## Stack
Python ≥ 3.11 (pandas, numpy) backend; web dashboard frontend; single app.

## Phases & acceptance criteria
1. **Discovery** *(this phase)* — written spec, precise ORB rules, repo
   scaffold, CI green.
2. **Backtesting core** — given symbols + date range + params, produces metrics
   and a trade log; deterministic; no look-ahead; costs modeled. Tests cover
   opening-range computation, entry timing, and stop/target resolution.
3. **UI** — configure params, run a backtest, view equity curve, metrics, and
   trade log.
4. **Paper signals** — emit ORB signals on delayed/paper data; no orders;
   logged and timestamped.
5. **(Optional) Live execution** — only after explicit approval; security and
   regulatory review first. (Note: Fidelity has no public retail trading API, so
   execution would remain manual.)

## Parameter surface
Defined in `src/orb/config.py`; rationale in `docs/ORB_RULES.md`.

## Risk / QA checklist (apply every phase)
- **Look-ahead bias:** no decision uses data unavailable at decision time.
- **Entry realism:** fills modeled with slippage; breakout and stop fills are
  pessimistic, not optimistic.
- **Overfitting:** avoid tuning many parameters to a single sample; reserve
  out-of-sample data before trusting any result.
- **Determinism:** identical inputs produce identical outputs.
- **Secrets/data:** no credentials and no market data committed to the repo.

## Git workflow
- Phase 1 bootstraps `main` (this scaffold).
- Phase 2+: one feature branch per phase → PR → merge after review.
- Small, logical commits with conventional messages.
- GitHub Actions runs the test suite on every push and PR.
- Tag a release per completed phase: `v0.x.0-phaseN`.

## Open decisions (defaults chosen; confirm or override)
1. **Data source** — recommend Alpaca to start (free, programmatic, paper
   account doubles for Phase 4); Polygon.io if paying for cleaner/longer 1-min
   history. `yfinance` only for a throwaway smoke test — its 1-min history is
   short and patchy and is **not** adequate for real backtesting. *Needed before
   Phase 2.*
2. **Opening range period** — default 15 min (configurable 5/15/30).
3. **Breakout confirmation & entry** — default bar-close confirmation, enter
   next bar open (look-ahead-safe).
4. **Exits** — default opposite-range stop, 2R target, flat by 15:55 ET.
5. **Direction** — default long-only first (shorting adds borrow/locate realism
   issues even on paper).
6. **First backtest set** — SPY + QQQ, ~last 2 years.
7. **Repo visibility & license** — default private repo, MIT license
   (placeholder copyright "bgoldswo").
