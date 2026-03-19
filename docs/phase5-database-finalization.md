# Phase 5：数据库与模型收口

## 1. 目标结论

本阶段完成了“模型定义、主链代码、Alembic 迁移”三方收口：
- 已删除仍残留于模型中的旧兼容字段（不再只在文档层面标注弃用）。
- 已将关系表达统一到关系表（不再依赖 JSON 或单值区域字段）。
- 已补充并执行迁移脚本验证，确保可从基线迁移到当前头部版本。

## 2. 逐域核查结果

### 2.1 address

核查项：
1. `transport_node` 与 `region` 的关系
2. `region_waterway_relation` / `region_city_relation` 是否落地并被主链使用

处理结果：
- 删除 `transport_node.region_id`（旧单值归属）并改为仅使用 `region_address_relation`。
- 删除 `region.main_rivers/main_rivers_names/main_cities/main_cities_names`（旧 JSON 关系表达）。
- `AddressService` 分页查询区域详情改为从关系表批量读取 `waterway_ids/city_ids`。
- `RegionCreate/RegionUpdate` 请求字段改为 `waterway_ids`，城市归属由边界自动计算并写入 `region_city_relation`。

### 2.2 commodity

- 货品体系模型无旧主线残留字段；`match_keywords/match_regex/source/confidence/is_ai_generated` 等已由主链保留。
- 本阶段未新增/删除 commodity 字段，保持与一期标准化能力一致。

### 2.3 vessel

核查项：`vessel_dynamic` 分析字段是否实际使用。

处理结果：
- `current_region_id/current_city_code` 已在船舶统计任务主链中作为优先归属维度使用。
- `position_match_type/position_match_distance_m` 在接入侧保留并通过 ingestion 写入，供后续质量分析扩展。

### 2.4 cargo

核查项：`cargo_record/cargo_freight` 定位统一。

处理结果：
- 保留表名 `cargo_freight`，但在模型语义明确为“一期货源分析记录表”，非交易订单。
- 统计任务统一按分析口径过滤 `record_status/analysis_status/is_test_data`，确保与一期定位一致。

### 2.5 route

核查项：`route/path/segment` 是否真正支撑一期。

处理结果：
- `shipping_route_path_segment` 从“仅有模型”提升为可用主链：
  - Repository 增加 segment 查询/新增/删除/批量替换能力。
  - Service 增加 segment 业务方法。
  - API 新增 segment 接口（新增、批量替换、删除）。
- 新增路径完整性约束：
  - `uk_route_path_node_sequence(path_id, sequence)`
  - `uk_route_path_segment_sequence(path_id, sequence)`

### 2.6 analysis

核查项：统计表与分析任务是否一致。

处理结果：
- 统计主链已由 `app/jobs/cargo_stats.py` 与 `app/jobs/ship_stats.py` 接管。
- Analysis Service 仅查询统计表并触发 jobs，不再依赖旧 `stat_tasks` 主实现。

### 2.7 audit

处理结果：
- 审核目标类型从 `CARGO_OPPORTUNITY` 收口为 `CARGO_FREIGHT`。
- 审核服务表映射 `_TARGET_TABLE_MAP` 已切换为 `CARGO_FREIGHT -> cargo_freight`。
- 补充 `NODE_ALIAS -> node_alias` 映射，避免审核更新时出现未知类型。

## 3. 本阶段变更清单

### 3.0 最终保留的核心表（一期）

1. address 域
- `waterway`
- `admin_region`
- `node_type`
- `region`
- `transport_node`
- `node_alias`
- `region_address_relation`
- `region_waterway_relation`
- `region_city_relation`

2. commodity 域
- `commodity_category`
- `commodity_type`
- `commodity_standard`
- `commodity_alias`

3. vessel 域
- `vessel_type_dict`
- `vessel`
- `vessel_name_history`
- `vessel_ais_history`
- `vessel_dynamic`

4. cargo 域
- `cargo_raw_message`
- `cargo_ai_parse_result`
- `cargo_freight`（一期定位：货源分析记录，不是交易订单）
- `tms_cargo_raw`

5. route 域
- `shipping_route`
- `shipping_route_path`
- `shipping_route_path_node`
- `shipping_route_path_segment`

6. analysis 域
- `cargo_city_heatmap`
- `cargo_stat_daily`
- `cargo_commodity_stat_daily`
- `cargo_od_daily`
- `cargo_channel_daily`
- `ship_stat_region`
- `ship_stat_city`
- `ship_stat_dwt`
- `ship_stat_age`

7. audit / system 域（一期最小内控）
- `audit_task`
- `audit_record`
- `sys_user` / `sys_role` / `sys_permission` / `sys_role_permission` / `sys_user_role`

### 3.1 删除的旧字段

1. `region.main_rivers`
2. `region.main_rivers_names`
3. `region.main_cities`
4. `region.main_cities_names`
5. `transport_node.region_id`

### 3.2 删除的旧表（存在则清理）

迁移中执行 `DROP TABLE IF EXISTS` 清理以下历史遗留表：
1. `cargo_opportunity`
2. `cargo_heatmap_daily`
3. `ship_heatmap_daily`
4. `heatmap_stat_daily`
5. `cargo_region_stat_daily`
6. `ship_capacity_region_daily`
7. `ship_type_stat_daily`
8. `ship_age_stat_daily`

### 3.3 新增的关键数据库约束

1. `uk_route_path_node_sequence`（`shipping_route_path_node.path_id + sequence` 唯一）
2. `uk_route_path_segment_sequence`（`shipping_route_path_segment.path_id + sequence` 唯一）

### 3.4 一期主链关键字段（保留并实际使用）

1. 地址关系
- `region_address_relation.relation_type / is_primary / source`
- `region_waterway_relation.relation_type / is_primary / source`
- `region_city_relation.relation_type / is_primary / source`
- `transport_node.province_code / city_code / district_code`

2. 船舶动态分析
- `vessel_dynamic.data_source`
- `vessel_dynamic.reported_at / ingested_at`
- `vessel_dynamic.current_region_id / current_city_code`
- `vessel_dynamic.position_match_type / position_match_distance_m`

3. 货源分析记录
- `cargo_freight.record_source / record_status / analysis_status`
- `cargo_freight.data_quality_score / location_match_score / commodity_match_score`
- `cargo_freight.is_test_data / is_long_term_info / source_message_time`

## 4. 迁移脚本与模型一致性

- 新迁移：`alembic/versions/9d4d6be9f1a2_phase5_database_finalization.py`
- 迁移链：`c878ba817509 -> 9d4d6be9f1a2`
- 已在临时 SQLite 库验证：
  - `alembic upgrade head` 成功
  - 当前版本为 `9d4d6be9f1a2 (head)`

## 5. 一期定位支撑说明

数据库最终形态满足一期“标准数据与分析平台”定位：
1. 地址关系采用关系表表达，可支撑多归属和分析维度扩展。
2. 货源表定位为分析记录，不承载交易闭环。
3. 船舶动态字段支持区域/城市归属与热力分析。
4. 航线模型已包含路线分段能力，可支持单边/多边/多式联运路径表达。
5. 分析表与 jobs 主链对应清晰，统计口径可落地执行。
