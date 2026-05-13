# Test And Acceptance

## Backend Commands

```bash
.venv/bin/python -m py_compile main.py
.venv/bin/pytest
.venv/bin/python -m scripts.verify_local_acceptance
.venv/bin/python -m scripts.verify_foundation_data_acceptance
```

Focused checks used during the final rebuild:

```bash
.venv/bin/pytest tests/test_seed_profiles.py
.venv/bin/pytest tests/test_production_remediation.py::test_legacy_freight_list_route_is_not_business_entrypoint
.venv/bin/pytest tests/test_vessel_routes.py::test_vessel_seed_menu_groups_keep_business_entries_visible
.venv/bin/pytest tests/test_water_systems.py::test_water_system_backend_menus_are_initialized_for_visible_routes
```

## Frontend Commands

```bash
npm run type-check
npm run build
npm run e2e
```

## Manual Browser Acceptance

With backend on `127.0.0.1:8000` and frontend on `127.0.0.1:5173`:

1. Login as an admin user.
2. Confirm top-level menu:
   - 经营总览
   - 货源洞察中心
   - 运力中心
   - 航线与区域中心
   - 运价与报价中心
   - 数据质量与治理
   - 系统配置
3. Open `/freight/list`.
4. Confirm the page title is `机会样本库`.
5. Confirm it shows backend aggregate total, not current-page tonnage cards.
6. Open evidence drawer and confirm lineage/quality/actions render.
7. Open `/freight/supply-demand-fit` and confirm it enters freight-context candidate analysis.
8. Open flow map and quote simulator map-state panels.
9. Confirm blank maps are replaced by READY/PENDING/FAILED/NOT_COMPUTABLE state messaging.

## API Acceptance

```bash
curl -sS http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/api/v1/freight
curl -i http://127.0.0.1:8000/api/v1/freight/opportunities
```

Expected:

- `/health` returns `{"status":"ok"}`.
- `GET /api/v1/freight` returns 404.
- `GET /api/v1/freight/opportunities` returns 401 without auth and works with valid auth.

## Data Acceptance

Production seed must produce:

- dictionaries
- code sequences
- administrative regions and boundaries
- water systems and boundaries
- commodity taxonomy and standards
- navigation constraints
- roles, permissions, menus and config skeletons

Production seed must not produce:

- demo freight chain
- demo AIS tracks
- demo vessel risk narratives
- `LOCAL_SAMPLE` facts used as production evidence

Local-demo seed may create demo data, but it must stay visibly isolated and must not be used for production conclusions.

## Quality Gates

- No menu points to a missing route.
- 货源洞察中心菜单按 `货源态势总览 / 微信语义解析 / TMS 结构化入站 / 解析批次监控 / 候选证据池 / 机会样本库 / 供需适配分析 / 质量治理与回算` 排列。
- No frontend page uses deleted `fetchFreights`.
- No backend route exposes deleted `GET /api/v1/freight`.
- No KPI card represents page-local rows as whole-query metrics.
- Map failures show explicit provider state and business impact.
- Analysis outputs expose sample size, coverage, confidence, lineage and actions where migrated.

## Known Remaining Hardening

These are accepted as post-rebuild hardening items, not hidden completion:

- Oversized backend services remain in freight, analysis, vessel, address, route and system modules.
- Oversized frontend pages remain in vessel, freight, commodity and address modules.
- Some analysis endpoints still return chart-oriented payloads and need continued migration into the full insight contract.
- Full E2E coverage for every cross-page context jump is not complete.
