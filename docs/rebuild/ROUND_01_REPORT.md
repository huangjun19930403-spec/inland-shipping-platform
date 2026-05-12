# Round 01 Report - Backend

## Completed

- Created the production delete-style rebuild branch plan.
- Audited the backend module shape, migration chain, seed boundary, local facts,
  and large service objects.
- Produced keep/delete/merge lists for Round 02 and Round 03.
- Confirmed production seed must remain broad and include foundation data such as
  administrative regions, water systems, navigation constraints, commodities,
  dictionary data, permissions, menus, code sequences, config skeleton, and
  AI/external placeholders.

## Key Findings

- The current backend is broad but module-oriented, not opportunity-oriented.
- The active Alembic chain still contains multiple migration files and must be
  collapsed into one explicit initial migration.
- `LOCAL_SAMPLE` analysis facts exist for ship city and ship flow facts and must
  be excluded from production analysis.
- Several backend service files are too large for maintainable production work
  and must be split by domain responsibility.
- Existing seed boundaries are close to the desired direction, but local-demo
  records still drive too much of the product experience.

## Next Round

Round 02 starts the destructive schema and seed rebuild:

- replace migration chain with one explicit `001_initial_schema`
- reshape the schema around freight lifecycle, shipping opportunity, capacity
  pool, route/region, pricing, insight lineage, and data quality workflow
- keep production foundation seed broad
- isolate local-demo records and mark every demo fact visibly
