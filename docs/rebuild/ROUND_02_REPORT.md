# Round 02 Report - Backend Schema and Seed Boundary

## Completed

- Collapsed the active Alembic chain into one explicit migration:
  - `alembic/versions/001_initial_schema.py`
- Removed the old active patch migrations:
  - `0002_water_systems.py`
  - `0003_navigation_water_systems.py`
  - `0004_water_system_display_quality.py`
  - `0005_water_system_boundary_coordinate_system.py`
  - `0006_sys_menu_permission_code.py`
- Merged water-system foundation tables and menu permission binding into the
  single initial schema.
- Updated the vessel redline check to enforce the new single migration name.
- Added a production guard that prevents deterministic `LOCAL_SAMPLE` ship city
  and ship flow facts from being generated outside explicit demo/debug profiles.

## Production Seed Verification

Fresh database verification used:

```bash
DATABASE_URL=sqlite+aiosqlite:////tmp/prod_delete_round2_fresh.db DEBUG=false .venv/bin/alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:////tmp/prod_delete_round2_fresh.db SEED_PROFILE=production DEBUG=false .venv/bin/python -m scripts.seed_system_init --profile production
DATABASE_URL=sqlite+aiosqlite:////tmp/prod_delete_round2_fresh.db SEED_PROFILE=production DEBUG=false .venv/bin/python -m scripts.seed_system_init --profile production
```

Verified counts after running production seed twice:

| Object | Count |
| --- | ---: |
| alembic_version | 001_initial_schema |
| std_dict | 119 |
| code_sequence | 15 |
| admin_region | 3244 |
| admin_region_boundary | 404 |
| water_system | 120 |
| water_system_boundary | 120 |
| commodity_standard | 36 |
| navigation_constraint_point | 3 |
| sys_menu | 57 |
| sys_permission | 32 |
| system_config | 75 |

Production seed demo-data checks:

| Object | Count |
| --- | ---: |
| freight | 0 |
| freight_candidate | 0 |
| vessel_profile | 0 |
| shipping_route | 0 |
| LOCAL_SAMPLE ship city facts | 0 |
| LOCAL_SAMPLE ship flow facts | 0 |

## Additional Checks

```bash
python3 -m py_compile alembic/versions/001_initial_schema.py app/modules/analysis/statistics.py scripts/check_vessel_redlines.py
.venv/bin/python scripts/check_vessel_redlines.py
```

Both checks passed.

## Known Follow-up

- `scripts.seed_analysis_samples` still correctly refuses to run without sample
  ship and freight data. It is therefore not part of production seed and remains
  a local-demo concern.
- The schema is now migration-clean, but Round 03 must still remove scattered
  API/service ownership and expose business workbench contracts.
