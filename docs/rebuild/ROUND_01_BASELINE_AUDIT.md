# Round 01 Backend Baseline Audit

## Current Baseline

The backend is not an empty shell. It already contains broad modules for
dictionary, address, commodity, vessel, freight, route, analysis, audit, files,
and system configuration. The issue is that these modules are organized as a
wide administration backend instead of a closed production analysis platform.

Observed local data snapshot:

| Object | Count |
| --- | ---: |
| freight | 248 |
| freight_candidate | 385 |
| vessel_profile | 140 |
| vessel_latest_position_snapshot | 137 |
| shipping_route | 1 |
| fact_ship_city_daily | 540 |
| fact_ship_flow_daily | 540 |
| analysis_job_run | 18 |

Analysis fact versions currently show:

| Fact source | Version | Count |
| --- | --- | ---: |
| fact_ship_city_daily | LOCAL_SAMPLE | 540 |
| fact_ship_flow_daily | LOCAL_SAMPLE | 540 |
| fact_freight_daily | FORMAL_ANALYSIS_V1 | 90 |

This confirms that production-looking analysis pages can be backed by local
sample facts, which must not survive into production analysis.

## Keep List

Keep as production capabilities, but refactor their ownership:

- System foundation:
  - users, roles, permissions, menus, system config, code sequences
  - audit records and approval workflow
- Foundation master data:
  - dictionaries and dictionary items
  - administrative regions and boundaries
  - business regions
  - water systems
  - transport nodes and navigation constraint points
  - commodity categories, types, standards, aliases, and rules
- Freight lifecycle:
  - raw source records
  - AI parse evidence
  - candidate freights
  - normalization issues
  - formal freights
  - source lineage between raw/candidate/formal records
- Vessel capacity:
  - vessel identity and profile
  - capacity dimensions
  - owners/operators/contact relationship history
  - certificates and recognition evidence
  - AIS/latest position freshness
  - quality issues and risk signals
- Route and region:
  - route object
  - route plan
  - route line/segment/node
  - provider route status and failure reason
- Analysis:
  - fact tables only when they carry data version, source layer, sample size,
    coverage, confidence, lineage, and not-computable reasons
  - job definitions and job runs only as backend/admin support
- Seed:
  - `production` profile for system and foundation data
  - `local-demo` profile for marked demo data

## Delete List

Delete or stop exposing these production surfaces in later rounds:

- Alembic history files beyond the single rebuilt `001_initial_schema`.
- Analysis routes or facts that depend on `LOCAL_SAMPLE` in production mode.
- Any API that only triggers demo-style aggregation and has no frontend business
  action or lineage contract.
- Any seed path where demo freight, demo vessels, fake AIS, fake route tracks,
  or sample analysis facts are required for system startup.
- Page/API concepts that treat analysis jobs as a primary business module for
  ordinary users.
- Duplicate vessel routers that expose asset, quality, compliance, AIS,
  recognition, and candidate analysis as isolated business entrypoints instead
  of capacity-center capabilities.
- Long-lived compatibility wrappers after the frontend migrates to the new
  workbench APIs.
- Historical docs that describe removed APIs, removed tables, or old branch
  status.

## Merge List

Merge scattered backend behavior into these production domain services:

| Target service | Current behavior to absorb |
| --- | --- |
| FreightLifecycleService | WeChat/TMS/manual source, parse, candidate, confirmation, normalization, formal freight |
| ShippingOpportunityService | freight + route + capacity + pricing + risk as one business object |
| CapacityPoolService | vessel profile, AIS freshness, certificates, relationships, risks, availability |
| SupplyDemandMatchService | candidate vessel analysis, freight fit, shortage explanation |
| RouteRegionIntelligenceService | nodes, regions, water systems, constraints, route computability, flow facts |
| PricingDecisionService | quote simulator, price bands, cost breakdown, route evidence |
| DataQualityWorkflowService | quality issues, repair tasks, affected analysis, recalculation |
| AnalysisLineageService | source tables, sample size, coverage, confidence, data version, action query |

## Backend Code Quality Findings

Large objects that must be split:

| File | Lines | Required action |
| --- | ---: | --- |
| `app/modules/freight/service.py` | 3501 | split lifecycle, parser, normalization, confirmation, lineage |
| `app/modules/vessel/ais/methods.py` | 2860 | split position query, snapshots, spatial observation, route/node analysis |
| `app/modules/vessel/governance_service.py` | 1803 | split issue detection, task workflow, audit bridge |
| `app/modules/analysis/service.py` | 1830 | split insight API, task API, lineage API |
| `app/modules/analysis/statistics.py` | 1813 | split fact builders and remove production local-sample generation |
| `app/modules/vessel/asset/methods.py` | 1385 | split asset read model and summary builders |

Round 03 will enforce a target of no domain service over 800 lines.

## Migration Boundary

Current Alembic chain contains `0001_platform_current_schema.py` through
`0006_sys_menu_permission_code.py`. The rebuild target is:

- delete old active migration chain
- create one explicit `001_initial_schema.py`
- include the full rebuilt production schema in that file
- do not use dynamic metadata `create_all`
- accept destructive local database rebuild

## Seed Boundary

Keep production seed as a first-class production capability. It must include:

- built-in dictionaries and dictionary items
- code sequences
- administrative regions and boundaries
- water systems
- commodity taxonomy and standard commodities
- navigation constraints and node standards
- system base records, menus, roles, permissions, config skeleton
- AI/external provider placeholder configuration

Move all of the following to local-demo only:

- demo vessels
- fake AIS/current position snapshots
- fake node/route observation snapshots
- demo freights and demo candidates
- fake route plans/tracks
- sample audit records
- sample analysis facts

## Round 02 Input Decisions

Round 02 may start from this audit without asking new product questions:

- rebuild database destructively
- keep production seed foundation data broad
- isolate demo/dev seed
- remove `LOCAL_SAMPLE` from production analysis
- build around shipping opportunity and capacity center as core domain objects
