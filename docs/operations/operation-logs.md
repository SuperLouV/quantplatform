# Operation Logs

本地操作日志统一写入 `data/logs/`，按模块和日期分文件：

- `market_events_YYYYMMDD.jsonl`: 全市场事件日历更新和读取。
- `stock_snapshots_YYYYMMDD.jsonl`: 股票池批量快照刷新、单标的快照写入、指标附加结果。
- `ui_data_YYYYMMDD.jsonl`: UI/API 触发的快照读取、强制刷新、历史图表、分析和事件读取。
- `yfinance_history_YYYYMMDD.jsonl`: 单标的历史 K 线更新、raw/processed 写入。

每行是一条 JSON：

```json
{"timestamp":"2026-04-26T20:00:00+08:00","timezone":"Asia/Shanghai","level":"info","action":"ui.snapshot.refresh.success","symbol":"AAPL"}
```

## Logged Operations

重要 action 包括：

- `ui.snapshot.cache_hit`: UI 使用本地快照缓存。
- `ui.snapshot.cache_stale`: UI 判断单个股票快照落后于最近美股交易日。
- `ui.snapshot.refresh.start/success/error`: UI 强制或自动刷新单个股票快照。
- `ui.snapshot.history_overlay.success/skipped/error`: 用最新日线补齐快照 OHLCV 的结果。
- `ui.history.fetch.start/success/error`: UI 拉取历史 K 线。
- `ui.analysis.start/success/error`: UI 生成本地分析结果。
- `ui.indicators.enrich.start/success/skipped/error`: UI 为旧快照补充图表历史指标。
- `stock_snapshots.pool_update.start/success`: 批量刷新股票池。
- `stock_snapshots.symbol.success/error`: 单个股票批量刷新结果。
- `stock_snapshots.indicators.success/skipped/error`: 本地技术指标写入或跳过原因。
- `yfinance_history.update.start/success/error`: 单标的历史 K 线更新。
- `yfinance_history.write_raw.success`: 原始 yfinance bars 写入。
- `yfinance_history.write_processed.success`: processed parquet 写入。
- `market_events.update.start/success`: 全市场事件更新。
- `market_events.provider.start/success/error`: 单个事件 provider 更新状态。
- `daily_refresh.start/success`: 每日收盘后批量刷新历史、快照和事件的汇总。
- `daily_refresh.history.empty`: 历史 K 线请求未报错，但 cursor 没有达到目标美股交易日。
- `scheduler.start/stop/disabled`: UI 服务内置调度器启动、停止或关闭。
- `scheduler.daily_refresh.start/success/error/skipped`: UI 服务内置调度器触发的盘后刷新状态。

`launchd` 定时任务的标准输出和错误输出单独写入：

- `data/logs/daily_refresh_launchd.out.log`
- `data/logs/daily_refresh_launchd.err.log`

## Time Zones

本地操作时间统一使用北京时间，并写入 `timezone=Asia/Shanghai`。涉及美股交易日的字段明确标记为 `*_us`，例如 `latest_history_date_us` 和 `market_date_us`，对应 `America/New_York` 市场日期。

## Safety

日志会通过 `OperationLogger` 做基础脱敏，字段名包含 `key` 或 `token` 的值会写为 `***`。

`data/logs/` 是本地产物，不应提交 Git。后续 AI 自动检查可以直接读取最近的 JSONL 文件，按 `level=error`、`*.skipped` 和 `*.error` action 汇总数据问题。
