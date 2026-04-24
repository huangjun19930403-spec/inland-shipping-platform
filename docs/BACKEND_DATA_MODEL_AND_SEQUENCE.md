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
