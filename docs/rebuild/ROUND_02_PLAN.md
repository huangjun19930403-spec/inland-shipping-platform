# Round 02 Plan - Database and Seed Rebuild

## Objective

Rebuild the backend schema and seed boundary so the project can start from an
empty database with one explicit migration and production-safe foundation data.

## Migration Work

- Replace the active Alembic chain with one explicit `001_initial_schema.py`.
- The migration must create the full production schema directly.
- It must not depend on SQLAlchemy metadata `create_all`.
- Remove tables that only support demo behavior or old module boundaries.
- Add or reshape tables for:
  - freight lifecycle
  - shipping opportunity
  - capacity pool
  - route and region intelligence
  - pricing decision
  - analysis insight and lineage
  - data quality workflow

## Seed Work

- Keep `scripts.seed_system_init` as the explicit profile entrypoint.
- Keep supported profiles:
  - `production`
  - `local-demo`
- Production seed must include:
  - dictionary and code sequences
  - roles, permissions, menus
  - system config skeleton
  - administrative regions and boundaries
  - water systems
  - transport node standards and navigation constraints
  - commodity categories, types, standards
  - analysis buckets
  - AI/external provider placeholders
- Local-demo seed must:
  - run after production seed
  - create demo freight, vessel, route, audit, and analysis records
  - mark every demo record with a visible source layer/version
  - never be required for production startup

## Guardrails

- No production fact may be generated with `LOCAL_SAMPLE`.
- Any non-computable analysis must return reasons instead of fake values.
- All new tables must have explicit ownership by one domain service.
- Every renamed/deleted table must be reflected in the regenerated docs later.

## Exit Criteria

- `alembic upgrade head` succeeds on an empty database.
- `SEED_PROFILE=production python -m scripts.seed_system_init` succeeds twice.
- Production seed contains foundation data but no demo freight/vessel/fake facts.
- `SEED_PROFILE=local-demo python -m scripts.seed_system_init` creates a complete,
  visibly marked demo chain.
- Backend tests and local acceptance probes are updated to the new schema.
