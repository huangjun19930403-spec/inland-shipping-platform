# Backend Architecture

## Runtime

- Framework: FastAPI
- ORM: SQLAlchemy async ORM
- Migration: Alembic, single baseline `001_initial_schema`
- Task runtime: Celery with Redis-compatible broker
- Default local DB: SQLite via `aiosqlite`
- Production DB option: MySQL via `asyncmy`
- External integrations: AMap/AMMS route geometry, AIS/ES, HiFleet, DashScope Qwen, COS object storage

`main.py` creates the FastAPI app, registers request ID middleware, error handlers, CORS and lifespan cleanup for external sessions/shared HTTP clients.

## Module Assembly

`app/api/v1/__init__.py` mounts these modules under `/api/v1`:

- `/dictionary`
- `/address`
- `/commodity`
- `/vessels`
- `/freight`
- `/route`
- `/analysis`
- `/audit`
- `/files`
- `/auth` and `/system`

Module-level permission guards use `require_permission`. Fine-grained service methods still validate domain state transitions and write permissions where needed.

## Domain Modules

### Freight

Freight owns collection, parsing, candidate confirmation, normalization, manual entry, detail maintenance and shipping opportunity read models.

Important files:

- `app/modules/freight/router.py`
- `app/modules/freight/service.py`
- `app/modules/freight/opportunity_service.py`
- `app/modules/freight/opportunity_actions.py`
- `app/modules/freight/ai_evidence_gate.py`

The business list entry is `GET /api/v1/freight/opportunities`. Legacy `GET /api/v1/freight` has been deleted.

### Vessel

Vessel owns capacity, asset profile, AIS spatial observations, certificate ledger, owner/operator/contact relations, compliance risk, governance tasks, OCR review and candidate-fit analysis.

Important files:

- `app/modules/vessel/router.py`
- `app/modules/vessel/routers/*`
- `app/modules/vessel/service.py`
- `app/modules/vessel/spatial_service.py`
- `app/modules/vessel/governance_service.py`
- `app/modules/vessel/candidate_service.py`

The vessel module is still broad. Future hardening should continue splitting oversized services by capability.

### Route And Region

Route owns shipping routes, plans, route lines, nodes, segments and route tracks. Address owns administrative regions, boundaries, business regions, water systems, transport nodes and navigation constraints.

Important files:

- `app/modules/address/*`
- `app/modules/route/*`
- `app/modules/analysis/map_state.py`
- `app/modules/analysis/quote_route_service.py`

Map-state logic prevents blank maps or fake fallback lines from being mistaken for production routes.

### Analysis

Analysis owns operational overview, freight, vessel, region, flow, price and job/task APIs. It reads fact tables, constructs evidence blocks, and returns quality/lineage/actions where implemented.

Important files:

- `app/modules/analysis/router.py`
- `app/modules/analysis/service.py`
- `app/modules/analysis/pricing_decision_service.py`
- `app/modules/analysis/statistics.py`
- `app/modules/analysis/job_catalog.py`

`statistics.py` builds daily facts. Production analysis must not treat local sample facts as real external evidence.

`PricingDecisionService` owns pricing decision logic. Known-price quote decisions and unknown-market-rate estimates are persisted in `pricing_decision_record` with input context, advanced configuration, route evidence, sample evidence, coverage, confidence, lineage and recommended actions.

### Governance And System

Audit owns approval tasks and records. System owns authentication, users, roles, permissions, menus, runtime config and config connection tests. Storage owns file upload and content retrieval.

## Response Design

Business decision APIs should include:

- source context
- metrics
- evidence
- lineage
- quality
- recommended actions
- unavailable or not-computable reasons

`ShippingOpportunityService` demonstrates this contract by combining freight profile, route evidence, capacity evidence, pricing evidence, cleaning issues, lineage, quality and actions.

## Map-State Contract

Map and route-dependent APIs use four explicit states:

- `READY`: real route geometry exists and can support map display, distance and pricing.
- `PENDING`: route geometry task is not ready; do not draw a fake line.
- `FAILED`: provider call failed; expose provider, error and retry action.
- `NOT_COMPUTABLE`: missing node, coordinate, business category or service configuration.

The helper lives in `app/modules/analysis/map_state.py`.

## Code Quality Rules

- New service classes should remain below 800 lines.
- Complex logic should be split into domain service, repository, schema and rule/evidence builder.
- New APIs must have real business owners, data sources, states, tests and docs.
- No production API may depend on random/demo seed data for a production conclusion.
- Removed APIs are not kept through long-term compatibility wrappers.
