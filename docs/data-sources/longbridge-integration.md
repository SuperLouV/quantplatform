# Longbridge Integration

日期：2026-05-02

## 定位

Longbridge 在本项目中先作为只读研究数据源，不作为自动交易入口。

当前原则：

- Skill / MCP 给 AI 开发助手使用，不进入项目运行时代码
- CLI 作为本机原型接入方式，依赖用户本地 OAuth 登录状态
- SDK / OpenAPI 作为后续更正式的数据源实现
- 暂不启用自动下单、撤单或账户交易动作

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

## 后续优先级

1. 将 Longbridge quote 作为单股手动刷新增强源，yfinance 继续兜底。
2. 接 `market_status` 和 `trading_days`，替代本地简化交易日判断。
3. 接期权链：
   - expiration 列表
   - 指定日期 option chain
   - option quote
   - bid / ask / delta / IV / volume / open interest
4. 将期权助手从手工输入升级为自动读取候选合约。
5. 评估 SDK Provider，降低 CLI subprocess 依赖。

## 风控边界

即使后续 Longbridge 能提供账户和交易能力，本项目仍默认只做：

- 美股量化研究
- 扫描
- 日报
- 风控
- 回测
- 人工决策辅助

交易动作必须由用户在券商界面人工确认。
