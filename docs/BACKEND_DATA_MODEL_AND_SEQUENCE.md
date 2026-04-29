# BACKEND DATA MODEL AND SEQUENCE

## 1. 数据模型真值范围

当前后端数据库真值以 `app/models/*` 为准，迁移链收口为单一初始迁移：  
`alembic/versions/0001_initial_schema.py`。

不包含历史链路：

- `ai_*`
- `freight_candidate / freight_clue / freight_batch_task / freight_workflow*`
- `freight_tms_inbound / manual_feedback`
- `waterway / region_waterway_relation / region_address_relation`

## 2. 正式表分组

### 2.1 通用与字典
- `std_dict`
- `std_dict_item`
- `code_sequence`

### 2.2 地址与空间
- `admin_region`
- `admin_region_boundary`
- `region`
- `region_boundary_version`
- `region_city_relation`
- `transport_node`
- `transport_node_profile`
- `node_alias`
- `transport_node_business_category`
- `transport_node_packaging_form`
- `transport_node_handling_mode`
- `navigation_constraint_point`

### 2.3 货品
- `commodity_category`
- `commodity_type`
- `commodity_standard`
- `commodity_alias`
- `commodity_standard_attribute`
- `commodity_packaging_form`
- `commodity_transport_mode`
- `commodity_ship_type_rule`
- `commodity_node_type_rule`
- `commodity_handling_mode_rule`

### 2.4 船舶
- `ship_profile`
- `ship_capacity`
- `ship_operation`
- `ship_owner`
- `ship_contact`
- `ship_certificate`
- `ship_certificate_file`
- `ship_name_history`
- `ship_mmsi_history`
- `ship_import_batch`
- `ship_import_raw`
- `ship_import_record`
- `ship_dynamic`（扩展事实表，非当前主流程核心）

### 2.5 正式货源
- `freight`
- `freight_contact`
- `freight_source_attachment`
- `freight_tag_relation`

### 2.6 航线与方案
- `shipping_route`
- `shipping_route_plan`
- `shipping_route_plan_segment`
- `shipping_route_plan_segment_point`

### 2.7 统计与分析
- `cargo_channel_daily`
- `stat_cargo_daily`
- `stat_cargo_city_daily`
- `stat_cargo_flow_daily`
- `stat_cargo_commodity_daily`
- `stat_ship_city_daily`
- `stat_ship_flow_daily`
- `stat_job_run`

### 2.8 审核与系统
- `audit_task`
- `audit_record`
- `sys_user`
- `sys_role`
- `sys_user_role`
- `sys_permission`
- `sys_role_permission`
- `sys_menu`
- `sys_role_menu`
- `sys_data_scope`
- `sys_role_data_scope`
- `sys_user_status_log`
- `sys_login_log`
- `system_config`

## 2.9 system_config 元数据扩展（阶段 1 收口）

`system_config` 已从简单 key-value 表扩展为配置中心元数据表，除原有
`config_key/config_name/config_value/value_type_code/config_group_code` 外，补充：

- `config_profile_code`：配置 profile（如 `SYSTEM/AMAP/HIFLEET/ES`）
- `sensitive_flag`：是否敏感值（1 为敏感）
- `encrypted_flag`：加密标记占位（本阶段仅元数据标记）
- `editable_flag`：是否可编辑
- `sort_order`：列表排序
- `config_status_code`：配置状态（如 `ACTIVE`）
- `last_test_status_code/last_test_message/last_tested_at`：连接测试结果占位

说明：

- 阶段 1 不引入独立 profile 表，profile 仍由 `config_profile_code` 字段表达。
- 运行时读取优先级由 `RuntimeConfigService` 负责：DB 优先 -> ENV/settings 回退 -> default -> EMPTY。
- 连接测试由 `ConfigTestService` 执行，结果回写本表 `last_test_*` 字段。

## 3. code_sequence 真值结构

`CodeSequence` 字段（`app/models/common.py`）：

- `biz_code`（唯一）
- `biz_name`
- `target_table`
- `target_column`
- `prefix`
- `date_format`
- `separator`
- `current_value`
- `value_length`
- `step`
- `reset_rule`（`NONE`/`DAY`/`MONTH`/`YEAR`）
- `is_enabled`
- `remark`

统一生成入口：

- `CodeSequenceRepository.next_code`
- `CodeSequenceService.next_code`

生成规则：

1. 按 `reset_rule` 判断是否重置序列
2. `current_value += step`
3. 按 `prefix + date_part + serial_part` 生成编码  
   - `date_part` 由 `date_format` 决定  
   - `serial_part` 按 `value_length` 左侧补零  
   - `separator` 控制连接符

## 4. 自动编号接入对象

以下对象在创建时“未显式传编码”会走 `code_sequence` 自动生成：

- `region.code` → `REGION_CODE`
- `transport_node.code` → `NODE_CODE`
- `navigation_constraint_point.code` → `NAV_CONSTRAINT_POINT_CODE`
- `shipping_route.code` → `ROUTE_CODE`
- `shipping_route_plan.plan_code` → `ROUTE_PLAN_CODE`
- `commodity_category.code` → `COMMODITY_CATEGORY_CODE`
- `commodity_type.code` → `COMMODITY_TYPE_CODE`
- `commodity_standard.code` → `COMMODITY_STANDARD_CODE`
- `freight.freight_no` → `FREIGHT_NO`
- `audit_task.task_no` → `AUDIT_TASK_NO`
- `ship_import_batch.batch_no` → `SHIP_IMPORT_BATCH_NO`

## 5. 明确不接入自动编号

- `admin_region.code`
- `ship_profile.ais_id`
- `ship_profile.current_mmsi`
- `ship_certificate.certificate_no`
- `sys_role.role_code`
- `sys_permission.permission_code`
- `sys_menu.menu_code`
- `sys_data_scope.scope_code`

## 6. 阶段 3D 航线地图 E2E 基线数据

为保障航线地图 Playwright 验收稳定性，初始化链新增 `scripts/seed_route_map_e2e.py`。

该脚本在不新增表结构、不改业务接口前提下，为以下既有表写入幂等测试基线：

- `region`
- `region_boundary_version`
- `shipping_route`
- `shipping_route_plan`
- `shipping_route_plan_segment`
- `shipping_route_plan_segment_point`

关键业务标识：

- `E2E_ROUTE_ORIGIN`
- `E2E_ROUTE_DEST`
- `E2E_ROUTE_MAP`
- `E2E_ROUTE_PLAN_MAP`

用途边界：

- 仅用于本地开发、CI 与 E2E 自动化验证。
- 不改变正式业务逻辑，不依赖固定自增 ID。
- 通过业务编码与组合键幂等 upsert，重复执行不重复插入。

## 7. 阶段 4B 航线产品化模型重构方向

阶段 4B 审计结论见 `docs/STAGE_4B_ROUTE_PRODUCTIZATION_AUDIT.md`。

当前航线模型可支撑基础 CRUD 与地图只读展示，但不应把 `shipping_route_plan_segment` 和 `shipping_route_plan_segment_point` 作为业务用户的主维护对象。后续模型演进建议：

- 新增 `RoutePlanNode / RoutePlanStop`：表达用户维护的路径节点串。
- 扩展 `shipping_route_plan_segment`：表达由相邻路径节点生成的航段结果，补充 `geometry_status / geometry_source / geometry_message / provider_code / generated_at` 等生成状态字段。
- 保留旧的航段起终节点与约束点字段用于兼容历史数据，但前端主流程应隐藏。
- 扩展通航约束点能力：优先新增 `NavigationConstraintProfile` 承载吨位、吃水、净空、宽度、规则 JSON 等约束能力字段。
- 后续新增 `RouteSegmentConstraintImpact`：保存 geometry 生成后匹配到的通航约束影响结果。

上述调整预计从后续 4D 起涉及 migration；阶段 4B 仅固化审计方案，不修改现有表结构。
