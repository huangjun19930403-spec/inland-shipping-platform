# Seed And Initialization

## Explicit Profiles

Seed must be run with an explicit profile:

```bash
.venv/bin/python -m scripts.seeds.cli --profile production
.venv/bin/python -m scripts.seeds.cli --profile local-demo
.venv/bin/python -m scripts.seeds.cli --profile test
```

If no profile is provided, the script fails intentionally.
`demo` is accepted as an alias for `local-demo`.

Seed profile dispatch lives under `scripts/seeds/`. Legacy root `scripts/seed_*.py` entrypoints have been removed.

Current seed code layout:

- `scripts/seeds/loaders/`: production loaders only.
- `scripts/seeds/demo/`: local-demo orchestration, cleanup and experience data.
- `scripts/seeds/test/`: automated-test profile and fixtures.
- `scripts/seeds/curation/`: read-only/write-curated tools for generating final JSON seed data.
- `scripts/seeds/validation/`: local and foundation acceptance checks.

## Production Seed

`production` is the safe production preset. It does not create demo freights, demo vessels, sample AIS tracks or local analysis facts.
It validates `scripts/seed_data/production_manifest.json` before loading result data files.

Execution order:

1. dictionaries and code sequences
2. administrative regions and boundaries
3. navigation channels and navigation constraints
4. commodity taxonomy and standard commodities
5. business regions and transport nodes
6. production vessel profiles and TMS historical freights
7. analysis job definitions
8. roles, permissions, menus and system configs

Production seed includes:

- dictionaries and dictionary items
- code sequences
- administrative regions and boundaries
- navigation channels, channel boundaries and channel segments
- commodity taxonomy and standard commodities
- navigation constraint points/profiles
- roles, permissions, production menus, system configs
- AI, map, AIS, HiFleet, COS and ES configuration skeletons

Production result data currently listed in the manifest:

- `scripts/seed_data/admin_region/admin_region_raw.json`
- `scripts/seed_data/admin_region/admin_region_boundary_city_raw.json`
- `scripts/seed_data/navigation/navigation_channels.json`
- `scripts/seed_data/navigation_constraints/constraint_points.json`
- `scripts/seed_data/commodity/commodity_categories.json`
- `scripts/seed_data/commodity/commodity_types.json`
- `scripts/seed_data/commodity/commodity_standards.json`
- `scripts/seed_data/address/business_regions.json`
- `scripts/seed_data/address/transport_nodes.json`
- `scripts/seed_data/vessel/production_vessels.json`
- `scripts/seed_data/freight/tms_freights.json`

Raw attachments and intermediate cleaning outputs must not be imported directly by production seed.
Current administrative-region coverage is pinned by tests: 3244 region rows, 404 boundary rows, and all 370 city-level regions have boundary geometry and bounding boxes.
Current commodity production seed uses the national/intermodal cargo-classification layer plus inland-port business extensions: 22 categories, 126 types and 169 standards. Every type has at least one enabled standard commodity, and the Round 3 TMS commodity attachment coverage check is read-only:

```bash
python3 -m scripts.seeds.curation.commodity_seed --input /Users/hj/Downloads/货品数据.csv
```

## Demo Seed

`demo` and the compatible `local-demo` profile are for local demonstration only. The profile resets a local database, loads production seed, imports local private config, tests external integrations, then appends explicitly marked demo chain data.

It refuses to reset non-local environments.

Local-demo uses the production curated seed as its base layer. Large dimensions are intentionally sampled for local usability: vessel seed defaults to the highest-value 20,000 production profiles, sorted by TMS/high-value source, profile completeness, contact availability, Chinese display name and capacity. Set `SEED_VESSEL_LIMIT=full` to load all production vessels locally.

Demo profile steps:

1. reset local database
2. seed production preset
3. seed local private config
4. assert external config is complete
5. run external connection tests
6. purge legacy E2E data
7. seed experience scenarios from `scripts/seed_data/demo/demo_scenarios.json`
8. run local-demo analysis facts from the seeded production/demo base
9. run local acceptance verification

The demo profile no longer calls `seed_foundation_samples.py`, `seed_vessel_samples.py`, `seed_freight_samples.py` or `seed_route_samples.py`. Demo records are visible through `FR-DEMO-*`, `FCA-DEMO-*`, `DEMO_ROUTE_*`, `DEMO_AIS_*` and `LOCAL_DEMO`; they are not production evidence.
The local cleanup step removes legacy `E2E_*` rows and old automated constraint rows named `自动化新增约束点-*`.

## Test Seed

`test` is reserved for automated test fixtures. It creates missing schema for isolated SQLite test databases, runs the production base seed, then appends only `TEST_*` / `TEST-FR-*` fixture data and deterministic test analysis facts. It must not create `FR-DEMO-*` rows or `LOCAL_DEMO` evidence.

Test profile also samples large dimensions for speed. Vessel seed defaults to 1,500 production profiles in `test`; set `SEED_VESSEL_LIMIT=full` only for explicit full-volume test runs.

## Experience Scenario Seed

`scripts.seeds.demo.experience.main` is a local-demo-only补数层. It does not run in `production`.

It adds scenario-coherent rows for:

- 42 main `FR-DEMO-*` freight samples plus local-demo historical comparable samples for rate estimation.
- `FBT-DEMO-*`, `FTI-DEMO-*`, `FCU-DEMO-*`, `FCA-DEMO-*` source evidence.
- raw quote text preserving both shipper quote and owner/boat-owner quote.
- AIS snapshot `DEMO_AIS_EXPERIENCE_CURRENT`.
- node snapshots for Taicang, Jiangyin, Nanjing and Wuhu.
- route snapshots for Taicang-Wuhu, Taicang-Nanjing and Changxing-Wuhu.
- freight-context vessel candidate analyses for every computable main demo freight, including the top visible opportunity rows.
- node surrounding vessel observations, route-segment samples and navigation-constraint evidence.

Realtime ES strategy:

- The script first attempts to query configured realtime ES for seeded MMSI values.
- If fewer than 8 usable positions are returned, it writes mirror data with `source_index="DEMO_ES_MIRROR"`.
- `DEMO_ES_MIRROR` is only a local-demo fallback. It must never be used as production analytical evidence.

The experience seed is designed to support manual page checks for:

- opportunity sample library rows.
- freight-to-vessel matching with high, medium, stale-AIS, high-risk, blocked-constraint and wrong-ship-type candidates.
- node surrounding vessel observations.
- route segment match samples.
- navigation constraints with `PASS`, `WARNING`, `BLOCKED` and `UNKNOWN`.
- quote-ready freight rows with origin node, destination node, commodity, tonnage and current shipper quote.
- at least five quote-ready `FR-DEMO-*` rows whose raw evidence can populate智能报价测算 and运价预估测算.
- at least five visible `FR-DEMO-*` opportunity rows whose supply-demand fit page can show candidate vessels without an empty demo state.

Known-price quote context parses owner/boat-owner quote and advanced configuration from the existing `FBT-DEMO-*` / `FTI-DEMO-*` / `FCA-DEMO-*` evidence. Rate estimation uses the added local-demo historical comparable freight rows, with `LOCAL_DEMO` clearly reported as a demo evidence layer. Pricing decisions are created only when a user or test runs the pricing APIs.

## Local Fresh Database

For a production-style local database without demo/test data:

```bash
rm -f inland_shipping.db
alembic upgrade head
.venv/bin/python -m scripts.seeds.cli --profile production
```

Use this when validating that `001_initial_schema` can build the database from scratch.

For the normal local debugging/demo database:

```bash
.venv/bin/python -m scripts.seeds.cli --profile local-demo
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

`local-demo` resets only a local/dev/test database, then loads production curated data, local private config from `.env.local`, demo business chains and analysis facts. It does not print raw private config values.

For automated-test fixture verification:

```bash
DATABASE_URL=sqlite+aiosqlite:////private/tmp/inland_seed_test.db \
  .venv/bin/python -m scripts.seeds.cli --profile test
```

Expected isolation after successful runs:

- `production`: `FR-TMS-*` exists; `FR-DEMO-*`, `TEST-FR-*`, `DEMO_ROUTE_*`, `TEST_ROUTE_*` are zero.
- `local-demo`: production base exists; `FR-DEMO-*`, `FCA-DEMO-*`, `DEMO_ROUTE_*`, `DEMO_AIS_*`, `LOCAL_DEMO` and analysis facts exist; `TEST-FR-*` is zero.
- `test`: production base exists; `TEST-FR-*`, `TEST_ROUTE_*` and test analysis facts exist; `FR-DEMO-*` and `LOCAL_DEMO` are zero.

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
.venv/bin/python -m scripts.seeds.validation.local_acceptance
.venv/bin/python -m scripts.seeds.validation.foundation_data_acceptance
```

Production acceptance must confirm:

- no missing foundation data
- no old menu IA
- no legacy freight list entry
- no `E2E_%` pollution in main business data
- no production analysis depending on `LOCAL_SAMPLE` or `LOCAL_DEMO`

Static seed-profile acceptance also confirms that `scripts/seeds/production.py` does not import demo, local or sample seed modules, and that the demo runner does not call the legacy `seed_*_samples.py` scripts.
