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
  webapp.py     # Streamlit dashboard: Backtest + Paper signals pages
  signals.py    # paper-signal scan engine + timestamped logger (Phase 4)
streamlit_app.py   # dashboard entry point (`streamlit run streamlit_app.py`)
scripts/scan_signals.py            # CLI: scan delayed data, log signals (no orders)
scripts/install_scheduled_scan.ps1 # register the daily scan (Windows Task Scheduler)
docs/SPEC.md       # specification + acceptance criteria
docs/ORB_RULES.md  # precise strategy definition + failure modes
docs/RESULTS.md    # backtest findings log (incl. Phase 2 baseline)
scripts/baseline.py # reproducible vanilla-vs-filters A/B run
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

## Dashboard (Phase 3)
A Streamlit app wraps the engine — configure parameters, run a backtest, and view
the equity curve, headline metrics, exit-reason breakdown, and the trade log
(with CSV download).
```bash
pip install -e ".[ui]"
streamlit run streamlit_app.py
```
Data loads via the same Alpaca-backed `load_intraday` (needs `.env` keys on first
fetch, then served from `data/cache/`). The dashboard places **no orders** — it's
a research tool, not financial advice.

## Paper signals (Phase 4)
Scan recent/**delayed** data for the day's ORB breakout signals — entry, stop,
target, and a risk-based suggested size — **logged and timestamped**. This places
**no orders**; every record carries `placed_order: false`. Live execution remains
an explicitly-gated future phase.

```bash
python scripts/scan_signals.py            # cfg.symbols, latest session
python scripts/scan_signals.py NVDA TSLA  # override symbols
```
Signals append to `outputs/signals.jsonl` (idempotent per day+symbol). The
dashboard's **Paper signals** page scans on demand and shows the running log.

**Daily automation (Windows Task Scheduler):**
```powershell
# Register a weekday job (time is LOCAL — set ~30 min after the 16:00 ET close)
powershell -ExecutionPolicy Bypass -File scripts\install_scheduled_scan.ps1 -Time 16:30
# Remove it
powershell -ExecutionPolicy Bypass -File scripts\uninstall_scheduled_scan.ps1
```
Run output is captured to `outputs/scan.log`.

### Fidelity order tickets + Telegram alerts
Each signal can be rendered as a copy-paste **Fidelity bracket order** (a
One-Triggers-an-OCO: entry limit + protective stop + target) — since Fidelity has
no trading API, execution stays manual. New signals can also push to your phone
via **Telegram** (optional). To enable alerts:
1. In Telegram, message **@BotFather** → `/newbot` → copy the bot token into `.env`
   as `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message, then run `python scripts/telegram_setup.py` to
   discover your chat id; put it in `.env` as `TELEGRAM_CHAT_ID`.
3. Run it again to send a test. After that, `scan_signals.py` (and the daily task)
   text you a ready-to-place order ticket for each **new** signal.

Alerts are optional and fail-safe: if Telegram isn't configured, scanning still
logs signals normally. Nothing here places an order.

### Live intraday monitor (real-time-ish alerts)
Run during market hours to get alerted the moment an ORB breakout fires — not
after the close. It watches your symbols, detects the day's signal as it forms,
and Telegram-alerts you the Fidelity ticket. **It places no orders** — you trade
manually.
```bash
python scripts/live_monitor.py            # cfg.symbols, poll every 60s
python scripts/live_monitor.py NVDA TSLA --poll 30
python scripts/live_monitor.py --once     # single pass (testing)
```
Data caveat: the **free IEX feed is ~15 min delayed**, so alerts lag ~15 min —
fine for testing, but real-time entry needs a paid feed (`ALPACA_FEED=sip` with a
subscription, or Polygon). The loop is feed-agnostic; only the data source changes.

## Auto parameter selection — walk-forward optimization (Phase 4.5)
Let the *machine* choose the parameters, honestly. Naive optimization over all
history overfits and lies; this uses **walk-forward**: optimize on an in-sample
window, then measure on the next *unseen* out-of-sample window, roll forward, and
stitch the OOS slices into one equity curve. The in-sample-vs-out-of-sample gap is
reported as the overfitting tell.
```bash
python scripts/optimize.py SPY QQQ --is-days 365 --oos-days 90 --objective avg_r
```
The bot searches OR-minutes, take-profit R, direction, and the day filters, with a
minimum-trades guard so a low-count fluke can't win. The per-fold in-sample search
runs in parallel across CPU cores (`--workers`, default auto). **Optimization
cannot create an edge that isn't in the data** — if ORB has none on a universe, the
OOS result will show it. See `src/orb/optimize.py` and findings in `docs/RESULTS.md`.

## Phase status
- [x] **Phase 1 — Discovery:** spec, precise ORB rules, scaffold, CI.
- [x] **Phase 2 — Backtesting core:** look-ahead-safe ORB engine with cost model,
  deterministic day-by-day simulation, metrics, Alpaca loader; tests cover OR
  computation, entry timing, and stop/target resolution.
- [x] **Phase 3 — Dashboard UI:** Streamlit app to configure params, run a
  backtest, and view the equity curve, metrics, exit breakdown, and trade log.
- [x] **Phase 4 — Paper-trading signals:** scan delayed data for the day's ORB
  signals, logged + timestamped, **no orders** — via CLI, a dashboard page, and a
  daily scheduled task.
- [x] **Phase 4.5 — Walk-forward optimization:** the bot searches the parameter
  space and reports honest *out-of-sample* performance, flagging overfitting (the
  human defines the search, not the parameters).
- [ ] Phase 5 — (gated) Live execution

## Configuration & secrets
Copy `.env.example` to `.env` and fill in your data-provider keys. **Never commit
`.env`** — it is git-ignored. Market data is not committed either.

## Disclaimer
This software is for research and education. It is **not financial advice**.
Backtested results are not predictive of future returns.
