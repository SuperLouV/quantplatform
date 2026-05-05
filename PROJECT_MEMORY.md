# Project Memory

最后更新：2026-05-06

## 项目一句话

`QuantPlatform` 是一个以股票池为核心的美股量化研究与交易辅助系统。当前阶段目标是帮助用户完成“收盘后数据更新 -> 选股扫描 -> 风险/策略复盘 -> 人工决策”，不是自动实盘交易系统。

## 当前产品边界

- 当前只做研究、筛选、报告、风险提示和人工下单前辅助。
- 当前不做真实自动下单；后续接入 Longbridge / broker 能力时也只允许读取行情、账户、现金、持仓、期权链等信息用于分析。
- 明确禁止在项目中实现真实下单、撤单、改单或自动执行交易动作；交易动作必须由用户在券商界面人工确认。
- 当前策略重点是日线 swing trading，初始持仓周期假设为 2 到 15 个交易日。
- 当前股票范围优先是 `default_core`、`NASDAQ 100`、后续 `S&P 500`、高热度股票和用户自定义池。
- 当前免费数据源以 `yfinance` 为主，必须把它视为研究/原型数据源，不视为生产级行情源。
- AI 是分析层，不是确定性规则层。AI 读取结构化数据和报告做综合研判，但不能替代信号、风控和回测。
- DeepSeek/OpenAI-compatible API 已接入结构化报告解读；API key 必须本地保存，不提交 Git。AI 输出必须保守，明确不确定性和风险。

## 用户背景和工作流

- 用户有技术背景，但不是专业量化交易员。
- 用户希望逐步学习策略逻辑，所以解释设计时要讲清楚原因、风险和取舍。
- 用户希望 Codex 同时像专业项目经理和架构师一样工作：先完善设计和路线图，再落地代码、测试、文档和提交。
- 用户偏好专业纯色决策仪表板 UI，可参考 Longbridge 深蓝黑配色和信息密度，但产品定位是信息处理和分析系统，不是默认盯盘式交易终端；避免玻璃拟态、营销化 dashboard 和装饰化组件。
- UI 可用性问题要认真处理，例如滚动条过大、主图与 RSI/指标副图分隔不清、未来多个指标标签的扩展方式。
- RSI 不是特殊核心指标，只是用户最早明确提出的第一个可视化指标。图表、策略和 AI 分析必须把 RSI 当作通用指标系统的一部分，不能围绕 RSI 单点设计。
- 用户主要工作流预期：
  - 每日收盘后自动刷新数据
  - 第二天开盘前查看扫描候选和报告
  - 结合 AI 分析做人工判断
  - 人工下单或暂不交易
- 当前长期目标按“真实持仓/自选/AI/新闻股票池 -> 收盘后自动准备包 -> 决策面板 AI 对话 -> 宏观/新闻风险过滤 -> 回测验证”推进。AI 可以回答股票和期权交易辅助问题，但必须基于结构化本地产物并保持只读、保守、人工决策边界。

账户背景：

- `LongPort`：约 `20,000 USD`
- `IBKR`：约 `5,000 USD`

账户规模、单笔风险、仓位上限、PDT 等都必须配置化，不允许写死在策略代码里。

## 当前已实现重点

- 本地目录结构、配置、状态库和 Makefile。
- `yfinance` 历史日线、快照、搜索和图表数据。
- raw JSON、processed parquet、SQLite checkpoint。
- 股票池：默认池、NASDAQ 100、watchlist 等。
- 单股快照刷新、股票列表动态同步、每日刷新脚本。
- UI 服务内置北京时间 06:30 盘后刷新调度器。
- 本地操作日志 `data/logs/*.jsonl`。
- `make daily-refresh` 和 UI 内置调度会默认打印关键步骤日志，便于第二天从 terminal 看到 Longbridge 股票池同步、行情刷新、账户健康、期权建议、AI 解读和日报生成状态。
- 美股交易日历，避免盘中把未完成交易日当作收盘日。
- 重大事件日历：Fed FOMC、Census、FRED release calendar。
- 指标引擎：SMA、EMA、MACD、RSI6/12/14/24、ROC、Bollinger、ATR、volume ratio。
- Scanner Strategy V1 初步实现：
  - `strategy_id = trend_momentum_v1`
  - 截面动量排名 `momentum_rank_pct`
  - `ret_20d_skip5 / ret_60d_skip5 / ret_120d_skip5`
  - `rsi_14_delta_5d`
  - `volume_zscore_60`
  - `trend_distance_sma50_atr14`
  - 旧快照缺少新指标时，扫描接口会从本地 parquet 兜底计算，不联网。
- 中文 Markdown 每日报告 MVP：
  - 本地市场概览
  - scanner 候选
  - 未来 14 天市场事件
  - daily refresh 数据质量摘要
  - 持仓、期权与 AI 自动分析摘要，读取 daily refresh summary 的 `supplemental_outputs`
  - 给 AI 的结构化分析提示
  - 当目标交易日没有成功刷新时，自动回落到本地最新可用行情日。
- 简单市场宏观分析：
  - `SPY/QQQ/DIA` 判断大盘、科技成长和道指蓝筹趋势
  - `^VIX` 判断波动/恐慌状态
  - 11 个 sector ETF 预留板块轮动分析
- Longbridge 只读接口：
  - quote snapshots
  - assets / portfolio / positions
  - 真实 positions/watchlist 股票池同步
  - 真实持仓健康度和自选关注度基本策略报告
  - option chain / option volume
  - 账户摘要可用于期权助手自动填充净值、现金、持仓股数和成本价
  - 当前仍禁止任何真实下单、撤单、改单或自动执行交易
- 自动化 AI 分析层：
  - `make analyze` 保留旧 dashboard 结构化摘要
  - `make ai-analyze` 读取最新 `account_health_*.json`，构建 prompt 并调用 DeepSeek/OpenAI-compatible provider，输出账户健康度中文 Markdown 解读
  - `make ai-options` 读取最新 `options_advice_*.json`，输出 covered call / cash-secured put 建议的模型解读
  - `make ai-stock SYMBOL=AAPL` 读取本地单股 snapshot，并可结合最新账户健康/期权建议中的匹配项做技术面解读
  - AI 失败时明确写入 `model_status=error/skipped`，不使用 placeholder 假结论；AI 输出只做解释、风险提示和人工复核问题，不生成自动交易动作
  - 常用脚本优先读取本地 `config/settings.yaml`，不存在时回落到 example；API key 仍从 `.env` / 环境变量读取，不能提交 Git
- 真实持仓期权建议：
  - `make options-advice` 读取 Longbridge 只读持仓，yfinance 读取期权链
  - 默认只扫描 AAPL、TSLA、NVDA、GOOGL/GOOG、TSM 等高流动性期权标的；ETF、BRK.B 和非白名单标的跳过并写入原因，避免全持仓期权链扫描超时
  - 第一版只评估 covered call / cash-secured put，输出 strike、到期日、权利金收入和年化回报率
  - Cash-secured put 只使用保守现金，不把 margin buying power 当成现金
- 账户风控和健康度：
  - `make account-health` 读取 Longbridge 只读账户、本地持仓快照和事件日历
  - 输出单股集中度、行业敞口、HHI、现金比例、ATR 止损、PDT 门槛、事件风险、最大亏损检查和改善建议
  - 保留 `BRK.B` 这类 class-share symbol；VOO/QQQ/EWT/EWJ/DRAM、BRK.B/CRCL/XE/NOK 有行业兜底；缺 ATR 时会尝试补齐本地 yfinance 日线并即时计算指标
- 历史交易复盘：
  - `make trade-review` 读取 Longbridge 只读订单/成交记录
  - 第一版按股票多头 FIFO 统计胜率、盈亏比、平均持有时间、最大回撤、个股和月份表现
- 自动扫描报告：
  - `make auto-scan` 汇总 Scanner Strategy V1、真实持仓 covered call / cash-secured put 建议和 CSP 观察候选
  - 自动扫描只输出研究报告，不生成订单动作
- 期权截图解析：
  - `make option-screenshot` 可解析 OCR 文本或本机 OCR 图片中的 expiry、strike、bid/ask
  - 截图结果可用 yfinance 期权链交叉验证；仍需用户在券商界面人工确认

## Scanner 策略与交易策略

必须严格区分：

- Scanner 策略回答：明天重点看哪些股票？
- Trading 策略回答：什么时候买、什么时候卖、买多少、在哪里止损？

当前 `trend_momentum_v1` 是 Scanner 策略。它只输出候选优先级，不是买卖指令。

交易策略必须在实现前补齐：

- 明确入场/离场规则
- 仓位和止损规则
- 交易成本和滑点
- 回测验证
- 样本外验证或至少纸面观察

## 量化原则

- 每个策略参数都要有设计理由，后续最好通过回测验证。
- 不把 SMA、RSI、MACD 等滞后指标当成天然 edge。
- 优先寻找可解释 edge：截面动量、波动率标准化、市场状态过滤、多信号确认。
- 风控是核心，不是 UI 附属功能。
- 没有回测验证的策略不能视为可执行交易策略。
- 回测必须复用正式指标和信号代码，不能另写一套。
- 避免过拟合：参数少、跨股票池稳定、不能只对单票调参。

## 工程约束

- API key 只放本地 `.env` 或本机配置，不能提交仓库。
- 生成数据、日志、缓存不提交 Git。
- 前端只展示后端产物，不在 UI JavaScript 里实现策略核心逻辑。
- 单个股票失败不能中断股票池扫描或每日刷新。
- 数据失败、跳过、过期、质量异常必须写日志，并进入摘要或报告。
- 所有时间默认展示为北京时间；涉及美股交易日、开盘收盘或 provider 需要美东时间时，字段名或文案必须标明。
- 不要在未确认前启动或关闭用户正在使用的 8000 端口服务。
- 修改计划、实现重要功能或改变方向时，同步更新计划文档。

## 文档职责

- `AGENTS.md`：Codex 新窗口入口和行为约束。
- `PROJECT_MEMORY.md`：项目长期记忆、产品理解和自我约束。
- `tasks/plan.md`：动态开发计划，记录阶段、取舍和下一步。
- `tasks/roadmap.md`：短版路线图。
- `tasks/backlog.md`：未来功能/API/策略增强池。
- `tasks/work_journal.md`：按时间记录已经完成的事情。
- `HANDOFF.md`：当前接手状态和下一步。
- `README.md`：用户可读的当前能力、命令和入口。

## 当前下一步判断

当前最值得继续推进的顺序：

1. 在用户正常 Python/Longbridge 网络环境运行 `make account-health`、`make trade-review`、`make auto-scan`，用真实本地产物校验账户、成交和期权链权限。
2. 在依赖完整的本机环境验证 Dashboard 默认首页、候选跳转、期权弹窗、一键刷新和日报渲染。
3. 将账户健康度、风控建议、交易复盘摘要、期权建议、自选关注度和 scanner 候选接入每日报告。
4. 扩展市场概览历史数据：DIA、^VIX 和 11 个 SPDR sector ETF。
5. 做最小回测框架，验证 scanner 候选到交易策略的可行性。
6. 扩展交易复盘口径：期权成交、费用、部分成交、转仓和做空。
7. 将 DeepSeek 账户/期权/个股解读接入每日报告。
8. 再接入更多 API 和数据源，优先评估 SEC 13F、FINRA、NAAIM、AAII、Fear & Greed、新闻和舆情数据。
