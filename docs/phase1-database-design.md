# 一期数据库设计（标准数据与分析平台）

## 1. 设计原则
1. 主数据关系显式化：正式关系不用 JSON 存储。
2. 统计口径可追溯：统计字段与状态过滤规则清晰。
3. 分析友好：货源/船舶数据表优先支持分析检索。
4. AI 可追踪：提示词版本、调用日志、置信度、反馈闭环。

## 2. 地址体系

### 2.1 核心主表
1. `waterway`
2. `admin_region`
3. `node_type`
4. `region`
5. `transport_node`
6. `node_alias`
7. `shipping_route`
8. `shipping_route_path`
9. `shipping_route_path_node`
10. `shipping_route_path_segment`（新增）

### 2.2 核心关系表
1. `region_address_relation`（节点与区域关系）
- `region_id`
- `transport_node_id`
- `relation_type`（PRIMARY/SECONDARY/PASSING）
- `is_primary`
- `source`（RULE/AI/MANUAL）

2. `region_waterway_relation`（区域与水系）
- `region_id`
- `waterway_id`
- `relation_type`（MAIN/RELATED）
- `is_primary`
- `source`

3. `region_city_relation`（区域与城市）
- `region_id`
- `admin_region_id`
- `relation_type`（MAIN/COVERED/RELATED）
- `is_primary`
- `source`

### 2.3 关键调整
1. `transport_node` 增加行政编码字段：
- `province_code`
- `city_code`
- `district_code`
2. 保留冗余展示字段：`province/city/district`。
3. 废弃 `region.main_rivers/main_cities` 作为正式关系表达。
4. `transport_node.region_id` 不再作为区域归属主表达（由关系表承载）。

## 3. 货品体系

### 3.1 保留表
1. `commodity_category`
2. `commodity_type`
3. `commodity_standard`
4. `commodity_alias`

### 3.2 强化字段
1. `commodity_standard` 新增：
- `match_keywords`
- `match_regex`
- `default_density`
- `danger_level`
- `common_unit`
- `source`
- `confidence`
- `is_ai_generated`

2. `commodity_alias` 新增：
- `match_keywords`
- `match_regex`
- `source`
- `confidence`
- `is_ai_generated`

## 4. 船舶体系

### 4.1 保留表
1. `vessel_type_dict`
2. `vessel`
3. `vessel_name_history`
4. `vessel_ais_history`
5. `vessel_dynamic`

### 4.2 动态表增强
`vessel_dynamic` 新增：
- `data_source`
- `reported_at`
- `ingested_at`
- `current_region_id`
- `current_city_code`
- `position_match_type`
- `position_match_distance_m`

## 5. 货源体系

### 5.1 分层
1. `cargo_raw_message`：原始消息
2. `cargo_ai_parse_result`：AI 解析中间层
3. `cargo_record`：标准化货源分析记录（一期主表）
4. `tms_cargo_raw`：外部结构化暂存层

### 5.2 说明
当前代码保留 `cargo_freight` 作为兼容模型，短期以其承载 `cargo_record` 语义；后续可进行表名切换迁移。

### 5.3 新增分析字段
在 `cargo_freight`（一期语义=record）增加：
- `record_source`
- `record_status`
- `data_quality_score`
- `location_match_score`
- `commodity_match_score`
- `analysis_status`
- `is_test_data`
- `is_long_term_info`
- `source_message_time`

## 6. 审核体系
1. `audit_task`：当前待处理任务。
2. `audit_record`：完整历史。
3. 业务表仅保存审核状态快照，过程留在审核表。

## 7. 统计分析体系

### 7.1 日报聚合
1. `cargo_stat_daily`
2. `cargo_city_heatmap_daily`（当前实现名：`cargo_city_heatmap`）
3. `cargo_commodity_stat_daily`
4. `cargo_od_daily`
5. `cargo_channel_daily`

### 7.2 快照表
1. `ship_stat_region_snapshot`（当前实现名：`ship_stat_region`）
2. `ship_stat_city_snapshot`（当前实现名：`ship_stat_city`）
3. `ship_stat_dwt_snapshot`（当前实现名：`ship_stat_dwt`）
4. `ship_stat_age_snapshot`（当前实现名：`ship_stat_age`）

## 8. 迁移策略
1. 使用 Alembic 统一管理，不再依赖启动时 `create_all`。
2. 增量迁移优先做“新增字段/新增关系表/数据回填”。
3. 旧字段先标记弃用并迁移调用，再删除。
