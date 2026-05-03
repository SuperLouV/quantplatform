# UI and Architecture Review

日期：2026-05-03

## 结论

当前系统可以继续开发，但 UI 和本地 API 已经接近早期单文件原型的复杂度上限。下一阶段应保持“研究台 + 扫描 + 日报 + 期权候选”的主线，不应继续把新业务都堆进 `ui/index.html` 和 `scripts/serve_ui.py`。

项目边界保持不变：只做行情、扫描、风险、日报、回测和人工决策辅助，不实现真实下单、撤单、改单或自动执行交易。

## 本次参考 UI

桌面两张 Longbridge 截图的风格特征：

- 深蓝黑底色，而不是纯黑玻璃拟态。
- 面板是纯色块，边框弱，主要靠字号、间距和颜色层级区分信息。
- 数字字号更大，价格、盈亏和涨跌幅优先级高。
- 强对比涨跌色：橙红和青绿色都更鲜明。
- 操作入口少，按钮直接，信息密度比营销式 dashboard 更高。

本次已把现有本地 UI 的基础色板向这个方向调整，但还没有做彻底组件化重写。

## 主要问题

### `ui/index.html` 过大

当前文件超过 4,000 行，同时包含：

- CSS 主题
- 布局结构
- 股票列表
- K 线图
- scanner 页
- 右侧上下文工作栏
- 期权助手 modal
- API 调用和状态管理

短期还能维护，但继续增加期权、日报、情绪和回测页面会明显降低可读性。后续应拆成：

- `ui/styles.css`
- `ui/app.js`
- `ui/options.js`
- `ui/scanner.js`
- `ui/chart.js`

### `scripts/serve_ui.py` 职责偏多

当前服务脚本同时负责静态文件、本地 API route、payload 解析、调度器状态、期权请求转换和服务调用。

短期可以继续使用，因为本项目还处在本地研究阶段；但新增更多 API 时，应拆出：

- `quant_platform.api.routes`
- `quant_platform.api.payloads`
- `quant_platform.api.responses`

### `UIDataService` 边界偏宽

`UIDataService` 同时处理股票池、快照、历史、分析、scanner、事件和 Longbridge fallback。后续应按数据产品拆分：

- `PoolDataService`
- `SnapshotDataService`
- `HistoryDataService`
- `ScannerDataService`
- `MarketEventDataService`

### 期权助手第一版表单偏重

手工输入 bid/ask 的规则检查适合验证策略模型，但不是日常使用的第一入口。

V2 应改成：

- 默认入口：SELL PUT 扫描任务
- 输出：候选列表、资金占用、OTM、DTE、风险标签
- 合约级检查：作为候选详情或人工补充 bid/ask 后的第二步

Longbridge `option quote` 无权限时，系统不能计算精确权利金、IV、delta、open interest、ROI 和 breakeven，必须在 UI 中明确提示用户手工确认报价。

## 已执行调整

- 新增 Longbridge 只读期权链和成交量适配。
- 新增 SELL PUT V2A 扫描模型和命令行脚本。
- 新增本地 API：`POST /api/options/scan-sell-put`。
- UI 期权助手新增“扫描 SELL PUT”入口。
- UI 主题调整为更接近 Longbridge 的深蓝黑纯色风格。
- K 线和成交量涨跌色改为更高对比度。

## 下一步建议

1. 完成期权助手 V2A 前端体验：
   - 候选列表支持点击填入合约检查表单。
   - 候选显示“需要手工确认 bid/ask”。
   - 支持当前股票、默认池和自定义列表扫描。
2. 拆分 `ui/index.html`，先拆 CSS 和期权 JS，降低单文件复杂度。
3. 增加回测最小框架，验证 scanner 信号是否能转成交易策略。
4. 日报接入期权候选摘要，但仍然只作为人工分析辅助。
5. 有 `option quote` 权限后再实现 V2B 的精确 ROI、spread、IV、delta 和 open interest 过滤。

## 暂不做

- 不复制 Longbridge 或 TradingAgents-CN 的 UI 代码。
- 不实现真实交易动作。
- 不在前端重新计算策略结论。
- 不在没有期权报价权限时伪造收益率或胜率。
