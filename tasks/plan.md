# Plan

日期：2026-05-03

## 项目目标

`QuantPlatform` 是一个以股票池驱动的美股量化研究与交易辅助平台。

当前重点不是自动下单，而是形成稳定闭环：

- 股票池管理
- 数据更新
- 技术指标
- 规则信号
- 风险建议
- 每日报告
- 回测验证
- 本地分析台展示

系统定位为“量化规则为核心，AI 研判为增强层”。规则、回测、风控必须由代码确定性生成；AI 不直接替代交易逻辑，主要阅读结构化报告后做宏观、事件、行业和综合判断。

## 账户与交易阶段

- `LongPort`：约 `20,000 USD`
- `IBKR`：约 `5,000 USD`
- 当前以人工下单为主
- 第一版策略以日线和波段交易为主，不做高频，不依赖日内交易
- PDT 规则需要纳入风控提示，但不应把整个系统只绑定到 `5,000 USD` 账户
- 当前不进入真实自动下单阶段，只预留后续执行接口

## 关键判断

参考桌面 `IMPLEMENTATION_PLAN.md`、`QUANTPLATFORM_REVIEW.md` 和后续 `SCANNER_STRATEGY_V1.md` 后，本项目计划做如下调整：

- 采纳“指标 -> 信号 -> 报告 -> AI 研判”的主链路，因为这比继续扩 UI 更接近核心价值。
- 采纳“不引入新依赖，优先用 pandas”的原则，避免早期工程复杂度失控。
- 采纳“每日报告作为 AI 入口”的设计，但报告必须先服务人工决策和复盘，不能只服务 prompt。
- 采纳风控和仓位计算前置，但只做建议和检查，不做自动执行。
- 暂不采纳过早细化 IBKR 接入、复杂事件日历、完整券商模型和大范围 UI 增强，这些应排在策略闭环之后。
- 当前最缺的是策略规格、数据层保护和可复现验证，不是更多页面和更多数据源。
- 严格区分 Scanner 策略和 Trading 策略。当前 `trend_momentum_v1` 是 Scanner 策略，只负责生成候选观察列表，不直接代表买卖指令。

## 当前状态

项目已经完成：

- 基础包结构和配置模板
- 本地 `raw / processed / reference / cache / state` 存储布局
- `yfinance` 历史日线与最新快照
- SQLite 增量更新 checkpoint
- 股票池产品对象和构建链路
- 纳斯达克100股票池和批量快照更新
- `StockSnapshot` 与 `AIAnalysisResult` 骨架
- 第一版本地 UI 和个股工作台
- 第一版简单分析接口 `/api/analysis`
- 数据源限频、重试、超时、失败降级和操作日志
- 新标的首次扫描 10 年历史回填，单股可手动拉取上市以来全量历史
- 美股交易日历和最近已完成交易日判断
- 每日刷新脚本、Makefile 和 UI 服务内置定时器
- 技术指标模块、信号模型和信号检测
- 全市场重大事件日历：Fed FOMC、Census、FRED release calendar
- 候选池扫描 MVP 和 `MarketScanner`
- `Scanner Strategy V1` 初步落地：截面动量排名、跳过最近 5 日收益、RSI 变化、成交量 z-score、ATR 归一化趋势距离

当前主要缺口：

- 风控建议：仓位、止损、PDT、事件阻断
- 每日 Markdown 报告
- 扫描结果持久化和日报接入
- 最小回测框架
- 市场状态过滤：SPY/QQQ/VIX/市场宽度
- provider fallback 和更可靠行情源
- 期权助手 V2：Longbridge 当前可读期权链和成交量统计，但具体合约 `option quote` 可能受行情权限限制，因此要先设计无报价权限也能运行的候选扫描骨架
- UI/架构拆分：参考 Longbridge 深蓝黑纯色工作台风格，后续拆分 `ui/index.html`、`scripts/serve_ui.py` 和 `UIDataService`

## 优化后的执行路线

### Phase A：策略规格与数据层保护

目标：先把策略输入输出、数据可靠性和失败边界定义清楚。

工作内容：

- 编写第一版策略规格文档，明确股票池范围、买点、卖点、止损、仓位、持仓周期和排除条件。
- 第一版股票推荐范围只覆盖 `NASDAQ 100`、`S&P 500`、高热度股票和用户自定义列表，不做全美全市场扫描。
- 将账户参数配置化，至少支持 `LongPort 20k` 和 `IBKR 5k` 两套风险假设。
- 为 `yfinance` 客户端增加 rate limit、retry/backoff、timeout 和失败日志。
- 新标的首次进入扫描时显式回填配置化历史窗口，默认 10 年；已有标的保留 cursor 增量更新；单股研究可使用 full-history 模式拉取上市以来尽可能完整的数据。
- 明确数据质量检查规则，包括缺失 OHLCV、成交量为 0、历史长度不足、异常跳价。
- 定义所有下游模块共享的输入契约：历史日线、最新快照、指标、信号、风险建议。

交付物：

- `docs/strategy/strategy-v1.md`
- 数据层保护能力
- 数据质量检查结果可被报告和 UI 读取

验收：

- 单只股票失败不会中断批量更新。
- 批量更新结束后能看到成功、失败、跳过和数据不足的清单。

### Phase B：技术指标模块

目标：把简单分析逻辑升级为可复用、可回测的指标层。

工作内容：

- 在 `src/quant_platform/indicators/` 中实现指标基类和引擎。
- 实现 SMA、EMA、MACD、RSI、ROC、布林带、ATR、成交量比率。
- 指标计算返回完整序列，最新值写入 `StockSnapshot.indicators`。
- 所有指标只依赖 pandas，不引入 TA-Lib 等额外库。
- 指标 key 采用稳定命名，例如 `sma_20`、`rsi_14`、`macd_histogram`、`atr_14`、`volume_ratio_20`。

交付物：

- `indicators/base.py`
- `indicators/trend.py`
- `indicators/momentum.py`
- `indicators/volatility.py`
- `indicators/volume.py`
- `indicators/engine.py`

验收：

- 使用 AAPL 历史数据能输出完整指标表和最新指标字典。
- 历史长度不足时返回 `None` 或空序列，不抛出不可控异常。

### Phase C：扫描信号与风控建议

目标：把指标转成可解释的扫描候选，并给出可执行但不自动下单的风险建议。

工作内容：

- 新增统一 `Signal`、`SignalSummary`、`RiskAdvice` 模型。
- 实现 MACD 交叉、RSI 反转、布林带反弹、放量突破、均线交叉、趋势排列等第一批信号。
- 信号必须包含方向、强度、触发时间、触发价格、原因和依赖指标。
- Scanner Strategy V1 使用池内截面动量排名，不把单股绝对指标阈值当作唯一依据。
- 风控先实现仓位建议、止损价、最大单笔风险、财报前警告、PDT 提醒。
- 仓位计算使用账户配置，不把 `5,000 USD` 写死。

交付物：

- `core/signal_models.py`
- `indicators/signals.py`
- `risk/position_sizer.py`
- `risk/rules.py`
- 更新 `config/risk.example.yaml`

验收：

- 对纳斯达克100股票池运行后，能输出有信号、无信号、数据不足的标的列表。
- 任一买入信号都有建议止损和建议仓位。

### Phase D：每日分析报告

目标：交付第一版真正可用的日常研究产物。

工作内容：

- 生成中文 Markdown 每日报告。
- 报告包含市场环境、指数趋势、VIX 状态、板块轮动、买入候选、卖出/风险候选、数据质量摘要、风险建议和复盘字段。
- 报告末尾生成“给 AI 的分析提示”，方便在 Codex 或 Claude Code 中继续研判。
- 宏观数据先用 `SPY / QQQ / DIA / ^VIX` 和 11 个 SPDR 板块 ETF，不急于接复杂宏观日历。
- 重要事件先用可配置静态列表，后续再接 FRED、SEC 或其它来源。

交付物：

- `services/market_overview.py`
- `services/daily_report.py`
- `scripts/generate_daily_report.py`
- `storage/layout.py` 增加报告路径

验收：

- 运行脚本后生成 `data/reports/daily_YYYY-MM-DD.md`。
- 报告能独立支持一次人工交易前复盘，不需要额外查散落文件。

### Phase E：日常管线编排

目标：把数据更新、指标、信号、风控和报告串成一键流程。

工作内容：

- 实现 `DailyPipeline`，串联历史数据更新、快照更新、指标计算、信号检测、宏观概览和报告生成。
- 增加运行日志和失败汇总。
- 单个标的失败不中断整条管线。
- 提供本地定时执行说明，但先不强制安装 launchd 或 crontab。

交付物：

- `ingestion/pipeline.py`
- `scripts/run_daily_pipeline.py`
- `docs/operations/daily-run.md`

验收：

- 一条命令可以完成日常更新并生成报告。
- 失败标的和失败原因能在日志和报告中看到。

### Phase F：最小回测框架

目标：验证信号规则是否值得继续迭代。

工作内容：

- 实现日线、长仓、信号驱动的最小回测。
- 第一版只支持固定或风险预算仓位，不做复杂组合优化。
- 加入基础滑点和交易成本。
- 输出总收益、最大回撤、胜率、平均持仓天数、交易明细。
- 回测输入复用 Phase B/C 的指标和信号，避免回测里重写一套规则。

交付物：

- `backtest/models.py`
- `backtest/engine.py`
- `scripts/run_backtest.py`

验收：

- 能对单只股票和一个股票池跑回测。
- 回测结果能解释每笔交易为什么开仓、为什么平仓。

### Phase F2：策略增强数据源

目标：在价格、指标和信号稳定后，补充能增强策略判断的数据，而不是过早扩大扫描范围。

工作内容：

- 接入 SEC 13F，跟踪重要基金经理、机构持仓、增持、减持、新建仓和清仓。
- 接入 FINRA short interest / short sale volume，形成空头压力和情绪辅助指标。
- 评估 NAAIM Exposure Index、AAII Investor Sentiment Survey、Fear & Greed 等市场情绪和仓位数据。
- 基于本地 OHLCV 计算 volume profile / 筹码分布近似指标。
- 保留 Nasdaq Retail Trading Activity、期权流和付费 alternative data 的接口位置，但暂不作为第一版依赖。

验收：

- 个股和市场分析可以展示机构持仓变化、主动管理人仓位、散户看多看空、空头压力和成交量成本区间。
- 这些数据只作为策略辅助特征，不直接替代价格、指标、信号和风控规则。

### Phase G：UI 增强

目标：只展示已经稳定的指标、信号和报告，不让 UI 领先后端太多。

工作内容：

- 股票列表展示信号方向、强度和风险等级。
- 个股页展示关键指标、信号原因、建议止损和仓位。
- 图表叠加 SMA、布林带，副图展示 RSI 或 MACD。
- 新增每日报告视图，支持查看最新报告和复制 AI prompt。

交付物：

- `/api/indicators`
- `/api/signals`
- `/api/reports`
- UI 对应面板

验收：

- UI 展示的数据全部来自后端产物，不在前端重新计算策略。

### Phase H：执行层预留

目标：为后续 IBKR / LongPort / 模拟盘接入留接口，但不做实盘自动化。

工作内容：

- 设计订单、持仓、账户摘要模型。
- 设计 `BaseBroker` 抽象接口。
- 设计模拟执行器，用于回测和纸面交易之间的过渡。
- 只做接口和模拟，不接真实交易权限。

交付物：

- `broker/models.py`
- `broker/base.py`
- `broker/paper.py`

验收：

- 后续接券商时不需要改策略、信号、风控和报告模块的核心接口。

## 近期优先级

接下来优先做：

1. 完成期权助手 V2A 前端体验：候选点击填入合约检查表单、默认池扫描、明确缺少 bid/ask。
2. 把 Longbridge 只读账户摘要接入 UI：账户净值、保守 CSP 现金、当前股票持仓、成本价。
3. 完成 DeepSeek 分析层最小闭环：股票基础分析、市场情绪摘要、期权策略解释，所有 prompt 读取后端结构化上下文。
4. 拆分 `ui/index.html`：先拆 CSS 和期权 JS，降低单文件复杂度。
5. 实现 `Phase C` 风控建议：ATR 止损、仓位、PDT、财报/事件风险，并读取真实账户净值和持仓作为输入。
6. 将 `Scanner Strategy V1` 输出接入日报和后续持久化扫描结果。
7. 实现 `Phase F` 最小回测框架，验证 scanner 候选能否转化为交易策略。

暂缓：

- 复杂 UI 页面数量扩展
- 真实券商自动下单
- 依赖 `option quote` 权限的实时权利金、IV、delta、open interest 和精确 ROI 扫描
- 复杂宏观事件数据源
- 复杂组合优化
- 模型自动调用和付费 AI API

## 设计原则

- 规则优先：买卖信号、风控和回测必须可复现。
- AI 后置：AI 读取报告做研判，不直接改写策略结果。
- 配置化账户：资金规模、单笔风险、PDT 限制和券商差异必须可配置。
- 数据可追踪：每个信号都能追溯到数据、指标和规则。
- 先小闭环：先完成可运行日报和可回测策略，再扩数据源、UI 和执行。

## 计划维护规则

- 新增未来功能、API 或策略想法时，先记录到 `tasks/backlog.md`。
- 改变实现顺序或阶段目标时，同步更新本文件和 `tasks/roadmap.md`。
- 完成有意义的代码或文档改动时，同步写入 `tasks/work_journal.md`。
- 改变新窗口接手规则或项目长期理解时，同步更新 `AGENTS.md` 和 `PROJECT_MEMORY.md`。
