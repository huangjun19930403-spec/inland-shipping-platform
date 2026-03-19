# 重构变更日志（一期）

## 2026-03-19

### 新增文档
1. `docs/phase1-architecture.md`
2. `docs/phase1-database-design.md`
3. `docs/phase1-analysis-design.md`
4. `docs/phase1-refactor-progress.md`
5. `docs/refactor-changelog.md`

### 已实施重大变更
1. 统一 Base 元数据来源：
- 所有模型统一继承 `app.models.base.Base`
- `app/core/database.py` 不再定义第二个 Base

2. 启动逻辑调整：
- `main.py` 移除启动阶段 `create_all`
- 数据库初始化统一走 Alembic

3. 迁移体系重建：
- 旧迁移归档到 `alembic/versions_legacy/`
- 新建一期基线迁移：`alembic/versions/c878ba817509_phase1_baseline_schema.py`

4. 地址体系重构：
- 新增 `region_waterway_relation`
- 新增 `region_city_relation`
- 增强 `region_address_relation`（`relation_type`/`source`）
- `transport_node` 增加 `province_code/city_code/district_code`
- `transport_node.region_id` 标记弃用（正式归属改为关系表）

5. 货品体系增强：
- `commodity_standard` 新增匹配与质量字段
- `commodity_alias` 新增匹配与质量字段

6. 船舶体系增强：
- `vessel_dynamic` 新增 `data_source/reported_at/ingested_at/current_region_id/current_city_code/position_match_type/position_match_distance_m`

7. 货源体系增强：
- `cargo_freight` 新增分析记录字段（`record_*`, `*_score`, `is_test_data`, `is_long_term_info`, `source_message_time`）

8. 航线体系增强：
- 新增 `shipping_route_path_segment`（路线分段）

9. API 分域重组：
- 新增 `standard_data` 域
- 新增 `ingestion` 域
- 新增 `system_domain` 域
- 顶层路由重组为 `standard-data/ingestion/analysis/ai/system`

10. 统计链路调整：
- 船舶区域归属统计优先使用 `current_region_id` 与 `region_address_relation`

11. 工程结构重组：
- 新增 `app/domain/*`
- 新增 `app/infrastructure/*`
- 新增 `app/jobs/*`
- 新增 `app/ai/prompts|parsers|evaluators|explainers|orchestration`

12. README 重写：
- 按一期定位重写启动、迁移、初始化、接口与部署说明

### 废弃说明
1. 废弃启动自动建表（`create_all`）。
2. 废弃旧迁移主链（已归档，不再用于新环境）。
3. 废弃以 `region.main_rivers/main_cities` 作为正式关系表达（保留字段仅作过渡兼容）。
4. 废弃 `transport_node.region_id` 作为正式区域归属主表达（保留字段仅作兼容读取）。
