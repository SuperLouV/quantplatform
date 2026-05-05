"""Application service layer.

Service classes are exposed lazily so importing a pure service does not
eagerly import optional market-data dependencies such as pandas/yfinance.
"""

_EXPORTS = {
    "AIAnalysisService": ("quant_platform.services.ai_analysis", "AIAnalysisService"),
    "AccountHealthRunResult": ("quant_platform.services.portfolio_health", "AccountHealthRunResult"),
    "AccountHealthService": ("quant_platform.services.portfolio_health", "AccountHealthService"),
    "AutomatedAIAnalysisRunResult": ("quant_platform.services.ai_analysis", "AutomatedAIAnalysisRunResult"),
    "AutomatedAIAnalysisService": ("quant_platform.services.ai_analysis", "AutomatedAIAnalysisService"),
    "AutoScannerRunResult": ("quant_platform.services.auto_scanner", "AutoScannerRunResult"),
    "AutoScannerService": ("quant_platform.services.auto_scanner", "AutoScannerService"),
    "BootstrapArtifacts": ("quant_platform.services.bootstrap", "BootstrapArtifacts"),
    "DailyRefreshResult": ("quant_platform.services.daily_refresh", "DailyRefreshResult"),
    "DailyRefreshService": ("quant_platform.services.daily_refresh", "DailyRefreshService"),
    "DailyReportResult": ("quant_platform.services.daily_report", "DailyReportResult"),
    "DailyReportService": ("quant_platform.services.daily_report", "DailyReportService"),
    "LongbridgeAccountService": ("quant_platform.services.account", "LongbridgeAccountService"),
    "LongbridgePoolSyncResult": ("quant_platform.services.longbridge_pools", "LongbridgePoolSyncResult"),
    "LongbridgeStockPoolService": ("quant_platform.services.longbridge_pools", "LongbridgeStockPoolService"),
    "MarketEventService": ("quant_platform.services.market_events", "MarketEventService"),
    "MarketEventUpdateResult": ("quant_platform.services.market_events", "MarketEventUpdateResult"),
    "MarketOverview": ("quant_platform.services.market_overview", "MarketOverview"),
    "MarketOverviewService": ("quant_platform.services.market_overview", "MarketOverviewService"),
    "Nasdaq100PoolService": ("quant_platform.services.nasdaq100_pool", "Nasdaq100PoolService"),
    "PortfolioStrategyResult": ("quant_platform.services.portfolio_strategy", "PortfolioStrategyResult"),
    "PortfolioStrategyService": ("quant_platform.services.portfolio_strategy", "PortfolioStrategyService"),
    "PresetPoolService": ("quant_platform.services.preset_pools", "PresetPoolService"),
    "DailyRefreshScheduler": ("quant_platform.services.server_scheduler", "DailyRefreshScheduler"),
    "StockPoolService": ("quant_platform.services.stock_pool", "StockPoolService"),
    "StockSnapshotService": ("quant_platform.services.stock_snapshot", "StockSnapshotService"),
    "StockSnapshotBatchService": ("quant_platform.services.stock_snapshot_batch", "StockSnapshotBatchService"),
    "TradeReviewRunResult": ("quant_platform.services.trade_review", "TradeReviewRunResult"),
    "TradeReviewService": ("quant_platform.services.trade_review", "TradeReviewService"),
    "UIDataService": ("quant_platform.services.ui_data", "UIDataService"),
    "UniverseService": ("quant_platform.services.universe", "UniverseService"),
    "YFinanceHistoryUpdateResult": ("quant_platform.services.yfinance_history", "YFinanceHistoryUpdateResult"),
    "YFinanceHistoryUpdater": ("quant_platform.services.yfinance_history", "YFinanceHistoryUpdater"),
    "bootstrap_local_state": ("quant_platform.services.bootstrap", "bootstrap_local_state"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
