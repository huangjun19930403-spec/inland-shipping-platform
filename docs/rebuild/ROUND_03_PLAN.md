# Round 03 Plan - Backend Domain Services and API Convergence

## Objective

Move backend business entrypoints away from scattered module CRUD and toward
production workbench APIs. This round must not create shell services; every new
service must own existing behavior or replace a current API path.

## Target Domain Services

- `FreightLifecycleService`
  - owns raw source, parse evidence, candidates, normalization, confirmation,
    and formal freight lineage.
- `ShippingOpportunityService`
  - owns the cross-domain opportunity object linking freight, route, capacity,
    price, risk, and next action.
- `CapacityPoolService`
  - owns available vessel capacity, AIS freshness, certificate/subject/contact
    completeness, and capacity confidence.
- `SupplyDemandMatchService`
  - owns vessel-fit calculation and supply shortage explanation.
- `RouteRegionIntelligenceService`
  - owns route computability, region/flow analysis, water-system and constraint
    evidence.
- `PricingDecisionService`
  - owns quote simulation, price bands, cost breakdown, and pricing risk.
- `DataQualityWorkflowService`
  - owns issue discovery, repair task generation, recalculation impact, and
    quality closure.
- `AnalysisLineageService`
  - owns sample size, coverage, confidence, source versions, source tables, and
    drill-down query metadata.

## API Convergence Rules

- Business workbench routes must return:
  - `context`
  - `metrics`
  - `insights`
  - `lineage`
  - `quality`
  - `actions`
- Existing CRUD routes may remain only when they are admin/support resources.
- Delete or deprecate routes that:
  - have no frontend consumer
  - only trigger demo-style analysis
  - expose analysis jobs as ordinary business navigation
  - return chart data without lineage and action metadata

## Implementation Order

1. Inventory current backend routes and match them to frontend consumers.
2. Add shared response schemas for insight, lineage, quality, and action blocks.
3. Refactor analysis API responses to include the shared blocks.
4. Extract freight lifecycle read/write methods from the oversized freight
   service into smaller production services.
5. Introduce shipping opportunity read model backed by existing freight, route,
   vessel, pricing, and quality data.
6. Remove unused/demo-only API surfaces once the frontend has moved.

## Exit Criteria

- No production analysis response lacks lineage and next action fields.
- No new service exceeds 800 lines.
- No route remains solely because old demo pages used it.
- Backend tests cover freight lifecycle, opportunity detail, capacity summary,
  pricing decision, data-quality issue impact, and analysis lineage.
