# Round 01 Plan - Baseline Audit and Deletion Boundary

## Objective

Round 01 is the non-code audit round for the production delete-style rebuild branch.
It must define what stays, what is removed, and what is merged before any schema,
API, seed, or service rewrite starts.

This round intentionally does not change runtime code.

## Starting Branch Discipline

- Source branch: `refactor/vessel-capacity-center`
- Rebuild branch: `refactor/production-delete-rebuild`
- Required pre-checks:
  - `git status --short --branch`
  - `git pull --ff-only`
  - create the rebuild branch only from a clean tree

## Audit Scope

Backend audit scope:

- Alembic migration chain and target single `001_initial_schema` policy.
- Production seed, local-demo seed, and demo/sample data boundaries.
- Current API modules and their target ownership after rebuild.
- Large services and mixin-style service boundaries.
- Analysis fact tables and `LOCAL_SAMPLE` leakage into analysis views.
- Documentation inventory and future delete/regenerate boundary.

Frontend counterpart audit scope:

- Menu information architecture.
- Route and page ownership after rebuild.
- Large pages that must be split into smaller workbench components.
- KPI and chart behavior that currently misleads or lacks drill-down.
- Analysis context requirements across pages.

## Deliverables

Round 01 must produce:

- `docs/rebuild/ROUND_01_BASELINE_AUDIT.md`
- `docs/rebuild/ROUND_01_REPORT.md`
- `docs/rebuild/ROUND_02_PLAN.md`

The frontend repository must produce matching frontend audit documents in its own
`docs/rebuild/` directory.

## Decision Rules

- Keep only capabilities that support a production shipping data analysis mainline.
- Delete API/page/documentation surfaces that have no production data, no consumer,
  no business action, or only exist for demo charts.
- Merge module-scattered behavior into domain services in later rounds.
- Production seed must include real platform foundation data:
  - dictionary and code sequences
  - roles, permissions, menus, and system config skeleton
  - administrative regions and boundaries
  - water systems
  - navigation constraints and node type standards
  - commodity categories, types, and standard commodities
  - analysis buckets and AI/external-provider placeholders
- Demo/dev data must be isolated from production seed and visibly marked.

## Exit Criteria

- Keep/delete/merge lists are explicit enough to drive Round 02 without new product
  decisions.
- Round 02 has a concrete schema and seed rebuild entry plan.
- No runtime code is changed in Round 01.
