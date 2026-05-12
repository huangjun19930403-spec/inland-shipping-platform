# Round 05 Report - Freight Opportunity Workbench Evidence

## Scope

本轮把 Round 04 的运输机会读模型扩展为详情工作台所需的证据结构，并补服务测试。

## Changes

- 扩展 `ShippingOpportunityDetailResponse`。
  - `source_evidence`：来源类型、批次、TMS、线索、候选、原文摘要、AI 版本、确认记录摘要。
  - `cleaning_issues`：待处理清洗建议、影响字段、建议对象、置信度、匹配依据。
  - `route_evidence`：航线状态、路线绑定、起终点、不可计算原因。
  - `capacity_evidence`：最近一次船货适配分析、候选数、低可信数、覆盖率、置信度。
  - `pricing_evidence`：价格来源层、声明价格、报价上下文、不可计算原因、是否使用 demo 数据。
- 增强 action contract。
  - 清洗动作携带 `keyword=freight_no` 和 `status_code=PENDING`，前端可以定位到对应清洗建议。
  - 报价动作携带起终点、标准货品、吨位、当前价格。
  - 有待处理清洗问题时，即使主字段完整，也返回 `OPEN_FREIGHT_CLEANING`。
- 新增 `tests/test_shipping_opportunity_service.py`。
  - 覆盖完整机会：来源、清洗、航线、运力、报价证据。
  - 覆盖不可计算机会：缺节点、缺货品、缺吨位、缺价格。

## Verification

- `.venv/bin/python -m py_compile app/modules/freight/schemas.py app/modules/freight/opportunity_service.py app/modules/freight/router.py tests/test_shipping_opportunity_service.py`
- `.venv/bin/pytest tests/test_shipping_opportunity_service.py`

## Notes

- `ShippingOpportunityService` 当前 637 行，继续满足单 service 小对象约束。
- 本轮仍未新增物理表。是否将 opportunity 状态沉淀为表，将在后续数据库重建轮统一处理。

