# Work Journal

## 2026-04-22

- 阅读 `README.md`、`PROJECT_STRUCTURE.md`、`tasks/*`、`config/*`
- 确认项目当前处于初始化阶段，核心代码尚未开始实现
- 确认当前目标为美股数据接入、自动分析、指标计算、候选股评分和回测
- 新建独立计划文件 `tasks/plan.md`
- 新建独立工作日志文件 `tasks/work_journal.md`
- 待用户确认第一版范围、数据源优先级和策略方向

## 2026-04-23

- 阅读桌面文档 [量化交易系统路线.md](/Users/louyilin/Desktop/量化交易系统路线.md)
- 提取其中对本项目有价值的阶段划分思路
- 明确当前先不锁定标的、资金规模和具体策略参数
- 将项目路线调整为以“数据接口介入”为第一核心阶段
- 将路线图扩展为 `Phase 0` 到 `Phase 5`
- 强化了“先数据、后分析、再回测、再模拟执行”的推进顺序
- 明确第一版数据接口组合优先为 `yfinance + SEC + FRED`
- 初始化 `src/quant_platform/` 分层骨架
- 增加配置加载、统一数据模型和 ingestion 基础入口
- 预留 `clients/yfinance`、`clients/sec`、`clients/fred` 三类 provider 边界
- 项目根目录从 `Stock` 重命名为 `QuantPlatform`
- Python 包名从 `stock` 重命名为 `quant_platform`
- 同步更新配置默认值、README 和结构设计文档中的项目名称引用
- 明确数据落地方案为 `raw=json`、`processed=parquet`、状态账本=`SQLite`
- 增加本地存储布局和 SQLite 更新状态管理骨架
- 去除对外部 YAML 依赖的强绑定，改为标准库可运行的轻量配置解析
- 增加本地数据目录和状态库初始化脚本
- 安装 `yfinance`、`pandas`、`pyarrow`
- 实现 `yfinance` 历史日线拉取、原始 JSON 落盘、处理后 Parquet 落盘
- 增加基于 SQLite checkpoint 的增量更新入口脚本
- 端到端验证 `AAPL` 日线更新链路，成功写入 raw JSON、processed Parquet 和 checkpoint
- 验证增量更新可从 SQLite cursor 续拉，不需要重复全量抓取
- 更新 `README.md`，补充当前进度、系统主流程和审阅用流程图
- 完成股票筛选第一版设计，明确 `theme_pool`、`system_pool`、`watchlist`、`tradable_universe`
- 增加 `screeners` 配置模型、规则引擎和股票池构建器
- 增加 `scripts/build_universe.py` 和筛选设计文档

## 2026-04-24

- 根据产品形态重新整理路线图，明确“股票池驱动的数据分析产品”方向
- 调整 `plan.md` 和 `roadmap.md`，把分析台与 AI 分析层前置到执行之前
- 新增产品对象模型：`StockPool`、`StockSnapshot`、`AIAnalysis`
- 新增产品服务骨架：`StockPoolService`、`StockSnapshotService`、`AIAnalysisService`
- 扩展 `storage` 路径约定，补充股票池、个股快照和 AI 分析产物路径
- 更新 `README.md` 和产品对象设计文档，便于后续审阅与实现
- 实际运行 `scripts/build_universe.py`，成功生成 `theme/system/watchlist/tradable` 四类股票池 JSON
- 新增纳斯达克100成分股列表和独立股票池构建服务
- 增加股票池批量最新快照抓取脚本，面向 `StockSnapshot` 输出当前行情和关键基本面字段
- 增加第一版本地 UI 页面和本地静态服务脚本
- 将本地 UI 重构为更接近终端的四栏布局：图标导航、股票列表、主工作区、右侧上下文面板
- 为 UI 补充中文公司名、行业、交易所映射，优化前台中文化展示
- 为右侧分析区增加简单建议引擎，基于 `6mo` 历史价格与当前快照计算趋势、风险和建议
- 本地服务新增 `/api/analysis` 接口，前台可直接展示第一版系统判断
