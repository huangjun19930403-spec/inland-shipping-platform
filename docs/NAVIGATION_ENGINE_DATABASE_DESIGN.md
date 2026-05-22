# Navigation Routing Engine Database Design

日期：2026-05-22

本文定义 Navigation Routing Engine 的目标数据结构。它是后续模型、迁移、导入脚本、服务和前端页面的共同依据。当前已有 `NavigationChannel*` 表继续保留；新增表用于补齐原始水域、中心线、图网络、路径结果和标注闭环。

第一阶段模型原则：

- 不迁移旧 `NavigationChannel*` 类到 `app/models/navigation.py`。
- 先新增 `NavigationWaterArea`、centerline、graph、route result、quality issue、annotation task 等新表。
- 旧 address API、seed 脚本和 imports 保持稳定。
- 等 Navigation Engine 功能稳定后，再单独规划模型归位和 import 路径整理。

## 1. 通用约定

### 1.1 坐标和几何

- 所有持久化 `geometry_json` 默认使用 WGS84 GeoJSON。
- 前端地图如需要 GCJ02，只在展示层转换，不改变源数据。
- 需要米制距离、buffer、面积时，服务层用 `pyproj` 转局部投影后计算。
- Shapely 是标准几何处理库，负责 make_valid、buffer、intersection、distance、snap。

### 1.2 ID 与版本

- 主键使用现有风格：`BigInteger autoincrement`。
- 可回溯对象必须有来源字段和版本字段。
- 可发布对象必须有 `is_current` 或 `status_code`。
- 历史路径必须记录 `graph_version_id`，否则图更新后无法解释历史结果。

### 1.3 状态字段

常用状态：

```text
RAW
VALID
REPAIRED
INVALID
READY
READY_WITH_WARNING
NEED_REVIEW
FAILED
MISSING
ACTIVE
ARCHIVED
```

状态含义必须由服务写入，不能只靠前端推断。

## 2. 现有表保留和增强

### 2.1 `navigation_channel`

用途：航道目录。表示“业务上要识别的一条航道或航道组合”，不是具体路径。

现有关键字段：

```text
channel_code
channel_name
official_name
display_name
alias_names
parent_channel_code
channel_type_code
planning_level_code
planning_basis_code
start_place
end_place
via_city_names
via_port_names
technical_grade_current_code
technical_grade_planned_code
ais_scope_code
review_required
source_version
is_enabled
```

后续建议补充：

```text
water_system_code
planned_tonnage
current_tonnage
routing_enabled
routing_priority
graph_ready
coverage_status_code
centerline_ready
graph_ready_at
```

关系：

- 一条 channel 可有多个 boundary、segment、centerline、graph edge。
- route result 通过 `channel_ids` 记录经过航道。

状态策略：

- `coverage_status_code` 表达从目录到可路径搜索的进度：

```text
NO_DATA
BOUNDARY_ONLY
CENTERLINE_READY
GRAPH_READY
NEED_REVIEW
```

版本策略：

- `source_version` 记录目录来源版本。
- 不直接覆盖原有 channel；目录变更用更新字段和 source audit 解释。

### 2.2 `navigation_channel_boundary`

用途：业务航道包络。用于展示、中心线候选范围、路径质量校验和人工修正。

现有关键字段：

```text
channel_id
geometry_json
boundary_paths_low / medium / high
center_longitude
center_latitude
bbox_min_lng / bbox_min_lat / bbox_max_lng / bbox_max_lat
geometry_status_code
boundary_quality_code
connectivity_status_code
repair_status_code
coverage_policy_code
geometry_coordinate_system_code
boundary_coordinate_system_code
is_current
```

后续建议补充：

```text
boundary_type_code
version_no
parent_boundary_id
confidence_score
review_status_code
matched_water_area_ids
match_report_json
source_policy_codes
source_version
```

关系：

- belongs to `navigation_channel`。
- 可由多个 `navigation_water_area` 匹配生成。
- 可约束 `navigation_channel_centerline` 和 `navigation_graph_edge` 的质量。

状态策略：

```text
DRAFT
NEED_REVIEW
APPROVED
REJECTED
ACTIVE
```

版本策略：

- 同一 channel 同时只允许一个 `is_current=True` 的 active boundary。
- AI 或人工修正必须生成新版本，不直接覆盖历史 boundary。

## 3. 新增原始水域层

### 3.1 `navigation_water_area`

用途：保存 `revier.zip` 导入的原始水域面。它表示“这里是水域”，不等于“这里可通航”。

关键字段：

```text
id
source_code
source_layer_name
source_object_id
water_name
normalized_water_name
alias_names
water_level
water_type_code
remark
geometry_json
geometry_status_code
simplified_geometry_low_json
simplified_geometry_mid_json
simplified_geometry_high_json
bbox_min_lng
bbox_min_lat
bbox_max_lng
bbox_max_lat
center_lng
center_lat
shape_length_degree
shape_area_degree
area_km2
is_low_value
is_enabled
created_at
updated_at
```

关系：

- 可被 `navigation_channel_boundary.matched_water_area_ids` 引用。
- 可被 graph validation 用于水域覆盖校验。
- 不直接参与路径搜索。

状态策略：

```text
RAW
VALID
REPAIRED
INVALID
LOW_VALUE
```

版本策略：

- `source_code + source_layer_name + source_object_id` 唯一。
- 新 river 数据包导入时使用新 `source_code`，不覆盖旧批次。

索引建议：

```text
source_code
source_layer_name
source_object_id
normalized_water_name
bbox_min_lng / bbox_max_lng / bbox_min_lat / bbox_max_lat
is_enabled
```

## 4. 中心线层

### 4.1 `navigation_channel_centerline`

用途：保存航道中心线候选和发布线，是生成 graph edge 的直接来源。

关键字段：

```text
id
channel_id
segment_id
centerline_code
centerline_name
geometry_json
source_type_code
direction_code
is_main_line
confidence_score
quality_code
review_status_code
version_no
parent_centerline_id
is_current
source_trace_json
approved_by
approved_at
bbox_min_lng
bbox_min_lat
bbox_max_lng
bbox_max_lat
created_at
updated_at
```

来源类型：

```text
MANUAL
AIS_INFERRED
OSM_WATERWAY
HYDRORIVERS
WATER_SKELETON
HIFLEET_REFERENCE
SEED_CENTERLINE
```

关系：

- belongs to channel。
- 可选 belongs to `navigation_channel_segment`。
- graph edge 通过 `centerline_id` 继承来源。

状态策略：

```text
READY
READY_WITH_WARNING
NEED_REVIEW
BROKEN
OUT_OF_BOUNDARY
DUPLICATED
REJECTED
```

版本策略：

- 每次人工修正或 AI 修改生成新 `version_no`。
- 只有 `review_status_code=APPROVED` 且 `is_current=True` 的中心线进入 graph 构建。
- `HIFLEET_REFERENCE`、`WATER_SKELETON` 不能自动进入 `APPROVED/current`。
- 未审核 OSM 只能作为候选资产。

## 5. 图网络层

### 5.1 `navigation_graph_version`

用途：记录一次可搜索航道图网络发布版本。

关键字段：

```text
id
version_code
version_name
scope_code
source_summary_json
node_count
edge_count
channel_count
quality_score
status_code
is_active
built_at
created_by
build_scope_bbox_json
build_config_json
validation_report_json
created_at
updated_at
```

关系：

- 一版 graph 有多个 node 和 edge。
- route request/result 必须记录 graph version。

状态策略：

```text
BUILDING
READY
FAILED
ARCHIVED
```

版本策略：

- 同一 `scope_code` 同时只允许一个 `is_active=True` 且 `status_code=READY` 的版本。
- 历史 graph version 不删除，用于解释历史路径。

### 5.2 `navigation_graph_node`

用途：路径搜索节点。来源包括中心线端点、交叉点、船闸、桥梁、码头接入点、人工连接点。

关键字段：

```text
id
graph_version_id
node_code
node_name
node_type_code
longitude
latitude
geometry_json
channel_id
related_transport_node_id
related_constraint_point_id
is_enabled
quality_code
source_type_code
snap_distance_m
snap_confidence
created_at
updated_at
```

节点类型：

```text
CENTERLINE_VERTEX
CHANNEL_JUNCTION
LOCK
BRIDGE
PORT
TERMINAL
ANCHORAGE
WATERWAY_ENTRY
SNAP_CONNECTOR
MANUAL_CONNECTOR
```

关系：

- belongs to graph version。
- 可关联 `TransportNode` 或 `NavigationConstraintPoint`。
- graph edge 通过 `from_node_id/to_node_id` 连接。

状态策略：

```text
READY
NEED_REVIEW
DUPLICATED
ISOLATED
DISABLED
```

版本策略：

- 节点属于具体 graph version，不跨版本复用主键。

### 5.3 `navigation_graph_edge`

用途：路径搜索的核心对象。每条 edge 表示两个 graph node 之间的一段可搜索水路。

关键字段：

```text
id
graph_version_id
edge_code
from_node_id
to_node_id
channel_id
centerline_id
geometry_json
length_km
direction_code
technical_grade_code
min_depth_m
min_width_m
max_allowed_draft_m
max_allowed_tonnage
max_air_draft_m
max_beam_m
max_length_m
lock_required
bridge_count
risk_score
base_cost
routing_enabled
quality_code
source_type_code
confidence_score
version_no
unknown_constraint_flag
validation_summary_json
created_at
updated_at
```

关系：

- belongs to graph version。
- from/to node 均属于同一 graph version。
- belongs to channel。
- 可继承 centerline 来源和质量。
- 可有多个 edge constraint。

状态策略：

```text
READY
NEED_REVIEW
BROKEN
OUT_OF_BOUNDARY
LOW_CONFIDENCE
DUPLICATED
DISABLED
```

版本策略：

- edge 属于具体 graph version。
- graph 重建生成新 edge，不覆盖旧版本 edge。
- polygon、water area、boundary 不得生成可搜索 edge；edge 必须来自 approved/current centerline 或显式 `SNAP_CONNECTOR/MANUAL_CONNECTOR`。

### 5.4 `navigation_graph_edge_constraint`

用途：表达边级通航约束。点状约束继续由 `NavigationConstraintPoint/Profile` 表达。

关键字段：

```text
id
edge_id
constraint_type_code
constraint_name
effective_from
effective_to
rule_json
severity_level
warning_message
is_blocking
is_enabled
data_completeness_code
source_trace_json
created_at
updated_at
```

约束类型：

```text
DRAFT_LIMIT
TONNAGE_LIMIT
AIR_DRAFT_LIMIT
BEAM_LIMIT
LENGTH_LIMIT
TIME_WINDOW
CLOSED
SPEED_LIMIT
ONE_WAY
LOCK_SCHEDULE
WATER_LEVEL_SEASONAL
```

关系：

- belongs to graph edge。
- routing engine 根据 vessel profile 和约束决定禁用、加权或仅提示。

状态策略：

- `is_enabled=False` 的约束不参与路径生成。
- `is_blocking=True` 且规则命中时禁用 edge。
- 缺失关键约束时不默认禁用 edge，但 route result 必须生成 `UNKNOWN_CONSTRAINT_DATA`，并限制最高质量为 `READY_WITH_WARNING`。

版本策略：

- 初版约束跟随 edge version。
- 后续实时约束可独立建事件表，不在第一阶段实现。

## 6. 路径结果层

### 6.1 `navigation_route_request`

用途：记录一次路径生成请求，便于追溯输入参数和失败原因。

关键字段：

```text
id
request_no
origin_lng
origin_lat
origin_name
origin_ref_type_code
origin_ref_id
destination_lng
destination_lat
destination_name
destination_ref_type_code
destination_ref_id
vessel_profile_json
routing_preference_code
graph_version_id
status_code
error_code
error_message
created_by
created_at
```

关系：

- belongs to graph version。
- 可有多个 route result。

状态策略：

```text
SUCCESS
FAILED
NEED_REVIEW
```

版本策略：

- 请求不可变；重新生成创建新 request。

### 6.2 `navigation_route_result`

用途：保存推荐路线或备选路线。

关键字段：

```text
id
request_id
result_no
result_type_code
status_code
geometry_json
distance_km
estimated_duration_hour
edge_ids
channel_ids
passed_node_ids
passed_lock_count
passed_bridge_count
quality_score
quality_code
quality_summary_json
provider_code
engine_code
reference_result_id
created_at
updated_at
```

结果类型：

```text
RECOMMENDED
SHORTEST
ALTERNATIVE
REFERENCE_HIFLEET
```

关系：

- belongs to route request。
- route track version summary 记录 `navigation_route_result_id`。

状态策略：

```text
READY
READY_WITH_WARNING
NEED_REVIEW
FAILED
```

版本策略：

- result 与 request 一起不可变。
- 用户人工修线后进入 route track version，不反写 route result。
- `REFERENCE_HIFLEET` 只能作为显式参考结果，不自动设为当前业务轨迹。

### 6.3 `navigation_route_quality_issue`

用途：保存路径质量问题，支持前端展示、人工标注和后续修复。

关键字段：

```text
id
route_result_id
issue_type_code
severity_code
geometry_json
message
suggestion
related_edge_id
related_node_id
related_annotation_task_id
created_at
```

问题类型：

```text
ORIGIN_TOO_FAR_FROM_WATER
DESTINATION_TOO_FAR_FROM_WATER
ORIGIN_SNAP_LOW_CONFIDENCE
DESTINATION_SNAP_LOW_CONFIDENCE
NO_GRAPH_NEAR_ORIGIN
NO_GRAPH_NEAR_DESTINATION
GRAPH_DISCONNECTED
PATH_OUT_OF_WATER
PATH_OUT_OF_CHANNEL_BOUNDARY
LOW_CONFIDENCE_EDGE
UNKNOWN_CONSTRAINT_DATA
VSL_DRAFT_EXCEEDS_LIMIT
VSL_TONNAGE_EXCEEDS_LIMIT
EDGE_NEED_MANUAL_REVIEW
```

状态策略：

```text
INFO
WARNING
BLOCKING
```

版本策略：

- issue 属于 route result，不跨 result 复用。

## 7. 标注闭环层

### 7.1 `navigation_annotation_task`

用途：将缺边、断点、低置信度中心线、路径失败等问题变成人工/AI 可处理任务。

关键字段：

```text
id
task_no
task_type_code
target_type_code
target_id
channel_id
graph_version_id
geometry_json
priority_code
status_code
issue_summary
suggestion_json
assigned_to
reviewed_by
reviewed_at
resolution_type_code
resolution_target_type_code
resolution_target_id
created_by
created_at
updated_at
resolved_at
```

任务类型：

```text
CENTERLINE_REVIEW
GRAPH_BREAK_FIX
BOUNDARY_REVIEW
CONSTRAINT_REVIEW
ROUTE_FAILURE_REVIEW
MISSING_EDGE
```

关系：

- 可关联 channel、graph version、edge、route quality issue。
- 人工处理结果后生成新的 centerline/boundary/constraint/graph version，不直接改历史结果。
- 从 quality issue 自动生成任务时，应回写 `related_annotation_task_id` 或在任务中记录源 issue。

状态策略：

```text
OPEN
IN_PROGRESS
NEED_REVIEW
RESOLVED
REJECTED
ARCHIVED
```

版本策略：

- annotation task 是工作流记录，不参与 graph version；处理结果通过新版本数据体现。
- 审核通过后是否 rebuild graph 由任务 resolution 决定；旧 graph version 只能归档，不能原地改写。

## 8. 与现有 route 表关系

`ShippingRoutePlanTrackVersion.summary_json` 后续扩展：

```json
{
  "engine": "NAVIGATION_ENGINE",
  "graph_version_id": 1,
  "navigation_route_request_id": 100,
  "navigation_route_result_id": 101,
  "quality_score": 86,
  "quality_code": "READY_WITH_WARNING",
  "edge_ids": [1, 2, 3],
  "channel_ids": [10, 11],
  "issues": []
}
```

原则：

- 不把 navigation route result 外键直接硬塞进 route track version 表的第一版结构。
- 先通过 `summary_json` 兼容接入，降低改动面。
- 后续如果查询压力变大，再考虑显式字段或关系表。

## 9. 第一版迁移边界

第一版新增迁移只创建新表和必要索引，不做：

- 导入 river 全量数据。
- 覆盖 seed boundary。
- 删除 HiFleet。
- 改写现有 route 历史轨迹。
- 启用 PostGIS 专有类型。
- 迁移旧 `NavigationChannel*` 类位置。
- 把旧 `navigation_channel_boundary` 当作 graph edge 使用。

这样 SQLite 本地和后续生产库都能先保持迁移可执行。
