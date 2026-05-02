# QuantPlatform

美股交易系统主目录。

当前目标：

- 搭建股票池驱动的数据分析产品骨架
- 优先支持免费数据接口
- 先做股票池、数据层、分析层和回测底座
- 后续扩展到网页分析台和半自动执行
- 只做信息分析和人工决策辅助，不实现真实下单、撤单、改单或自动交易动作

Codex 接手入口：

- [AGENTS.md](/Users/louyilin/项目文件夹/QuantPlatform/AGENTS.md)

## 当前进度

- 已完成项目分层骨架和本地存储结构初始化
- 已完成 `yfinance` 历史日线接入
- 已完成原始 `JSON` 落盘、处理后 `Parquet` 落盘
- 已完成基于 `SQLite` 的增量更新 checkpoint
- 已完成股票筛选的第一版设计与股票池构建骨架
- 已完成 `StockPool / StockSnapshot / AIAnalysis` 产品对象骨架
- 已完成纳斯达克100独立股票池、最新快照批量抓取链路和第一版本地 UI
- 已完成第一版券商式个股界面，当前前台范围收敛为 `默认列表 + 自选列表`
- 已完成中文 UI 文案、中文池子名称和常用公司/行业中文映射
- 已完成终端式四栏 UI 骨架：图标导航、股票列表、主工作区、右侧分析区
- 已将 UI 视觉方向从玻璃拟态调整为更专业的纯色研究终端风格
- 已将主图区比例收敛为更紧凑的终端布局，中间区域新增交易指标矩阵，避免走势图过大影响信息密度
- 已支持左右分栏伸缩，便于后续扩展右侧新闻和 AI 分析面板
- 已完成第一版简单建议引擎，基于历史价格与当前快照输出趋势、风险和动作建议
- 已完成第一版日线波段策略规格文档
- 已为 `yfinance` 客户端接入配置化限频、重试、backoff 和 timeout 保护
- 已新增基础数据质量检查，批量快照会输出数据质量摘要
- 已完成第一版技术指标计算层，可从本地 processed parquet 输出完整序列和最新指标
- 已将技术指标接入批量快照，并对本地 bars 与快照时间做一致性检查
- 已完成第一版规则信号检测，可识别 MACD、RSI、布林带、放量突破、均线交叉和均线排列信号
- 已接入全市场重大事件日历，当前来源包括 Fed FOMC、Census 经济指标日历和 FRED release calendar
- 已增加本地操作日志，市场事件、UI 数据请求和股票快照刷新会写入 `data/logs/*.jsonl`
- 已新增单标的快照自动新鲜度检查：选中股票时若缓存缺少或落后 `latest_history_date_us`，会自动刷新，并用最新日线覆盖快照 OHLCV，保证收盘后尽量显示最新收盘信息
- 已修复左侧股票列表与单股快照不同步的问题：选中股票自动刷新或手动刷新后，当前列表会同步使用最新快照价格、涨跌幅和行情交易日
- 已新增 macOS `launchd` 盘后刷新安装脚本，可通过 `make schedule-install` 安装每天北京时间 06:30 的自动刷新任务
- 已新增 UI 服务内置盘后刷新调度器：`make ui` 启动后会在后台按北京时间 06:30 执行每日刷新，可通过 `/api/scheduler` 查看状态
- 已在右侧数据状态区展示定时任务状态、计划时间、最近一次全量刷新交易日和历史数据成功/失败数量
- 已加固 `yfinance` 历史请求：默认启用 `repair=True`，并预留 `prepost` 配置；批量请求最小间隔调整为 1 秒
- 已将新标的首次历史更新改为显式回填窗口，默认回填 10 年日线；已有足够历史后继续按 cursor 增量更新，单股支持 `--full-history` 获取上市以来尽可能完整的数据
- 已新增第二页“候选池扫描”MVP：`/api/scanner?pool_id=default_core` 基于本地快照、技术指标和数据状态输出候选表，前端可在“个股/扫描”之间切换
- 已将候选池扫描规则从 UI 服务拆到 `screeners/scanner.py`，输出结构化 `ScanSignal / ScanCandidate / ScanSummary`，后续可复用于日报、回测和策略迁移
- 已参考外部策略扫描方案，落地 `Scanner Strategy V1` 的第一批基础字段：池内截面动量排名、跳过最近 5 日的 20/60/120 日收益、RSI 变化、60 日成交量 z-score 和 ATR 归一化趋势距离；扫描页会在本地缓存缺少新字段时从本地 parquet 兜底计算，不联网
- 已新增中文 Markdown 每日报告 MVP，汇总本地市场概览、scanner 候选、市场事件、数据刷新摘要和给 AI 的分析提示
- 已新增期权策略 MVP，支持 `cash_secured_put` 和 `covered_call` 的规则层风险检查；右侧工作栏已有“期权助手”入口，可手工输入合约并展示资金占用、盈亏平衡、硬性风险和观察项，不自动下单
- 已新增 Longbridge Terminal CLI 只读数据源原型，可通过本地 OAuth 登录后的 `longbridge quote` 获取实时、盘前和盘后行情，并归一化为项目快照字段
- 已将单股强制刷新接入 `quote_provider: auto`：优先 Longbridge CLI 获取实时/盘前/盘后快照，失败时 fallback 到 yfinance，前端数据状态展示快照来源
- 下一步重点是补齐风控建议、扫描结果持久化、市场概览 ETF 历史更新和最小回测

## 当前主流程

系统当前按下面的主链路推进：

1. 先确定股票候选来源
2. 再形成正式股票池对象
3. 针对股票池批量更新最新快照
4. 计算技术指标、规则信号和风险建议
5. 生成每日报告，供人工复盘和 AI 辅助研判
6. 用同一套指标和信号进入回测验证

当前 UI 第一版遵循最小化原则：

- 默认只展示 `默认列表`
- 支持通过搜索把股票手动加入 `自选列表`
- 每只股票都提供独立图形界面和当前快照指标
- 第二页“扫描”展示当前股票池的候选动作、分数、趋势、RSI、MACD、成交量、风险和行情日期
- 右侧分析区已接入第一版系统判断，会展示风险等级、关键点和风险提示
- 股票推荐范围先聚焦 `NASDAQ 100`、`S&P 500`、高热度股票和用户自定义列表，复杂列表和全市场扫描后续再逐步放开

## 流程图

```mermaid
flowchart TD
    A[手动主题 / 自定义名单 / AI候选] --> B[股票池构建]
    B --> C[StockPool]
    C --> D[批量数据更新]
    D --> E[raw JSON]
    D --> F[processed Parquet]
    D --> G[SQLite checkpoint]
    F --> H[StockSnapshot]
    H --> I[AIAnalysis]
    H --> J[回测验证]
    I --> K[分析台展示]
    J --> L[执行建议]
```

## 产品对象

当前产品层围绕三个对象展开：

1. `StockPool`
2. `StockSnapshot`
3. `AIAnalysis`

它们和当前工程层的关系是：

- `screeners`：负责候选合并和基础筛选
- `services`：负责把筛选结果升级成产品对象
- `storage`：负责产品产物的物理组织

对应设计文档：

- [docs/architecture/stock-screening-design.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/architecture/stock-screening-design.md)
- [docs/architecture/product-objects.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/architecture/product-objects.md)
- [docs/strategy/strategy-v1.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/strategy/strategy-v1.md)
- [docs/strategy/scanner-strategy-v1.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/strategy/scanner-strategy-v1.md)
- [docs/strategy/options-strategy-mvp.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/strategy/options-strategy-mvp.md)
- [docs/data-sources/longbridge-integration.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/data-sources/longbridge-integration.md)

Codex 新会话请先阅读：

- [AGENTS.md](/Users/louyilin/项目文件夹/QuantPlatform/AGENTS.md)
- [PROJECT_MEMORY.md](/Users/louyilin/项目文件夹/QuantPlatform/PROJECT_MEMORY.md)

`AGENTS.md` 会指向当前需要继续阅读的计划、长期记忆和交接文档。

当前可用脚本：

- 初始化本地目录和状态库：`PYTHONPATH=src python3 scripts/bootstrap_local_state.py`
- 生成纳斯达克100股票池：`PYTHONPATH=src python3 scripts/build_nasdaq100_pool.py`
- 更新单个标的历史日线：`PYTHONPATH=src python3 scripts/update_yfinance_history.py AAPL --start 2025-01-01 --end 2025-01-15`
- 按配置构建股票池快照：`PYTHONPATH=src python3 scripts/build_universe.py`
- 批量更新股票池最新快照：`PYTHONPATH=src python3 scripts/update_pool_snapshots.py`
- 计算单个标的本地技术指标：`PYTHONPATH=src python3 scripts/compute_indicators.py AAPL`
- 检测单个标的本地规则信号：`PYTHONPATH=src python3 scripts/detect_signals.py AAPL`
- 手动评估一笔期权策略：`PYTHONPATH=src python3 scripts/evaluate_option_strategy.py --strategy cash_secured_put --symbol TSM --as-of 2026-05-01 --underlying-price 140 --option-type put --strike 130 --expiration 2026-06-19 --bid 2.0 --ask 2.2 --delta -0.24 --open-interest 500`
- 查询 Longbridge CLI 只读行情：`make longbridge-quote LONGBRIDGE_SYMBOL=AAPL`
- 更新全市场重大事件日历：`PYTHONPATH=src python3 scripts/update_market_events.py --start 2026-01-01 --end 2026-12-31`
- 启动本地 UI：`python3 scripts/serve_ui.py`
- 启动本地 UI 快捷命令：`make ui`，自定义端口：`make ui PORT=8001`
- Makefile 日常命令默认只在 terminal 打印最终成功摘要，详细过程写入 `data/logs/*.jsonl`；如需调试逐条日志：`make daily-report LOG_TO_CONSOLE=1`
- UI 服务默认不打印每个 HTTP 请求和 yfinance 已知非致命噪音；每日内置调度刷新完成后只打印一行 `DAILY_REFRESH ...`。如需查看 HTTP access log：`QP_HTTP_ACCESS_LOG=1 make ui`
- 更新单个标的 10 年历史日线：`make history SYMBOL=AAPL YEARS=10`
- 更新单个标的上市以来尽可能完整日线：`make history-full SYMBOL=AAPL`
- 收盘后刷新默认股票池：`make daily-refresh`
- 收盘后刷新 NASDAQ 100：`make daily-refresh-nasdaq100`
- 收盘后刷新自定义股票池：`make daily-refresh POOL=data/reference/system/stock_pools/watchlist/watchlist.json`
- 刷新市场宏观代理历史：`make market-overview-refresh`
- 生成中文每日报告：`make daily-report`
- 收盘刷新、宏观代理刷新后生成报告：`make daily-refresh-report`
- UI 服务内置调度器状态：`curl http://127.0.0.1:8000/api/scheduler`
- 安装盘后自动刷新：`make schedule-install`
- 查看盘后自动刷新状态：`make schedule-status`
- 卸载盘后自动刷新：`make schedule-uninstall`
- 本地检查和单元测试：`make check`

本地日志说明：

- 操作日志目录：`data/logs/`
- 日志格式说明：[docs/operations/operation-logs.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/operations/operation-logs.md)
- 盘后定时刷新说明：[docs/operations/daily-refresh-schedule.md](/Users/louyilin/项目文件夹/QuantPlatform/docs/operations/daily-refresh-schedule.md)

下一阶段计划入口：

- [tasks/plan.md](/Users/louyilin/项目文件夹/QuantPlatform/tasks/plan.md)
- [tasks/roadmap.md](/Users/louyilin/项目文件夹/QuantPlatform/tasks/roadmap.md)
- [tasks/backlog.md](/Users/louyilin/项目文件夹/QuantPlatform/tasks/backlog.md)

## 审阅约定

- 后续每次推进实现，我都会同步更新 `README.md`
- `README.md` 会优先记录当前进度、主流程和入口脚本
- 关键阶段尽量补流程图，方便你快速审阅代码方向
