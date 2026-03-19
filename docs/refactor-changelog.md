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

### 2026-03-19（Phase 4：Jobs / Analysis Cutover）

1. 统计主实现切换到 `app/jobs/*`：
- 重写 `app/jobs/cargo_stats.py`，接管货源热力/趋势/货品排行/OD/渠道统计。
- 重写 `app/jobs/ship_stats.py`，接管区域热力/城市热力/载重吨分布/船龄分布快照。
- 重写 `app/jobs/region_compute.py`，改为调用新 `ship_stats` 动态快照主链。

2. 分析链路切断旧任务依赖：
- `app/domain/analysis/service.py` 手动重算入口改为调用 `app/jobs/*`。
- `app/tasks/scheduler.py` 每日任务改为调用新 jobs。
- `app/tasks/celery_app.py` include / beat / route 改为面向 `app/jobs.*`。

3. 写入触发链路切断旧任务依赖：
- `app/api/v1/ingestion/cargo.py` 改为触发 `run_cargo_stats`。
- `app/consumers/tms_cargo_consumer.py` 改为触发 `run_cargo_stats`。
- `app/consumers/vessel_dynamic_consumer.py` 改为触发 `run_ship_dynamic_stats`。
- `app/domain/vessel/service.py` 改为触发 `run_ship_static_stats`。

4. 旧任务退场：
- 迁移：`app/tasks/stat_tasks.py` -> `app/tasks/legacy/stat_tasks_legacy.py`。
- 新建：`app/tasks/stat_tasks.py` 仅保留 deprecated 兼容桥接，不再承载主实现。

5. 脚本链路同步更新：
- `scripts/seed_data.py` 与 `scripts/seed_cargo_test_data.py` 从旧 `stat_tasks` 切换到 `app/jobs/cargo_stats.py`。

6. 阶段文档：
- 新增 `docs/phase4-analysis-cutover.md`。

### 2026-03-19（Phase 5：数据库与模型收口）

1. 删除地址域旧兼容字段：
- `region.main_rivers/main_rivers_names/main_cities/main_cities_names`
- `transport_node.region_id`

2. 地址关系主链切换：
- `AddressService` 区域详情改为从 `region_waterway_relation` / `region_city_relation` 读取。
- 区域创建/更新请求改为 `waterway_ids`，城市归属由边界自动计算并同步关系表。

3. 航线分段主链补齐：
- Route Repository/Service/API 增加 `shipping_route_path_segment` 的新增、批量替换、删除能力。
- 新增约束：
  - `uk_route_path_node_sequence`
  - `uk_route_path_segment_sequence`

4. 审核域收口：
- 审核目标类型统一为 `CARGO_FREIGHT`。
- `_TARGET_TABLE_MAP` 修复 `CARGO_FREIGHT -> cargo_freight`，补充 `NODE_ALIAS -> node_alias`。

5. 迁移脚本：
- 新增 `alembic/versions/9d4d6be9f1a2_phase5_database_finalization.py`。
- 迁移内容包含：字段删除、路径唯一约束、审核类型数据迁移、遗留旧表清理（IF EXISTS）。

6. 种子脚本同步：
- `scripts/seed_data.py` 去除对已删除字段的写入。
- 新增区域关系初始化（`seed_region_relations`），将 `REGIONS` 常量中的河流/城市名称落到关系表。

### 2026-03-19（Phase 6：文档、测试、运行验证）

1. 迁移链修复（主链补齐 `code_sequence`）：
- 新增迁移 `alembic/versions/6b4b44f84a6a_phase6_add_code_sequence_table.py`。
- 新环境仅执行主迁移链即可完成编码序列表初始化，不再依赖 legacy 迁移。

2. 模型收口：
- `app/models/system.py` 新增 `CodeSequence` ORM 模型，统一纳入主元数据。

3. AI 链路可运行性修复：
- `app/tools/cargo_tools.py` 在 provider 未配置等异常场景下改为降级输出空解析结构，
  保证 `cargo_parse_workflow` 可继续产出 `CargoAiParseResult`（可追踪、可人工确认）。

4. 测试与验证补齐：
- 新增并通过 Phase 6 测试（API smoke / domain-service / jobs / AI parse smoke）。
- 执行全量 `pytest`：13 passed。

5. 文档交付：
- README 校对为真实可用接口与结构说明。
- 新增 `docs/phase6-runbook-and-validation.md`，记录迁移、初始化、启动、任务运行和在线接口验证结果。
