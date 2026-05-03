# Options Assistant V2 Notes

日期：2026-05-02

## 背景

当前期权助手第一版偏“规则表单”，输入字段多，适合验证规则层，但不适合用户日常快速使用。

用户更喜欢 Longbridge 社区示例：

- 链接：https://longbridge.com/zh-CN/topics/39722881
- 标题：用 AI 扫描期权机会，39 个合约年化收益最高 423%
- 发布时间：2026-04-05

该示例的核心体验是：用户只说“帮我看看有什么 SELL PUT 的期权机会”，系统自动读取自选股、扫描到期日和期权链，再输出筛选后的候选合约。

## 值得参考的体验

1. 输入简单
   - 不让用户先填完整期权合约表单
   - 用户只需要选择策略、股票池和少量偏好

2. 自动扫描
   - 从自选股或股票池读取标的
   - 扫描 0-45 天内到期日
   - 自动读取 put/call 合约链

3. 输出候选，而不是直接下单
   - 输出候选合约列表
   - 按风险、收益、流动性排序
   - 明确说明只用于人工分析

4. 指标要少而清晰
   - IV
   - 成交量
   - open interest
   - bid/ask spread
   - 单合约资金占用
   - 权利金
   - ROI / 年化 ROI
   - OTM%
   - 不被行权概率
   - 风险等级

5. 风险提示必须显眼
   - 杠杆 ETF 如 TQQQ / SOXL 要单独标记
   - 高年化不代表低风险
   - 4 天到期、高 IV、高杠杆标的可能主要反映高尾部风险

## V2 产品形态

第一屏应从“表单输入”改成“扫描任务”：

- 策略：SELL PUT / Covered Call / Wheel Watch
- 股票范围：当前股票 / 自选列表 / 默认池 / NASDAQ 100
- 到期范围：7-45 天
- 账户约束：现金、最大单笔资金占用、是否允许被指派
- 风险偏好：保守 / 平衡 / 激进

点击扫描后输出：

- Top candidates 表格
- 每个候选的核心指标
- 风险标签
- 为什么入选
- 为什么要谨慎
- 可导出 CSV / JSON

## 默认保守参数

为了匹配当前小账户学习阶段，默认不应照搬文章中的激进筛选。

第一版保守默认值建议：

- DTE：14-45 天
- Put delta：-0.10 到 -0.30
- bid/ask spread：不高于 15%
- open interest：不低于 100
- 单笔现金占用：不超过账户净值 40%
- 极端最大亏损估算：不超过账户净值 50%
- 杠杆 ETF：默认只允许观察，不直接列为低风险候选
- 财报 7 天内：默认降级或排除

## 与当前项目边界

- 只做信息分析，不做下单。
- Longbridge 只读：行情、期权链、账户现金、购买力、持仓。
- AI 可以解释结果，但不能输出自动交易指令。
- 策略规则和风险过滤必须由代码确定性执行，AI 只负责解释和补充问题。

## 后续实现顺序

## Longbridge 权限约束

当前 Longbridge CLI 暴露了三类期权能力：

- `longbridge option chain`：到期日、strike、call/put 合约代码
- `longbridge option volume`：标的 call/put 成交量、put/call ratio 和历史统计
- `longbridge option quote`：具体合约实时报价、IV、open interest、Greeks 等

如果 `option quote` 返回 `no quote access`，说明当前账号/行情权限可以读取期权链和成交量统计，但没有具体期权合约的实时报价权限。这通常是行情权限/市场数据 entitlement 问题，不是项目代码问题。

这会影响：

- 不能可靠计算实时权利金
- 不能用实时 bid/ask spread 过滤流动性
- 不能读取实时 IV、delta、open interest
- 不能精确计算 ROI、年化 ROI、breakeven 和不被行权概率

但仍然可以先做：

- 从期权链生成候选 universe
- 按 DTE、strike、OTM% 做基础筛选
- 结合正股价格、账户现金和最大资金占用排除明显不适合的小账户合约
- 使用 `option volume` 做标的层面的期权活跃度和 put/call 情绪参考
- 将候选标记为 `quote_required`，提示用户需要报价权限或手工补充 bid/ask

## 分阶段实现顺序

### V2A：无 option quote 权限也能跑

1. 接 Longbridge 期权链到期日和合约列表。
2. 建立 `OptionCandidate` 数据模型，允许 quote 字段为空。
3. 写 SELL PUT scanner 的基础过滤：
   - DTE
   - strike
   - OTM%
   - 单合约现金担保
   - 账户资金占用
   - 杠杆 ETF 风险标签
4. 接 `option volume`，展示标的级别 put/call 活跃度。
5. UI 新增“扫描模式”，输出候选列表，并明确标记“缺少实时合约报价，需手工确认 bid/ask”。

### V2B：有 option quote 权限后的增强

1. 接具体合约报价。
2. 增加 bid/ask spread、IV、delta、open interest、volume 过滤。
3. 计算权利金、ROI、年化 ROI、breakeven。
4. 估算不被行权概率。
5. 输出 CSV / JSON，供日报和 AI 分析使用。
