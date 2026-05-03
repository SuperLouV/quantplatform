# AI Analysis Design

日期：2026-05-03

## 定位

AI 分析是 `QuantPlatform` 的解释层，不是交易执行层。

AI 可以做：

- 股票分析摘要
- 市场情绪和新闻解释
- 风险点检查
- 多空情景拆解
- 期权策略的人工决策辅助
- 每日报告后的问答

AI 不可以做：

- 自动下单
- 自动撤单
- 自动改单
- 绕过风控规则
- 把没有回测的策略包装成确定性买卖建议

## DeepSeek 接入

根据 DeepSeek 官方 API 文档，当前 OpenAI-compatible base URL 是：

- `https://api.deepseek.com`

当前新集成默认模型：

- `deepseek-v4-flash`

`deepseek-chat` 和 `deepseek-reasoner` 仍可兼容，但官方文档标记它们将在 `2026-07-24` 后废弃，因此项目默认不再使用旧模型名。

API key 只允许放在本地：

```bash
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

不要把 key 写入 `config/settings.example.yaml`，也不要提交 `.env`。

## 输入数据

AI 不直接抓散落文件。后端应先生成结构化上下文：

- 当前股票快照
- 历史指标和信号
- scanner 候选原因
- Longbridge 账户摘要
- 当前持仓和成本
- Longbridge news / topic / filing 摘要
- 市场概览：SPY、QQQ、DIA、VIX、sector ETF
- 重大事件日历
- 期权候选和规则层风险检查

## 输出格式

第一版输出应固定为结构化文本或 JSON：

- 结论：观察 / 谨慎 / 不适合
- 多头理由
- 空头理由
- 关键风险
- 失效条件
- 需要补充的数据
- 是否适合进入人工 watchlist

输出必须显式说明：

- 这不是自动交易指令
- 历史数据和新闻不能保证未来收益
- 如果缺少实时合约报价，期权收益率和风险不能精确计算

## 实现顺序

1. 建立 `DeepSeekClient`，只做 OpenAI-compatible chat completion。
2. 建立 prompt/context builder，不把 prompt 写散在 UI 中。
3. 先实现“股票基础分析”和“市场情绪摘要”两个只读 API。
4. 后续再接入 Longbridge news/topic/filing。
5. UI 只展示后端产物，不在前端拼策略逻辑。
