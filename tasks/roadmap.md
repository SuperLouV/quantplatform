# Roadmap

日期：2026-04-27

## Phase A：策略规格与数据层保护

- 定义第一版波段策略规格
- 配置化账户、风险预算和 PDT 提醒
- 为 `yfinance` 增加限频、重试、超时和失败降级
- 增加数据质量检查和失败汇总
- 股票推荐范围先聚焦 `NASDAQ 100`、`S&P 500`、高热度股票和用户自定义列表，暂不做全美全市场扫描
- 新标的首次进入扫描时回填足够的日线历史，避免 SMA200、RSI 和后续信号在历史不足时失真

## Phase B：技术指标模块

- 实现 SMA、EMA、MACD、RSI、ROC、布林带、ATR、成交量比率
- 指标输出完整序列和最新值
- 指标结果写入 `StockSnapshot.indicators`
- 保持纯 pandas 实现，不引入新指标库
- Scanner Strategy V1 新增截面动量、RSI 变化、成交量 z-score 和 ATR 归一化趋势距离

## Phase C：扫描信号与风控建议

- 定义 `Signal`、`SignalSummary`、`RiskAdvice`
- 实现第一批趋势、动量、波动和成交量信号
- 将 `trend_momentum_v1` 扫描结果接入日报和后续扫描结果持久化
- 实现仓位建议、止损价、集中度和事件风险提醒
- 支持 `LongPort 20k` 与 `IBKR 5k` 两套账户假设

## Phase D：每日分析报告

- 生成中文 Markdown 日报
- 包含市场环境、板块轮动、scanner 候选、风险候选和数据质量摘要
- 报告末尾生成给 AI 研判的结构化 prompt
- 报告作为人工交易前复盘的核心产物

## Phase E：日常管线编排

- 一键执行数据更新、指标、信号、风控、宏观概览和报告生成
- 单标的失败不中断整体流程
- 记录运行日志和失败原因
- 提供本地定时执行说明

## Phase E2：策略增强数据源

- 接入 SEC 13F，跟踪重要基金经理和机构持仓变化
- 评估 NAAIM Exposure Index、AAII Investor Sentiment Survey、Fear & Greed 等情绪/仓位数据，作为市场状态过滤和 AI 研判辅助
- 接入 FINRA short interest / short sale volume，辅助判断空头压力和市场情绪
- 基于本地 OHLCV 计算 volume profile / 筹码分布近似指标
- 评估 IBKR、Polygon.io、Finnhub、Twelve Data、Alpha Vantage 等行情源作为 yfinance 的后续替代或补充
- 预留舆情监控模块：X/Twitter、Reddit、新闻、StockTwits 等讨论热度和情绪数据
- 暂不购买昂贵散户资金流数据，等策略需求稳定后再评估 Nasdaq Data Link 等付费源

## Phase F：最小回测框架

- 实现日线长仓信号回测
- 支持成本、滑点、止损和平仓规则
- 输出收益、回撤、胜率、平均持仓天数和交易明细
- 回测复用正式指标和信号模块

## Phase G：UI 增强

- 股票列表展示信号、强度和风险等级
- 个股页展示指标、信号原因、仓位建议和止损
- 图表叠加关键指标
- 新增每日报告视图

## Phase H：执行层预留

- 设计订单、持仓、账户和 broker 抽象接口
- 实现纸面交易或模拟执行器
- 暂不接入真实自动下单
