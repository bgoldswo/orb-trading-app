# orb-trading-app

Backtesting and (later) paper-trading **signals** for the Opening Range Breakout
(ORB) strategy on liquid US equities (SPY, QQQ, AAPL, MSFT, NVDA, …).

**No live order execution.** This app backtests and emits paper/delayed signals
only. Live trading is an explicitly-gated future phase that has not been approved.

## Why this exists
The backtest is here to test the ORB edge *honestly under realistic costs* — its
main job is to disprove a fragile edge cheaply, not to flatter one. Stop-out
slippage is modeled from day one because backtests that ignore it overstate ORB.

## Stack
Python ≥ 3.11 (pandas, numpy) backend; web dashboard frontend (Phase 3); single
deployable app.

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## Project layout
```
src/orb/
  config.py     # parameter surface (defaults live here) — implemented
  data.py       # intraday OHLCV loading — Phase 2 stub
  strategy.py   # ORB signal logic — Phase 2 stub (look-ahead contract documented)
  backtest.py   # backtest engine — Phase 2 stub
  metrics.py    # performance metrics — Phase 2 stub
docs/SPEC.md       # specification + acceptance criteria
docs/ORB_RULES.md  # precise strategy definition + failure modes
```

## Phase status
- [x] **Phase 1 — Discovery:** spec, precise ORB rules, scaffold, CI.
- [ ] Phase 2 — Backtesting core
- [ ] Phase 3 — Dashboard UI
- [ ] Phase 4 — Paper-trading signals
- [ ] Phase 5 — (gated) Live execution

## Configuration & secrets
Copy `.env.example` to `.env` and fill in your data-provider keys. **Never commit
`.env`** — it is git-ignored. Market data is not committed either.

## Disclaimer
This software is for research and education. It is **not financial advice**.
Backtested results are not predictive of future returns.
