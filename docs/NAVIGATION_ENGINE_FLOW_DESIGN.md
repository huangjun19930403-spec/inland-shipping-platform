# Navigation Routing Engine Flow Design

日期：2026-05-22

本文定义 Navigation Routing Engine 的完整流程。它回答“数据如何进入系统、如何变成 graph、如何生成路线、失败时如何解释、质量如何评分、如何接入现有 route 轨迹版本”。

## 1. 总流程

```text
数据生产链路：
river / seed boundary / OSM / AIS / 人工
  -> 原始资产入库
  -> 候选边界和中心线
  -> 人工/规则审核
  -> graph 构建
  -> graph 校验
  -> graph version 发布

路径生成链路：
A/B 点 + 船舶参数 + 路径偏好 + graph version
  -> 起终点解析
  -> 吸附 graph
  -> 约束过滤
  -> networkx 搜索
  -> edge 拼接
  -> Shapely 水域/边界校验
  -> 质量评分
  -> route request/result/issue 落表
  -> 可保存为 ShippingRoutePlanTrackVersion
```

## 2. River 导入流程

脚本：

```text
scripts/navigation/import_river_shapefile.py
```

输入：

```text
--input /Users/hj/Documents/河道数据/revier.zip
--source-code RIVER_SHAPEFILE_2026
--layers rx,一级水系,二级水系,三级水系,四级水系,五级水系,六级水系,七级水系
```

处理步骤：

1. 读取 zip 内 Shapefile，编码按 `.cpg=UTF-8`。
2. 用 `pyshp` 读取 records 和 shapes。
3. 将 shape 转为 Shapely geometry。
4. 对 invalid geometry 执行 `shapely.make_valid`。
5. 计算 bbox、center、area、point_count、multipart 状态。
6. 标准化 `NAME` 为 `normalized_water_name`。
7. 识别 `water_level` 和 `water_type_code`。
8. 写入 `navigation_water_area`。

输出：

```text
navigation_water_area rows
import summary
invalid/repaired geometry report
```

失败原因：

```text
ZIP_NOT_FOUND
LAYER_FILE_MISSING
SHAPEFILE_READ_FAILED
GEOMETRY_INVALID_UNREPAIRABLE
DATABASE_WRITE_FAILED
```

质量标记：

```text
RAW
VALID
REPAIRED
INVALID
LOW_VALUE
```

关键边界：

- river 导入不更新 `navigation_channel_boundary`。
- river 导入不生成 graph。
- river 导入只生产原始水域资产。

## 3. 航道目录和边界匹配流程

脚本：

```text
scripts/navigation/seed_navigation_catalog.py
scripts/navigation/build_channel_boundaries.py
```

输入：

- 现有 `navigation_channel` seed。
- 现有 `navigation_channel_boundary` seed boundary。
- `navigation_water_area`。
- 航道别名配置。
- 省市范围配置。

处理步骤：

1. 读取航道目录和别名。
2. 对 water area 执行精确名称、包含名称、别名名称匹配。
3. 用省市范围、bbox 和 water type 过滤异地同名。
4. 对匹配结果生成 `match_report_json`。
5. 若已有 seed boundary，保留 seed boundary 为 current。
6. 若无 seed boundary，可生成候选 boundary，默认 `NEED_REVIEW`。

输出：

- boundary match report。
- 可选候选 `navigation_channel_boundary` 新版本。

失败原因：

```text
CHANNEL_ALIAS_MISSING
NO_WATER_AREA_MATCH
MULTIPLE_AMBIGUOUS_MATCHES
BOUNDARY_GEOMETRY_INVALID
```

质量标记：

```text
HIGH_CONFIDENCE
MEDIUM_CONFIDENCE
LOW_CONFIDENCE
REVIEW
MISSING
```

关键边界：

- seed boundary 不能被 river 自动覆盖。
- 规划航道名称无法直接匹配时，必须标记 `NEED_REVIEW`，不能胡乱生成。

## 4. 中心线生产流程

脚本：

```text
scripts/navigation/import_centerlines_geojson.py
scripts/navigation/import_osm_waterways.py
scripts/navigation/build_centerline_candidates.py
scripts/navigation/build_centerline_from_water_area.py
```

输入来源优先级：

```text
MANUAL
SEED_CENTERLINE
已审核 OSM_WATERWAY
AIS_INFERRED
HYDRORIVERS
WATER_SKELETON
HIFLEET_REFERENCE
```

处理步骤：

1. 导入候选 LineString。
2. 按 channel boundary 或行政范围裁剪。
3. 按名称、别名、空间关系归属 channel。
4. 过滤过短、孤立、明显离开水域的线。
5. 计算 confidence_score。
6. 低置信度标记 `NEED_REVIEW`。
7. 人工确认后设置 `review_status_code=APPROVED` 和 `is_current=True`。

输出：

```text
navigation_channel_centerline
centerline quality report
annotation task candidates
```

失败原因：

```text
CENTERLINE_SOURCE_MISSING
CHANNEL_NOT_RESOLVED
CENTERLINE_OUT_OF_BOUNDARY
CENTERLINE_TOO_SHORT
CENTERLINE_DUPLICATED
```

质量标记：

```text
READY
NEED_REVIEW
BROKEN
OUT_OF_BOUNDARY
DUPLICATED
```

关键边界：

- HiFleet 返回线只能是 `HIFLEET_REFERENCE`，不能直接发布为正式中心线。
- 水域骨架线默认候选，不直接进入生产 graph。
- 只有 approved/current centerline 进入 graph 构建。
- 江苏 MVP 第一阶段 graph 只允许 `MANUAL`、`SEED_CENTERLINE`、已审核 `OSM_WATERWAY`。
- 无 approved/current centerline 的航道必须返回 `NO_APPROVED_CENTERLINE`。
- 人工中心线 GeoJSON、OSM 归属、候选去重规则见 `docs/NAVIGATION_ENGINE_CENTERLINE_AND_GRAPH_RULES.md`。

## 5. Graph 构建流程

脚本：

```text
scripts/navigation/build_graph_from_centerline.py
```

输入：

- approved/current centerline。
- `TransportNode` 码头/港口。
- `NavigationConstraintPoint` 船闸/桥梁/浅滩等点状约束。
- active channel boundary。
- water area。

处理步骤：

1. 创建 `navigation_graph_version(status=BUILDING)`。
2. 读取目标范围 current centerline。
3. 在端点、交叉点、码头接入点、约束点、人工断点处切分。
4. 生成 graph node。
5. 相邻节点间生成 graph edge。
6. 计算 edge 长度、方向、source_type、confidence。
7. 继承 channel 技术等级和可用约束。
8. 检查 edge 与 water area/channel boundary 关系。
9. 更新 edge quality。
10. 汇总 node_count、edge_count、channel_count。
11. 通过校验后设置 graph version `READY`。

细化规则：

- 两条中心线几何相交不等于可通航交汇；只有同一 channel 或配置了 allowed junction 才创建可路由 `CHANNEL_JUNCTION`。
- 端点距离另一条线 `<=20m` 可自动 snap；`20-80m` 生成 `NEED_REVIEW` junction；`>80m` 不自动连接。
- 跨河桥、立交或疑似投影相交但不可通航时，生成 `CROSSING_NOT_NAVIGABLE`，不创建可搜索连接。
- 码头距 approved centerline `0-200m` 可创建 `SNAP_CONNECTOR` edge；`200-500m` 仅候选并 `NEED_REVIEW`；`>500m` 不自动接入。
- 船闸应创建 `LOCK` node 并在相关 edge 写 `lock_required` 或 `LOCK_SCHEDULE` constraint。
- 桥梁可创建 `BRIDGE` node，净空等限制写入 edge constraint；缺失净空产生 `UNKNOWN_CONSTRAINT_DATA`。
- 非终点断点、孤立子图、重复 edge、短边合并按中心线和 graph 规则文档处理。
- 短边合并不得吞掉 `LOCK/BRIDGE/PORT/TERMINAL/JUNCTION/CONSTRAINT` 节点。
- 默认方向为 `BIDIRECTIONAL`；只有明确来源支持时才设置单向。

输出：

```text
navigation_graph_version
navigation_graph_node
navigation_graph_edge
navigation_graph_edge_constraint
```

失败原因：

```text
NO_APPROVED_CENTERLINE
CENTERLINE_INTERSECTION_FAILED
NODE_GENERATION_FAILED
EDGE_GENERATION_FAILED
GRAPH_DISCONNECTED
GRAPH_QUALITY_TOO_LOW
```

质量标记：

```text
READY
NEED_REVIEW
BROKEN
OUT_OF_BOUNDARY
LOW_CONFIDENCE
DUPLICATED
DISABLED
```

关键边界：

- graph edge 是唯一可搜索对象。
- graph version 未 `READY` 不能作为默认路径版本。
- graph 重建必须生成新版本，不覆盖历史版本。
- polygon、water area、channel boundary 不能在 graph 构建或搜索阶段临时充当路线。
- graph 构建性能边界见 `docs/NAVIGATION_ENGINE_PERFORMANCE_RULES.md`。

## 6. Graph 校验流程

脚本：

```text
scripts/navigation/validate_navigation_graph.py
```

校验项：

- node/edge 数量是否合理。
- 是否存在孤立 node。
- 是否存在断裂 channel。
- edge 是否大段离开 water area。
- edge 是否大段离开 channel boundary。
- edge 是否缺少 channel_id。
- edge 是否低置信度。
- 码头/船闸/桥梁是否正确接入 graph。

输出：

```text
graph quality score
graph issue report
navigation_annotation_task candidates
```

发布规则：

- `quality_score >= 80` 且无 blocking issue，可发布 `READY`。
- `60 <= quality_score < 80`，进入 `NEED_REVIEW`。
- `< 60` 或存在严重断裂，标记 `FAILED`。

## 7. 路径生成流程

服务：

```text
NavigationRoutingEngineService.generate_route()
```

API：

```text
POST /api/v1/navigation/routes/generate
```

输入：

```text
origin
destination
vessel_profile_json
routing_preference_code
graph_version_id optional
```

### 7.1 起终点解析

支持：

```text
TRANSPORT_NODE
CONSTRAINT_POINT
MANUAL_POINT
LNG_LAT
```

规则：

- 城市不能直接生成内河路径。
- 城市必须先转为可用码头、运输节点或人工点。
- 点位经纬度必须合法。

失败原因：

```text
ORIGIN_NOT_RESOLVED
DESTINATION_NOT_RESOLVED
POINT_COORDINATE_INVALID
CITY_ENDPOINT_NOT_ALLOWED
```

### 7.2 起终点吸附

吸附优先级：

```text
1. 最近 PORT/TERMINAL graph node
2. 最近 graph edge
3. 最近 centerline
4. 最近 water area 内点
```

吸附阈值：

```text
0-200m: HIGH
200-500m: MEDIUM
500-2000m: LOW, NEED_REVIEW
>2000m: 默认失败
>5000m: 强制失败
```

输出：

```json
{
  "snap_type": "GRAPH_EDGE",
  "snap_distance_m": 136.5,
  "snap_confidence": 86,
  "snap_edge_id": 12888,
  "snap_point": [120.5632, 31.3451]
}
```

失败原因：

```text
NO_GRAPH_NEAR_ORIGIN
NO_GRAPH_NEAR_DESTINATION
ORIGIN_TOO_FAR_FROM_GRAPH
DESTINATION_TOO_FAR_FROM_GRAPH
```

### 7.3 图加载

规则：

1. 选择 `graph_version_id`，未传则选择 active ready version。
2. 根据 A/B 点构造 bbox。
3. bbox 外扩 30-100km。
4. 加载 bbox 内 enabled node/edge。
5. 如无路径，可按策略扩大 bbox 一次。

性能边界：

- 禁止全国 graph 一次性加载进 NetworkX。
- edge/node 数量超过配置上限时返回 `GRAPH_LOAD_TOO_LARGE`。
- 水域和边界校验只加载 route bbox 外扩后的候选 polygon。

失败原因：

```text
NO_ACTIVE_GRAPH_VERSION
NO_ROUTING_EDGE_IN_BBOX
GRAPH_LOAD_FAILED
```

### 7.4 船舶约束过滤

输入船舶参数：

```text
length_m
beam_m
draft_m
deadweight_ton
air_draft_m
loaded_status
```

规则：

- 明确超过 edge 约束时禁用 edge。
- `CLOSED` 生效时禁用 edge。
- 约束缺失不禁用，但生成 `UNKNOWN_CONSTRAINT_DATA` 并扣分。
- `routing_preference_code=AVOID_LOCKS` 时提高过闸成本，不直接禁用。
- 存在未知关键约束时，结果最高 `READY_WITH_WARNING`。
- 前端必须显示“约束数据缺失，未完成通航安全核验”一类提示。
- 允许保存为业务轨迹版本，但 summary_json 必须保留 issue 和 quality warning，不能显示为完全 READY。

失败原因：

```text
VESSEL_CONSTRAINT_BLOCKED
ALL_CANDIDATE_EDGES_FILTERED
```

### 7.5 路径搜索

第一版使用 `networkx`：

- 构建 directed/multidigraph。
- 双向 edge 拆成两个方向。
- 起终点吸附到 edge 时临时拆分 edge。
- 使用 Dijkstra 或 A*。
- edge cost 来自长度、等级、质量、约束、过闸、未知数据惩罚。

成本模型：

```text
edge_cost =
  length_km
  * grade_factor
  * quality_factor
  * confidence_factor
  + lock_penalty
  + bridge_penalty
  + unknown_constraint_penalty
  + manual_review_penalty
```

失败原因：

```text
GRAPH_DISCONNECTED
NO_PATH_FOUND
PATH_SEARCH_FAILED
```

### 7.6 轨迹拼接

步骤：

1. 读取 edge 序列。
2. 判断每条 edge 是否需要反转。
3. 去重相邻连接点。
4. 插入 origin_snap_point 和 destination_snap_point。
5. 合并为完整 LineString。
6. 计算距离、点数、经过 channel/node/lock/bridge。

失败原因：

```text
EDGE_GEOMETRY_MISSING
EDGE_DIRECTION_INVALID
PATH_ASSEMBLY_FAILED
```

### 7.7 水域和边界校验

使用 Shapely：

- route buffer 30m/50m/100m。
- 与 water area union 计算相交比例。
- 与 channel boundary union 计算相交比例。
- 检查断裂、重复点、异常跳点。

建议阈值：

```text
water_intersect_ratio >= 0.95: 通过
0.85-0.95: warning
<0.85: NEED_REVIEW
<0.70: FAILED
```

质量问题：

```text
PATH_OUT_OF_WATER
PATH_OUT_OF_CHANNEL_BOUNDARY
EDGE_NEED_MANUAL_REVIEW
LOW_CONFIDENCE_EDGE
```

### 7.8 质量评分

初始 100 分。

扣分规则：

```text
吸附 200-500m: -5
吸附 500-2000m: -15
LOW_CONFIDENCE edge: 每条 -3
NEED_REVIEW edge: 每条 -5
UNKNOWN_CONSTRAINT edge: 每条 -2
离开水域比例 > 5%: -20
离开航道边界比例 > 10%: -15
graph 断裂: FAILED
船舶约束不满足: FAILED
```

质量等级：

```text
90-100: READY
75-89: READY_WITH_WARNING
60-74: NEED_REVIEW
<60: FAILED
```

### 7.9 落表

成功：

- `navigation_route_request.status_code=SUCCESS`
- `navigation_route_result.status_code=READY/READY_WITH_WARNING/NEED_REVIEW`
- quality issues 落表

失败：

- `navigation_route_request.status_code=FAILED`
- 写 `error_code/error_message`
- 能定位的问题写入 quality issue 或 annotation task。

## 8. Route 轨迹版本接入流程

当前：

```text
WATER -> HIFLEET
ROAD -> AMAP
fallback -> local curve
```

目标：

```text
WATER -> NavigationRoutingEngineService
ROAD -> AMapRouteClient
RAIL -> unsupported
HIFLEET -> explicit reference provider
```

接入规则：

- `provider_code=None/AUTO` 时，WATER 必须走自研引擎。
- `provider_code=HIFLEET` 时只生成 `REFERENCE_HIFLEET`，不设为默认，不自动保存为当前业务轨迹。
- HiFleet reference 不能写入正式 centerline，也不能参与 graph 构建。
- 自研引擎失败时，轨迹版本失败或部分失败，不能 fallback 成曲线。
- 水路 fallback 配置化：生产默认 `ROUTE_WATER_FALLBACK_MODE=disabled`；`local_demo/test` 只允许演示或测试，并必须显式标识。
- 生成版本后 `summary_json` 记录 navigation result 信息。

失败原因对用户展示：

```text
起点附近没有可用航道图网络
终点附近没有可用航道图网络
当前图网络不连通
船舶参数超过通航限制
当前范围尚未发布 graph version
```

## 9. 前端流程

路径生成测试页：

输入：

- 起点。
- 终点。
- 船舶吨级、吃水、船长、船宽、净空。
- 路径偏好。
- graph version。

输出：

- 推荐路线地图。
- 总里程、预计耗时。
- edge_ids、channel_ids。
- 经过船闸/桥梁。
- 质量评分和质量等级。
- 问题列表。
- 保存为业务轨迹版本入口。

失败态：

- 不显示假路线。
- 地图定位到失败区域或吸附点。
- 显示失败原因和建议，例如“需要补中心线/graph”。

## 10. 标注和修正流程

触发来源：

- graph 校验失败。
- route generation 失败。
- 人工在前端发现边界/中心线错误。
- AIS 轨迹发现缺边。

流程：

```text
quality issue
  -> annotation task
  -> 人工/AI 提建议
  -> 新 boundary/centerline/constraint 版本
  -> rebuild graph
  -> validate graph
  -> publish graph version
```

关键规则：

- AI 不能直接发布正式 graph edge。
- 人工修正必须保留历史版本。
- 修复 graph 后不重写历史 route result，只影响新生成路径。
- graph validation 和 route quality issue 可自动生成 annotation task。
- 任务处理结果必须落到新 boundary、centerline、constraint 或 connector 版本。
- 审核通过后才允许 rebuild graph；新 graph version 发布后，旧 graph version 归档或继续保留解释历史路线。
- 标注任务必须记录 reviewer、resolution target 和 source issue，不能只有一张孤立任务表。
