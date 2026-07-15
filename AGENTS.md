# Repository Agent Guide

日期：2026-05-22

本仓库正在建设 Navigation Routing Engine。后续 coding agent 必须先读本文，按轮次增量工作，不得把后续轮次提前做掉。

## 1. 必读文档顺序

处理 navigation engine 相关任务前，按顺序阅读：

1. `docs/NAVIGATION_ENGINE_MASTER_PLAN.md`
2. `docs/NAVIGATION_ENGINE_DATABASE_DESIGN.md`
3. `docs/NAVIGATION_ENGINE_FLOW_DESIGN.md`
4. `docs/NAVIGATION_ENGINE_CENTERLINE_AND_GRAPH_RULES.md`
5. `docs/NAVIGATION_ENGINE_TEST_FIXTURES.md`
6. `docs/NAVIGATION_ENGINE_PERFORMANCE_RULES.md`
7. `docs/NAVIGATION_ENGINE_ROUND_PLAN.md`
8. `docs/NAVIGATION_ENGINE_EXECUTION_RECEIPT_TEMPLATE.md`
9. `docs/NAVIGATION_DATA_AUDIT.md`

`docs/NAVIGATION_ENGINE_DESIGN.md` 是 Round 1 baseline，只作为历史上下文。

## 2. 代码导航入口

后端模型：

- `app/models/address.py`: 当前 `NavigationChannel*`、`TransportNode`、`NavigationConstraintPoint/Profile` 仍在这里。
- `app/models/route.py`: `ShippingRoutePlan*` 和轨迹版本模型。
- `app/models/__init__.py`: 模型注册入口。

航道和 seed：

- `scripts/seed_data/navigation/navigation_channels.json`: 当前 104 个航道 seed 来源。
- `scripts/seed_data/navigation/navigation_real_scope.json`: 真实江苏/长三角生产 scope 配置。
- `scripts/seed_data/`: seed 和初始化相关脚本。
- `data_audit/navigation_channel_match_report.json`: 当前航道/边界审计摘要。
- `tests/fixtures/navigation/navigation_mvp_acceptance.json`: 历史/测试 fixture，只能用于测试，不得进入本地演示数据库、生产 seed 或 active graph。

Route 链路：

- `app/tasks/route_tasks.py`: `route.generate_track_version` 异步任务入口。
- `app/modules/route/service.py`: 当前 route 业务服务，后续接入前应先拆分。
- provider/client 相关文件用 `rg "HifleetRouteClient|AMap|generate_track_version|FALLBACK|TRACK_VERSION_SOURCES"` 查找。

API 和前端：

- 后端路由用 `rg "APIRouter|navigation-channels|routes"` 定位。
- 前端页面和 API 类型按现有目录结构用 `rg "navigation|route|track"` 定位。

## 3. 常用测试命令

按改动范围选择，不要机械全跑但必须说明选择理由。

后端：

```bash
.venv/bin/python -m py_compile main.py
.venv/bin/pytest
.venv/bin/python -m scripts.seeds.validation.local_acceptance
.venv/bin/python -m scripts.seeds.validation.foundation_data_acceptance
```

前端：

```bash
npm run type-check
npm run build
npm run e2e
```

文档轮：

```bash
git status --short
rg "NO_APPROVED_CENTERLINE|UNKNOWN_CONSTRAINT_DATA|ROUTE_WATER_FALLBACK_MODE|REFERENCE_HIFLEET" docs AGENTS.md
```

## 4. Navigation Engine 硬约束

- 不提前做后续轮次。
- 不修改本轮范围外的 Python/TypeScript 代码。
- 不覆盖用户已有未提交改动。
- 不覆盖 seed boundary；river 是原始水域资产，seed boundary 是业务航道包络资产。
- 不把 polygon、water area、boundary 当路径搜索对象。
- 路径搜索只能基于 `navigation_graph_edge`。
- 无 approved/current centerline 的航道不得进入 graph。
- `HIFLEET_REFERENCE` 不能直接发布为正式 centerline。
- `provider_code=AUTO` 的 WATER 段后续必须走 `NavigationRoutingEngineService`。
- HiFleet 只能作为显式 reference provider，不能自动设为当前业务轨迹。
- 生产默认禁用水路 fallback 假路线；演示或测试必须显式标识。
- 第一阶段不要迁移旧 `NavigationChannel*` 类到 `app/models/navigation.py`；先新增新表，避免破坏 address API、seed 和 imports。
- 约束缺失允许路径生成，但必须产生 `UNKNOWN_CONSTRAINT_DATA`、扣分、前端提示，结果最高 `READY_WITH_WARNING`。
- 本地演示和页面默认体验必须使用真实 `revier.zip` 水系资产、清洗 seed 航道/边界/运输节点；不得运行 `seed_mvp_navigation_data` 作为默认演示数据。
- 测试 fixture 可以保留在 `tests/fixtures`，但不得写入生产 seed、页面默认值或 active graph。
- Graph build 默认 scope 使用 `REAL-JS-YRD` 等真实业务命名，不得默认 `MVP`。

## 5. 每轮最终回复

每轮完成后，最终回复必须包含 `docs/NAVIGATION_ENGINE_EXECUTION_RECEIPT_TEMPLATE.md` 中定义的执行回执。尤其要声明：

- 做了什么。
- 没做什么。
- 跑了什么测试或检查。
- 是否越界。
- 是否提前做了后续轮次。

<!-- BEGIN CODEX BACKEND SKILLS PACK -->
## Codex backend change controls

These rules apply to all work in this repository.

### Required workflow

- For every backend code change, use the `backend-minimal-change` skill.
- For defects, configuration failures, Elasticsearch, Docker, Celery, or runtime issues, use `debug-before-edit` before changing code.
- When an endpoint is consumed by the existing frontend, use `api-contract-guard`.
- For database configuration, migrations, or Docker database writes, use `safe-database-config`.
- Before claiming completion, use `verify-before-done` and provide fresh command evidence.

### Permanent constraints

- Make the smallest coherent change that satisfies the request.
- Search for and reuse existing implementations before creating files or abstractions.
- Do not refactor unrelated code or rewrite working modules to a preferred architecture.
- Preserve existing routes, request parameters, response schemas, and frontend compatibility.
- Do not modify the frontend repository unless the user explicitly requests it.
- Preserve uncommitted user changes.
- Never run `git reset --hard`, `git clean -fd`, delete Docker volumes, recreate the database, or clear business data.
- Do not put credentials in source code, committed files, test fixtures, documentation, or logs.
- More than 8 modified files or 300 added production lines is a scope warning, not permission to continue. Reassess reuse and explain why the budget must be exceeded.
- Add regression tests only for behavior changed by the task; do not build broad new test infrastructure for a local fix.
- Do not claim success without testing the changed behavior and checking the final Git diff.
<!-- END CODEX BACKEND SKILLS PACK -->
