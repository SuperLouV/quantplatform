# Plan

日期：2026-05-06

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
- Longbridge 真实股票池同步：只读 `positions/watchlist` 生成 `longbridge_positions / longbridge_watchlist / longbridge_core`
- 真实持仓/自选基本策略分析：复用 indicators、signals、MarketScanner，输出持仓健康度和自选关注度 JSON + Markdown
- 模型驱动 AI 解读层：读取本地 `StockSnapshot`、最新账户健康 JSON 和期权建议 JSON，构建结构化 prompt，调用 DeepSeek/OpenAI-compatible provider 生成保守中文 Markdown；模型失败时明确写入错误状态，不使用 placeholder
- 真实持仓期权建议：读取 Longbridge 只读持仓，使用 yfinance 期权链筛选 covered call / cash-secured put，输出 strike、到期日、权利金和年化回报；默认只扫描高流动性期权标的，ETF/BRK.B/非白名单持仓跳过并写明原因
- 账户健康度报告：保留 `BRK.B` 等 class-share symbol，VOO/QQQ/EWT/EWJ/DRAM、BRK.B/CRCL/XE/NOK 有行业兜底，缺 ATR 时尝试补齐 yfinance 日线并即时计算指标，报告输出可量化控仓动作
- 期权截图解析工具：从 OCR 文本或本机 OCR 图片中提取 expiry、strike、bid/ask，并支持 yfinance 交叉验证

当前主要缺口：

- 综合每日报告已接入真实持仓健康度、自选关注度、风控建议、期权建议、宏观/新闻风险和 AI 解读产物；后续重点是验证真实本地产物质量，而不是继续拆散生成多份日报
- 最小回测框架
- 市场状态过滤：SPY/QQQ/VIX/市场宽度
- provider fallback 和更可靠行情源
- 期权助手 V2 后续增强：把截图解析结果更深地接入建议报告，增加更严格的流动性、财报、IV 和组合风险检查
- UI/架构拆分：参考 Longbridge 深蓝黑纯色工作台风格，后续拆分 `ui/index.html`、`scripts/serve_ui.py` 和 `UIDataService`

## 2026-05-06 阶段落地：综合每日报告 V1

本阶段完成：

- `DailyReportService` 输出唯一综合日报：同名 Markdown 供人工速读，同名 JSON 作为 AI 主入口。
- JSON schema 为 `daily_comprehensive_report_v1`，包含 `executive_summary / market_context / holdings_analysis / watchlist_monitor / options_strategy_advice / data_update / data_gaps / ai_reading_contract`。
- 每个真实持仓条目整合基本面概况、价格-成交量资金流代理、基金/机构持仓数据状态、技术走势、宏观/新闻情绪、期权建议和人工复核事项。
- 自选股监控读取 Longbridge watchlist 策略分析，输出进场机会状态、关注分数、技术摘要、情绪摘要和人工复核提示。
- 期权策略建议读取真实持仓期权建议，第一版只把 covered call / cash-secured put 规则化纳入日报；复杂价差、跨式、滚仓先作为后续增强，不生成伪建议。
- `DailyRefreshService` 新增 `portfolio_strategy` 补充任务，确保收盘后准备包里有真实持仓/自选策略产物可供综合日报读取。
- 决策面板 AI chat 现在优先读取结构化日报 JSON，再读取 Markdown 摘录和其它散落产物。

设计取舍：

- 当前数据源没有稳定的真实逐笔 capital flow 和完整基金/机构持仓更新，所以日报明确区分 `真实数据 / proxy / missing data gap`。资金流先用价格、涨跌幅、成交量、量比和 volume z-score 做 proxy，并在字段中标明不是逐笔资金流。
- 基金/机构持仓字段不做编造；若本地 snapshot 没有 holders 数据，进入 `data_gaps`，后续数据源优先接 yfinance holders cache 或 SEC 13F。
- “一份日报”指统一综合输出和 AI 读取入口；账户健康、期权建议、宏观风险、portfolio_strategy 仍作为底层结构化产物存在，供复用和诊断。

## 2026-05-05 阶段落地：AI 分析与期权建议

本阶段完成：

- `make analyze`：基于本地结构化快照生成 AI 分析报告，模型层可通过 `QP_AI_PROVIDER / QP_AI_BASE_URL / QP_AI_MODEL / QP_AI_API_KEY` 或配置文件选择 OpenAI-compatible provider。
- `make ai-analyze`：读取最新账户健康 JSON，构建账户风险 prompt，并调用 DeepSeek/OpenAI-compatible provider 输出 Markdown 解读。
- `make ai-options`：读取最新期权建议 JSON，解释 covered call / cash-secured put 的适合性、现金担保、100 股要求和报价风险。
- `make ai-stock SYMBOL=AAPL`：读取单股 snapshot，并结合最新账户健康/期权建议中的匹配项做技术面和人工复核建议。
- `make options-advice`：读取 Longbridge 真实持仓，用 yfinance 期权链给每只持仓股生成 covered call / cash-secured put 简单建议。
- `make option-screenshot`：解析期权截图 OCR 文本或本机 OCR 图片，提取 strike、bid/ask、expiry，并可用 yfinance 验证。

设计取舍：

- AI 报告的确定性结构化层永远先生成；模型失败或未配置 API key 时只降级为规则层报告，不阻断流程。
- 期权建议只做研究辅助，不生成订单，不把保证金购买力当成 cash-secured put 的保守现金。
- yfinance 期权报价只视为研究数据，报告中明确要求在券商界面人工核对合约代码和 bid/ask。

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

2026-05-05 更新：

- 已按 Claude Code 全面审核方案，先修复 5 个 P0 运行可靠性问题。
- UI 产品方向从默认“盯盘终端”调整为默认“决策仪表板”：打开后优先展示市场状态、今日候选、持仓风控、事件、AI 研判和每日报告。
- 新增 `/api/dashboard`、`/api/reports/latest`、`POST /api/refresh` 和 `/api/health`，Dashboard 只读取本地产物，不触发联网计算。
- 保留原有个股分析、扫描器和期权助手视图，不改变已有核心模块接口。

2026-05-06 更新：

- 新增 `/api/chat` 和决策面板 AI 对话窗口。后端只读取最新日报、scanner、账户健康、期权建议、宏观风险、AI 解读和指定股票快照作为上下文，回答股票/期权辅助问题。
- 新增 `MacroRiskService`、`make macro-risk` 和 Dashboard 宏观/新闻风险区。第一版优先 Longbridge `market-temp/news`，结合本地 `SPY/QQQ/DIA/^VIX/sector ETF` 市场概览。
- `daily-refresh` 默认生成 `macro_risk` 补充产物，terminal 会打印 `daily_refresh.macro_risk.start/success/error`，日报补充产物表会展示宏观风险状态。

工作内容：

- 继续把股票列表展示信号方向、强度和风险等级。
- 继续在个股页展示关键指标、信号原因、建议止损和仓位。
- 图表叠加 SMA、布林带，副图展示 RSI 或 MACD。
- 完善每日报告视图，支持更好的 Markdown 表格渲染和报告日期选择。
- 后续拆分 `ui/index.html`，优先拆 CSS、Dashboard JS、Options JS。

交付物：

- `/api/indicators`
- `/api/signals`
- `/api/dashboard`
- `/api/reports/latest`
- `/api/chat`
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

1. 在真实 Longbridge 网络环境下运行新的 `make daily-refresh`，校验 Longbridge pool sync、账户健康、期权建议、日报和 AI 解读是否全部写入 `supplemental_outputs`，并确认 terminal 能看到关键步骤日志。
2. 在用户本机网络环境用真实 DeepSeek key 复核每日自动 AI Dashboard / 账户健康 / 期权建议解读和 `/api/chat` 的 prompt 长度、Markdown 质量和数据边界措辞。
3. 在真实 Longbridge CLI 环境运行 `make macro-risk`，确认 `market-temp/news` 的字段、权限和失败降级质量。
4. 下一个开发任务：把宏观/新闻风险转成 scanner 过滤字段和日报专章，形成 `risk_on / neutral / risk_off / overheated` 对候选和期权建议的约束。
5. 在本机依赖完整环境启动 UI，人工验证 Dashboard 默认首页、候选跳转、期权弹窗、一键刷新、AI 对话和日报渲染。
6. 将历史复盘摘要和自选关注度进一步接入每日报告和 Dashboard。
7. 实现 `Phase F` 最小回测框架，验证 scanner 候选能否转化为交易策略。
8. 扩展 `TradeReviewService` 对期权成交、部分成交费用、转仓和做空的识别能力。
9. 拆分 `ui/index.html`：先拆 CSS、Dashboard JS 和期权 JS，降低单文件复杂度。

暂缓：

- 复杂 UI 页面数量扩展
- 真实券商自动下单
- 依赖 `option quote` 权限的实时权利金、IV、delta、open interest 和精确 ROI 扫描
- 复杂宏观事件数据源
- 复杂组合优化
- 高频或盘中自动模型调用

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
