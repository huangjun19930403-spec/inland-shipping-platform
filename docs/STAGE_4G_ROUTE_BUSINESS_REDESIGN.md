# Stage 4G 航线规划业务化重构说明

## 1. 本轮结论

上一版航线工作台仍然围绕 `route_plan_nodes / route_plan_segments / route_plan_segment_points` 包装前端交互，无法表达“一个运输方案下多条路线”的真实业务。Stage 4G 采用删除式重构，把主链路调整为：

```text
航线 Route
  └── 运输方案 Plan
        └── 路线 Line
              ├── 路线节点 Line Node
              ├── 路线段 Line Segment
              └── 路线轨迹 Line Track
```

运输方案不强制绑定货主、货品、船型或吨位。当前业务场景通过方案名称、方案类型、说明和备注表达，例如“煤炭运输方案”“低水位绕行方案”。如后续需要结构化分析，应新增标签或关联表，而不是污染主模型。

## 2. 数据模型

### shipping_route

航线/区域走廊。保留 `code / name / origin_region_id / destination_region_id / transport_org_type_code / multimodal_combination_code / description` 以及治理字段。航线状态不进入前端主流程。

### shipping_route_plan

运输方案。字段收敛为 `route_id / plan_code / plan_name / plan_type_code / description / remark`。不再包含版本、默认方案、状态、生效时间、总距离、总时长等主流程字段。

### shipping_route_line

路线。一条运输方案下可以有主路线、备用路线、绕行路线、应急路线。路线承载 `line_role_code / priority / trigger_condition / track_status / track_generated_at`。

### shipping_route_line_node

路线节点。仅支持 `TRANSPORT_NODE / CONSTRAINT_POINT / MANUAL_POINT`。不再暴露区域锚点，不允许用户手填已有节点 ID。

### shipping_route_line_segment

路线段。路线段挂在 `line_id` 下，通过 `start_line_node_id / end_line_node_id` 表达 A→B，记录运输方式和段轨迹状态。

### shipping_route_line_track

完整路线轨迹快照。地图预览读取已保存的 line track，不实时调用 provider。

## 3. 删除旧主链路

本轮从 clean migration 中移除：

- `shipping_route_plan_node`
- `shipping_route_plan_segment`
- `shipping_route_plan_segment_point`

旧节点串、下一段运输方式、预览生成航段等概念不再作为主业务模型。

## 4. API 主链路

- `GET/POST/PUT/DELETE /api/v1/route`
- `GET/POST /api/v1/route/{route_id}/plans`
- `PUT/DELETE /api/v1/route/plans/{plan_id}`
- `GET/POST /api/v1/route/plans/{plan_id}/lines`
- `GET/PUT/DELETE /api/v1/route/lines/{line_id}`
- `GET/PUT /api/v1/route/lines/{line_id}/structure`
- `GET /api/v1/route/lines/{line_id}/track`
- `POST /api/v1/route/lines/{line_id}/track/generate`

`track/generate` 当前只返回 provider 未配置，不接入真实路径规划。

## 5. Seed

`seed_route_map_e2e.py` 已重构为新模型基线：

- `E2E_ROUTE_MAP`
- `E2E_ROUTE_PLAN_MAP`
- `E2E_ROUTE_PLAN_LOW_WATER`
- `E2E_ROUTE_LINE_MAIN`
- `E2E_ROUTE_LINE_DETOUR`
- E2E 运输节点：`E2E_ROUTE_LOAD_NODE / E2E_ROUTE_UNLOAD_NODE`
- 每条路线有 line nodes、line segments、line track。

clean DB 初始化后可直接用于前端 Playwright 验收。

## 6. 本轮未做

- 不接入真实 HiFleet / AMMS / 高德 provider。
- 不生成真实 geometry。
- 不做船舶尺度/吃水判断。
- 不做约束影响计算。
- 不做复杂地图编辑。
- 不做拖拽排序。
