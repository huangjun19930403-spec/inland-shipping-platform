# Seed And Initialization

## Explicit Profiles

Seed must be run with an explicit profile:

```bash
.venv/bin/python -m scripts.seed_system_init --profile production
.venv/bin/python -m scripts.seed_system_init --profile local-demo
```

If no profile is provided, the script fails intentionally.

## Production Seed

`production` is the safe production preset. It does not create demo freights, demo vessels, sample AIS tracks or local analysis facts.

Execution order:

1. `seed_builtin_dicts`
2. `seed_code_sequences`
3. `seed_admin_regions`
4. `seed_water_systems`
5. `seed_commodity_taxonomy`
6. `seed_commodity_standards`
7. `seed_navigation_constraints`
8. `seed_system_base`

Production seed includes:

- dictionaries and dictionary items
- code sequences
- administrative regions and boundaries
- water systems and water-system boundaries
- commodity taxonomy and standard commodities
- navigation constraint points/profiles
- roles, permissions, production menus, system configs
- AI, map, AIS, HiFleet, COS and ES configuration skeletons

Water-system seed rows are embedded in `scripts/seed_data/navigation_water_systems_v5.py`.
The source-assignment audit trail is kept as seed provenance at
`scripts/seed_data/water_system_source_assignment_v5.jsonl`, not as generated docs.

## Local Demo Seed

`local-demo` is for local demonstration only. It resets a local database, loads production seed, imports local private config, tests external integrations, then creates demo chain data.

It refuses to reset non-local environments.

Additional local-demo steps:

1. reset local database
2. seed production preset
3. seed local private config
4. assert external config is complete
5. run external connection tests
6. seed foundation samples
7. purge legacy E2E data
8. seed vessel samples
9. seed freight samples
10. seed analysis samples
11. seed audit samples
12. seed route samples
13. run local acceptance verification

Demo records and `LOCAL_SAMPLE` facts are not production evidence.

## Local Fresh Database

```bash
rm -f inland_shipping.db
alembic upgrade head
.venv/bin/python -m scripts.seed_system_init --profile production
```

Use this when validating that `001_initial_schema` can build the database from scratch.

## Menu Seed

The production menu seed creates these top-level visible roots:

- `OVERVIEW_ROOT`: 经营总览
- `FREIGHT_ROOT`: 货源洞察中心
- `VESSEL_ROOT`: 运力中心
- `ROUTE_ROOT`: 航线与区域中心
- `ANALYSIS_ROOT`: 运价与报价中心
- `AUDIT_ROOT`: 数据质量与治理
- `SYSTEM_ROOT`: 系统配置

Hidden legacy roots are kept only where necessary to avoid breaking existing database rows, and they are not visible in the product navigation.

## Configuration Preservation

`seed_system_base(preserve_existing_config_values=True)` preserves non-empty local runtime config values. Sensitive keys must come from environment variables or `.env.local`, not committed source.

## Validation

```bash
.venv/bin/python -m scripts.verify_local_acceptance
.venv/bin/python -m scripts.verify_foundation_data_acceptance
```

Production acceptance must confirm:

- no missing foundation data
- no old menu IA
- no legacy freight list entry
- no `E2E_%` pollution in main business data
- no production analysis depending on `LOCAL_SAMPLE`
