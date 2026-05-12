# Round 06 Report - Action Semantics and Deletion Boundary

## Scope

本轮只做三件事：明确运输机会是否落表、把机会动作从 service 条件分支里抽出、形成第一批后端删除候选。未做壳式表结构扩张。

## Changes

1. 新增 `ShippingOpportunityActionEvaluator`。
   - 统一生成 `OPEN_FREIGHT_DETAIL`、`OPEN_FREIGHT_CLEANING`、`OPEN_CANDIDATE_VESSELS`、`OPEN_QUOTE_SIMULATOR`、`OPEN_ROUTE_PLANNING`。
   - 每个动作返回 `enabled`、`disabled_reason`、`required_fields`、`target_route`、`query`。
   - 船货适配和报价不再让前端猜测是否可执行，后端根据节点、标准货品、价格口径和不可计算状态给出明确阻断原因。

2. 扩展分析和运输机会 action schema。
   - `AnalysisActionBlock` 与 `ShippingOpportunityActionResponse` 增加 `enabled` 和 `required_fields`。
   - 旧字段兼容当前前端，但新工作台以 `enabled === false` 作为禁用动作的生产口径。

3. 收敛 `ShippingOpportunityService`。
   - 删除 service 内部散落的 action 拼装逻辑。
   - service 继续负责证据聚合、状态判断、质量口径和推荐动作选择。
   - 当前文件 581 行，低于 800 行约束。

4. 增强测试。
   - 覆盖可报价动作的 `enabled` 和 `required_fields`。
   - 覆盖不可计算船货适配动作的 `enabled=false` 与 `disabled_reason`。

## Opportunity Persistence Decision

本轮不新增 `shipping_opportunity` 物理表。

原因：

- 当前机会对象仍然是从货源、路线、船货适配、清洗建议、价格字段实时聚合出的读模型。
- 如果现在只落一张空壳机会表，会把“运输机会”做成壳式重构，不能表达状态机、证据快照、报价决策、匹配结果和动作履历。
- 生产级落表必须等三类行为真正闭合：机会状态流转、匹配/报价决策快照、动作执行与回算记录。

下一轮建议在单一 `001_initial_schema` 中引入的最小表组：

- `shipping_opportunity`：机会主状态、关联货源、路线、当前阶段、综合置信度、最近刷新时间。
- `shipping_opportunity_evidence`：来源、路线、运力、价格、质量证据快照，带 lineage 和 sample size。
- `shipping_opportunity_action_log`：动作生成、禁用、执行、跳转、失败原因。

## API Deletion Candidates

前端消费盘点结果：

- `fetchShippingOpportunities` 已成为正式货源主列表入口。
- 旧 `fetchFreights` 仍被 `DashboardPage` 最近货源、`useVesselCandidateRemoteOptions` 远程货源选择器消费。
- `fetchFreightDetail` 仍用于货源详情维护页和船货适配选择器补全。

第一批删除边界：

- 暂不删除 `/freight` 资源接口，先迁走仪表盘和船货适配选择器。
- 下一轮删除列表响应中仅服务旧后台展示、且不参与机会证据的大厅展示字段和分页局部统计字段。
- 旧接口不做长期兼容层；迁移完成后直接删前端调用和后端响应字段。

## Quality Findings

新增/重构文件满足本轮大小约束：

- `app/modules/freight/opportunity_service.py`：581 行。
- `app/modules/freight/opportunity_actions.py`：109 行。

既有遗留大对象仍需继续拆分，不能作为最终验收通过项：

- `app/modules/freight/service.py`：3501 行。
- `app/modules/analysis/service.py`：1927 行。
- 船舶 AIS、关系、治理、地址等旧 service/methods 文件仍超过 800 行。

这些将在第七轮开始进入强制拆分和删除清单。

## Verification

- `.venv/bin/python -m py_compile app/modules/freight/opportunity_actions.py app/modules/freight/opportunity_service.py app/modules/freight/schemas.py app/modules/analysis/schemas.py`
- `.venv/bin/python -m pytest tests/test_shipping_opportunity_service.py tests/test_analysis_quote_route_estimate.py`

结果：10 个测试通过，存在既有 `datetime.utcnow()` 警告。
