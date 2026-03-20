# 数据库设计（当前主线）

本文档仅描述当前代码与迁移链真实生效的数据结构。

## 1. 主线原则

1. 业务写入走业务表（`app/models/*`）
2. 分析接口只读统计表（`app/models/analysis.py`）
3. 迁移仅使用 Alembic 单主链（`0001_initial_schema`）
4. 历史表结构已不在当前主线

## 2. 表分组

### 2.1 系统与权限

- `sys_user`
- `sys_role`
- `sys_user_role`

### 2.2 审核中心

- `audit_task`
- `audit_record`

### 2.3 地址与节点

- `waterway`
- `region`
- `admin_region`
- `node_type`
- `transport_node`
- `transport_node_profile`
- `node_alias`
- `region_address_relation`
- `region_waterway_relation`
- `region_city_relation`
- `code_sequence`（编码原子序列，Repository 通过 SQL 使用）

### 2.4 货品与货源

- `commodity_category`
- `commodity_type`
- `commodity_standard`
- `commodity_alias`
- `cargo_raw_message`
- `cargo_ai_parse_result`
- `cargo_freight`
- `tms_cargo_raw`

### 2.5 船舶

- `vessel_type_dict`
- `vessel`
- `vessel_name_history`
- `vessel_ais_history`
- `vessel_dynamic`

### 2.6 航线

- `shipping_route`
- `shipping_route_path`
- `shipping_route_path_node`
- `shipping_route_path_segment`

### 2.7 统计分析

货源统计（日表）：
- `cargo_city_heatmap`
- `cargo_stat_daily`
- `cargo_commodity_stat_daily`
- `cargo_od_daily`
- `cargo_channel_daily`

船舶统计（快照）：
- `ship_stat_region`
- `ship_stat_city`
- `ship_stat_dwt`
- `ship_stat_age`

### 2.8 AI 管理

- `ai_prompt_template`
- `ai_prompt_version`
- `ai_call_log`

## 3. 核心数据流

### 3.1 货源链路

`cargo_raw_message` -> `cargo_ai_parse_result` -> `cargo_freight` -> 货源统计表

`cargo_freight` 一期分析字段：
- `source_message_time`
- `location_match_level`
- `data_quality_score`
- `analysis_status`

### 3.2 船舶链路

`vessel` + `vessel_dynamic` -> 船舶快照统计表

其中 `vessel_dynamic` 一期分析字段：
- `current_region_id`
- `current_city_code`
- `position_match_type`
- `position_match_distance_m`
- `reported_at`
- `data_source`

### 3.3 审核链路

业务对象提交 -> `audit_task` + `audit_record` -> 审核通过/驳回回写业务表 `audit_status`

## 4. 迁移主链

当前单链版本：
- `0001_initial_schema`

## 5. 运行约束

1. 新环境优先执行：`alembic upgrade head`
2. 不再使用历史 SQL 初始化脚本作为主方案
3. 结构变更必须通过新的 Alembic 迁移提交
