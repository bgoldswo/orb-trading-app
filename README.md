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
  data.py       # intraday OHLCV loading (Alpaca + local cache) — implemented
  strategy.py   # ORB signal logic (look-ahead-safe) — implemented
  backtest.py   # backtest engine (cost model, stop/target) — implemented
  metrics.py    # performance metrics — implemented
docs/SPEC.md       # specification + acceptance criteria
docs/ORB_RULES.md  # precise strategy definition + failure modes
```

## Running a backtest
```python
from orb.config import ORBConfig
from orb.data import load_intraday
from orb.backtest import run_backtest
from orb.metrics import performance_summary

cfg = ORBConfig()                         # defaults; override any field
bars = {s: load_intraday(s, "2023-01-01", "2024-12-31", cfg.bar_minutes)
        for s in cfg.symbols}             # first fetch hits Alpaca, then cached
trade_log, equity_curve = run_backtest(bars, cfg)
print(performance_summary(trade_log, equity_curve))
```
`load_intraday` needs `ALPACA_API_KEY` / `ALPACA_API_SECRET` in `.env` on the
first fetch; results cache to `data/cache/` (git-ignored) so reruns are offline
and deterministic. The engine itself needs no network — see `tests/` for
fully synthetic, hermetic coverage.

### Optional day filters (off by default)
Two opt-in session filters can gate which days ORB trades — a **gap filter**
(skip large overnight gaps) and an **OR-width/ATR filter** (skip days whose
opening range is already wide). They are **off by default** so the baseline
measures plain ORB; their thresholds are unvalidated and should be tuned only
against out-of-sample data. Enable per run, e.g.:
```python
cfg = ORBConfig(use_gap_filter=True, use_or_width_filter=True)
```
See `src/orb/filters.py` (look-ahead-safe; fail-closed when context is missing).

## Phase status
- [x] **Phase 1 — Discovery:** spec, precise ORB rules, scaffold, CI.
- [x] **Phase 2 — Backtesting core:** look-ahead-safe ORB engine with cost model,
  deterministic day-by-day simulation, metrics, Alpaca loader; tests cover OR
  computation, entry timing, and stop/target resolution.
- [ ] Phase 3 — Dashboard UI
- [ ] Phase 4 — Paper-trading signals
- [ ] Phase 5 — (gated) Live execution

## Configuration & secrets
Copy `.env.example` to `.env` and fill in your data-provider keys. **Never commit
`.env`** — it is git-ignored. Market data is not committed either.

## Disclaimer
This software is for research and education. It is **not financial advice**.
Backtested results are not predictive of future returns.
