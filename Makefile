PORT ?= 8000
PYTHON ?= python3
POOL ?= data/reference/system/stock_pools/longbridge/longbridge_core.json
POOL_ID ?= longbridge_core
NASDAQ100_POOL ?= data/reference/system/stock_pools/index/nasdaq100.json
SYMBOL ?= AAPL
YEARS ?= 10
OPTION_STRATEGY ?= cash_secured_put
OPTION_ARGS ?= --help
OPTIONS_ADVICE_ARGS ?=
OPTION_SCREENSHOT_ARGS ?= --help
ACCOUNT_HEALTH_ARGS ?=
AUTO_SCAN_ARGS ?=
TRADE_REVIEW_ARGS ?=
MACRO_RISK_ARGS ?=
LONGBRIDGE_SYMBOL ?= AAPL
OPTION_SCAN_SYMBOL ?= AAPL
ANALYZE_ARGS ?=
AI_ANALYZE_ARGS ?=
AI_OPTIONS_ARGS ?=
AI_STOCK_ARGS ?=
LOG_TO_CONSOLE ?= 0
UPDATE_HISTORY ?= 0
CONSOLE_LOG_ENV = QP_LOG_TO_CONSOLE=$(LOG_TO_CONSOLE)

.PHONY: ui check analyze ai-analyze ai-options ai-stock events history history-full option-evaluate option-scan-symbol option-screenshot options-advice account-health trade-review macro-risk auto-scan longbridge-quote longbridge-pool-sync longbridge-portfolio-analysis market-overview-refresh pool-refresh pool-refresh-nasdaq100 daily-refresh daily-refresh-nasdaq100 daily-report daily-refresh-report schedule-install schedule-uninstall schedule-status schedule-plist

ui:
	@$(CONSOLE_LOG_ENV) $(PYTHON) scripts/serve_ui.py $(PORT)

check:
	$(PYTHON) -m compileall -q src scripts
	node -e 'const fs=require("fs"); const html=fs.readFileSync("ui/index.html","utf8"); const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).filter(s=>s.trim()); for (const script of scripts) new Function(script); console.log(`checked $${scripts.length} inline scripts`);'
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests/unit -p 'test_*.py'

analyze:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/analyze.py $(ANALYZE_ARGS)

ai-analyze:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/analyze.py --mode account $(AI_ANALYZE_ARGS)

ai-options:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/analyze.py --mode options $(AI_OPTIONS_ARGS)

ai-stock:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/analyze.py --mode stock --symbol $(SYMBOL) $(AI_STOCK_ARGS)

events:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/update_market_events.py --start 2026-01-01 --end 2026-12-31

history:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/update_yfinance_history.py $(SYMBOL) --years $(YEARS)

history-full:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/update_yfinance_history.py $(SYMBOL) --full-history

option-evaluate:
	@PYTHONPATH=src $(PYTHON) scripts/evaluate_option_strategy.py $(OPTION_ARGS)

option-scan-symbol:
	@PYTHONPATH=src $(PYTHON) scripts/scan_sell_put_candidates.py $(OPTION_SCAN_SYMBOL)

option-screenshot:
	@PYTHONPATH=src $(PYTHON) scripts/extract_option_screenshot.py $(OPTION_SCREENSHOT_ARGS)

options-advice:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/generate_options_advice.py $(OPTIONS_ADVICE_ARGS)

account-health:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/generate_account_health.py $(ACCOUNT_HEALTH_ARGS)

trade-review:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/review_trades.py $(TRADE_REVIEW_ARGS)

macro-risk:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/generate_macro_risk.py $(MACRO_RISK_ARGS)

auto-scan:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/run_auto_scan.py --pool-id $(POOL_ID) $(AUTO_SCAN_ARGS)

longbridge-quote:
	@PYTHONPATH=src $(PYTHON) scripts/query_longbridge_quote.py $(LONGBRIDGE_SYMBOL)

longbridge-pool-sync:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/sync_longbridge_stock_pool.py

longbridge-portfolio-analysis:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/analyze_longbridge_portfolio.py $(if $(filter 1 true yes on,$(UPDATE_HISTORY)),--update-history,)

market-overview-refresh:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/update_market_overview_history.py

pool-refresh:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/update_pool_snapshots.py --pool $(POOL)

pool-refresh-nasdaq100:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/update_pool_snapshots.py --pool $(NASDAQ100_POOL)

daily-refresh:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/run_daily_refresh.py --pool $(POOL)

daily-refresh-nasdaq100:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/run_daily_refresh.py --pool $(NASDAQ100_POOL)

daily-report:
	@$(CONSOLE_LOG_ENV) PYTHONPATH=src $(PYTHON) scripts/generate_daily_report.py --pool-id $(POOL_ID)

daily-refresh-report: daily-refresh market-overview-refresh daily-report

schedule-install:
	$(PYTHON) scripts/install_daily_refresh_launchd.py install

schedule-uninstall:
	$(PYTHON) scripts/install_daily_refresh_launchd.py uninstall

schedule-status:
	$(PYTHON) scripts/install_daily_refresh_launchd.py status

schedule-plist:
	$(PYTHON) scripts/install_daily_refresh_launchd.py print-plist
