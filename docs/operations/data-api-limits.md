# Data API Limits

最后更新：2026-04-24

## FRED

官方文档：

- API key: https://fred.stlouisfed.org/docs/api/api_key.html
- FRED API index: https://fred.stlouisfed.org/docs/api/fred/
- Error and rate-limit behavior: https://fred.stlouisfed.org/docs/api/fred/errors.html
- v2 error and throttle note: https://fred.stlouisfed.org/docs/api/fred/v2/errors.html

当前项目使用：

- API key 只放本地 `.env` 的 `FRED_API_KEY`，不写入 `settings.example.yaml`，不提交 Git。
- 当前节流参数来自 `config/settings.example.yaml`：
  - `request_min_interval_seconds: 0.5`
  - `request_max_retries: 2`
  - `request_backoff_seconds: 1.0`
  - `request_timeout_seconds: 15.0`

官方限制和错误：

- FRED API 请求必须带 API key。
- FRED v1 错误页列出标准错误码，包括 `400`、`404`、`423`、`429`、`500`。
- FRED v2 错误页明确写到，超过 `2 requests per second` 可能返回 `429 Too Many Requests`，不遵守节流可能导致临时封锁。

项目处理原则：

- 单个 provider 失败不能中断整个事件日历更新。
- 事件更新会写入 `data/logs/market_events_YYYYMMDD.jsonl`。
- 日志包含 `info` 和 `error` 级别，不记录 API key。
- 需要提高 FRED 调用频率前，先调整本地节流并确认官方限制。

## Fed FOMC Calendar

官方页面：

- https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm

当前项目使用：

- 从官方页面读取 FOMC 会议日程。
- 页面不可用时使用代码内置的 2026/2027 FOMC 日期作为降级兜底。
- FOMC 会议结束日按 `14:00 America/New_York` 记入事件日历，再转换为 UTC 存储。

## Census Economic Indicator Calendar

官方页面：

- https://www.census.gov/economic-indicators/calendar-listview.html

当前项目使用：

- 从 Census 经济指标日历读取零售销售、耐用品、新屋开工、新屋销售、贸易帐、建筑支出等事件。
- 发布时间按页面给出的美东时间解析，再转换为 UTC 存储。
