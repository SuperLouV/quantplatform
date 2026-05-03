# Longbridge Integration

日期：2026-05-02

## 定位

Longbridge 在本项目中先作为只读研究数据源，不作为自动交易入口。

当前原则：

- Skill / MCP 给 AI 开发助手使用，不进入项目运行时代码
- CLI 作为本机原型接入方式，依赖用户本地 OAuth 登录状态
- SDK / OpenAPI 作为后续更正式的数据源实现
- 只读取行情、账户资金、购买力、持仓、期权链等信息用于分析
- 禁止实现下单、撤单、改单、自动执行交易动作

## 三种接入方式

### Skill

Skill 是给 Codex / Claude / Cursor 等 AI 助手看的能力说明书。它能帮助 AI 理解 Longbridge 能查什么，但不能在项目代码里 `import`。

### MCP

Longbridge MCP 适合 AI 助手在开发时查询真实字段和接口行为。它属于当前 AI 会话能力，不应该成为 `QuantPlatform` 服务端的运行时依赖。

### CLI

Longbridge Terminal CLI 适合本地原型阶段。用户本地执行：

```bash
brew install --cask longbridge/tap/longbridge-terminal
longbridge auth login
longbridge quote AAPL.US --format json
```

项目当前已新增 `LongbridgeCLIClient`：

```bash
make longbridge-quote LONGBRIDGE_SYMBOL=AAPL
```

代码入口：

- `src/quant_platform/clients/longbridge_cli.py`
- `scripts/query_longbridge_quote.py`

## 当前已支持

第一版只封装 `quote`，并归一化为项目现有 `StockSnapshot` 风格字段：

- `open_price`
- `high_price`
- `low_price`
- `latest_close`
- `current_price`
- `regular_market_price`
- `pre_market_price`
- `post_market_price`
- `previous_close`
- `change_percent`
- `latest_volume`
- `market_state`
- `snapshot_refreshed_at_beijing`

这样后续 UI、每日刷新、期权助手可以复用统一字段。

## 当前项目接入方式

`config/settings.example.yaml` 中：

```yaml
data:
  provider: yfinance
  quote_provider: auto
```

含义：

- `provider: yfinance` 继续负责历史日线、技术指标、扫描和日报
- `quote_provider: auto` 用于单股快照刷新，优先 Longbridge CLI，失败时 fallback 到 yfinance

前端点击“刷新当前股票”会走 `/api/snapshot?...&force_refresh=1`，当前会优先尝试 Longbridge。快照里会记录：

- `quote_provider`
- `quote_provider_status`

右侧“数据状态”会展示本次快照来源。

## 后续优先级

1. 接 `market_status` 和 `trading_days`，替代本地简化交易日判断。
2. 接只读账户信息：
   - `assets`
   - `portfolio`
   - `positions`
   - 用于期权助手自动判断现金担保、购买力、持股数量和成本价
3. 接期权链和成交量统计：
   - expiration 列表
   - 指定日期 option chain
   - call/put 合约代码
   - option volume
   - put/call ratio
4. 在没有 `option quote` 权限时，先做基础候选扫描，并提示用户手工确认具体合约 bid/ask。
5. 如果后续开通具体期权报价权限，再接 `option quote`：
   - bid / ask
   - delta / IV
   - volume / open interest
   - greeks
6. 将期权助手从手工输入升级为自动读取候选合约。
7. 评估 SDK Provider，降低 CLI subprocess 依赖。

## 期权权限分层

Longbridge CLI 的期权能力不是一个单一权限：

- `longbridge option chain`：期权链结构，通常用于列出到期日、strike 和合约代码。
- `longbridge option volume`：标的层面的 call/put 成交量和 put/call ratio。
- `longbridge option quote`：具体期权合约的实时报价、IV、open interest、Greeks 等。

如果 `option quote` 返回 `no quote access`，项目应视为“缺少具体合约报价权限”，而不是接口失败。此时可以继续使用 chain/volume 做候选发现，但不能声称已经完成可交易价格分析。

## 风控边界

即使后续 Longbridge 能提供账户和交易能力，本项目仍默认只做：

- 美股量化研究
- 扫描
- 日报
- 风控
- 回测
- 人工决策辅助

交易动作必须由用户在券商界面人工确认。项目代码不得调用或封装真实交易命令，例如：

- `longbridge order buy`
- `longbridge order sell`
- `longbridge order cancel`
- `longbridge order replace`
