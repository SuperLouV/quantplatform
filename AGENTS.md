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
- Learning-stage quant project: be useful, but do not overstate prediction accuracy

Hard execution boundary:

- Do not implement real-money order placement, cancellation, replacement, or automatic trade execution.
- Longbridge / broker integrations are read-only for market data, account cash, buying power, positions, and options chains.
- Any trading action must remain a manual user action in the brokerage interface.
- AI analysis can explain, compare, summarize, and flag risk; it must not become an auto-execution authority.

Current design direction:

- Quant rules are the core.
- AI is an analysis layer that reads structured reports.
- Trading signals, risk rules, reports, and backtests must be deterministic and reproducible.
- The first strategy family is daily-bar swing trading, not intraday or high-frequency trading.
- The product should behave like a serious research desk: scanner, watchlist, market context, risk, options assistant, report, and later AI chat.

## User Requirements

The user expects Codex to act as both senior engineer and pragmatic project manager:

- Keep the roadmap current before and after implementation.
- Make architecture decisions, document tradeoffs, then implement without repeatedly asking for confirmation when the direction is clear.
- Preserve project momentum: design, code, test, document, commit, and push when meaningful work is complete.
- Explain important financial concepts in clear Chinese when the user asks, especially strategy, risk, data freshness, and API limitations.
- Treat all account data, API keys, OAuth state, logs, generated datasets, and screenshots as sensitive unless they are intentionally committed examples.
- Do not put real API keys, real account values, OAuth tokens, or full account snapshots into Git.
- If sample account data is needed in tests or docs, use obviously fake values.
- Prefer Beijing time in UI and logs. Use clearly named US/Eastern fields only when market logic needs it.
- The user often keeps the local UI server running; do not start or stop port `8000` unless explicitly asked.
- The user prefers professional pure-color UI, inspired by Longbridge: deep blue-black surfaces, high information density, strong orange-red/teal-green contrast, restrained borders, and useful layout over decorative effects.
- UI issues that affect daily use should be treated as real product work, not cosmetic polish. Current known pain points include oversized scrollbars, unclear separation between main chart and RSI/indicator subpanels, and scaling future indicator tabs beyond RSI.

## Startup Reading Order

Read in this order when taking over a new session:

1. `AGENTS.md`
2. `PROJECT_MEMORY.md`
3. `tasks/plan.md`
4. `HANDOFF.md`
5. `README.md`

Only open deeper documents when needed:

- Architecture: `docs/architecture/`
- Strategy: `docs/strategy/`
- Full structure notes: `PROJECT_STRUCTURE.md`
- Product context: `PROJECT_CONTEXT.md`
- Work history: `tasks/work_journal.md`
- Short roadmap: `tasks/roadmap.md`
- Future backlog: `tasks/backlog.md`

## Current Priority

Do not spend the next stage mainly expanding UI. The current core track is:

1. Scanner Strategy V1 output and daily report
2. Risk advice: position sizing, ATR stop, event risk, PDT
3. Daily Markdown report
4. Minimal signal-driven backtest
5. Strategy-enhancing data sources after the core loop works

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
- Daily refresh command and UI scheduler
- US market calendar for latest completed trading day
- Market event calendar from Fed, Census, and FRED release calendar
- Scanner page and backend `MarketScanner`
- `Scanner Strategy V1` with cross-sectional momentum rank and local parquet indicator fallback
- Longbridge Terminal CLI read-only integration:
  - quote snapshots
  - assets / portfolio / positions
  - option chain / option volume
  - SELL PUT V2A scanner without concrete option quote permission
- Options assistant MVP:
  - manual cash-secured put / covered call rule check
  - SELL PUT candidate scan
  - account-aware inputs using read-only Longbridge account summary

Main missing pieces:

- Signal integration into daily reports and backtests
- Position sizing and risk advice
- Minimal signal-driven backtest
- Provider fallback beyond `yfinance`
- Market regime filter using SPY/QQQ/VIX/breadth
- Strategy-enhancing data sources such as SEC 13F and FINRA short interest
- DeepSeek/OpenAI-compatible AI analysis layer that reads structured local data and produces conservative explanations
- News/sentiment layer using Longbridge news first, then other sources later
- UI decomposition: `ui/index.html` is still too large and should be split after the current user-facing fixes

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
- `PROJECT_MEMORY.md`: long-lived project understanding and Codex self-constraints

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
- Treat Longbridge account and quote data as more current, but still validate provider limitations and permissions.
- For cash-secured put analysis, do not treat margin buying power as conservative cash unless the user explicitly chooses a margin-aware mode.
- A single symbol failure must not break a pool-level or daily pipeline run.
- Do not mix stale local bars into current snapshots; stale indicators should become warnings, not fake values.
- Every signal should be traceable to data, indicators, and a named rule.
- Reports should be readable by humans first and AI second.
- Do not implement real broker auto-trading until the user explicitly asks for it.
- Treat `Scanner Strategy` and `Trading Strategy` as different layers. Scanner outputs watch candidates; trading strategy outputs buy/sell/size/stop and requires backtesting.
- Default user-facing timestamps should be Beijing time. Use explicitly named US/Eastern fields when market-calendar logic requires it.
- Do not start or stop the user's local UI server unless explicitly asked.
- For AI features, keep deterministic preprocessing in code and feed the model structured context. AI output must include uncertainty and risk, especially because market prediction from historical data is limited.

## UI Product Rules

- The local UI is a working research terminal, not a landing page.
- Prefer compact, professional, pure-color layouts over glassmorphism, gradients, and decorative cards.
- Major panels must have usable vertical scrolling without oversized browser-default scrollbars dominating the interface.
- Main chart, volume, RSI, MACD, and future indicator subpanels should have clear visual separation and consistent tab/toolbar patterns.
- RSI is not a privileged indicator. It was the first visual indicator requested by the user, but chart and strategy architecture must treat it as one member of a broader indicator system.
- Design indicator controls as scalable groups:
  - overlay indicators on the candlestick chart, such as SMA/EMA/Bollinger
  - lower-panel indicators, such as RSI/MACD/ATR/volume-derived signals
- Chart colors must keep strong contrast and avoid conflicting with indicator series colors.
- Do not let UI JavaScript become the strategy engine; frontend can render, select, and request backend analysis only.

## AI Integration Rules

- DeepSeek/OpenAI-compatible API keys must stay local in `.env` or user config and must not be committed.
- AI modules should read structured artifacts: account summary, snapshots, scanner results, market overview, news, events, risk checks, and report sections.
- AI should produce conservative analysis: bull case, bear case, key risks, invalidation points, missing data, and questions for the user.
- No AI-generated automatic order instructions. Wording should support manual review, not execution.
- Longbridge news should be the first news source when available. Store only normalized metadata or user-approved summaries, not sensitive account data.

## Documentation Maintenance

When changing direction or completing meaningful work:

- Update `AGENTS.md` only if the startup guide, priority, or structure changed.
- Update `tasks/plan.md` when the implementation plan changes.
- Update `tasks/backlog.md` when future features, APIs, or strategy ideas are added.
- Update `tasks/work_journal.md` with a short chronological note.
- Update `README.md` when user-facing commands or current progress change.
- Update `HANDOFF.md` when the next-session handoff changes.
- Update `PROJECT_MEMORY.md` when the durable project understanding or self-constraints change.

Avoid duplicating long explanations across documents. `AGENTS.md` should stay as the entrypoint and index; detailed plans belong in `tasks/plan.md`.
