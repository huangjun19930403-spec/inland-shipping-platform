# Navigation Routing Engine Design - Round 1 Baseline

日期：2026-05-22

本文是 Round 1 审计后的 baseline 设计记录，保留当前仓库边界和初始判断。后续开发以新的总文档包为准：

- `docs/NAVIGATION_ENGINE_MASTER_PLAN.md`
- `docs/NAVIGATION_ENGINE_DATABASE_DESIGN.md`
- `docs/NAVIGATION_ENGINE_FLOW_DESIGN.md`
- `docs/NAVIGATION_ENGINE_CENTERLINE_AND_GRAPH_RULES.md`
- `docs/NAVIGATION_ENGINE_TEST_FIXTURES.md`
- `docs/NAVIGATION_ENGINE_PERFORMANCE_RULES.md`
- `docs/NAVIGATION_ENGINE_ROUND_PLAN.md`
- `docs/NAVIGATION_ENGINE_EXECUTION_RECEIPT_TEMPLATE.md`

重要修正：

- SQLite 是当前本地持久化环境，不代表功能降级。
- 后续实现轮必须补齐 `shapely`、`networkx`、`pyproj`，完整支撑 geospatial 和 graph 能力。
- `river` 是原始水域资产，seed boundary 是业务航道包络资产，两者并存，不能互相覆盖。
- 无 graph 时必须失败并解释原因，不能用 fallback 曲线冒充水路。

## 1. 产品定位

目标不是让 AI 直接“画一条水路线”，而是先生产自己的内河航道图网络：

```text
river 水系面
  -> 航道目录
  -> 候选边界
  -> 中心线
  -> graph node / edge
  -> 通航约束
  -> A-B 路径搜索
  -> 质量校验
  -> 人工标注
  -> 图网络版本发布
  -> route 业务轨迹版本
```

系统定位：

```text
用于业务级路径规划、运距估算、货源线路分析、航道数据生产和内部调度辅助；
不作为船舶安全航行的官方导航依据。
```

## 2. 当前仓库边界

已有模块：

- `app/models/address.py`：行政区、区域、运输节点、通航约束点、航道目录、航道边界、航道分段、来源审计。
- `app/models/route.py`：业务航线、方案、点、段、轨迹版本、轨迹版本分段。
- `app/modules/address/navigation_channel_service.py`：航道基础数据查询。
- `app/modules/route/service.py`：业务航线 CRUD、结构维护、轨迹版本生成、外部 provider 调用、fallback 处理。
- `app/tasks/route_tasks.py`：异步触发 `route.generate_track_version`。

当前航道数据只支持“边界展示/AIS 归属/审计说明”，不能支持路径搜索。原因是当前缺少中心线和 graph edge。

## 3. 模型拆分策略

后续实现轮新增 `app/models/navigation.py`，不要继续把 graph 和 route result 塞进 `address.py`。

`app/models/address.py` 保留：

```text
AdminRegion
AdminRegionBoundary
Region
RegionBoundaryVersion
RegionCityRelation
TransportNode
TransportNodeProfile
TransportNodeContact
NodeAlias
NavigationConstraintPoint
NavigationConstraintProfile
```

`app/models/navigation.py` 第一阶段只新增：

```text
NavigationWaterArea
NavigationChannelCenterline
NavigationGraphVersion
NavigationGraphNode
NavigationGraphEdge
NavigationGraphEdgeConstraint
NavigationRouteRequest
NavigationRouteResult
NavigationRouteQualityIssue
NavigationAnnotationTask
```

迁移原则：

- 第一阶段不要迁移旧 `NavigationChannel*` 类位置，避免破坏 address API、seed 和 imports。
- 等 Navigation Engine 稳定后，单独规划模型归位；若迁移 `NavigationChannel*` 类，应同步更新 imports，但不改变表名和现有 API 响应语义。
- 不删除旧数据，不重命名现有表，不破坏 `/api/v1/address/navigation-channels/*`。

## 4. 数据层阶段

### 4.1 水域面

新增 `navigation_water_area`，承接 `revier.zip` 中 `rx` 和一级到七级水系。

第一版字段重点：

```text
source_code
source_layer_name
source_object_id
water_name
normalized_water_name
water_level
water_type_code
geometry_json
geometry_status_code
bbox_min_lng / bbox_min_lat / bbox_max_lng / bbox_max_lat
center_lng / center_lat
shape_length_degree
shape_area_degree
area_km2
is_enabled
```

导入脚本后续放在：

```text
scripts/navigation/import_river_shapefile.py
```

### 4.2 航道边界

现有 `navigation_channel_boundary` 继续作为业务航道包络层。后续补充来源、版本和审核字段：

```text
boundary_type_code
version_no
parent_boundary_id
confidence_score
review_status_code
matched_water_area_ids
match_report_json
source_policy_codes
is_current
```

边界只用于展示、候选范围、质量校验和人工修正，不能作为路径搜索对象。

### 4.3 中心线

新增 `navigation_channel_centerline`，从候选线走向 graph。

来源优先级：

```text
MANUAL
SEED_CENTERLINE
已审核 OSM_WATERWAY
AIS_INFERRED
HYDRORIVERS
WATER_SKELETON
HIFLEET_REFERENCE
```

江苏 MVP 第一阶段只允许 `MANUAL`、`SEED_CENTERLINE`、已审核 `OSM_WATERWAY` 进入 graph。低置信度中心线默认 `NEED_REVIEW`，不能直接进入生产路径。`WATER_SKELETON` 和 `HIFLEET_REFERENCE` 不得自动发布。

### 4.4 图网络

新增：

```text
navigation_graph_version
navigation_graph_node
navigation_graph_edge
navigation_graph_edge_constraint
```

路径搜索必须基于 `navigation_graph_edge`，并且结果必须记录 `graph_version_id`。历史轨迹版本需要知道自己基于哪一版图生成。

## 5. Routing Engine 模块边界

后续新增模块：

```text
app/modules/navigation/engine/snapper.py
app/modules/navigation/engine/constrained_search.py
app/modules/navigation/engine/path_assembler.py
app/modules/navigation/engine/path_validator.py
app/modules/navigation/engine/quality_scoring.py
app/modules/navigation/services/routing_engine_service.py
app/modules/navigation/router.py
app/modules/navigation/schemas.py
```

职责划分：

- `snapper.py`：运输节点/经纬度到 graph edge/node 的吸附。
- `constrained_search.py`：按船舶参数过滤 edge，并执行 Dijkstra/A*。
- `path_assembler.py`：edge 序列拼接为 LineString。
- `path_validator.py`：水域、航道边界、断裂、禁用 edge、NEED_REVIEW edge 校验。
- `quality_scoring.py`：输出质量分、质量等级和问题列表。
- `routing_engine_service.py`：请求校验、图版本选择、事务落表和服务编排。

第一版图搜索使用 Python 内存图和 `networkx`。后续实现轮必须补齐 `shapely`、`networkx`、`pyproj` 依赖和测试；PostGIS/pgRouting 是全国级规模化演进方向，不阻塞第一版完整功能模块。

## 6. API 边界

现有 API 保持：

```text
GET /api/v1/address/navigation-channels/summary
GET /api/v1/address/navigation-channels
GET /api/v1/address/navigation-channels/{channel_code}
GET /api/v1/address/navigation-channels/{channel_code}/boundary
GET /api/v1/address/navigation-channels/{channel_code}/segments
GET /api/v1/address/navigation-channels/{channel_code}/source-audit
```

后续新增路径生成 API：

```text
POST /api/v1/navigation/routes/generate
```

请求最小字段：

```text
origin
destination
vessel_profile_json
routing_preference_code
graph_version_id optional
```

响应最小字段：

```text
navigation_route_request_id
navigation_route_result_id
graph_version_id
geometry_json
distance_km
estimated_duration_hour
edge_ids
channel_ids
quality_score
quality_code
issues
```

## 7. Route 模块接入原则

当前 route 轨迹生成链路：

```text
ShippingRoutePlan
  -> points
  -> segments
  -> generate_track_version
  -> WATER 调 HIFLEET
  -> ROAD 调 AMAP
  -> fallback 曲线
  -> ShippingRoutePlanTrackVersion
```

目标链路：

```text
ShippingRoutePlan
  -> points
  -> segments
  -> generate_track_version
  -> WATER 调 NavigationRoutingEngineService
  -> ROAD 调 AMapRouteClient
  -> RAIL 暂不支持
  -> ShippingRoutePlanTrackVersion
```

接入时必须做到：

- `TRACK_VERSION_SOURCES` 增加 `NAVIGATION_ENGINE`。
- `WATER` 默认 provider 改为 `NAVIGATION_ENGINE`。
- HiFleet 仅作为 reference/compare provider，不再是默认水路生成源。
- 生产模式下不能用 fallback 曲线冒充真实水路。
- `summary_json` 记录 `graph_version_id`、`navigation_route_request_id`、`navigation_route_result_id`、`quality_score`、`quality_code`、`edge_ids`、`channel_ids`、`issues`。

## 8. 前端边界

当前已有：

- `航道基础数据` 页面：列表、筛选、详情、边界预览。
- `轨迹版本编辑` 页面：查看、人工重画、保存当前版本。

后续新增：

```text
航道数据
  水系边界
  航道边界
  航道中心线
  航道图网络
  通航约束
  路径生成测试
  标注任务
```

第一版前端不做全量生产工具，只做地图图层展示和路径生成测试页，保证能看见 water area、boundary、centerline、graph node/edge、route result、quality issue。

## 9. 第二轮交付边界

第二轮只做模型和迁移，不接入业务生成逻辑：

```text
新增 app/models/navigation.py
新增 navigation_water_area / centerline / graph / route result / quality issue 模型
必要时迁移 NavigationChannel* imports
生成 migration
更新 app/models/__init__.py
补充模型/迁移测试
```

第二轮不得：

```text
导入 revier.zip 全量数据
接入 route.generate_track_version
实现 Dijkstra/A*
改前端页面
删除 HiFleet
```

## 10. 风险与默认决策

- 当前本地数据库是 SQLite，但功能设计不因此降级；实现轮通过 `shapely`、`pyproj`、`networkx` 补齐几何计算和图搜索能力。
- PostGIS/pgRouting 是后续规模化演进方向，不阻塞第一版完整 Navigation Routing Engine。
- 当前 seed 已经包含 104 个航道对象和 95 个可用边界，不能被 river 全量导入覆盖。
- `river` 是原始水域资产，seed boundary 是业务航道包络资产；路径搜索对象只能是 graph edge。
- 无 graph、graph 断裂、吸附失败或船舶约束阻断时，必须返回可解释失败，不能 fallback 成假水路。
