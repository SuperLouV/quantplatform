PORT ?= 8000
PYTHON ?= python3
POOL ?= data/reference/system/stock_pools/preset/default_core.json
POOL_ID ?= default_core
NASDAQ100_POOL ?= data/reference/system/stock_pools/index/nasdaq100.json

.PHONY: ui check events market-overview-refresh pool-refresh pool-refresh-nasdaq100 daily-refresh daily-refresh-nasdaq100 daily-report daily-refresh-report schedule-install schedule-uninstall schedule-status schedule-plist

ui:
	$(PYTHON) scripts/serve_ui.py $(PORT)

check:
	$(PYTHON) -m compileall -q src scripts
	node -e 'const fs=require("fs"); const html=fs.readFileSync("ui/index.html","utf8"); const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).filter(s=>s.trim()); for (const script of scripts) new Function(script); console.log(`checked $${scripts.length} inline scripts`);'
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests/unit -p 'test_*.py'

events:
	PYTHONPATH=src $(PYTHON) scripts/update_market_events.py --start 2026-01-01 --end 2026-12-31

market-overview-refresh:
	PYTHONPATH=src $(PYTHON) scripts/update_market_overview_history.py

pool-refresh:
	PYTHONPATH=src $(PYTHON) scripts/update_pool_snapshots.py --pool $(POOL)

pool-refresh-nasdaq100:
	PYTHONPATH=src $(PYTHON) scripts/update_pool_snapshots.py --pool $(NASDAQ100_POOL)

daily-refresh:
	PYTHONPATH=src $(PYTHON) scripts/run_daily_refresh.py --pool $(POOL)

daily-refresh-nasdaq100:
	PYTHONPATH=src $(PYTHON) scripts/run_daily_refresh.py --pool $(NASDAQ100_POOL)

daily-report:
	PYTHONPATH=src $(PYTHON) scripts/generate_daily_report.py --pool-id $(POOL_ID)

daily-refresh-report: daily-refresh market-overview-refresh daily-report

schedule-install:
	$(PYTHON) scripts/install_daily_refresh_launchd.py install

schedule-uninstall:
	$(PYTHON) scripts/install_daily_refresh_launchd.py uninstall

schedule-status:
	$(PYTHON) scripts/install_daily_refresh_launchd.py status

schedule-plist:
	$(PYTHON) scripts/install_daily_refresh_launchd.py print-plist
