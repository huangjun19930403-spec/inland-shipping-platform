# Round 06 Plan - Opportunity Persistence and API Deletion Candidates

## Goal

继续把“运输机会”从读模型推进到生产级领域对象边界，并开始第一批删除候选确认。

## Work Items

1. 数据结构判断。
   - 判断哪些 opportunity 状态需要沉淀到新表。
   - 给出 `shipping_opportunity`、`shipping_opportunity_evidence`、`shipping_opportunity_action` 是否落表的最终建议。
   - 如果落表，更新单一 `001_initial_schema` 和 seed 边界。

2. API 删除候选。
   - 盘点前端已经迁移到 `/freight/opportunities` 后，旧 `/freight` 列表还被哪些页面消费。
   - 标记纯后台字段、无动作、无分析价值的旧响应字段。
   - 给出第一批删除接口和字段清单，不做兼容层。

3. 动作闭环后端增强。
   - 为清洗、船货适配、报价三个动作补统一 action evaluator。
   - 每个动作返回 `enabled / disabled_reason / required_fields / target_route / query`。

4. 测试。
   - 扩展 opportunity 测试覆盖已有报价、无报价但可报价、已有适配分析、未运行适配分析、有清洗问题。

## Exit Criteria

- opportunity 是否落表有明确结论和迁移方案。
- 第一批待删除 API/字段有清单和依据。
- action evaluator 不再散落在 service 内部条件分支。

