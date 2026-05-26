# 航道图与路径模块架构说明

## 生产链路

航道图生产按“保存草稿 -> 发布前校验 -> 操作员确认发布”运行，不接审批、不创建 approval task。边界、中心线、Graph 和路径的关系如下：

1. 航道先完成水体归属，归属水体作为边界生产参考。
2. 边界草稿通过 `geometry_draft_service` 保存和发布，发布后写入当前航道边界。
3. 中心线草稿通过同一草稿服务保存和发布，发布前由 `geometry_validation_service` 校验边界约束、长度、端点连接等问题。
4. Graph 构建读取已发布 current centerline，由 `graph_build_service` 生成 GraphVersion、GraphNode、GraphEdge 和边约束。
5. 路径规划 V2 只读取 READY/active Graph，负责吸附、约束搜索、备选路径、成本解释和失败解释。

## 服务职责

- `NavigationWorkbenchService`：工作台 Facade，保留摘要、列表、水体归属和共享几何辅助方法。
- `geometry_draft_service.py`：几何草稿 CRUD、归档、发布事务和发布后正式资产写入。
- `geometry_validation_service.py`：草稿校验入口和发布前校验入口。
- `snap_reference_service.py`：中心线编辑吸附参考点收集。
- `graph_workbench_service.py`：Graph 构建和激活的工作台入口。
- `graph_build_service.py`：从已发布中心线构建 Graph 的核心逻辑。
- `graph_validation_service.py`：Graph 拓扑和质量校验。

## Graph 入口

业务接口调用 `app.modules.navigation.services.graph_build_service.build_graph_from_centerlines()`。`scripts/navigation/build_graph_from_centerline.py` 只保留 CLI wrapper，用于本地或运维命令行触发，不再作为 app service 的依赖入口。

## 坐标系规则

- 后端存储、草稿保存、发布前校验、Graph 构建、路径规划均使用 `WGS84`。
- 高德地图展示由前端转换或读取 `display_coordinate_system_code=GCJ02_AMAP` 的地图图层。
- 后端校验问题返回的 `geometry_json` 仍是 `WGS84`，前端负责转为高德展示坐标。

## 路径规划 V2 职责

路径规划模块不修改生产状态机，不生成边界或中心线，不接审批。它负责：

- 端点吸附到 Graph。
- 按推荐、最短、安全优先、少过船闸等策略搜索。
- 生成备选路径并去重。
- 计算距离、时长、船闸、桥梁、约束等成本解释。
- 对无路径、约束阻断、端点不可吸附等失败给出结构化解释。
