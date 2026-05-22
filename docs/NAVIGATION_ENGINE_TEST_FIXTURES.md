# Navigation Engine Test Fixtures

日期：2026-05-22

本文定义 Navigation Routing Engine 后续测试 fixture 的最小规范。测试要验证真实流程的成功和失败，不允许用 48,192 条真实 `rx` 全量数据作为单元测试输入。

## 1. Fixture 目录建议

建议目录：

```text
tests/fixtures/navigation/
  water_area_tiny.geojson
  boundary_tiny.geojson
  centerline_manual_approved.geojson
  centerline_osm_candidate.geojson
  transport_nodes_tiny.json
  constraint_points_tiny.json
  graph_ready.json
  graph_disconnected.json
  graph_constraint_blocked.json
  graph_low_confidence_unknown_constraint.json
  route_requests.json
  expected_results.json
```

fixture 必须小、稳定、可人工读懂。单个 fixture 不应依赖本地真实数据库现状。

## 2. 最小水域和边界样本

`water_area_tiny.geojson`：

- 至少 2 条窄长河道 polygon。
- 至少 1 个湖泊或宽水域 polygon，用于验证 skeleton 不自动入 graph。
- 至少 1 个远离路线的 polygon，用于验证 bbox 筛选。
- 每个 feature 有 `source_layer_name`、`source_object_id`、`water_name`、bbox 字段。

`boundary_tiny.geojson`：

- 至少 2 个 channel boundary。
- 一个与 centerline 匹配良好。
- 一个只有 boundary、没有 approved centerline，用于验证 `NO_APPROVED_CENTERLINE`。

## 3. 中心线样本

`centerline_manual_approved.geojson`：

- 至少 3 条 `MANUAL` approved/current LineString。
- 包含一个真实 junction。
- 包含一个端点距离另一条线 `<=20m` 的自动 snap 场景。
- 包含一个端点距离 `20-80m` 的 `NEED_REVIEW` candidate junction 场景。

`centerline_osm_candidate.geojson`：

- 至少 1 条 OSM 名称匹配候选。
- 至少 1 条无名称但空间命中的候选。
- 至少 1 条跨多个 channel 的冲突候选。
- 默认 `review_status_code=NEED_REVIEW`，测试未审核 OSM 不得入 graph。

## 4. Graph 样本

`graph_ready.json`：

- 至少 5 个 node。
- 至少 4 条 edge。
- 至少 1 个 `CHANNEL_JUNCTION`。
- 至少 1 条 `SNAP_CONNECTOR` 码头接入 edge。
- 所有 edge 都有 length、direction、channel_id、centerline_id。

`graph_disconnected.json`：

- 至少 2 个子图。
- 用于验证 `GRAPH_DISCONNECTED`、`NO_PATH_FOUND` 和 annotation task 生成。

`graph_constraint_blocked.json`：

- 至少 1 条 edge 有 `DRAFT_LIMIT` 或 `CLOSED` blocking constraint。
- route request 中船舶参数必须触发阻断。

`graph_low_confidence_unknown_constraint.json`：

- 至少 1 条 `LOW_CONFIDENCE` edge。
- 至少 1 条缺桥梁净空或水深数据的 edge。
- 预期结果最高为 `READY_WITH_WARNING`，并产生 `UNKNOWN_CONSTRAINT_DATA`。

## 5. Route Request 样本

`route_requests.json` 至少覆盖：

```text
SUCCESS_RECOMMENDED
ORIGIN_TOO_FAR_FROM_GRAPH
DESTINATION_TOO_FAR_FROM_GRAPH
NO_APPROVED_CENTERLINE
GRAPH_DISCONNECTED
VESSEL_CONSTRAINT_BLOCKED
UNKNOWN_CONSTRAINT_READY_WITH_WARNING
PATH_OUT_OF_WATER_NEED_REVIEW
```

每个 request 必须包含：

```text
origin
destination
vessel_profile_json
routing_preference_code
expected_status_code
expected_quality_code
expected_issue_types
```

## 6. 测试必须验证的行为

基础导入：

- Shapefile/GeoJSON 小样本可导入。
- invalid geometry 能修复或被标记。
- river 导入不覆盖 seed boundary。

中心线：

- approved/current centerline 可进入 graph。
- 未审核 OSM、`WATER_SKELETON`、`HIFLEET_REFERENCE` 不得进入 graph。
- 无中心线 channel 返回 `NO_APPROVED_CENTERLINE`。

Graph：

- 近距 endpoint snap 按阈值处理。
- 不可通航 crossing 不生成可路由 junction。
- 短边合并不吞掉 lock/bridge/port 节点。
- duplicate edge 被禁用但保留记录。

Routing：

- 成功路径返回 edge_ids、channel_ids、graph_version_id。
- 无 graph、吸附过远、图断裂、约束阻断都失败并解释。
- 约束缺失允许生成，但扣分、出 issue、最高 `READY_WITH_WARNING`。
- fallback 假水路在生产配置下不可用。

## 7. 禁止使用真实全量数据做单元测试

禁止：

- 单元测试读取完整 `revier.zip`。
- 单元测试导入 48,192 条 `rx` 数据。
- 单元测试依赖开发者本机真实 SQLite 数据内容。
- 用 HiFleet 返回结果作为 expected route。

允许：

- 集成或人工验收命令提供真实 `revier.zip` dry-run。
- Round 12 业务验收使用真实 MVP 子集数据。
- 性能测试使用抽样或受控导入数据，但必须标记为 slow/integration。
