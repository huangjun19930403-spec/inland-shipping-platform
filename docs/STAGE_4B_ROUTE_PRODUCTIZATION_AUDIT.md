# 阶段 4B 航线模块产品化重构审计报告

## 1. 总体结论

当前航线模块更像“数据库维护后台”，不是生产级“路径方案设计工具”。问题不是单点页面文案，而是模型、接口、前端信息架构三层共同偏底层：业务用户被迫填写 `start_node_id`、`constraint_point_id`、`sort_order`、点位经纬度等数据库字段。

结论：不建议继续在现有航段/点位表单上小修；建议进行产品化重构。核心方向是从“手工维护航段”改为“维护路径节点串 -> 自动生成航段 -> 生成 geometry -> 分析约束影响 -> 展示/确认结果”。

## 2. 当前后端模型审计

| 模型 | 当前职责 | 审计结论 | 后续建议 |
|---|---|---|---|
| `ShippingRoute` | 商业航线，起终业务区域对 | 基本合理，但缺当前方案状态、geometry 状态摘要 | 保留，补摘要字段或通过聚合响应返回 |
| `ShippingRoutePlan` | 航线下的具体方案 | 概念合理，但缺路径节点串、生成状态、约束摘要 | 保留并扩展，成为方案设计主对象 |
| `ShippingRoutePlanSegment` | 航段明细，当前由用户手工维护 | 字段暴露过底层，不适合作为主操作 | 保留为“生成结果”，不再主推手工新增 |
| `ShippingRoutePlanSegmentPoint` | 航段点位 | 适合做 geometry/轨迹点结果，不适合作为路径设计入口 | 保留为底层结果或高级调试 |
| `NavigationConstraintPoint` | 通航约束空间点 | 后端已有基础模型，但字段不足，前端缺独立管理 | 扩展并产品化为独立基础数据 |
| `TransportNode` | 装卸、中转、港口等作业节点 | 与约束点边界清晰，应作为路径节点来源之一 | 保留，不与约束点混用 |
| `Region` | 业务区域 | 可作为航线起终点和路径锚点 | 保留，作为 RoutePlanNode 的 `REGION_ANCHOR` 来源 |

## 3. 当前后端接口审计

现有 `route` API 覆盖航线、方案、航段、点位、排序、刷新 geometry。

适合保留：`GET/POST/PUT /route`、`GET/POST/PUT /route/{id}/plans`、`activate plan`、`GET plan detail`。

应降级为高级调试：`POST/PUT/DELETE segments`、`POST/PUT/DELETE points`、`segments/order`、`points/order`。这些接口不符合业务用户心智。

应重构：`geometry/refresh` 应改为“预览生成”和“确认生成”，并带 `provider_code`、`force_refresh`、失败原因和状态。

应新增：路径节点串接口、生成航段接口、geometry preview/generate 接口、约束影响分析接口。

当前地址后端已有 `/address/constraint-points` CRUD，但前端未产品化；建议先补管理页面，再决定是否新增 `/address/navigation-constraints` 语义别名。

## 4. 当前前端页面审计

`RouteListPage` 同时承载航线列表和 `/route/plans` 入口，概念混乱。

`RouteDetailPage` 可保留为航线详情和方案列表，但需要强化“当前方案”和“进入方案设计”。

`RoutePlanDetailPage` 当前暴露航段/点位维护为主操作，不像方案设计器。

`RouteSegmentFormDialog` 要用户填起止节点 ID、约束点 ID、排序，是最大产品化问题。

`RouteSegmentPointFormDialog` 要用户填点位类型、关联 ID、经纬度，也偏数据库维护。

`RouteReadonlyMap`、`BaseAmap`、GeoJSON 工具、地图联动能力可以保留，是后续方案设计器的地图展示基础。

“上移/下移航段”应移出主流程；顺序应该调整路径节点串，而不是调整生成后的航段。

## 5. 核心问题归纳

- 最大问题是主操作对象错了：用户要设计“路径经过哪些节点”，系统却让用户维护“航段表和点位表”。
- 通航约束点没有独立产品入口，导致它被塞进航段表单 ID 字段。
- geometry 生成是刷新按钮，不是可解释的“生成过程”。
- 前端路由和页面入口没有清楚表达“航线 -> 方案 -> 路径设计 -> 生成结果”的链路。
- 当前 E2E seed 保障了地图联动测试，但不是完整业务路径设计数据模型。

## 6. 正确产品逻辑设计

创建航线：选择起点区域、终点区域、填写名称、组织类型。

创建路径方案：填写方案名称、方案类型、默认标记、备注。

设计路径节点串：添加运输节点、通航约束点、手工坐标点、区域锚点；支持搜索、地图选点、顺序调整、相邻节点运输方式。

自动生成航段：由相邻路径节点生成航段，根据运输方式选择水路/陆路/铁路 provider，生成 geometry，失败保留原因。

展示生成结果：地图展示、航段列表、geometry 状态、距离/时长、约束影响和生成日志。

设置当前方案：确认方案可用后设为当前启用方案。

## 7. TransportNode 与 NavigationConstraintPoint 边界定义

`TransportNode` 是作业节点，具备装卸、中转、港口、堆场等业务能力。

`NavigationConstraintPoint` 是空间约束节点，描述船闸、桥梁、浅滩、限航/禁航、限高/限宽/限吃水等通行限制。

二者都可以参与路径节点串，但业务能力不同。约束点不具备装卸能力，不应作为普通货物作业节点。

约束点不应暴露为“航段起始约束点 ID”让用户手填，而应通过独立管理和路径生成/匹配形成约束影响结果。

## 8. 新数据模型建议

建议新增 `RoutePlanNode`，作为方案设计的主数据：`id`、`plan_id`、`node_order`、`node_kind_code`、`transport_node_id`、`constraint_point_id`、`longitude`、`latitude`、`display_name`、`role_code`、`next_transport_mode_code`、`remark`、`created_at`、`updated_at`。

`RoutePlanNode` 与 `RouteSegmentPoint` 的区别：前者是用户设计节点串，后者是生成后的航段点位/轨迹结果。前者不替代点位表，但会驱动生成航段和点位。

建议扩展 `ShippingRoutePlanSegment`：`start_plan_node_id`、`end_plan_node_id`、`transport_mode_code`、`geometry_status`、`geometry_source`、`geometry_message`、`geometry_generated_at`、`provider_code`、`fallback_flag`。旧的 `start_node_id/end_node_id/start_constraint_point_id/end_constraint_point_id/sort_order` 保留兼容，前端隐藏，后续迁移。

建议新增 `NavigationConstraintProfile` 一对一承载约束能力字段：`max_tonnage`、`max_draft_m`、`max_air_draft_m`、`max_beam_m`、`max_length_m`、`min_water_depth_m`、`restriction_rule_json`、`valid_from`、`valid_to`、`severity_level`。复杂多规则后续再拆 `NavigationConstraintRule`。

建议新增 `RouteSegmentConstraintImpact`：`segment_id`、`constraint_point_id`、`impact_type_code`、`limit_value`、`limit_unit`、`blocking_flag`、`warning_message`、`matched_by`、`confirmed_flag`、`remark`。

## 9. 新接口设计建议

路径节点串：`GET /route/plans/{plan_id}/nodes`、`PUT /route/plans/{plan_id}/nodes`、`POST /route/plans/{plan_id}/nodes/preview-segments`、`POST /route/plans/{plan_id}/nodes/generate-segments`。

路径生成：`POST /route/plans/{plan_id}/geometry/preview` 只返回预览结果；`POST /route/plans/{plan_id}/geometry/generate` 保存 geometry；`POST /route/segments/{segment_id}/geometry/generate` 单航段生成。

通航约束点：优先产品化现有 `/address/constraint-points`，可新增 `/address/navigation-constraints` 语义别名；支持列表、新增、详情、编辑、状态。

约束影响：`GET /route/segments/{segment_id}/constraint-impacts`、`POST /route/segments/{segment_id}/constraint-impacts/analyze`、`PUT /route/constraint-impacts/{id}/confirm`，建议延后到 4H。

## 10. 新前端页面设计建议

航线列表页：顶部统计、筛选、航线表/卡片、起终区域、当前方案状态、方案数量、geometry 状态、主按钮“进入方案设计”。

航线详情页：航线基础信息、当前方案摘要、方案列表、当前方案地图，操作为设计方案、查看方案、复制方案、设为当前。

方案设计页：顶部方案信息，中间地图，侧边路径节点串，下方生成航段结果，右侧约束影响/生成日志/错误原因。

通航约束点管理页：列表、地图、新增/编辑、约束能力字段、状态管理、地图选点。

## 11. 保留、删除、降级、重构清单

| 对象/能力 | 建议 | 原因 |
|---|---|---|
| `RouteSegmentPanel` | 重构/降级 | 保留结果展示，移除主操作地位 |
| `RouteSegmentFormDialog` | 降级高级调试 | 不再让业务用户填数据库字段 |
| `RouteSegmentPointPanel` | 重构/降级 | 用于查看生成点位，非主设计入口 |
| `RouteSegmentPointFormDialog` | 降级高级调试 | 点位应由节点串/geometry 生成 |
| `reorder_segments` | 删除主入口 | 顺序应来自路径节点串 |
| `reorder_points` | 删除主入口 | 点位不是用户主排序对象 |
| `refresh_plan_geometry` | 重构 | 改为 preview/generate |
| `refresh_segment_geometry` | 降级/重构 | 作为高级单段重新生成 |
| `RouteReadonlyMap` | 保留 | 只读地图展示和联动已可复用 |
| E2E route seed | 保留并迁移 | 后续补 RoutePlanNode seed |
| `RoutePlanDetailPage` | 重构 | 从维护表变为方案设计器 |
| `/route/plans` 入口 | 重构 | 避免和航线列表混淆 |

## 12. 分阶段执行方案

4C：通航约束点管理模块补全。后端复用/补齐 constraint-points schema，前端新增管理页和地图选点；无或少量 migration；补 seed/E2E。验收：可维护约束点且不混入运输节点。

4D：RoutePlanNode 路径节点串模型落地。新增 migration、schema、service、API、seed、E2E。验收：方案可保存节点串。

4E：方案设计页重构。前端建设节点串 UI、节点搜索、地图选点、运输方式选择；隐藏手工航段主入口。验收：用户能按业务路径设计方案。

4F：自动生成航段。后端按节点串生成 segments，提供预览和确认保存；移除主流程上移/下移。验收：节点串 A-B-C 自动生成两段。

4G：geometry 状态与生成结果展示。补 `geometry_status/source/message/generated_at`，展示生成日志和失败原因。验收：生成成功/失败都可解释。

4H：约束影响分析。新增 impact 表，按 geometry 匹配约束点，显示阻断/警告/人工确认。验收：航段可看到受哪些约束影响。

## 13. 风险与迁移策略

- 不清空旧 segment/point 数据，保留旧 API 兼容，但从主 UI 隐藏。
- 旧 segment 可作为“legacy generated result”展示；新增 RoutePlanNode 后，E2E seed 同步补节点串。
- 避免新旧入口混杂：主入口只放“方案设计”，旧航段/点位维护移入高级调试折叠区或权限控制。
- 每阶段必须配套 migration、seed、Playwright，避免继续补丁式开发。
- 路径生成 provider 失败必须可解释，不能静默失败或只弹 toast。
- 通航约束点不能和运输节点合表处理，只能统一作为路径节点来源。

## 14. 下一步建议

推荐下一阶段先做 4C：通航约束点管理模块补全。原因是它是路径节点串的重要来源，也是当前概念混乱的根因之一。随后做 4D RoutePlanNode，再重构方案设计页和自动生成航段。

## 15. 本轮边界

- 本文档为产品化重构审计与分阶段方案。
- 本阶段不修改业务代码。
- 本阶段不新增数据库表。
- 本阶段不新增 migration。
- 本阶段不新增后端接口。
- 本阶段不新增前端路由。
