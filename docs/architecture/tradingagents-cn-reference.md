# TradingAgents-CN Reference Review

日期：2026-04-28

参考仓库：`/Users/louyilin/项目文件夹/TradingAgents-CN`

当前 commit：`cdd0316f chore: update database export config snapshot`

## 边界

TradingAgents-CN 的 README 写明 `app/` 和 `frontend/` 属于专有部分，需要商业授权。QuantPlatform 不复制这些目录代码，只参考可公开阅读的架构思想和产品设计。

QuantPlatform 的定位仍然是：美股量化研究、扫描、日报、风控、回测和人工决策辅助，不直接做自动实盘交易。

## 可参考设计

### 多阶段研究流程

TradingAgents-CN 把分析拆成：

- 市场技术分析
- 基本面分析
- 新闻分析
- 情绪分析
- 多头/空头研究员辩论
- 研究经理综合
- 交易员计划
- 风险团队辩论
- 最终交易决策

QuantPlatform 可以参考这个分层，但第一版不需要完整多 Agent。更适合的落地方式是：

- 规则层先生成确定性事实：行情、指标、信号、风控、事件、数据质量。
- AI 层只读取结构化事实，输出研究解释和人工决策建议。
- 买卖信号仍由规则、回测和风控约束，不由 AI 单独决定。

### 报告模块结构

TradingAgents-CN 的报告文档把中间状态和最终报告拆成独立模块。QuantPlatform 的日报可以沿用这个思想，把报告拆成稳定 section：

- 市场状态
- 板块轮动
- 股票池扫描结果
- 候选详情
- 风控建议
- 重大事件
- 数据质量
- AI 研判输入
- 人工复盘记录

这样后续 UI、AI prompt、历史复盘和回测解释都能读取同一份结构化产物。

### 数据源降级

TradingAgents-CN 对数据源有优先级和 fallback：缓存优先，然后按 provider 顺序尝试 API。QuantPlatform 应参考这个方向，但保持更轻量：

- 第一层：本地 processed parquet / JSON snapshot
- 第二层：yfinance 免费源
- 第三层：后续付费或官方 API，例如 Polygon、Finnhub、Alpha Vantage、SEC EDGAR、FRED
- 每次刷新记录 provider、cursor、状态、错误原因和数据时间

不要直接引入 MongoDB/Redis，除非数据规模和多进程需求真的出现。

### LLM Provider 抽象

TradingAgents-CN 有 `llm_clients`，区分快速模型和深度模型。QuantPlatform 后续做 AI 分析时可参考：

- `quick_model`：摘要、轻量解释、候选排序说明
- `deep_model`：日报综合研判、策略复盘、风险冲突分析
- provider 使用 OpenAI-compatible 抽象，支持 OpenAI、DeepSeek、Qwen、OpenRouter 等
- API key 只从本地 env/config 读取，不提交 Git

### 新闻和舆情过滤

TradingAgents-CN 有规则型新闻相关性过滤。QuantPlatform 后续舆情模块可先实现轻量版本：

- 标题/正文是否出现 ticker、公司名、产品名、高管名
- 财报、并购、监管、回购、裁员、诉讼、指引调整等关键词加权
- ETF、指数、泛市场新闻对个股相关性降权
- 输出 relevance_score，AI 只读取过滤后的高相关新闻

### 信号结构化

TradingAgents-CN 会把文本交易建议再抽取成结构化 action、target_price、confidence、risk_score。QuantPlatform 更适合反过来：

- 规则先输出结构化信号和风控字段
- AI 输出补充解释
- 若 AI 给出建议，也必须被解析成结构化字段，并和规则信号做一致性检查

### 工具调用防死循环

TradingAgents-CN 对 analyst 工具调用次数做了上限，避免 Agent 反复调用工具。QuantPlatform 后续接 AI agent 时应保留：

- 每个分析任务有最大工具调用次数
- 每次调用写 operation log
- 超时、失败和重试次数进入报告的数据质量区

## 不建议照搬

- 不引入它的 FastAPI/Vue 企业级后台。QuantPlatform 当前 UI 更轻，先聚焦研究闭环。
- 不引入 MongoDB/Redis 作为第一阶段依赖。本地文件和 SQLite 已够用。
- 不复制 verbose prompt 和大量 emoji 日志风格。QuantPlatform 应保持简洁日志和可机器读取 JSONL。
- 不让 AI 直接生成最终交易指令。必须经过策略规则、回测和风控。
- 不把 A股/港股复杂数据源架构搬进当前美股优先路线。

## 对 QuantPlatform 的近期落地建议

1. 先完善每日研究报告结构，让它成为 AI 和人工决策的共同输入。
2. 做风控建议模块：仓位、止损、事件阻断、PDT、账户风险预算。
3. 做最小回测框架，验证 scanner 策略是否值得进入 watchlist。
4. 设计轻量 AI 研判接口，但先只读本地日报和扫描结果，不直接联网抓取。
5. 舆情模块作为后续增强，先从新闻过滤和 StockTwits/Reddit/X API 候选调研开始。
