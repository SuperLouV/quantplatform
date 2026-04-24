# Strategy V1

日期：2026-04-24

## 目标

第一版策略不是追求复杂收益模型，而是建立可复现的日线波段交易研究闭环。

系统需要能回答：

- 哪些股票池标的值得今天重点看
- 触发了什么规则信号
- 当前风险是否允许交易
- 如果人工决定交易，建议仓位和止损在哪里
- 同一套规则在历史上表现如何

## 适用范围

市场：

- 美股
- 第一批以纳斯达克100和自选池为主

周期：

- 日线
- 持仓周期初始假设为 2 到 15 个交易日
- 不做日内高频策略

账户：

- `LongPort`：约 `20,000 USD`
- `IBKR`：约 `5,000 USD`
- 风控参数必须配置化，不允许把账户规模写死在策略代码里

交易方式：

- 当前只生成研究、信号、风险建议和报告
- 当前由用户人工确认和下单
- 不自动真实下单

## 数据输入

第一版策略只依赖下面的数据：

- 历史日线 OHLCV
- 最新 quote snapshot
- 股票池归属
- 基础公司信息：行业、市值、交易所、财报日期
- 宏观代理数据：`SPY`、`QQQ`、`DIA`、`^VIX`
- 板块代理数据：11 个 SPDR sector ETF

数据质量要求：

- 单个标的历史长度不足时，该标的进入 `insufficient_data`
- OHLCV 缺失、价格为 0、成交量为 0 或异常跳价时，该标的进入风险提示
- 单个标的数据失败不能中断整个股票池扫描
- 所有数据失败必须进入运行日志和报告摘要

## 技术指标

第一版指标集：

- 趋势：`sma_5`、`sma_10`、`sma_20`、`sma_50`、`sma_200`
- 趋势：`ema_12`、`ema_26`
- 趋势：`macd`、`macd_signal`、`macd_histogram`
- 动量：`rsi_14`
- 动量：`roc_10`
- 波动：`bbands_upper`、`bbands_middle`、`bbands_lower`
- 波动：`atr_14`
- 成交量：`volume_ratio_20`

指标输出要求：

- 指标模块必须能输出完整时间序列
- `StockSnapshot.indicators` 只保存最新值
- 回测必须复用同一套指标计算逻辑

## 买入候选规则

买入规则只产生候选，不代表自动买入。

### 趋势确认

满足越多，趋势评分越高：

- 收盘价高于 `sma_20`
- `sma_20` 高于 `sma_50`
- `sma_50` 高于 `sma_200`
- `macd_histogram` 从负转正或连续改善

### 触发信号

第一批买入信号：

- MACD 金叉：`macd` 上穿 `macd_signal`
- RSI 反弹：`rsi_14` 从 30 下方重新上穿 30
- 布林带反弹：价格触及或跌破下轨后收回下轨上方
- 放量突破：`volume_ratio_20 >= 2` 且收盘价突破 `sma_20`
- 均线金叉：`sma_20` 上穿 `sma_50`
- 多头排列：`sma_20 > sma_50 > sma_200`

强度初始规则：

- 放量突破：5
- RSI 反弹：4
- 均线金叉：4
- MACD 金叉：3
- 布林带反弹：3
- 多头排列：3

## 卖出与风险规则

第一批卖出或风险信号：

- MACD 死叉：`macd` 下穿 `macd_signal`
- RSI 过热回落：`rsi_14` 从 70 上方重新跌破 70
- 跌破趋势：收盘价跌破 `sma_20`
- 均线死叉：`sma_20` 下穿 `sma_50`
- 放量下跌：成交量显著放大且收盘下跌
- 跌破止损价

事件风险：

- 财报前 3 个自然日进入警告
- 财报当天和财报后 1 个交易日默认不新增仓，除非用户人工覆盖

## 风控参数

默认账户假设必须可配置。

`IBKR 5k` 初始建议：

- 单笔最大风险：账户净值 2%
- 单笔最大仓位：账户净值 20%
- 总持仓上限：账户净值 80%
- 同板块上限：账户净值 40%
- 止损距离：`1.5 * atr_14`
- PDT 提醒：5 个交易日窗口内日内交易次数不超过 3 次

`LongPort 20k` 初始建议：

- 单笔最大风险：账户净值 1% 到 2%
- 单笔最大仓位：账户净值 10% 到 15%
- 总持仓上限：账户净值 80%
- 同板块上限：账户净值 35%
- 止损距离：`1.5 * atr_14`

仓位计算：

```text
risk_amount = account_equity * max_risk_per_trade
stop_distance = atr_14 * atr_stop_multiplier
shares_by_risk = floor(risk_amount / stop_distance)
shares_by_position_cap = floor(max_position_value / latest_close)
suggested_shares = min(shares_by_risk, shares_by_position_cap)
```

如果 `atr_14` 缺失或为 0，不给出正式仓位，只给出 `needs_review`。

## 市场环境过滤

市场状态先使用简单规则：

- `Risk On`：`SPY` 高于 `sma_50`，且 `^VIX` 不高于 20
- `Neutral`：条件混合或数据不足
- `Risk Off`：`SPY` 低于 `sma_50`，或 `^VIX` 高于 25

市场过滤影响：

- `Risk On`：允许正常展示买入候选
- `Neutral`：降低建议仓位或提高确认要求
- `Risk Off`：买入候选只进入观察，不给积极行动建议

## 输出契约

每个标的的策略输出至少包含：

- `symbol`
- `as_of`
- `data_status`
- `signals`
- `signal_summary`
- `risk_advice`
- `latest_indicators`
- `explanations`

每个信号至少包含：

- `symbol`
- `signal_type`
- `direction`
- `strength`
- `triggered_at`
- `price`
- `details`
- `indicator_values`

每个风险建议至少包含：

- `account_profile`
- `suggested_shares`
- `suggested_position_value`
- `stop_price`
- `risk_amount`
- `warnings`
- `blocking_reasons`

## 报告要求

每日报告必须能独立支持人工复盘。

报告包含：

- 市场环境
- 板块轮动
- 买入候选
- 卖出或风险候选
- 数据质量摘要
- 风控建议
- 给 AI 研判的结构化 prompt

AI prompt 只用于辅助研判，不改变代码生成的信号和风控结论。

## 暂不做

第一版暂不做：

- 实盘自动下单
- 日内高频信号
- 复杂组合优化
- 机器学习选股
- 期权策略
- 大量外部宏观事件源
- 付费 AI API 自动调用
