# 阶段 4D RoutePlanNode 路径节点串基线

## 1. 阶段范围

阶段 4D 新增 `shipping_route_plan_node`，用于保存路径方案中的路径节点串。

本阶段只做：

- 路径节点串数据模型
- 节点串查询与整体替换 API
- 基于相邻节点的航段 preview API
- E2E 航线方案节点串 seed

本阶段不做：

- 自动生成真实 `shipping_route_plan_segment`
- geometry 生成
- 高德路径规划
- HiFleet/AMMS 路径规划
- 约束影响分析
- 完整方案设计页重构

## 2. 模型定位

`ShippingRoutePlanNode` 是方案设计的新底座，表达“用户希望路径经过哪些空间节点”。

节点类型包括：

- `REGION_ANCHOR`：区域锚点
- `TRANSPORT_NODE`：运输作业节点
- `CONSTRAINT_POINT`：通航约束点
- `MANUAL_POINT`：手工坐标点

`TransportNode` 是装卸/中转等作业节点；`NavigationConstraintPoint` 是通行限制空间点，二者可同时参与路径节点串，但业务能力不同。

## 3. 与旧航段/点位的关系

- `ShippingRoutePlanNode` 是用户维护的设计输入。
- `ShippingRoutePlanSegment` 是后续由相邻节点生成的结果对象。
- `ShippingRoutePlanSegmentPoint` 是航段轨迹点/点位结果，不作为主设计入口。

阶段 4D 不删除旧航段/点位接口，也不自动写入旧航段/点位表。

## 4. API

- `GET /route/plans/{plan_id}/nodes`：查询方案节点串。
- `PUT /route/plans/{plan_id}/nodes`：整体替换方案节点串。
- `POST /route/plans/{plan_id}/nodes/preview-segments`：按相邻节点预览可生成航段。

Preview 规则：

- 如果起点节点缺少 `next_transport_mode_code`，返回 `transport_mode_code=UNKNOWN`。
- `UNKNOWN` 不视为可生成状态，`can_generate=false`，`message=运输方式未配置`。
- `REGION_ANCHOR` 只要 `region_id` 存在即可视为有定位依据。
- Preview 不生成 geometry，不创建真实航段。

## 5. Seed

`seed_route_map_e2e.py` 为 `E2E_ROUTE_PLAN_MAP` 写入稳定节点串：

1. `REGION_ANCHOR`：E2E起点区域
2. `MANUAL_POINT`：E2E起点水路节点
3. `CONSTRAINT_POINT`：E2E桥梁约束点
4. `MANUAL_POINT`：E2E中间手工点
5. `REGION_ANCHOR`：E2E终点区域

该 seed 仅清理并重建 `E2E_ROUTE_PLAN_MAP` 的 nodes，不影响非 E2E plan，也不破坏现有 E2E segments/points。
