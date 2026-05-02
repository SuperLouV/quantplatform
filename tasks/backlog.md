# Backlog

最后更新：2026-05-02

这个文件记录尚未实现、未来可能实现、以及需要评估的功能/API。进入开发前，应先从这里移动到 `tasks/plan.md` 的具体阶段。

## 近期开发

- 轻量结构整理：
  - 合并 `tasks/worklog.md` 到 `tasks/work_journal.md` 后删除旧文件
  - 评估 `browser/`、`factors/`、`portfolio/` 空预留模块是否延后再建
  - 更新或归档早期 `PROJECT_STRUCTURE.md` 和 `us-stock-trading-system-outline.md`
- 参考 TradingAgents-CN 设计，但不复制源码：
  - 报告模块拆分：技术、基本面、新闻、情绪、风控、最终建议
  - 轻量 AI 研判接口：读取本地日报和扫描结果，输出结构化解释
  - 新闻/舆情 relevance_score 过滤
  - LLM provider 抽象：quick model / deep model
- 扩展日报市场概览所需历史数据：
  - `XLK / XLF / XLV / XLY / XLC / XLI / XLE / XLP / XLU / XLB / XLRE`
- 风控建议模块：
  - ATR 止损
  - 单笔风险预算
  - 建议仓位
  - 总仓位上限
  - 同板块集中度
  - PDT 提醒
  - 财报和重大事件风险
- 期权助手后续：
  - 将期权助手从手工输入升级为自动读取期权链候选合约
  - 粘贴券商/期权链截图后的结构化解析
  - DeepSeek OpenAI-compatible API 接入
  - 期权链数据源评估：Longbridge、IBKR、Polygon、Tradier、yfinance fallback
  - 飞书 / Telegram channel adapter
- Longbridge 数据源后续：
  - 接 Longbridge `market_status` / `trading_days`
  - 接 Longbridge 期权链、期权报价和期权成交持仓字段
  - 评估 Python SDK Provider，减少 CLI subprocess 依赖
- 最小回测框架：
  - 日线长仓
  - 交易成本和滑点
  - 止损和平仓规则
  - 复用正式指标和信号代码

## Scanner Strategy V1 后续增强

- 市场状态过滤：
  - `SPY` / `QQQ` 趋势
  - `^VIX`
  - 市场宽度
  - 风险开关：Risk On / Neutral / Risk Off
- 行业集中度控制：同板块候选数量或仓位上限。
- 财报日前后阻断规则。
- 更清晰的候选解释：matched rules、failed rules、risk flags。
- 参数验证：通过回测评估 `20/60/120`、skip 5 days、RSI 区间、volume z-score 阈值。

## 数据源和 API 候选

### 行情和基本面

- IBKR：后续真实账户、实时行情和模拟执行的候选源。
- Polygon.io：更可靠的美股历史、分钟线和实时行情，适合付费升级。
- Finnhub：新闻、基本面、earnings、部分免费额度。
- Twelve Data：行情和技术数据 API，可作为备选。
- Alpha Vantage：免费层可用，但限频较低。
- Nasdaq Data Link：后续评估散户、机构、另类数据成本。

### 宏观和事件

- FRED：已接入 release calendar，后续可接入具体宏观时间序列。
- SEC EDGAR：后续接入 filings、13F、10-K/10-Q。
- Earnings API：后续可评估 Finnhub、Polygon、Nasdaq 或其它日历源。

### 机构、筹码和情绪

- SEC 13F：基金经理和机构持仓变化。
- 基金经理/主动管理人仓位：
  - NAAIM Exposure Index：主动投资经理股票敞口，用于判断专业资金 risk-on/risk-off。
  - 后续可评估其它基金经理仓位、现金比例或风险预算数据源。
- FINRA short interest / short sale volume：空头压力和市场情绪辅助。
- Volume profile：先基于本地 OHLCV 做近似筹码分布。
- 期权流：后续评估，但暂不作为第一版依赖。
- 全市场情绪：
  - CNN Fear & Greed 或类似恐惧贪婪指标，作为市场风险偏好辅助。
  - AAII Investor Sentiment Survey：散户看多、看空、中性比例。
  - put/call ratio、VIX term structure 等可作为后续补充。
- 舆情监控：
  - X/Twitter 股票讨论
  - Reddit
  - StockTwits
  - 新闻标题和新闻情绪
  - 讨论热度变化

## UI 后续

- 每日报告页面。
- Scanner 候选详情页。
- 风控建议展示：建议仓位、止损、风险金额。
- 个股重大事件时间轴。
- 图表叠加更多指标：SMA、Bollinger、MACD、ATR。
- Watchlist 管理增强。

## 执行层预留

- Broker 抽象模型。
- 纸面交易或模拟执行器。
- IBKR / LongPort 后续适配。
- 真实自动下单暂缓，必须等策略回测、风控和人工验证完成。
