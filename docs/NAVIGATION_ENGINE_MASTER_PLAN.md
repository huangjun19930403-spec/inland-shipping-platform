# Navigation Routing Engine Master Plan

日期：2026-05-22

本文是 Navigation Routing Engine 大工程的总入口。它不是一轮代码实现指令，而是后续多轮开发共同遵守的工程蓝图：明确为什么做、做成什么、当前有什么、缺什么、采用什么依赖和架构、哪些资产不能互相覆盖，以及每一类模块之间如何协作。

## 1. 总目标

平台最终要形成自有内河航道路径生成能力：

```text
river 原始水域面
  -> 航道目录
  -> 业务航道边界
  -> 航道中心线
  -> graph node / edge
  -> 通航约束
  -> A-B 路径搜索
  -> 质量校验
  -> 人工标注和 AI 辅助修正
  -> 图网络版本发布
  -> route 业务轨迹版本
```

系统定位：

- 用于业务级路径规划、运距估算、货源线路分析、航道数据生产和内部调度辅助。
- 不作为船舶安全航行的官方导航依据。
- 不依赖 HiFleet 作为默认水路生成源；HiFleet 后续只能作为显式 reference provider 或质量对比来源。
- `READY` 只代表当前业务 graph 和几何结果可用，不代表官方通航安全确认、实时水深、桥梁净空、禁航限航已完整核验。

## 2. 当前现状

现有基础：

- `navigation_channel`、`navigation_channel_boundary`、`navigation_channel_segment`、`navigation_channel_source_audit` 已存在。
- 当前 seed 包含 104 个航道对象、104 条边界记录，其中 95 条可用边界、9 条缺边界。
- `TransportNode` 和 `NavigationConstraintPoint/Profile` 已存在，可承接码头、船闸、桥梁、限高、吃水等点状约束。
- `ShippingRoutePlanTrackVersion` 已存在，可保存业务航线轨迹版本。
- `route.generate_track_version` 已存在异步任务入口。
- 前端已有航道基础数据页面和轨迹版本编辑器。

关键缺口：

- 没有 `navigation_water_area` 原始水域面资产。
- 没有航道中心线表。
- 没有 graph version/node/edge。
- 没有边级通航约束。
- 没有路径请求、路径结果、质量问题落表。
- 没有起终点吸附、路径搜索、轨迹拼接、水域/边界校验、质量评分。
- 当前 `WATER` 默认走 HiFleet，失败时可能走 fallback 曲线；这不能作为生产级自研水路能力。
- 当前没有可直接生成真实生产 graph 的 approved/current centerline；中心线是第一阶段最大数据风险点。

## 3. 核心资产边界

必须严格区分三类资产：

| 资产 | 表/来源 | 定位 | 能否覆盖其他资产 |
| --- | --- | --- | --- |
| 原始水域面 | `navigation_water_area` / `revier.zip` | 全国水域底图、水域校验、候选边界来源 | 不能覆盖 seed boundary |
| 业务航道边界 | `navigation_channel_boundary` / seed/匹配/人工 | 业务航道包络、地图展示、中心线约束、质量校验 | 不能当 graph edge |
| 可搜索图网络 | `navigation_graph_node/edge` | 路径搜索唯一对象 | 由中心线发布生成 |

关键规则：

- `river` 全量导入只进入 `navigation_water_area`，不直接改写现有 `navigation_channel_boundary`。
- seed boundary 是当前业务航道包络资产，继续保留并参与中心线约束和质量校验。
- 边界不是路径搜索对象；路径搜索只能基于 graph edge。
- 没有 graph 的区域必须返回可解释失败，不允许画直线或 fallback 曲线冒充真实水路。
- 无 approved/current centerline 的航道不得进入 graph；polygon、water area、boundary 都不能被临时转换成路径结果。

## 3.1 中心线主源和发布边界

江苏/长三角真实生产第一阶段中心线主源：

```text
MANUAL / SEED_CENTERLINE 为主
已审核 OSM_WATERWAY 为补充
AIS_INFERRED 作为第二阶段增强
WATER_SKELETON / HIFLEET_REFERENCE 不得自动发布
```

发布规则：

- 只有 `review_status_code=APPROVED` 且 `is_current=True` 的中心线可以进入 graph。
- OSM 无名称线、跨多个航道候选线、仅空间命中的候选线默认 `NEED_REVIEW`。
- `HIFLEET_REFERENCE` 只能作为对比和人工参考，不能写成正式中心线，不能参与 graph 构建。
- 详细阈值和 graph 构建规则见 `docs/NAVIGATION_ENGINE_CENTERLINE_AND_GRAPH_RULES.md`。

## 4. 系统分层

### 4.1 数据资产层

负责存储可追溯资产：

- 原始水域面：`navigation_water_area`
- 航道目录和边界：现有 `navigation_channel*`
- 中心线候选和发布线：`navigation_channel_centerline`
- 图网络版本：`navigation_graph_version`
- 图节点和图边：`navigation_graph_node`、`navigation_graph_edge`
- 边级约束：`navigation_graph_edge_constraint`
- 路径请求、结果和问题：`navigation_route_request/result/quality_issue`
- 人工标注闭环：`navigation_annotation_task`

### 4.2 数据生产层

负责把外部/人工/历史数据变成可搜索图：

- river shapefile 导入。
- seed boundary 和 river water area 匹配。
- OSM/HydroRIVERS/AIS/人工中心线导入。
- 中心线审批发布。
- 图网络构建。
- 图网络质量校验。
- 图版本发布。

### 4.3 路径引擎层

负责 A/B 点生成路径：

- 起终点解析和吸附。
- 图版本选择和 bbox 图加载。
- 船舶参数约束过滤。
- `networkx` 最短路搜索。
- edge 序列轨迹拼接。
- Shapely 水域/边界校验。
- 质量评分和问题生成。
- 路径请求和结果落表。

### 4.4 业务接入层

负责接入现有 route 模块：

- `WATER -> NavigationRoutingEngineService`
- `ROAD -> AMapRouteClient`
- `RAIL -> 暂不支持`
- `HIFLEET -> explicit reference provider`
- `provider_code=AUTO` 时，WATER 必须走自研引擎。
- `provider_code=HIFLEET` 时只能生成 `REFERENCE_HIFLEET` 参考结果，不能自动设为当前业务轨迹。
- 生产默认 `ROUTE_WATER_FALLBACK_MODE=disabled`；`local_demo/test` 只能用于演示或测试，并必须在结果中显式标识。

轨迹版本必须记录自研引擎产出的 graph 和质量信息：

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

### 4.5 前端生产工具层

第一阶段前端至少提供：

- 水域面图层。
- 航道边界图层。
- 中心线图层。
- graph node/edge 图层。
- 路径生成测试页。
- 质量问题列表。
- 标注任务入口。

长期生产工具还需要补齐：

- 中心线编辑和审核。
- 断点连接和码头接入。
- graph edge 查看和质量问题定位。
- 标注任务处理。
- graph version 对比和回滚查看。

## 5. 依赖选择

后续实现轮必须补齐 geospatial 和 graph 依赖，不把 SQLite 当成功能降级理由。

| 依赖 | 用途 |
| --- | --- |
| `pyshp` | 读取 Shapefile，当前已存在 |
| `shapely` | make_valid、buffer、intersection、snap、distance、GeoJSON geometry 处理 |
| `pyproj` | WGS84 与米制投影转换，支撑距离、面积、buffer 计算 |
| `networkx` | 第一版内存图构建和最短路搜索 |
| PostGIS/pgRouting | 后续全国级规模化演进，不阻塞第一版完整模块 |

第一版策略：

- 持久化仍用当前数据库体系。
- 几何计算在应用层用 Shapely/pyproj 完成。
- 图搜索用 `networkx`。
- 后续当图规模、空间查询性能或并发压力上来，再迁移核心空间查询到 PostGIS/pgRouting。

## 6. 江苏/长三角真实生产第一阶段范围

第一阶段优先覆盖业务高频区域，不一开始做全国。默认数据源必须是真实 `revier.zip` 水域资产，以及当前清洗 seed 航道、边界、运输节点和约束点；历史 MVP/示例数据只能保留在 `tests/fixtures` 作为测试 fixture，不得写入本地演示库、页面默认值、生产 seed 或 active graph。

优先航道：

```text
长江江苏段
京杭运河江苏段
盐河 / 淮河出海航道
通扬线
芜申线
长湖申线
连申线
苏申外港线
苏申内港线
锡澄运河
丹金溧漕河
杭甬运河
黄浦江
钱塘江
太湖周边航道
```

第一阶段真实业务验收路线：

```text
靖江 -> 苏州
靖江 -> 无锡
苏州 -> 扬州
无锡 -> 常州
京杭运河江苏段任意两点
长江江苏段 -> 苏南内河码头
```

验收标准：

- 不允许直线 fallback 冒充真实路线。
- 必须返回 edge_ids 和 channel_ids。
- 必须返回 graph_version_id。
- 必须返回质量评分和问题列表。
- 图断裂、无 graph、吸附过远、约束阻断必须解释原因。
- 可保存为 `ShippingRoutePlanTrackVersion`。
- 在真实中心线发布前，graph build 和路径生成应明确失败并暴露 `NO_APPROVED_CENTERLINE` / `NO_ACTIVE_GRAPH_VERSION` 等原因，不能用测试 fixture 或 polygon 补线。

## 7. 数据质量策略

质量状态不能靠口头判断，必须落表或进入报告。

关键状态：

- `READY`：可生产使用。
- `READY_WITH_WARNING`：可用但有提示。
- `NEED_REVIEW`：需要人工复核。
- `FAILED`：不可用。
- `MISSING`：缺数据。
- `BROKEN`：断裂或拓扑问题。
- `LOW_CONFIDENCE`：候选质量低。

质量问题必须可定位：

- 起终点吸附过远。
- 起点/终点附近无 graph。
- graph 不连通。
- 航段离开水域。
- 航段离开航道边界。
- edge 低置信度。
- edge 缺少约束数据。
- 船舶参数超过约束。
- 经过待复核 edge。

约束缺失产品规则：

- 约束缺失允许生成路径，但必须产生 `UNKNOWN_CONSTRAINT_DATA`。
- 缺失约束需要扣分，并在前端显示“未完成通航安全核验”。
- 存在未知关键约束的路线最高为 `READY_WITH_WARNING`。
- 命中 blocking 约束时必须失败或绕行，不能静默忽略。

## 8. 文档地图

后续开发优先阅读顺序：

1. `docs/NAVIGATION_ENGINE_MASTER_PLAN.md`：总目标和架构。
2. `docs/NAVIGATION_ENGINE_DATABASE_DESIGN.md`：表结构和关系。
3. `docs/NAVIGATION_ENGINE_FLOW_DESIGN.md`：数据生产和路径生成流程。
4. `docs/NAVIGATION_ENGINE_CENTERLINE_AND_GRAPH_RULES.md`：中心线和 graph 构建硬规则。
5. `docs/NAVIGATION_ENGINE_TEST_FIXTURES.md`：测试 fixture 规范。
6. `docs/NAVIGATION_ENGINE_PERFORMANCE_RULES.md`：SQLite/Shapely/NetworkX 性能边界。
7. `docs/NAVIGATION_ENGINE_ROUND_PLAN.md`：逐轮执行计划。
8. `docs/NAVIGATION_ENGINE_EXECUTION_RECEIPT_TEMPLATE.md`：每轮执行回执。
9. `docs/NAVIGATION_DATA_AUDIT.md`：当前数据审计事实。
10. `docs/NAVIGATION_ENGINE_DESIGN.md`：Round 1 baseline 和历史设计上下文。

## 9. 非目标

第一阶段不做：

- 官方电子航道图替代。
- 实时禁航/限航自动同步。
- 全国全量高精度路径覆盖。
- 城市到城市直接生成水路，不落到码头/节点。
- 无 graph 时用几何曲线冒充路线。
- AI 直接发布正式 graph edge。
- 将 HiFleet 换壳为默认主链。
- 将 `READY` 宣称为官方通航安全结论。

## 10. 最终判断

这个工程的核心不是“优化 HiFleet 接口”，而是生产可版本化、可校验、可人工修正、可解释的内河航道图网络。只有当 centerline、graph edge、约束、质量和版本闭环建立后，route 模块才能真正从外部 provider 驱动切换为自研 Navigation Routing Engine 驱动。
