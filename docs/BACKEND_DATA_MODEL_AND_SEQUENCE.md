# Backend Data Model And Sequence

## 数据模型真值

以 `app/models/*` 和 Alembic head 为准。最终迁移链保留历史迁移文件，`0006_final_legacy_cleanup` 删除废弃表，`0007_foundation_dictionary_codes` 将标准货品主单位收敛为字典编码。

## 核心表分组

### 通用与字典

- `std_dict`
- `std_dict_item`
- `code_sequence`

### 地址与空间

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
- `navigation_constraint_profile`

### 货品

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

货品分类和类型为标准货品依赖元数据，只通过 `/commodity/metadata` 提供只读聚合。

`commodity_standard.main_unit_code` 使用 `COMMODITY_UNIT` 字典，不再保存自由文本主单位；危险等级使用 `DANGEROUS_GOODS_LEVEL` 字典，业务响应同时返回 code 和中文 name。

标准货品详情使用 `commodity_packaging_form`、`commodity_transport_mode`、`commodity_ship_type_rule`、`commodity_node_type_rule`、`commodity_handling_mode_rule` 组合返回结构化明细。包装形式和运输方式保留 `is_default`，船型、节点类型和作业方式保留 `allow_flag` 与 `rule_desc`，由 service 补齐中文 label 后返回给前端。

### 船舶

- `ship_profile`
- `ship_capacity`
- `ship_operation`
- `ship_owner`
- `ship_contact`
- `ship_certificate`
- `ship_certificate_file`
- `ship_name_history`
- `ship_mmsi_history`
- `ship_dynamic`

船舶导入批次表已删除。后续如重新需要导入能力，应按轻量技术日志重新设计，不作为核心产品对象。

### 货源采集

- `freight`
- `freight_contact`
- `freight_source_attachment`
- `freight_tag_relation`
- `freight_source_inbound`
- `freight_ai_parse_task`
- `freight_clue`
- `freight_candidate`
- `freight_candidate_feedback`

手工录入直达正式货源；微信/TMS/批量原文进入来源接入，经通义千问解析后进入候选池，由人工确认生成正式货源。

### 航线规划

- `shipping_route`
- `shipping_route_plan`
- `shipping_route_line`
- `shipping_route_line_node`
- `shipping_route_line_segment`
- `shipping_route_line_track`

### 数据分析

- `analysis_indicator_definition`
- `analysis_bucket_definition`
- `analysis_snapshot`
- `analysis_job_run`
- `fact_freight_daily`
- `fact_freight_flow_daily`
- `fact_freight_commodity_daily`
- `fact_freight_price_daily`
- `fact_ship_daily`
- `fact_ship_flow_daily`
- `fact_region_daily`

旧 `stat_*`、`cargo_channel_daily`、`stat_job_run` 表已删除。

### 审核与系统

- `audit_task`
- `audit_task_snapshot`
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

## 编码序列

保留自动编号的业务对象：

- `REGION_CODE`
- `NODE_CODE`
- `NAV_CONSTRAINT_POINT_CODE`
- `ROUTE_CODE`
- `ROUTE_PLAN_CODE`
- `ROUTE_LINE_CODE`
- `COMMODITY_STANDARD_CODE`
- `FREIGHT_NO`
- `AUDIT_TASK_NO`

不再提供货品分类、货品类型、船舶导入批次的业务创建编号。

## 删除对象

最终基线不再包含：

- `ship_import_batch`
- `ship_import_raw`
- `ship_import_record`
- `stat_cargo_daily`
- `stat_cargo_city_daily`
- `stat_cargo_flow_daily`
- `stat_cargo_commodity_daily`
- `cargo_channel_daily`
- `stat_ship_city_daily`
- `stat_ship_flow_daily`
- `stat_job_run`
