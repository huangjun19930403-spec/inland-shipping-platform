# Round 04 Plan - Backend Freight Lifecycle and Opportunity Service

## Objective

Extract the first real production domain service from the oversized freight
module and expose a shipping-opportunity read model backed by existing freight,
route, vessel, pricing, and data-quality data.

## Work Items

- Split freight service ownership:
  - source ingestion
  - parse evidence
  - candidate confirmation
  - normalization
  - formal freight
  - lineage summary
- Add `ShippingOpportunityService` as a real read model over existing data:
  - freight identity and source lineage
  - origin/destination/commodity completeness
  - route computability status
  - candidate capacity summary
  - price evidence summary
  - quality issues and recommended actions
- Add API contracts for:
  - opportunity list
  - opportunity detail
  - opportunity actions
- Remove or hide any freight/analysis API that is made redundant by the new
  opportunity API.

## Exit Criteria

- At least one freight detail can be followed from source to formal freight to
  opportunity summary.
- Opportunity responses include context, lineage, quality, and actions.
- No new service exceeds 800 lines.
- Backend tests cover source lineage, incomplete-data quality reasons, and
  opportunity next actions.
