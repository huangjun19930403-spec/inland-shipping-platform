# 一期架构设计（内河航运标准数据与分析平台）

## 1. 一期系统定位
一期仅聚焦三件事：
1. 建立并维护标准数据体系（地址/货品/船舶/航线）
2. 接入并标准化非结构化/半结构化数据（微信/TMS/AIS/Excel）
3. 输出内部分析能力并融合 AI（规则优先 + AI 增强）

明确不做：交易闭环、订单/运单/结算主流程、外部客户中心、多租户 SaaS、复杂流程引擎。

## 2. 现状问题与重构方向
现状存在以下偏差：
1. 模块边界不清，API 目录按历史模块组织，和一期业务域不一致。
2. 启动流程包含 `create_all`，与 Alembic 迁移机制冲突。
3. Base 元数据存在重复定义，存在迁移元数据漂移风险。
4. 地址域仍使用 `transport_node.region_id` 单值绑定，不适配多区域归属。
5. `region.main_rivers/main_cities` 以 JSON 维护正式关系，无法保障一致性。
6. 货源模型语义偏“业务单”，未完全收敛到“标准化分析记录”。

重构策略：
1. 先统一元数据与迁移机制，再做模型重构。
2. 以“分域 API + Domain Service + Repository”重组调用边界。
3. 用关系表替代 JSON/单值绑定表达主数据关系。
4. 统计与 AI 只做一期必须能力，不引入通用化过度框架。

## 3. 目标代码结构

```text
app/
  api/
    v1/
      standard_data/
      ingestion/
      analysis/
      ai/
      system/

  domain/
    address/
    commodity/
    vessel/
    cargo/
    route/
    analysis/
    audit/

  ai/
    prompts/
    parsers/
    evaluators/
    explainers/
    orchestration/

  jobs/
    cargo_stats.py
    ship_stats.py
    region_compute.py
    route_compute.py

  infrastructure/
    db/
    cache/
    mq/
    llm/
    storage/

  core/
```

## 4. 各层职责
1. API 层：鉴权、参数校验、响应包装。
2. Domain Service：业务规则与编排，不直接写 SQL。
3. Repository：唯一数据库访问入口。
4. AI 模块：提示词管理、解析、匹配建议、解释生成与调用日志。
5. Jobs：统计与异步计算入口，仅此处允许“业务表 -> 统计表”计算。

## 5. API 分域规划
1. `standard_data`：水系/区域/节点/别名/货品体系/船舶体系/航线与路线方案。
2. `ingestion`：微信货源文本接入、AI解析触发、TMS接入、AIS接入、Excel导入。
3. `analysis`：货源热力、趋势、货品排行、OD、船龄/载重、区域/城市热力。
4. `ai`：AI解析记录、匹配建议、提示词版本、分析解释。
5. `system`：登录、用户、角色、权限、审核任务。

## 6. AI 融合设计（一期）
1. 规则优先：先规则匹配，再 AI 补充建议。
2. AI 不能直接落正式主数据，必须经确认/审核。
3. AI 输出必须具备：prompt 版本、模型、置信度、调用日志、反馈回写。
4. 提供分析解释生成接口，但仅针对统计结果文本解释。

## 7. 统计架构
1. 货源统计采用日报聚合表（按统计口径固化）。
2. 船舶统计采用快照表（AIS 场景变化快，不强制日报分片）。
3. 统计任务写入口径文档化，并在任务代码中实现。

## 8. 实施顺序
1. 代码与表结构盘点。
2. 设计文档落库。
3. 模型与迁移改造。
4. 分域目录与模块重组。
5. API 重构。
6. AI 链路重构。
7. 统计链路重构。
8. 文档与最小测试。
9. 本地可运行验证。
