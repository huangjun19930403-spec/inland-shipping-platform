# 阶段 4C 通航约束点管理模块

## 1. 阶段范围

阶段 4C 补齐通航约束点作为独立基础数据的后端模型、接口、seed 与前端管理入口。该阶段只处理通航约束点及其约束能力 Profile，不进入航线方案重构。

## 2. 模型边界

- `NavigationConstraintPoint` 负责表达“这个约束点在哪里、是什么类型”，包含编码、名称、类型、行政区、经纬度、有效期、风险等级、说明和状态。
- `NavigationConstraintProfile` 负责表达“这个约束点限制什么”，与 `NavigationConstraintPoint` 一对一关联。
- 通航约束点不是运输节点，不具备装卸、中转、堆场等货物作业能力。
- 后续路径节点串可以引用通航约束点，但不能把约束点与 `TransportNode` 混为同一业务对象。

## 3. Profile 字段

`navigation_constraint_profile` 字段包括：

- `constraint_point_id`
- `max_tonnage`
- `max_allowed_draft_m`
- `min_water_depth_m`
- `under_keel_clearance_m`
- `max_air_draft_m`
- `max_beam_m`
- `max_length_m`
- `allowed_time_window`
- `restriction_rule_json`
- `rule_description`
- `warning_message`
- `created_at`
- `updated_at`

## 4. API 清单

- `GET /api/v1/address/constraint-points`
- `POST /api/v1/address/constraint-points`
- `GET /api/v1/address/constraint-points/{point_id}`：返回 `{ point, profile }`
- `PUT /api/v1/address/constraint-points/{point_id}`
- `PUT /api/v1/address/constraint-points/{point_id}/profile`
- `PUT /api/v1/address/constraint-points/{point_id}/status`

列表、创建、更新基础点位接口保持兼容；Profile 通过独立接口 upsert。

## 5. Seed 数据

`scripts/seed_navigation_constraints.py` 接入 `scripts/seed_system_init.py`，写入三条 E2E 基线数据：

- `E2E_CONSTRAINT_LOCK`
- `E2E_CONSTRAINT_BRIDGE`
- `E2E_CONSTRAINT_SHALLOW`

脚本按 `code` 幂等 upsert 通航约束点，按 `constraint_point_id` 幂等 upsert Profile。

## 6. 菜单与前端入口

地址管理菜单新增：

- `ADDRESS_CONSTRAINT_POINTS`
- `/address/constraint-points`
- `modules/address/pages/ConstraintPointListPage`

该入口用于维护基础通航约束数据，不承担航线生成和约束影响分析。

## 7. 当前未做

- RoutePlanNode
- 路径节点串
- 自动生成航段
- 约束影响分析
- 路径规划
- 航线页面重构
