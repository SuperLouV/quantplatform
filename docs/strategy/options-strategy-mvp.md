# Options Strategy MVP

日期：2026-05-02

## 定位

期权模块第一版是“策略合规检查器”，不是自动交易系统。

AI 的角色是解释规则检查结果、提示风险、提出需要确认的数据。AI 不直接决定买入或卖出，不输出自动下单指令。

## 第一版策略

只支持两类低复杂度策略：

- `cash_secured_put`：现金担保卖 put
- `covered_call`：持有 100 股正股后卖 call

暂不支持：

- 裸卖 call
- 复杂 spread
- 0DTE
- 高频日内期权
- 自动下单

## 默认账户假设

第一版按小账户保守假设设计：

- equity：`5000 USD`
- cash：`5000 USD`
- 单笔 cash 占用上限：默认 `40%`
- 极端最大亏损上限：默认 `50%`
- 默认允许被指派，但必须显式计算资金占用

这意味着高价股票的 cash-secured put 大多会被拒绝。例如 `TSM 130 put` 需要约 `130 * 100 = 13000 USD` 现金担保，超过 5000 美元账户。

## 必要输入

### 账户

- equity
- cash
- max_cash_per_trade_pct
- max_loss_pct
- allow_assignment
- stock_shares
- stock_cost_basis

### 股票上下文

- symbol
- current_price
- as_of
- support_price
- resistance_price
- earnings_days
- market_risk_state
- trend_state
- rsi14

### 期权合约

- option_type
- strike
- expiration
- bid
- ask
- delta
- implied_volatility
- volume
- open_interest

## 输出

规则层输出：

- decision：`符合策略` / `继续观察` / `不适合`
- capital_required
- premium_income
- max_loss_estimate
- breakeven
- return_on_capital_pct
- annualized_return_pct
- dte
- spread_pct
- violations
- warnings
- confirmations
- ai_context

`violations` 表示硬性不满足。`warnings` 表示可继续观察，但不应直接执行。

## 本地命令

```bash
PYTHONPATH=src python3 scripts/evaluate_option_strategy.py \
  --strategy cash_secured_put \
  --symbol TSM \
  --as-of 2026-05-01 \
  --underlying-price 140 \
  --option-type put \
  --strike 130 \
  --expiration 2026-06-19 \
  --bid 2.0 \
  --ask 2.2 \
  --delta -0.24 \
  --open-interest 500 \
  --with-prompt
```

## 本地 API

```http
POST /api/options/evaluate
Content-Type: application/json
```

示例 payload：

```json
{
  "strategy": "cash_secured_put",
  "with_prompt": true,
  "account": {
    "equity": 5000,
    "cash": 5000,
    "max_cash_per_trade_pct": 0.4,
    "max_loss_pct": 0.5,
    "allow_assignment": true
  },
  "stock": {
    "symbol": "TSM",
    "current_price": 140,
    "as_of": "2026-05-01",
    "support_price": 130,
    "earnings_days": 21,
    "market_risk_state": "Neutral"
  },
  "contract": {
    "option_type": "put",
    "strike": 130,
    "expiration": "2026-06-19",
    "bid": 2.0,
    "ask": 2.2,
    "delta": -0.24,
    "open_interest": 500
  }
}
```

## UI 入口

个股页面右侧“决策工作栏”提供“期权助手”入口。第一版只做人工输入合约后的规则检查：

- 自动带入当前股票代码、当前价格、行情日期和本地支撑参考
- 手动输入 strike、expiration、bid、ask、delta、open interest
- 展示资金占用、权利金、最大亏损估算、盈亏平衡、DTE、年化参考
- 按“硬性不通过 / 需要观察 / 通过项”展示检查结果

## 后续计划

- 支持粘贴期权链截图后的结构化解析
- 接 DeepSeek OpenAI-compatible API
- 接期权链数据源
- 接飞书 / Telegram channel adapter
