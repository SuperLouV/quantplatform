# Handoff

最后更新：2026-05-05

## 当前状态

项目已经从“纯骨架”进入“可运行的第一版研究工作台”阶段。

当前已经具备：

- 本地数据目录与状态库结构
- `yfinance` 历史数据与快照接入
- 股票池对象
- `StockSnapshot`
- 第一版本地 UI
- 终端式个股详情布局
- 基础图表展示
- 简单风险与建议输出
- 第一版日线波段策略规格
- `yfinance` 请求限频、重试、backoff 和 timeout 保护
- 基础数据质量检查和快照质量摘要
- 第一版技术指标计算层和本地指标验证脚本
- 批量快照指标接入具备 stale bars 防护，不会把过期指标写入当前快照
- 第一版规则信号模型和信号检测脚本
- 每日刷新脚本、Makefile 入口和 UI 服务内置北京时间 06:30 调度器
- 美股交易日历和最近已完成交易日判断
- 重大事件日历：Fed FOMC、Census、FRED release calendar
- 第二页候选池扫描和后端 `MarketScanner`
- `Scanner Strategy V1`：截面动量排名、跳过最近 5 日收益、RSI 变化、成交量 z-score、ATR 归一化趋势距离
- 新窗口项目记忆入口 `PROJECT_MEMORY.md`
- 中文 Markdown 每日报告 MVP：本地市场概览、scanner 候选、市场事件、数据刷新摘要和 AI 分析提示
- 简单市场宏观分析：`SPY/QQQ/DIA/^VIX`，其中 VIX 状态会进入日报和 AI 分析提示
- Longbridge 真实股票池同步：`make longbridge-pool-sync` 读取只读 `positions/watchlist`，生成本地敏感 `longbridge_core` 股票池，过滤指数、期权和非 US 市场
- 真实持仓/自选策略分析：`make longbridge-portfolio-analysis` 输出 JSON + Markdown，包含持仓健康度和自选关注度，复用 indicators、signals 和 `MarketScanner`
- 自动化 AI 分析报告：`make analyze` 读取本地快照、指标和最新持仓健康度，输出 `data/reports/ai_analysis/` JSON + Markdown；OpenAI-compatible 模型层可配置，失败时降级为规则结构化报告
- 真实持仓期权建议：`make options-advice` 读取 Longbridge 只读持仓，默认只扫 AAPL/TSLA/NVDA/GOOGL/GOOG/TSM 等高流动性期权标的；ETF、BRK.B 和非白名单持仓会跳过并写明原因
- 账户健康度报告：`make account-health` 会保留 `BRK.B` 这类 class-share symbol，ETF/特殊个股有行业兜底；缺 ATR 时会尝试补齐本地 yfinance 日线并即时计算指标，报告包含可量化控仓动作
- 期权截图解析：`make option-screenshot` 支持 OCR 文本/本机 OCR 图片提取 expiry、strike、bid/ask，并可用 yfinance 验证

## 当前前端状态

前端当前已经实现：

- 默认列表
- 自选列表
- 中文化标签和部分公司中文名
- 纯色专业研究终端布局
- 可缩放/拖拽的主图区域布局
- 使用 `Lightweight Charts` 的主图组件接入代码
- 中间工作区已压缩 K 线视图，并新增交易指标矩阵用于展示 SMA、RSI、MACD、ATR、量比、ROC 和布林带参考
- 图表上方新增历史游标数据栏，鼠标滑动 K 线时显示对应日期的开盘、收盘、最高、最低、涨跌额、涨跌幅和成交量
- 右侧决策工作栏已重构，顶部优先展示买入/卖出/AI 判断，其下展示全市场重要事件、当前股票事件、AI 关键点、风险提示和数据状态
- 右侧栏拖拽最大宽度限制为当前视口的 40%
- 左右拖拽改变列宽后，中间工作区和右侧工作栏支持独立纵向滚动，图表使用 `ResizeObserver` 自动适配容器变化
- 全市场重要事件已接入本地 API `/api/events/market`，事件历史落地到 `data/reference/system/market_events.json`
- 事件来源包括 Fed FOMC、Census 经济指标日历和 FRED release calendar；FRED key 只放本地 `.env`
- 单只快照接口会在本地快照缺少指标时，用 1 年图表历史在后端补算 UI 交易指标
- 扫描页通过 `/api/scanner?pool_id=...` 展示候选池，扫描结果来自后端 `MarketScanner`
- 扫描页如果旧快照缺少 Strategy V1 指标，会从本地 processed parquet 兜底计算，不触发联网请求
- 信号层已根据代码审查补充两个卖出信号：价格跌破 SMA20、放量跌破 SMA20；止损信号仍等待风控模块
- 信号层 timestamp 缺失时会报错，不再用当前时间伪造；`direction` 类型不再用 ignore
- 分析接口或图表接口失败时，前端会局部降级，不会替换掉整个页面

当前仍需继续验证和完善：

- 主图交互细节
- 时间轴行为
- 更完整的交易图形功能

## 当前后端状态

后端当前已经实现：

- `yfinance` 历史数据
- `yfinance` 搜索
- 快照生成
- 股票池批量更新
- 本地 UI API
- 简单分析接口 `/api/analysis`
- 候选池扫描接口 `/api/scanner`
- 调度器状态接口 `/api/scheduler`
- Longbridge 真实股票池同步脚本
- Longbridge 真实持仓/自选策略分析脚本
- 自动化 AI 分析脚本
- 真实持仓期权建议脚本
- 期权截图 OCR 文本解析和 yfinance 交叉验证工具
- 账户健康度与风控报告脚本
- 历史交易复盘报告脚本
- 股票 + 期权自动扫描报告脚本

当前数据层已具备基础 provider 请求保护、交易日历、操作日志和数据质量检查，还缺少：

- 报告可读取的失败原因输出
- provider 降级
- 更可靠的付费或半付费行情源

## 当前最优先任务

接下来最重要的不是继续扩 UI，而是进入核心系统阶段：

1. 在正常 Python/网络环境下运行 `make account-health`、`make options-advice`、`make trade-review`、`make auto-scan`，校验真实账户、历史成交和期权链权限，并重点复核 CRCL 等大幅盈亏的券商成本价口径
2. 把账户健康度、风控建议、历史复盘摘要、期权建议、自选关注度和 scanner 输出接入日报
3. 扩展市场概览 ETF 历史更新：11 个 SPDR sector ETF
4. 最小回测框架
5. 继续收口 DeepSeek/OpenAI-compatible 分析层读取这些结构化报告

## 建议的下一步顺序

### Step 1

继续补齐报告和风控输出：

- 扫描结果按日期持久化，供日报、UI 和回测复用
- 市场概览 ETF 加入每日历史更新范围
- 日报继续读取 scanner 候选、数据质量、事件和调度摘要

### Step 2

将风控建议接入输出层：

- 仓位建议、止损价、PDT 提醒和事件风险提示
- 每日报告买入候选和风险候选
- UI 列表信号标记

### Step 3

实现最小回测框架：

- 日线
- 长仓
- 复用正式指标和信号模块
- 基础交易成本和滑点
- 收益 / 回撤 / 胜率输出

## 当前已知边界

- `gh` 在代理执行环境中不稳定，不要依赖它做项目状态判断
- 当前 `yfinance` 可用于研究和原型，不应视为最终生产级行情源
- 前端主图已开始切换到 `Lightweight Charts`，但仍需继续收口和验证
- `data/logs/` 和 `.env` 是本地产物，不应提交 Git
- `data/reference/system/stock_pools/longbridge/`、`data/reference/system/longbridge/` 和 `data/reports/portfolio_strategy/` 包含真实账户/自选产物，已加入 `.gitignore`，不要提交
- 当前 Codex 沙箱内 Longbridge CLI 可通过临时 HOME 查看 help，但真实 `positions/watchlist` 请求被网络连接限制拦截；需要在用户正常终端环境运行同步命令
- 当前执行环境的 `python` 缺少项目依赖 `pandas/yfinance`，因此全量单元测试会在导入依赖时失败；已完成 `compileall` 和不依赖行情库的截图解析测试
- 本轮新增风控/账户健康度/交易复盘/自动扫描测试可在 `python` 3.11 下通过；系统 `python3` 仍指向 3.7，不符合项目 `>=3.11`
- `AGENTS.md` 是 Codex 新窗口入口，`PROJECT_MEMORY.md` 保存长期项目理解和自我约束
- `tasks/backlog.md` 保存未来功能和 API 接入计划

## 当前适合对外说明的状态

可以说这个项目已经具备：

- 股票池驱动的数据工作台
- 个股快照与图表
- 基础建议输出和候选池扫描

但还不应说已经具备：

- 完整策略系统
- 生产级数据层
- 生产级回测框架
- 可执行的自动交易系统
