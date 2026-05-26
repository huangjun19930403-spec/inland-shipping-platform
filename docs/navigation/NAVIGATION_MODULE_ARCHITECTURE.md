# 航道图与路径模块架构说明

## 生产链路

航道图生产按“保存草稿 -> 发布前校验 -> 操作员确认发布”运行，不接审批、不创建 approval task。完整链路是：

```text
水系规划 -> 边界候选与修复 -> 中心线区段修复 -> Graph 构建 -> 路径验证
```

边界、中心线、Graph 和路径的关系如下：

1. 航道先完成水体归属，归属水体作为边界生产参考。
2. `boundary_candidate_service.py` 基于已归属水体生成边界候选，操作员载入候选并修复草稿。
3. `boundary_draft_ops_service.py` 负责删除/保留分面、补画、裁剪、清理、简化等边界草稿修复操作。
4. 边界草稿通过 `geometry_draft_service.py` 发布为当前边界。
5. 当前边界发布后，中心线生产进入区段工作台。系统先生成中心线区段，操作员逐段修复、保存、确认。
6. 所有必要区段确认后，区段发布器合并生成正式 current centerline。
7. Graph 构建读取已发布 current centerline，由 `graph_build_service.py` 生成 GraphVersion、GraphNode、GraphEdge 和边约束。
8. 路径规划 V2 只读取 READY/active Graph，负责吸附、约束搜索、备选路径、成本解释和失败解释。

## 服务职责

- `NavigationWorkbenchService`：工作台 Facade，保留摘要、列表、水体归属和共享几何辅助方法，不承载边界候选生成或中心线区段生产。
- `boundary_candidate_service.py`：多策略边界候选生成，记录候选来源、点数、面积和质量信息。
- `boundary_draft_ops_service.py`：边界草稿 GIS 修复操作，执行后重新校验草稿。
- `geometry_draft_service.py`：几何草稿 CRUD、归档、发布事务和发布后正式资产写入。
- `geometry_validation_service.py`：草稿校验入口和发布前校验入口。
- `snap_reference_service.py`：中心线编辑吸附参考点收集。
- `centerline_segments/generator.py`：中心线区段生成，优先拆分已有中心线；无中心线时基于当前边界粗生成候选区段。
- `centerline_segments/validator.py`：区段 LineString、长度、边界约束、端点连接、急转弯等质量校验。
- `centerline_segments/publisher.py`：已确认区段的端点检查、合并和正式中心线发布。
- `centerline_segments/service.py`：对 router 暴露的区段 Facade，负责列表、更新、确认和组合调用。
- `graph_workbench_service.py`：Graph 构建和激活的工作台入口。
- `graph_build_service.py`：从已发布中心线构建 Graph 的核心逻辑。
- `graph_validation_service.py`：Graph 拓扑和质量校验。

## 发布不是审批

航道图生产中的“发布”是操作员确认后的生产状态切换，不是审批中心流程。边界发布、中心线区段确认、中心线合并发布都不创建 `approval task`，也不调用 approval 模块。后续若需要审批，只能在独立需求中设计，不应混入当前生产接口。

## Graph 入口

业务接口调用 `app.modules.navigation.services.graph_build_service.build_graph_from_centerlines()`。`scripts/navigation/build_graph_from_centerline.py` 只保留 CLI wrapper，用于本地或运维命令行触发，不再作为 app service 的依赖入口。

## 坐标系规则

- 后端存储、草稿保存、发布前校验、区段校验、Graph 构建、路径规划均使用 `WGS84`。
- 高德地图展示使用 `GCJ02`，由前端转换或读取 `display_coordinate_system_code=GCJ02_AMAP` 的地图图层。
- 地图点击和顶点编辑得到的是 `GCJ02`，保存到后端前必须转换为 `WGS84`。
- 后端校验问题返回的 `geometry_json` 仍是 `WGS84`，前端负责转为高德展示坐标。

## Graph 与路径引擎关系

中心线发布后只是生成了正式几何资产，路径规划不会自动使用新中心线。必须重新构建并激活 Graph 后，路径规划 V2 才会读取新 GraphEdge。路径引擎不直接读取边界或草稿，也不承担中心线生产职责。

## 路径规划 V2 职责

路径规划模块不修改生产状态机，不生成边界或中心线，不接审批。它负责：

- 端点吸附到 Graph。
- 按推荐、最短、安全优先、少过船闸等策略搜索。
- 生成备选路径并去重。
- 计算距离、时长、船闸、桥梁、约束等成本解释。
- 对无路径、约束阻断、端点不可吸附等失败给出结构化解释。
