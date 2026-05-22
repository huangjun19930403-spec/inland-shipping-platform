# Navigation Engine Performance Rules

日期：2026-05-22

本文定义 SQLite + JSON geometry + Shapely + NetworkX 第一版的性能边界。SQLite 是当前本地持久化方案，不等于功能降级；但所有空间和图计算必须有 bbox、数量上限和可观测报告，不能无界全量扫描。

## 1. 总原则

- 持久化使用 JSON geometry，但必须保留 bbox 数值字段。
- 路径生成必须按 bbox 加载 graph edge，不得全国 graph 一次性进入 NetworkX。
- 水域/边界校验必须按 route bbox 外扩筛选 polygon。
- union、buffer、intersection 必须基于候选集合，不得每次全量 union。
- 配置项必须允许调整 bbox 外扩、NetworkX edge 上限、polygon union 上限和重试次数。
- PostGIS/pgRouting 是后续规模化演进，不阻塞第一版完整模块。

## 2. Bbox 查询规则

所有几何资产必须具备：

```text
bbox_min_lng
bbox_min_lat
bbox_max_lng
bbox_max_lat
center_lng
center_lat
```

SQLite 查询候选时使用 bbox 数值字段：

```text
bbox_max_lng >= query_min_lng
bbox_min_lng <= query_max_lng
bbox_max_lat >= query_min_lat
bbox_min_lat <= query_max_lat
```

需要候选表：

- `navigation_water_area`
- `navigation_channel_boundary`
- `navigation_channel_centerline`
- `navigation_graph_edge`

如果某表缺 bbox 字段，实现轮必须先补字段或生成旁路索引表，不能直接扫描所有 JSON。

## 3. Graph 加载上限

建议配置：

```text
NAV_GRAPH_BBOX_EXPAND_KM_INITIAL=30
NAV_GRAPH_BBOX_EXPAND_KM_RETRY=75
NAV_GRAPH_BBOX_EXPAND_KM_MAX=150
NAV_GRAPH_MAX_EDGES_PER_REQUEST=50000
NAV_GRAPH_MAX_NODES_PER_REQUEST=60000
NAV_GRAPH_ALLOW_SECOND_EXPANSION=true
```

加载策略：

1. 用 A/B 点构造 bbox。
2. 外扩 initial km。
3. 查询 active graph version 内 enabled edge。
4. 如果 edge 数量为 0，返回 `NO_ROUTING_EDGE_IN_BBOX` 或按策略扩大一次。
5. 如果 edge 数量超过上限，返回 `GRAPH_LOAD_TOO_LARGE`，要求缩小范围或走后续规模化方案。

禁止：

- 每次路径生成加载全国 graph。
- edge 超上限时静默继续。
- 因 bbox 太小搜索失败后直接画 fallback。

## 4. Polygon 校验上限

建议配置：

```text
NAV_VALIDATION_BBOX_EXPAND_M=500
NAV_VALIDATION_MAX_WATER_POLYGONS=2000
NAV_VALIDATION_MAX_BOUNDARY_POLYGONS=1000
NAV_VALIDATION_ROUTE_BUFFER_M=50
NAV_VALIDATION_UNION_CACHE_ENABLED=true
```

校验策略：

1. 计算 route bbox。
2. bbox 按米制外扩后转 WGS84。
3. 查询候选 water area 和 channel boundary。
4. 只对候选集合做 Shapely union/intersection。
5. 候选 polygon 超上限时，优先按 bbox 距离、面积、channel_id、source priority 缩小集合；仍超上限则返回 `VALIDATION_CANDIDATE_TOO_LARGE`。

## 5. Union Cache 规则

常用区域可以缓存 union geometry，但 cache 必须带版本键：

```text
cache_key =
  scope_code
  graph_version_id
  water_area_source_code
  boundary_source_version
  bbox_tile_id
  simplify_level
```

cache 失效条件：

- graph version 更新。
- water area source_code 更新。
- boundary current version 更新。
- simplify 或 buffer 参数变化。

禁止使用无版本 cache，因为它会让历史路线和当前校验结果无法解释。

## 6. NetworkX 使用边界

第一版使用 `networkx` 做内存图搜索，但必须遵守：

- 只构造本次 bbox 内子图。
- edge cost 预先计算或快速计算。
- bidirectional edge 可以拆成两个 directed edge，但要计入数量上限。
- 临时 snap node 只存在于本次请求内，不写入 graph version。
- 搜索失败必须返回结构化错误，不得退回 polygon 画线。

性能日志至少记录：

```text
graph_version_id
query_bbox
loaded_node_count
loaded_edge_count
water_polygon_count
boundary_polygon_count
graph_load_ms
path_search_ms
validation_ms
total_ms
```

## 7. SQLite 到 PostGIS 的演进触发条件

任一条件持续出现时，进入 PostGIS/pgRouting 评估：

- MVP 区域 bbox 查询经常超过 edge 上限。
- 单次 graph load 或 Shapely validation 超过业务可接受延迟。
- union cache 命中率低且 CPU 开销高。
- 全国或跨省路径成为常规需求。
- 并发路径请求导致 SQLite 锁或 CPU 瓶颈。

演进要求：

- 保留 JSON geometry 兼容历史数据。
- 历史 graph version 和 route result 可解释。
- 分阶段迁移空间查询、graph search，不一次性重写业务模块。
