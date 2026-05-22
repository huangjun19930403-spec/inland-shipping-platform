# Navigation Routing Engine Round Plan

日期：2026-05-22

本文把 Navigation Routing Engine 拆成可执行开发轮次。每轮都有目标、改动范围、禁止事项和验收标准，避免一次性大改跑偏。

## Round 1：现状审计，已完成

目标：

- 审计 `revier.zip`、当前航道 seed、数据库状态和 route 轨迹生成链路。

产出：

- `docs/NAVIGATION_DATA_AUDIT.md`
- `docs/NAVIGATION_ENGINE_DESIGN.md`
- `data_audit/navigation_channel_match_report.json`

禁止：

- 不改业务代码。
- 不改迁移。
- 不导入数据。

验收：

- 记录 9 个 river 图层。
- 记录当前 104 条航道、95 条可用边界、缺边界和待复核清单。
- 明确当前 WATER 默认走 HiFleet，自研引擎不存在。

## Round 2：总体执行文档，本轮

目标：

- 形成完整模块执行蓝图，供后续所有轮次参考。

改动范围：

- 新增 master plan、database design、flow design、round plan。
- 更新旧 design 文档指向新文档包。

禁止：

- 不改代码。
- 不改 migration。
- 不装依赖。
- 不导入数据。

验收：

- 架构、表结构、流程、API、前端、测试、轮次边界完整。
- 明确 `shapely/networkx/pyproj` 是实现轮必须补齐的能力。
- 明确 river 和 seed boundary 资产边界。

## Round 2B：文档硬化和执行护栏

目标：

- 把中心线来源、graph 构建阈值、MVP 验收、测试 fixture、性能边界、执行回执和 agent 护栏写死。

改动范围：

- 新增中心线和 graph 规则文档。
- 新增 MVP acceptance、test fixtures、performance rules、execution receipt template。
- 新增根目录 `AGENTS.md`。
- 更新 master、database、flow、round 文档。

禁止：

- 不改 Python/TypeScript 代码。
- 不改 requirements。
- 不生成 migration。
- 不导入数据。
- 不改 seed。

验收：

- 15 个风险点都有对应章节。
- `AGENTS.md` 位于仓库根目录。
- 后续每轮都有执行回执模板可用。

## Round 3：依赖、新表模型和 fixture 骨架

目标：

- 建立 Navigation Engine 的数据库模型骨架。

改动范围：

- `requirements.txt` 增加 `shapely`、`networkx`、`pyproj`。
- 新增 `app/models/navigation.py`。
- 新增 water area、centerline、graph、route result、quality issue、annotation task 模型。
- 更新 `app/models/__init__.py`。
- 新增 Alembic migration。
- 增加模型创建测试。
- 新增 `tests/fixtures/navigation/` 最小 fixture 目录和说明文件。

禁止：

- 不导入 `revier.zip`。
- 不接入 route 生成。
- 不改前端。
- 不删除 HiFleet。
- 不迁移旧 `NavigationChannel*` 类位置。

验收：

- 空库 migration 可执行。
- `Base.metadata.create_all` 测试通过。
- 现有 `/address/navigation-channels/*` 测试不破。
- 新模型字段覆盖 database design 文档的关键字段。
- fixture 文件命名符合 `NAVIGATION_ENGINE_TEST_FIXTURES.md`。

## Round 4：River 原始水域导入

目标：

- 将 `revier.zip` 导入 `navigation_water_area`，形成原始水域资产。

改动范围：

- 新增 `scripts/navigation/import_river_shapefile.py`。
- 支持 `rx/rx8/一级~七级水系`。
- 使用 `pyshp + shapely + pyproj`。
- 支持 make_valid、bbox、center、area、简化 geometry、导入报告。
- 增加小 fixture 测试，不在测试里导入 48,192 条真实数据。

禁止：

- 不覆盖 `navigation_channel_boundary`。
- 不生成 graph。
- 不接入路径生成。

验收：

- 小 fixture 可导入并幂等 upsert。
- 真实 `revier.zip` dry-run 能输出预计导入统计。
- `rx` 全量导入命令可运行并生成 summary。

## Round 5：航道目录、边界匹配和候选报告

目标：

- 将 river 原始水域与现有航道目录建立可追溯匹配关系。

改动范围：

- 新增别名配置和 MVP 航道范围配置。
- 新增 `scripts/navigation/build_channel_boundaries.py`。
- 生成 `match_report_json`。
- 对无 seed boundary 的航道可生成候选 boundary，但默认 `NEED_REVIEW`。

禁止：

- 不自动覆盖 current seed boundary。
- 不把规划航道名称匹配失败的对象强行标成 READY。
- 不生成 graph。

验收：

- 长江、京杭运河、黄浦江、钱塘江等能生成匹配报告。
- 连申线、苏申内港线、赵家沟等匹配不足时明确 `NEED_REVIEW/MISSING`。
- 前端现有航道基础数据不受影响。

## Round 6：中心线导入和审核

目标：

- 建立中心线资产，为 graph 构建做准备。

改动范围：

- 新增 `scripts/navigation/import_centerlines_geojson.py`。
- 支持人工、OSM、AIS、HydroRIVERS、骨架候选来源类型。
- 低置信度中心线默认 `NEED_REVIEW`。
- 增加中心线列表/查询 API 或最小内部服务，供 graph 构建使用。

禁止：

- 不把 HiFleet reference 直接发布为正式中心线。
- 不让未审核中心线进入生产 graph。
- 不接入 route 生成。

验收：

- fixture 中心线能入库。
- approved/current 中心线可被查询。
- OUT_OF_BOUNDARY、BROKEN、DUPLICATED 可被标记。
- 无 approved/current centerline 的 channel 不会进入 graph。

## Round 7：Graph 构建和校验

目标：

- 从 approved/current centerline 生成可搜索 graph version/node/edge。

改动范围：

- 新增 `scripts/navigation/build_graph_from_centerline.py`。
- 新增 `scripts/navigation/validate_navigation_graph.py`。
- 生成 graph version、node、edge、edge constraint。
- 使用 Shapely 切分、snap、校验水域/边界覆盖。
- 输出 graph quality report 和 annotation task candidates。

禁止：

- 不接入 route 业务轨迹。
- 不发布质量不达标的 graph。
- 不覆盖历史 graph version。

验收：

- fixture graph 构建稳定。
- graph version 记录 node_count、edge_count、quality_score。
- 断裂、孤立、离开边界等问题可报告。
- 近距交汇、不可通航交叉、码头 SNAP_CONNECTOR、短边合并、方向规则均有测试覆盖。

## Round 8：Routing Engine API

目标：

- 提供自研路径生成 API。

改动范围：

- 新增 `app/modules/navigation/engine/*`。
- 新增 `NavigationRoutingEngineService`。
- 新增 `POST /api/v1/navigation/routes/generate`。
- 实现吸附、bbox 图加载、约束过滤、`networkx` 搜索、轨迹拼接、质量评分和落表。

禁止：

- 不接入 `ShippingRoutePlanStructureService` 默认生成。
- 不做前端完整生产工具。
- 不使用 fallback 曲线。

验收：

- 成功路径返回 geometry、edge_ids、channel_ids、quality。
- 无 graph、吸附过远、graph 不连通、约束阻断都有明确错误。
- route request/result/issue 正确落表。

## Round 8B：Route service 拆分

目标：

- 在接入 Navigation Engine 前，拆分当前过大的 `app/modules/route/service.py`，避免继续膨胀。

改动范围：

- 拆出 route CRUD、plan、structure、track generate、track version 等服务。
- 保持现有行为和 API 不变。
- 增加回归测试或 focused smoke。

禁止：

- 不在拆分轮改变 WATER provider 默认行为。
- 不删除 HiFleet。
- 不引入 Navigation Engine 主链。

验收：

- 现有 route 轨迹版本生成行为不变。
- 服务职责清晰，Round 9 可只在 track generate 层接入 Navigation Engine。

## Round 9：Route 模块接入

目标：

- 将业务航线 WATER 段默认切到自研 Navigation Engine。

改动范围：

- `TRACK_VERSION_SOURCES` 增加 `NAVIGATION_ENGINE`。
- `WATER -> NavigationRoutingEngineService`。
- `ROAD -> AMapRouteClient`。
- `HIFLEET` 作为显式 reference provider。
- `summary_json` 写入 navigation route result 和 graph 信息。
- 增加 `ROUTE_WATER_FALLBACK_MODE=disabled/local_demo/test` 配置。

禁止：

- 不删除 HiFleet client。
- 不让自研失败时生成水路 fallback 假路线。
- 不破坏人工修线和保存当前版本流程。
- 不把 `REFERENCE_HIFLEET` 自动设为当前业务轨迹。
- 不把 HiFleet reference 写成正式 centerline。

验收：

- WATER 默认不调用 HiFleet。
- 无 graph 时轨迹版本失败并解释原因。
- 成功时 TrackVersion 保存自研路线和质量 summary。

## Round 10：前端路径生成测试和图层展示

目标：

- 提供可用的路径生成测试界面和基础图层展示。

改动范围：

- 新增 API 类型。
- 新增路径生成测试页。
- 地图展示 water area、boundary、centerline、graph edge、route result、quality issue。
- 失败原因可视化。

禁止：

- 不做复杂 GIS 编辑器。
- 不做全国全量图层一次性加载。
- 不隐藏质量问题。

验收：

- 用户可输入 A/B 点和船舶参数生成路线。
- 成功显示路线、里程、经过航道、质量问题。
- 失败显示原因，不画假路线。

后续前端生产工具增强：

- 中心线编辑和审核。
- 断点连接。
- 码头接入。
- graph edge 查看。
- 质量问题定位。
- 标注任务处理。
- 版本对比。

## Round 11：标注任务和 AI 辅助闭环

目标：

- 将路径失败和 graph 质量问题转为可处理任务。

改动范围：

- 新增 annotation task 服务和 API。
- 支持从 graph validation 和 route quality issue 创建任务。
- AI 只生成建议，不直接发布正式 graph。
- 人工处理后生成新 boundary/centerline/constraint 版本。

禁止：

- 不让 AI 直接写 ACTIVE graph edge。
- 不覆盖历史版本。

验收：

- 缺边、断点、低置信度中心线能生成任务。
- 任务处理结果可追溯到新版本数据。

## Round 12：MVP 数据补齐和业务验收

目标：

- 用江苏/长三角 MVP 数据跑通业务路线。

改动范围：

- 导入 MVP river、水域、中心线、graph。
- 发布首个 MVP graph version。
- 跑通验收路线。
- 标定 `NAVIGATION_ENGINE_MVP_ACCEPTANCE.md` 中每条路线的里程范围和预期航道。
- 输出质量报告和待补清单。

禁止：

- 不以全国覆盖为验收条件。
- 不把 NEED_REVIEW 路线标成 READY。

验收路线：

```text
靖江 -> 苏州
靖江 -> 无锡
苏州 -> 扬州
无锡 -> 常州
京杭运河江苏段任意两点
长江江苏段 -> 苏南内河码头
```

验收标准：

- 返回真实 graph 路线。
- 返回 edge_ids/channel_ids。
- 返回 graph_version_id。
- 返回质量评分和问题。
- 可保存为业务轨迹版本。
- 未标定里程范围前，不能只以“返回路线”作为通过。

## Round 13：规模化和 PostGIS 演进

目标：

- 当 SQLite + Shapely + NetworkX 无法支撑规模时演进到 PostGIS/pgRouting。

改动范围：

- 评估空间查询热点。
- 引入 PostGIS geometry 字段或并行空间索引表。
- 将 bbox/intersects/dwithin/path search 分阶段迁移。

禁止：

- 不在 MVP 之前强行引入生产级数据库复杂度。
- 不破坏已有 JSON geometry 兼容。

验收：

- 查询性能、构图性能、路径生成延迟有量化对比。
- 历史 graph version 和 route result 可兼容迁移。
