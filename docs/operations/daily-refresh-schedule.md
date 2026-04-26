# Daily Refresh Schedule

盘后全量刷新用于保证第二天开盘前，股票池快照和本地历史数据已经更新到最近一个美股交易日。

## Manual Run

```bash
make daily-refresh
```

默认刷新：

- 股票池：`data/reference/system/stock_pools/preset/default_core.json`
- 市场日期：最近一个美股交易日，字段名为 `market_date_us`
- 本地时间：北京时间，字段名为 `generated_at_beijing`
- 日志：`data/logs/daily_refresh_YYYYMMDD.jsonl`
- 汇总：`data/reference/system/daily_refresh/{pool_id}_{market_date_us}.json`

## Server Scheduler

默认方案是在本地 UI 服务进程里启动调度器：

```bash
make ui
```

服务启动后会同时启动后台线程，每天北京时间 `06:30` 检查并执行一次 `daily-refresh`。这不会写入系统级任务；如果 UI 服务没有运行，调度器也不会运行。

查看调度器状态：

```bash
curl http://127.0.0.1:8000/api/scheduler
```

配置位于 `config/settings.example.yaml`：

```yaml
scheduler:
  enabled: true
  daily_refresh_time_beijing: "06:30"
  daily_refresh_pool: data/reference/system/stock_pools/preset/default_core.json
  daily_refresh_workers: 8
  daily_refresh_update_events: true
  poll_interval_seconds: 60
```

临时关闭：

```bash
QP_SCHEDULER_ENABLED=false make ui
```

## macOS launchd

`launchd` 是可选方案，适合 UI 服务没有运行时仍然希望定时刷新。

项目提供 `launchd` 安装脚本，但不会自动安装。确认后手动执行：

```bash
make schedule-install
```

默认计划：

- 每天北京时间 `06:30`
- 执行 `scripts/run_daily_refresh.py`
- 标识：`com.louyilin.quantplatform.daily-refresh`
- 输出日志：`data/logs/daily_refresh_launchd.out.log`
- 错误日志：`data/logs/daily_refresh_launchd.err.log`

查看生成的 plist：

```bash
make schedule-plist
```

查看状态：

```bash
make schedule-status
```

卸载：

```bash
make schedule-uninstall
```

## Timing

美股夏令时收盘约为北京时间 `04:00`，冬令时约为北京时间 `05:00`。设置为 `06:30` 是为了给 yfinance 和其他数据源留出更新延迟窗口。
