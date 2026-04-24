# QuantPlatform 项目结构设计

日期：2026-04-22

## 目标

`QuantPlatform` 是本项目的主文件夹，用于统一管理：

- 需求和任务
- 系统设计文档
- 数据接口封装
- 因子与策略实现
- 回测与模拟执行
- 浏览器辅助与本地网页

本阶段优先支持：

- 美股数据接入
- 自动分析
- 指标计算
- 候选股评分
- 回测验证
- 半自动执行准备

## 结构总览

```text
QuantPlatform/
  AGENTS.md
  README.md
  PROJECT_STRUCTURE.md
  docs/
    architecture/
    data-sources/
    strategy/
    execution/
    operations/
    research-notes/
  tasks/
    backlog.md
    roadmap.md
    worklog.md
  config/
    settings.example.yaml
    universe.example.yaml
    risk.example.yaml
  data/
    raw/
    staging/
    processed/
    reference/
    cache/
  notebooks/
  scripts/
  src/
    quant_platform/
      __init__.py
      core/
      clients/
      ingestion/
      indicators/
      factors/
      screeners/
      portfolio/
      risk/
      backtest/
      execution/
      broker/
      services/
      web/
      browser/
      utils/
  tests/
    unit/
    integration/
    fixtures/
  outputs/
    reports/
    signals/
    backtests/
    logs/
```

## 各目录职责

### `AGENTS.md`

Codex 每次打开项目时优先阅读的入口文件。

职责：

- 说明当前项目状态和下一阶段优先级
- 给出新会话阅读顺序
- 梳理真实目录职责和常用命令
- 指向详细计划和上下文文档

详细计划仍放在 `tasks/plan.md`，历史工作记录仍放在 `tasks/work_journal.md`。

### `docs/`

存放所有正式文档。

- `architecture/`：系统架构、模块边界、数据流
- `data-sources/`：数据接口调研、字段映射、限频与授权说明
- `strategy/`：策略说明、指标定义、评分模型
- `execution/`：执行规则、订单生命周期、交易约束
- `operations/`：部署、运行、监控、应急处理
- `research-notes/`：临时研究结论和外部资料摘要

### `tasks/`

存放任务管理文件。

- `backlog.md`：待办事项池
- `roadmap.md`：阶段计划
- `worklog.md`：开发与研究记录

### `config/`

存放配置模板，不直接提交敏感密钥。

- `settings.example.yaml`：全局配置样例
- `universe.example.yaml`：股票池和筛选规则样例
- `risk.example.yaml`：风险参数样例

后续实际运行时建议再加：

- `settings.local.yaml`
- `.env`

### `data/`

统一管理本地数据。

- `raw/`：原始抓取结果，不做手工修改
- `staging/`：清洗中的中间层
- `processed/`：回测和分析直接使用的数据
- `reference/`：股票代码、行业映射、交易日历、事件表
- `cache/`：临时缓存

### `notebooks/`

只放探索性分析，不放长期生产逻辑。

原则：

- 研究可以在这里起步
- 稳定逻辑必须回收进 `src/`

### `scripts/`

放命令行脚本和定时任务入口，例如：

- 抓取行情
- 更新财报数据
- 重建股票池
- 生成日报
- 启动本地服务

### `src/quant_platform/`

核心代码目录。

#### `core/`

放最基础的领域模型和通用类型：

- K线
- 信号
- 持仓
- 订单
- 成交
- 事件

#### `clients/`

各外部 API 的原始客户端封装：

- `alpaca`
- `sec`
- `fred`
- `polygon`
- `alpha_vantage`

职责只包括：

- 请求
- 重试
- 限频
- 原始响应转换

不在这里写策略逻辑。

#### `ingestion/`

数据抓取、标准化和入库流程：

- 股票列表同步
- 日线更新
- 财务数据同步
- 公司事件同步

#### `indicators/`

技术指标计算：

- SMA / EMA
- ATR
- 波动率
- 相对强弱
- 动量
- Beta

#### `factors/`

因子定义与打分：

- 动量因子
- 趋势因子
- 质量因子
- 防御因子
- 综合评分器

#### `screeners/`

股票池过滤逻辑：

- 价格过滤
- 流动性过滤
- IPO 冷静期过滤
- 财报窗口过滤

#### `portfolio/`

组合层逻辑：

- 仓位分配
- 调仓建议
- 行业暴露限制
- 单票权重限制

#### `risk/`

风控模块：

- 止损规则
- 回撤控制
- 仓位上限
- 市场状态风控
- 事件风控

#### `backtest/`

回测框架：

- 策略运行器
- 成本模型
- 滑点模型
- 绩效指标
- 样本内/样本外分析

#### `execution/`

交易指令生成与执行规划：

- 买卖建议
- 下单切片
- TWAP / VWAP 计划
- 执行约束

#### `broker/`

券商适配层，和 `clients/` 分离。

区别：

- `clients/` 更偏数据源
- `broker/` 更偏账户、订单、持仓、交易动作

#### `services/`

跨模块编排服务：

- 每日选股服务
- 开盘前检查
- 收盘后汇总
- 风险巡检

#### `web/`

本地网页分析台后端与接口。

#### `browser/`

浏览器自动化或页面辅助逻辑，例如：

- 抓取公开网页信息
- 辅助打开研究页面
- 半自动券商网页操作

#### `utils/`

公共工具函数，避免业务逻辑散落。

### `tests/`

- `unit/`：纯单元测试
- `integration/`：接口与流程测试
- `fixtures/`：测试样本数据

### `outputs/`

所有程序生成物统一输出到这里。

- `reports/`：日报、周报、研究报告
- `signals/`：候选股和交易信号
- `backtests/`：回测结果
- `logs/`：运行日志

## 推荐开发顺序

### 第一阶段

先做最小研究闭环：

1. `clients/`
2. `ingestion/`
3. `indicators/`
4. `screeners/`
5. `factors/`
6. `backtest/`

### 第二阶段

加入实用型能力：

1. `portfolio/`
2. `risk/`
3. `services/`
4. `web/`

### 第三阶段

再推进到执行：

1. `execution/`
2. `broker/`
3. `browser/`

## 当前建议的最小落地版本

第一版先实现这些文件和模块即可：

- `docs/data-sources/free-apis.md`
- `tasks/backlog.md`
- `config/settings.example.yaml`
- `src/quant_platform/clients/`
- `src/quant_platform/ingestion/`
- `src/quant_platform/indicators/`
- `src/quant_platform/factors/`
- `src/quant_platform/screeners/`
- `src/quant_platform/backtest/`
- `tests/unit/`

## 结构设计原则

- 先研究，后执行
- 先模块分层，后界面美化
- 先把原始数据和标准化数据分开
- 先把客户端和业务逻辑分开
- 先支持半自动，再考虑全自动
- 所有输出统一进入 `outputs/`
