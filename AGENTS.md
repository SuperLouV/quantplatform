# AGENTS

This is the first file Codex should read when opening this repository.

## Project Snapshot

`QuantPlatform` is a stock-pool-driven US equity research and trading-assistance platform.

Current product stage:

- Research and analysis platform
- Stock pool management tool
- Daily data update and snapshot system
- Manual trading decision support
- Not a real-money automatic trading system yet

Current design direction:

- Quant rules are the core.
- AI is an analysis layer that reads structured reports.
- Trading signals, risk rules, reports, and backtests must be deterministic and reproducible.
- The first strategy family is daily-bar swing trading, not intraday or high-frequency trading.

## Startup Reading Order

Read in this order when taking over a new session:

1. `AGENTS.md`
2. `tasks/plan.md`
3. `PROJECT_CONTEXT.md`
4. `HANDOFF.md`
5. `README.md`

Only open deeper documents when needed:

- Architecture: `docs/architecture/`
- Strategy: `docs/strategy/`
- Full structure notes: `PROJECT_STRUCTURE.md`
- Work history: `tasks/work_journal.md`
- Short roadmap: `tasks/roadmap.md`

## Current Priority

Do not spend the next stage mainly expanding UI. The current core track is:

1. Strategy specification
2. Data-layer protection
3. Technical indicators
4. Rule-based signals
5. Risk advice
6. Daily Markdown report
7. Daily pipeline
8. Minimal backtest

The optimized phase plan is in `tasks/plan.md`.

## Current State

Already available:

- Python package skeleton under `src/quant_platform/`
- Config templates under `config/`
- Local storage layout under `data/`
- `yfinance` daily history ingestion
- Raw JSON and processed Parquet outputs
- SQLite checkpoint state
- Stock pool models and builders
- Nasdaq 100 pool generation
- Batch latest snapshot update
- `StockSnapshot` and `AIAnalysisResult` product models
- First local UI under `ui/index.html`
- Local API/static server in `scripts/serve_ui.py`
- Simple analysis endpoint `/api/analysis`
- Strategy V1 spec under `docs/strategy/strategy-v1.md`
- Configurable provider request guard for `yfinance`
- Basic data quality checks for bars and quote snapshots
- Phase B1 technical indicator engine using local processed parquet data
- First rule-based signal detector for standardized indicator events

Main missing pieces:

- Indicator integration into snapshots and pool scans
- Signal integration into reports, UI, and backtests
- Position sizing and risk advice
- Daily report generator
- One-command daily pipeline
- Minimal signal-driven backtest
- Deeper failure logs and provider fallback

## Repository Structure

Top-level files:

- `AGENTS.md`: Codex entrypoint and working guide
- `README.md`: user-facing project summary and commands
- `PROJECT_CONTEXT.md`: product context and current boundaries
- `HANDOFF.md`: short handoff status for new sessions
- `PROJECT_STRUCTURE.md`: longer structural design notes
- `pyproject.toml`: Python project metadata

Planning and tracking:

- `tasks/plan.md`: main implementation plan
- `tasks/roadmap.md`: short phase roadmap
- `tasks/work_journal.md`: chronological work log
- `tasks/backlog.md`: backlog

Configuration:

- `config/settings.example.yaml`: global settings example
- `config/universe.example.yaml`: stock pool and screening config example
- `config/risk.example.yaml`: risk config example

Data:

- `data/raw/`: raw provider payloads
- `data/processed/`: normalized data for analysis and UI
- `data/reference/`: stock pools, reference lists, mappings
- `data/cache/`: temporary provider cache
- `data/system/state.db`: local SQLite state and checkpoints

Source modules:

- `src/quant_platform/core/`: canonical domain and product models
- `src/quant_platform/clients/`: external data clients such as `yfinance`
- `src/quant_platform/ingestion/`: ingestion and future daily pipeline
- `src/quant_platform/storage/`: local path layout and state store
- `src/quant_platform/screeners/`: stock pool filtering and construction rules
- `src/quant_platform/services/`: product-level orchestration services
- `src/quant_platform/services/data_quality.py`: reusable data quality checks
- `src/quant_platform/indicators/`: technical indicators and orchestration engine
- `src/quant_platform/indicators/signals.py`: rule-based signal detector
- `src/quant_platform/risk/`: risk and position sizing, currently mostly empty
- `src/quant_platform/backtest/`: backtesting, currently mostly empty
- `src/quant_platform/i18n/`: Chinese labels and market mappings
- `src/quant_platform/web/`: future API/backend web boundary
- `src/quant_platform/broker/`: future broker abstraction
- `src/quant_platform/execution/`: future execution planning

Scripts:

- `scripts/bootstrap_local_state.py`: initialize local data/state directories
- `scripts/update_yfinance_history.py`: update one symbol of historical daily data
- `scripts/build_universe.py`: build configured stock pools
- `scripts/build_nasdaq100_pool.py`: build Nasdaq 100 pool
- `scripts/build_preset_pools.py`: build preset pools
- `scripts/update_pool_snapshots.py`: batch update latest stock snapshots
- `scripts/serve_ui.py`: serve local UI and API

UI:

- `ui/index.html`: current single-file local terminal-style UI

## Useful Commands

Use these from the repository root.

```bash
PYTHONPATH=src python3 scripts/bootstrap_local_state.py
PYTHONPATH=src python3 scripts/update_yfinance_history.py AAPL --start 2025-01-01 --end 2025-01-15
PYTHONPATH=src python3 scripts/build_nasdaq100_pool.py
PYTHONPATH=src python3 scripts/build_universe.py
PYTHONPATH=src python3 scripts/update_pool_snapshots.py
PYTHONPATH=src python3 scripts/compute_indicators.py AAPL
PYTHONPATH=src python3 scripts/detect_signals.py AAPL
PYTHONPATH=src python3 scripts/update_market_events.py --start 2026-01-01 --end 2026-12-31
python3 scripts/serve_ui.py
```

## Implementation Rules

- Keep quant logic in backend modules, not in UI JavaScript.
- Reuse product models instead of inventing parallel shapes.
- Use pandas for indicators and backtests; do not introduce TA-Lib or heavy dependencies unless explicitly approved.
- Keep account size and risk parameters configurable; do not hard-code the `5,000 USD` IBKR account.
- Treat `yfinance` as a research/prototype source, not production-grade market data.
- A single symbol failure must not break a pool-level or daily pipeline run.
- Do not mix stale local bars into current snapshots; stale indicators should become warnings, not fake values.
- Every signal should be traceable to data, indicators, and a named rule.
- Reports should be readable by humans first and AI second.
- Do not implement real broker auto-trading until the user explicitly asks for it.

## Documentation Maintenance

When changing direction or completing meaningful work:

- Update `AGENTS.md` only if the startup guide, priority, or structure changed.
- Update `tasks/plan.md` when the implementation plan changes.
- Update `tasks/work_journal.md` with a short chronological note.
- Update `README.md` when user-facing commands or current progress change.
- Update `HANDOFF.md` when the next-session handoff changes.

Avoid duplicating long explanations across documents. `AGENTS.md` should stay as the entrypoint and index; detailed plans belong in `tasks/plan.md`.
