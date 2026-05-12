# Round 04 Report - Shipping Opportunity Read Model

## Scope

本轮按 `ROUND_04_PLAN.md` 先落一个真实业务入口，不继续扩写旧货源大 service。

目标是把正式货源从普通列表提升为“运输机会”读模型：同一条货源必须同时暴露来源血缘、节点/货品/吨位/价格完整性、航线可计算状态、船货适配状态、报价状态、数据质量问题和下一步动作。

## Changes

- 新增 `app/modules/freight/opportunity_service.py`。
  - 从 `freight` 事实出发读取机会列表和详情。
  - 批量补齐 `transport_node`、`commodity_standard`、`shipping_route`、`vessel_candidate_analysis`、`freight_normalization_suggestion` 上下文。
  - 输出 `route_status_code`、`capacity_status_code`、`pricing_status_code`、`data_quality_status_code`。
  - 输出 `context / lineage / quality / actions`，避免只给表格字段。
- 扩展 `app/modules/freight/schemas.py`。
  - 新增 `ShippingOpportunityListQuery`。
  - 新增机会上下文、血缘、质量、动作、列表项和详情响应 schema。
- 扩展 `app/modules/freight/router.py`。
  - 新增 `GET /api/v1/freight/opportunities`。
  - 新增 `GET /api/v1/freight/opportunities/{freight_id}`。
  - 两个路由放在 `/{freight_id}` 之前，避免动态路由吞掉 opportunity 路径。

## Verification

- `.venv/bin/python -m py_compile app/modules/freight/schemas.py app/modules/freight/opportunity_service.py app/modules/freight/router.py`
- 本地库服务探针通过：
  - 机会总数：248。
  - 首条机会返回 `lineage.source_tables`。
  - 首条机会返回 `quality.not_computable_reasons` 和 `quality.uncertainty_reasons`。
  - 首条机会返回 `OPEN_FREIGHT_DETAIL / OPEN_FREIGHT_CLEANING / OPEN_CANDIDATE_VESSELS / OPEN_QUOTE_SIMULATOR` 动作。

## Notes

- 本轮没有新增物理表，先用现有事实链建立生产读模型，下一轮再判断哪些状态应该沉淀到 `shipping_opportunity` 表。
- 旧 `/freight` 资源接口暂时保留为底层资源接口；前端正式货源列表已经迁移到 opportunity API，后续可继续清理无消费字段和旧列表语义。

