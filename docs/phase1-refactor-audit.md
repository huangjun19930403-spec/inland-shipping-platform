# Phase 1 旧主线识别与返工清场审计

更新时间：2026-03-19
范围：仅做“旧主线识别 + 清场方案”，不做大规模业务改造。

---

## 1. 当前项目真实主执行链路（事实链路）

### 1.1 应用入口
1. `main.py` 注册 `app.api.v1.api_router`，统一前缀 `/api/v1`。
2. `app/api/v1/__init__.py` 把请求分发到 5 个域入口：
   - `/standard-data` → `app/api/v1/standard_data/router.py`
   - `/ingestion` → `app/api/v1/ingestion/router.py`
   - `/analysis` → `app/api/v1/analysis/router.py`
   - `/ai` → `app/api/v1/ai/router.py`
   - `/system` → `app/api/v1/system_domain/router.py`

### 1.2 API 请求实际落点（router 层）

#### A. standard_data 域（当前是“新入口 + 旧路由主逻辑”）
1. `app/api/v1/standard_data/router.py` 只是聚合器，实际逻辑落在旧路由：
   - `app/api/v1/address/router.py`
   - `app/api/v1/cargo/router.py`
   - `app/api/v1/vessel/router.py`
   - `app/api/v1/route/router.py`

#### B. ingestion 域（当前是“新旧混合链路”）
1. `app/api/v1/ingestion/router.py` 同时包含两类逻辑：
   - 通过 `include_router` 转发到旧 `app/api/v1/freight/router.py`（货源文本/确认/手工录入）
   - 自身直接写数据库或直调旧 service（TMS raw、AIS 动态、Excel 导入）

#### C. analysis 域（仍由旧 service 主导）
1. `app/api/v1/analysis/router.py` 直接调用 `AnalysisService`。

#### D. ai 域（router 直接持有数据库逻辑）
1. `app/api/v1/ai/router.py` 内直接 `get_db + select(...)`，并直接创建 Repository。
2. 仍直接调 `app.tasks.ai_tasks.trigger_cargo_parse`。

#### E. system 域（新入口壳 + 旧路由主逻辑）
1. `app/api/v1/system_domain/router.py` 只是聚合器，实际逻辑落在：
   - `app/api/v1/auth/router.py`（router 直接操作系统模型）
   - `app/api/v1/system/router.py`（router 直接操作系统模型）
   - `app/api/v1/audit/router.py`（通过旧 `AuditService`）

### 1.3 router 实际调用的 service
1. `address/router.py` → `AddressService`
2. `cargo/router.py` + `freight/router.py` → `CargoService`
3. `vessel/router.py` + `ingestion/router.py`（部分）→ `VesselService`
4. `route/router.py` → `RouteService`
5. `analysis/router.py` → `AnalysisService`
6. `audit/router.py` → `AuditService`
7. `ai/router.py` / `auth/router.py` / `system/router.py`：大量逻辑绕过 service，直接 DB + Repository/Model

### 1.4 service 实际依赖（repository / model / task）
1. `AddressService`
   - Repository：`AddressRepository`
   - 审核：`AuditService` → `AuditRepository`
   - 模型：`app.models.address`, `app.models.audit`
2. `CargoService`
   - Repository：`CargoRepository`, `AddressRepository`, `AiRepository`
   - 审核：`AuditService` → `AuditRepository`
   - 模型：`app.models.cargo`, `app.models.audit`
3. `VesselService`
   - Repository：`VesselRepository`
   - 审核：`AuditService`
   - 任务触发：内部调 `app.tasks.stat_tasks.refresh_vessel_static_stats`
   - 模型：`app.models.vessel`, `app.models.audit`
4. `RouteService`
   - Repository：`RouteRepository`
   - 模型：`app.models.route`
5. `AnalysisService`
   - Repository：`AnalysisRepository`
   - 统计触发：`app.tasks.stat_tasks.daily_stat_job`, `refresh_all_vessel_stats`
6. `AuditService`
   - Repository：`AuditRepository`
   - 额外行为：对业务表审核状态做直接 SQL 更新

### 1.5 task / workflow 实际主链路
1. 货源 AI 解析主链路：
   - `freight/router.py` 或 `ai/router.py` 触发 `app.tasks.ai_tasks.trigger_cargo_parse`
   - `ai_tasks` 调 `app.workflows.cargo_parse_workflow.CargoParseWorkflow`
   - Workflow 调 `app.agents.cargo_agent.CargoAgent`
   - Agent 调 `app.tools.cargo_tools.CargoParseTextTool` + `app.tools.entity_match_tools.EntityMatchTool`
   - 最终回写 `CargoAiParseResult` / `AiCallLog` / `CargoRawMessage.status`
2. 统计主链路：
   - `freight/router.py` 确认/录入后触发 `app.tasks.stat_tasks.refresh_cargo_stats`
   - `analysis/router.py` 可手动触发 `daily_stat_job` / `refresh_all_vessel_stats`
   - `main.py` DEBUG 模式加载 `app.tasks.scheduler.setup_scheduler`，定时调度旧 `stat_tasks`
3. `app/jobs/*.py` 当前不是主链路，只是对 `app/tasks/*` 的别名封装。

### 1.6 主链路速查表（router → service → repository/model → task）

| 入口 | 实际落点 | service 层 | repository/model 层 | task/workflow |
| --- | --- | --- | --- | --- |
| `/api/v1/standard-data/address/**` | `app/api/v1/address/router.py` | `AddressService` | `AddressRepository` + `AuditRepository` + `app.models.address/audit` | 无直接 task |
| `/api/v1/standard-data/commodity/**` | `app/api/v1/cargo/router.py` | `CargoService` | `CargoRepository` + `AddressRepository` + `AiRepository` + `AuditRepository` + `app.models.cargo/audit` | 无直接 task |
| `/api/v1/standard-data/vessel/**` | `app/api/v1/vessel/router.py` | `VesselService` | `VesselRepository` + `AuditRepository` + `app.models.vessel/audit` | service 内触发 `stat_tasks.refresh_vessel_static_stats` |
| `/api/v1/standard-data/route/**` | `app/api/v1/route/router.py` | `RouteService` | `RouteRepository` + `app.models.route` | 无直接 task |
| `/api/v1/ingestion/cargo/text`、`/parse-result/*/confirm`、`/freight` | `app/api/v1/freight/router.py`（经 `ingestion/router.py` 转发） | `CargoService` | `CargoRepository` + `app.models.cargo` | `ai_tasks.trigger_cargo_parse`、`stat_tasks.refresh_cargo_stats` |
| `/api/v1/ingestion/cargo/tms/raw` | `app/api/v1/ingestion/router.py` | 无（router 直写） | `CargoRepository` + `TmsCargoRaw` | 无 |
| `/api/v1/analysis/run-stats`、`/run-stats/ship` | `app/api/v1/analysis/router.py` | `AnalysisService` | `AnalysisRepository` + `app.models.analysis` | `stat_tasks.daily_stat_job`、`refresh_all_vessel_stats` |
| `/api/v1/ai/reparse/*` | `app/api/v1/ai/router.py` | 无（router 直写） | 直接 `get_db + select(CargoRawMessage)` + `AiRepository` | `ai_tasks.trigger_cargo_parse` |
| `/api/v1/system/auth/*`、`/system/users*` | `app/api/v1/auth/router.py`、`app/api/v1/system/router.py` | 无（router 直写） | 直接 `get_db + SysUser/SysRole/SysUserRole` | 无 |
| `main.py` DEBUG 生命周期 | `lifespan()` | 无 | 无 | `tasks.scheduler.setup_scheduler` → `stat_tasks.daily_stat_job` |

---

## 2. 哪些“新架构目录”目前只是壳层

1. `app/api/v1/standard_data/router.py`
   - 仅 `include_router`，没有接管业务编排。
2. `app/api/v1/system_domain/router.py`
   - 仅 `include_router`，没有接管业务编排。
3. `app/domain/*/__init__.py`
   - 只是 re-export `app/services/*`，并未形成独立 domain 实现。
4. `app/jobs/cargo_stats.py`, `app/jobs/ship_stats.py`, `app/jobs/region_compute.py`
   - 只是旧 `app.tasks.stat_tasks` 的函数别名。
5. `app/jobs/route_compute.py`
   - 仅返回占位信息，不承担真实计算。
6. `app/infrastructure/db/__init__.py`
   - 只是 re-export `app.core.database`。
7. `app/infrastructure/cache|mq|llm|storage/__init__.py`
   - 仅占位说明，无实际适配实现。
8. `app/ai/parsers|evaluators|explainers|orchestration|prompts/__init__.py`
   - 仅目录声明；实际 AI 主逻辑仍在 `app/workflows`, `app/agents`, `app/tools`, `app/ai/*.py`。

---

## 3. 新旧并存且职责冲突模块

1. `app/api/v1/ingestion/router.py`
   - 同时包含“新入口”与“旧 freight 路由转发 + 直接 DB 逻辑”。
2. `app/api/v1/standard_data/router.py`
   - 新域名入口存在，但核心逻辑仍在旧地址/货品/船舶/航线路由。
3. `app/api/v1/system_domain/router.py`
   - 新域名入口存在，但系统与认证仍由旧路由承载。
4. `app/core/dependencies.py`
   - 依赖注入仍绑定 `app/services/*` 旧实现。
5. `app/jobs/*` vs `app/tasks/*`
   - 表面上有 jobs 分层，但执行主线仍在 tasks。
6. `app/ai/*` 新目录 vs `app/workflows|agents|tools`
   - AI 目录结构与真实执行结构并存，主逻辑未收口到目标架构。
7. router 直写 DB（`ai/router.py`, `auth/router.py`, `system/router.py`, `ingestion/router.py` 部分）
   - 与“API 层仅做参数与响应”目标冲突。

---

## 4. 旧文件处置策略（按阶段执行）

### 4.1 旧文件必须删除（完成新主线接管后执行）

1. `app/api/v1/address/`
2. `app/api/v1/cargo/`
3. `app/api/v1/vessel/`
4. `app/api/v1/route/`
5. `app/api/v1/freight/`
6. `app/api/v1/auth/`
7. `app/api/v1/system/`
8. `app/api/v1/audit/`

删除条件：对应业务域在新路径下完成同等或更完整能力接管，并通过接口回归后删除。

### 4.2 旧文件必须迁入 legacy（不能立刻删除，但必须退出主入口）

1. `app/services/address_service.py`
2. `app/services/cargo_service.py`
3. `app/services/vessel_service.py`
4. `app/services/route_service.py`
5. `app/services/analysis_service.py`
6. `app/services/audit_service.py`
7. `app/tasks/stat_tasks.py`
8. `app/tasks/ai_tasks.py`
9. `app/tasks/scheduler.py`
10. `app/workflows/cargo_parse_workflow.py`
11. `app/agents/cargo_agent.py`
12. `app/tools/cargo_tools.py`
13. `app/tools/entity_match_tools.py`
14. `app/consumers/tms_cargo_consumer.py`
15. `app/consumers/vessel_dynamic_consumer.py`

迁入目的：保留历史实现用于对照与回退，但禁止继续作为生产主链路入口。

### 4.3 旧文件可暂时保留，但不得再作为主入口

1. `app/repositories/*.py`
   - 可继续作为数据访问实现基座，但只能被新 domain service 调用。
2. `app/models/*.py`
   - 可继续作为 ORM 基础，但后续按一期口径持续演进字段与关系。
3. `app/ai/providers/*.py`, `app/ai/llm_registry.py`, `app/ai/prompt_manager.py`, `app/ai/entity_cache.py`
   - 可复用，但要由新 `app/ai/*` 业务编排模块接管调用入口。
4. `app/tasks/celery_app.py`
   - 暂保留执行器配置，但任务路由要改为新 jobs 主线。

---

## 5. 哪些新文件必须重写（当前只是转发/壳层）

1. `app/api/v1/standard_data/router.py`
2. `app/api/v1/ingestion/router.py`
3. `app/api/v1/system_domain/router.py`
4. `app/core/dependencies.py`
5. `app/domain/__init__.py`
6. `app/domain/address/__init__.py`
7. `app/domain/commodity/__init__.py`
8. `app/domain/vessel/__init__.py`
9. `app/domain/cargo/__init__.py`
10. `app/domain/route/__init__.py`
11. `app/domain/analysis/__init__.py`
12. `app/domain/audit/__init__.py`
13. `app/jobs/cargo_stats.py`
14. `app/jobs/ship_stats.py`
15. `app/jobs/region_compute.py`
16. `app/jobs/route_compute.py`
17. `app/infrastructure/db/__init__.py`
18. `app/infrastructure/cache/__init__.py`
19. `app/infrastructure/mq/__init__.py`
20. `app/infrastructure/llm/__init__.py`
21. `app/infrastructure/storage/__init__.py`
22. `app/ai/parsers/__init__.py`
23. `app/ai/evaluators/__init__.py`
24. `app/ai/explainers/__init__.py`
25. `app/ai/orchestration/__init__.py`
26. `app/ai/prompts/__init__.py`
27. `app/core/database.py`（移除 `init_db/create_all` 开发建表入口，统一迁移路径）

---

## 6. 每个业务域最终新主线文件（目标接管点）

以下是本次返工后“应成为主入口”的文件集合（本阶段仅定义，不实施大改）：

1. standard_data
   - `app/api/v1/standard_data/address.py`
   - `app/api/v1/standard_data/commodity.py`
   - `app/api/v1/standard_data/vessel.py`
   - `app/api/v1/standard_data/route.py`
   - `app/domain/address/service.py`
   - `app/domain/commodity/service.py`
   - `app/domain/vessel/service.py`
   - `app/domain/route/service.py`

2. ingestion
   - `app/api/v1/ingestion/cargo.py`
   - `app/api/v1/ingestion/tms.py`
   - `app/api/v1/ingestion/vessel.py`
   - `app/api/v1/ingestion/batch.py`
   - `app/domain/cargo/ingestion_service.py`
   - `app/domain/vessel/dynamic_ingestion_service.py`

3. analysis
   - `app/api/v1/analysis/cargo.py`
   - `app/api/v1/analysis/vessel.py`
   - `app/domain/analysis/service.py`
   - `app/jobs/cargo_stats.py`（真实实现）
   - `app/jobs/ship_stats.py`（真实实现）

4. ai
   - `app/api/v1/ai/parse_records.py`
   - `app/api/v1/ai/match_suggestions.py`
   - `app/api/v1/ai/prompts.py`
   - `app/api/v1/ai/explain.py`
   - `app/ai/parsers/cargo_text_parser.py`
   - `app/ai/evaluators/data_quality.py`
   - `app/ai/explainers/analysis_explainer.py`
   - `app/ai/orchestration/cargo_parse_pipeline.py`

5. system
   - `app/api/v1/system/auth.py`
   - `app/api/v1/system/user.py`
   - `app/api/v1/system/role.py`
   - `app/api/v1/system/audit_task.py`
   - `app/domain/audit/service.py`

---

## 7. 三张强制清单

### A. delete list

1. `app/api/v1/address/`
2. `app/api/v1/cargo/`
3. `app/api/v1/vessel/`
4. `app/api/v1/route/`
5. `app/api/v1/freight/`
6. `app/api/v1/auth/`
7. `app/api/v1/system/`
8. `app/api/v1/audit/`

### B. legacy move list

1. `app/services/address_service.py`
2. `app/services/cargo_service.py`
3. `app/services/vessel_service.py`
4. `app/services/route_service.py`
5. `app/services/analysis_service.py`
6. `app/services/audit_service.py`
7. `app/tasks/stat_tasks.py`
8. `app/tasks/ai_tasks.py`
9. `app/tasks/scheduler.py`
10. `app/workflows/cargo_parse_workflow.py`
11. `app/agents/cargo_agent.py`
12. `app/tools/cargo_tools.py`
13. `app/tools/entity_match_tools.py`
14. `app/consumers/tms_cargo_consumer.py`
15. `app/consumers/vessel_dynamic_consumer.py`

### C. rewrite list

1. `app/api/v1/standard_data/router.py`
2. `app/api/v1/ingestion/router.py`
3. `app/api/v1/system_domain/router.py`
4. `app/core/dependencies.py`
5. `app/core/database.py`
6. `app/domain/__init__.py`
7. `app/domain/address/__init__.py`
8. `app/domain/commodity/__init__.py`
9. `app/domain/vessel/__init__.py`
10. `app/domain/cargo/__init__.py`
11. `app/domain/route/__init__.py`
12. `app/domain/analysis/__init__.py`
13. `app/domain/audit/__init__.py`
14. `app/jobs/cargo_stats.py`
15. `app/jobs/ship_stats.py`
16. `app/jobs/region_compute.py`
17. `app/jobs/route_compute.py`
18. `app/infrastructure/db/__init__.py`
19. `app/infrastructure/cache/__init__.py`
20. `app/infrastructure/mq/__init__.py`
21. `app/infrastructure/llm/__init__.py`
22. `app/infrastructure/storage/__init__.py`
23. `app/ai/parsers/__init__.py`
24. `app/ai/evaluators/__init__.py`
25. `app/ai/explainers/__init__.py`
26. `app/ai/orchestration/__init__.py`
27. `app/ai/prompts/__init__.py`

---

## 8. 当前主线代码入口（本阶段结论）

当前“真实主线入口”不是 `app/domain/*` 或 `app/jobs/*`，而是：

1. API 主入口：`main.py` → `app/api/v1/__init__.py`
2. 业务主逻辑：`app/api/v1/address|cargo|vessel|route|freight|analysis|ai|auth|system|audit/router.py`
3. 核心业务实现：`app/services/*.py`
4. 核心异步与统计：`app/tasks/stat_tasks.py`, `app/tasks/ai_tasks.py`, `app/tasks/scheduler.py`
5. AI 解析编排：`app/workflows/cargo_parse_workflow.py` + `app/agents/cargo_agent.py` + `app/tools/*.py`

即：当前仍是“旧主线在跑，新目录在包裹”。
