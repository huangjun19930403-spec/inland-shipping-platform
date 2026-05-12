# Rebuild Execution Log

Branch: `refactor/production-delete-rebuild`

## Locked Decisions

- Rebuild is delete-style: remove demo-backend surfaces instead of hiding them behind shell pages.
- Active migration chain is a single `001_initial_schema`.
- Production seed is broad and includes foundation data: administrative regions, water systems, commodities, dictionaries, constraints, permissions, menus and config skeletons.
- `local-demo` seed is isolated and may reset local DB.
- Frontend information architecture is business-led, not old admin-led.
- Old `GET /api/v1/freight` business list is deleted; shipping opportunity list is `/api/v1/freight/opportunities`.

## Round Summary

### Round 01

Audited baseline and identified the root issue: modules, tables and pages existed, but business mainline, data lineage, analysis actions and frontend context were not closed.

### Round 02

Rebuilt database baseline around a single explicit Alembic migration and separated production seed from local demo seed.

### Round 03

Started backend domain convergence and introduced production-oriented service/API entry points.

### Round 04

Introduced shipping opportunity APIs as the freight business entry and began moving UI consumers off the old freight list.

### Round 05

Implemented business workbench paths for freight insight, capacity center, route/region, quote and governance flows.

### Round 06

Tightened analysis logic so responses carry evidence, confidence, lineage, quality and recommended actions where migrated.

### Round 07

Introduced production map-state semantics and frontend `MapStatePanel`:

- READY
- PENDING
- FAILED
- NOT_COMPUTABLE

Blank maps and fake fallback lines are no longer accepted as production failure representation.

### Round 08

Fixed local page not changing after seed. Root cause was not an empty database; backend `sys_menu` still held old IA and frontend preferred backend menus over static fallback.

Completed:

- production menu seed rebuilt
- role menu grants aligned
- production seed rerun locally
- browser confirmed new menu
- frontend `fetchFreights` deleted
- backend `GET /api/v1/freight` deleted
- transportation opportunity page removed page-local KPI cards

Verified:

- backend focused pytest passed
- frontend type-check/build passed
- `GET /api/v1/freight` returns 404

### Round 09

Final documentation deletion/rebuild round.

Plan:

1. Delete old backend and frontend docs, including round fragments and stale historical reports.
2. Regenerate a unified final documentation pack.
3. Keep docs aligned with current code, seed profiles, production menus and deleted APIs.
4. Record remaining hardening honestly.
5. Verify backend tests, frontend checks and local page state.

Report:

- Old docs were removed.
- Final backend docs now consist of README plus product, backend, database, API, frontend, seed, deployment, test and execution-log documents.
- Frontend docs are reduced to README plus current frontend architecture and acceptance docs.
- Final docs no longer cite deleted pages, old branch names or historical migration chains as the source of truth.

## Final Documentation Pack

- `README.md`
- `docs/PRODUCT_SPEC.md`
- `docs/BACKEND_ARCHITECTURE.md`
- `docs/DATABASE_SCHEMA.md`
- `docs/API_REFERENCE.md`
- `docs/FRONTEND_ARCHITECTURE.md`
- `docs/SEED_AND_INITIALIZATION.md`
- `docs/DEPLOYMENT_AND_CONFIG.md`
- `docs/TEST_AND_ACCEPTANCE.md`
- `docs/REBUILD_EXECUTION_LOG.md`

## Remaining Work

- Continue splitting oversized backend service files.
- Continue splitting oversized frontend pages.
- Complete migration of chart-style analysis endpoints into the full insight contract.
- Expand E2E tests for cross-page analysis context propagation and map failure states.
