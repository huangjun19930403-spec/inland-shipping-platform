# Navigation Data Audit - Round 1

日期：2026-05-22

本轮只做现状审计和后续落地边界确认，不改业务代码、不改迁移、不改 seed 执行逻辑。审计对象包括 `revier.zip` 水域面数据、当前航道 seed/数据库状态、route 轨迹生成链路，以及 Navigation Routing Engine 缺口。

## 1. 当前仓库状态

- 后端仓库：`/Users/hj/Documents/paltform_data_V2/inland-shipping-platform`
- 当前分支：`refactor/production-delete-rebuild`
- 本轮复核时 `git status --short --branch` 仅显示一个未跟踪数据库备份文件：`inland_shipping.db.backup_before_route_revision_20260522_091625`
- 本轮新增内容只限：
  - `docs/NAVIGATION_DATA_AUDIT.md`
  - `docs/NAVIGATION_ENGINE_DESIGN.md`
  - `data_audit/navigation_channel_match_report.json`

## 2. River Shapefile 数据核验

源文件：`/Users/hj/Documents/河道数据/revier.zip`

读取方式：

- zip 内中文文件名可正常被 Python `zipfile` 读取。
- `.cpg` 标记为 `UTF-8`。
- 项目虚拟环境已安装 `pyshp==2.3.1`。
- 当前虚拟环境未安装 `shapely`、`networkx`、`geopandas`、`fiona`、`pyogrio`。

9 个核心图层核验如下：

| 图层 | 记录数 | 几何类型 | 命名记录 | 无名记录 | multipart 形状 | bbox |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| `rx` | 48,192 | POLYGON | 13,374 | 34,818 | 2,222 | 73.6756,16.0536,135.1060,53.5592 |
| `rx8` | 4,857 | POLYGON | 1,473 | 3,384 | 115 | 73.9016,18.2342,134.9952,49.1756 |
| `一级水系` | 234 | POLYGON | 209 | 25 | 94 | 75.9462,21.5636,135.0652,53.5592 |
| `二级水系` | 285 | POLYGON | 225 | 60 | 133 | 75.0434,22.5378,135.1060,50.7224 |
| `三级水系` | 608 | POLYGON | 529 | 79 | 227 | 75.5002,22.2142,134.1578,53.4586 |
| `四级水系` | 1,407 | POLYGON | 1,144 | 263 | 398 | 74.4042,18.7508,134.7174,49.4040 |
| `五级水系` | 4,541 | POLYGON | 2,598 | 1,943 | 525 | 74.9612,18.2278,134.7528,49.9430 |
| `六级水系` | 5,175 | POLYGON | 2,338 | 2,837 | 280 | 73.6756,18.3882,133.4282,50.3084 |
| `七级水系` | 27,181 | POLYGON | 4,833 | 22,348 | 406 | 74.4042,18.3406,134.8188,53.4954 |

`rx` 字段：

```text
OBJECTID
NAME
REMARK
Shape_Leng
Shape_Area
```

审计结论：

- `revier.zip` 是全国水域面数据，不是航道中心线，也不是可直接路径搜索的 graph。
- `rx` 是第一优先导入层，一级到七级水系可作为分层水域来源。
- `rx8` 有属性字段且可读取，本轮仍按备用层处理，后续导入策略单独确定。
- Shapefile 形状类型显示为 `POLYGON`，但存在大量 multipart 形状；转 GeoJSON 时需要正确表达为 Polygon 或 MultiPolygon。
- 当前依赖只够做 shapefile 读取和基础字段审计；后续要做 make_valid、面积、buffer、intersects、骨架线或 graph，需要补充 geospatial/graph 依赖或迁移到 PostGIS 流程。

## 3. 当前航道 seed 与数据库状态

当前航道 seed 文件：

```text
scripts/seed_data/navigation/navigation_channels.json
```

当前 seed 版本：

```text
revier_navigation_channel_v7
```

当前 SQLite 数据库表数量：

| 表 | 数量 |
| --- | ---: |
| `navigation_channel` | 104 |
| `navigation_channel_boundary` | 104 |
| `navigation_channel_segment` | 200 |
| `navigation_channel_source_audit` | 294 |
| `transport_node` | 1,181 |
| `navigation_constraint_point` | 3 |
| `shipping_route_plan_track_version` | 0 |
| `shipping_route_plan_segment_result` | 0 |

当前已有 navigation 表：

```text
navigation_channel
navigation_channel_boundary
navigation_channel_segment
navigation_channel_source_audit
navigation_constraint_point
navigation_constraint_profile
```

当前还没有：

```text
navigation_water_area
navigation_channel_centerline
navigation_graph_version
navigation_graph_node
navigation_graph_edge
navigation_graph_edge_constraint
navigation_route_request
navigation_route_result
navigation_route_quality_issue
navigation_annotation_task
```

这说明当前系统已有“航道目录/边界/分段/来源审计”和“点状通航约束”，但还没有“水域原始面、中心线、图网络、路径请求结果、质量问题”的自研路径生成核心数据层。

## 4. 当前边界状态

边界状态汇总：

| geometry_status_code | boundary_quality_code | repair_status_code | 数量 |
| --- | --- | --- | ---: |
| AVAILABLE | HIGH_CONFIDENCE | NONE | 84 |
| MISSING | MISSING | MISSING | 9 |
| AVAILABLE | REVIEW | REVIEW_FALLBACK | 8 |
| AVAILABLE | MEDIUM_CONFIDENCE | NONE | 2 |
| AVAILABLE | REVIEW | REVIEW_CORRIDOR | 1 |

缺边界航道：

| channel_code | channel_name | planning_level_code |
| --- | --- | --- |
| `NC-JIANGHAN-CANAL` | 江汉运河 | PLANNED_GAP |
| `NC-SHAYING-RIVER` | 沙颍河航道 | PLANNED_GAP |
| `NC-SUNAN-CANAL` | 苏南运河 | PLANNED_GAP |
| `NC-SUBEI-CANAL` | 苏北运河 | PLANNED_GAP |
| `NC-SUSHEN-INNER-PORT-LINE` | 苏申内港线 | PLANNED_GAP |
| `NC-XUSULIAN-CORRIDOR` | 徐宿连通道 | PLANNED_GAP |
| `NC-ZHAJIAGOU` | 赵家沟 | PLANNED_GAP |
| `NC-DALU-LINE` | 大芦线 | PLANNED_GAP |
| `NC-DAPU-LINE` | 大浦线 | PLANNED_GAP |

待复核或边界质量为 REVIEW 的重点航道：

```text
京杭运河
长三角高等级航道网
江汉运河
合裕线
沙颍河航道
苏南运河
苏北运河
苏申内港线
徐宿连通道
赵家沟
大芦线
大浦线
杭湖锡线
连申线
芜申线—苏申外港线
长湖申线—黄浦江—大浦线
淮河出海航道—盐河
湖嘉申线
苏申外港线—苏申内港线
```

第一阶段江苏/长三角 MVP 中，长江、盐河、通扬线、锡澄运河、丹金溧漕河、杭甬运河、黄浦江、钱塘江已有高可信边界；京杭运河、连申线、芜申线、长湖申线、苏申外港线、淮河出海航道等有边界但需要复核；苏申内港线、赵家沟、大芦线、大浦线缺少独立边界。

## 5. 当前 route 轨迹生成链路

现有模型能力：

- `app/models/route.py` 已有业务航线、方案、点、段、段结果、轨迹版本、轨迹版本分段。
- `shipping_route_plan_track_version.summary_json` 可作为后续记录 `navigation_route_result_id`、`graph_version_id`、`quality_score`、`edge_ids` 的扩展入口。

现有服务链路：

- `route.generate_track_version` Celery 任务调用 `ShippingRoutePlanStructureService.generate_track_version()`。
- `ShippingRoutePlanStructureService._geometry_client_for_segment()` 当前选择：
  - `WATER -> HIFLEET`
  - `ROAD -> AMAP`
  - `RAIL -> 暂不支持`
- `TRACK_VERSION_SOURCES` 当前只有：

```text
AMAP
HIFLEET
MANUAL
FALLBACK
```

- `_call_geometry_provider()` 在外部服务超时或网络异常时可能生成本地 fallback LineString，并标记 `source="fallback"`。

审计结论：

- 当前系统是“业务航线点位 -> 外部 provider -> 轨迹版本”。
- 当前没有 `NavigationRoutingEngineService`。
- 当前没有基于 graph edge 的路径搜索。
- 当前 fallback 曲线可以保障编辑体验，但不能作为生产级自研水路路径结果。

## 6. 当前已有能力与缺口

已有能力：

- 航道目录、边界、分段、来源审计。
- AIS 航道归属依赖当前航道边界。
- 运输节点与通航约束点。
- 业务航线轨迹版本管理。
- 异步轨迹生成任务。
- 前端已有“航道基础数据”列表和边界预览。
- 前端已有轨迹版本编辑器。

关键缺口：

- 缺少 `navigation_water_area` 原始水域层。
- 缺少航道中心线层。
- 缺少 graph version/node/edge。
- 缺少边约束。
- 缺少路径请求、路径结果、质量问题落表。
- 缺少起终点吸附、约束过滤、路径搜索、轨迹拼接、边界校验、质量评分。
- 缺少路径生成测试 API 和前端页面。
- 缺少人工标注与 AI 修正闭环。

## 7. 第一轮验收结论

本轮要求均已覆盖到交付物中：

- 已记录 `revier.zip` 的 9 个核心图层。
- 已记录 `rx` 记录数、bbox、字段、命名数量。
- 已记录当前数据库航道数量、缺边界航道清单、待复核航道清单。
- 已指出当前 `ShippingRoutePlanStructureService.generate_track_version()` 调用外部 provider，`WATER -> HIFLEET`、`ROAD -> AMAP`。
- 已明确生产级自研 Navigation Routing Engine 尚不存在。
- 本轮未新增 API、未新增模型、未改表结构、未改 seed 执行逻辑。
