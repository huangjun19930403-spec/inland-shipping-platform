# Rebuild Execution Log

Branch: `refactor/production-delete-rebuild`

## Locked Decisions

- Rebuild is delete-style: remove demo-backend surfaces instead of hiding them behind shell pages.
- Active migration chain is a single `001_initial_schema`.
- Production seed is broad and includes foundation data: administrative regions, water systems, commodities, dictionaries, constraints, permissions, menus and config skeletons.
- `local-demo` seed is isolated and may reset local DB.
- Frontend information architecture is business-led, not old admin-led.
- Old `GET /api/v1/freight` business list is deleted; shipping opportunity list is `/api/v1/freight/opportunities`.

## Round Summary

### Round 01

Audited baseline and identified the root issue: modules, tables and pages existed, but business mainline, data lineage, analysis actions and frontend context were not closed.

### Round 02

Rebuilt database baseline around a single explicit Alembic migration and separated production seed from local demo seed.

### Round 03

Started backend domain convergence and introduced production-oriented service/API entry points.

### Round 04

Introduced shipping opportunity APIs as the freight business entry and began moving UI consumers off the old freight list.

### Round 05

Implemented business workbench paths for freight insight, capacity center, route/region, quote and governance flows.

### Round 06

Tightened analysis logic so responses carry evidence, confidence, lineage, quality and recommended actions where migrated.

### Round 07

Introduced production map-state semantics and frontend `MapStatePanel`:

- READY
- PENDING
- FAILED
- NOT_COMPUTABLE

Blank maps and fake fallback lines are no longer accepted as production failure representation.

### Round 08

Fixed local page not changing after seed. Root cause was not an empty database; backend `sys_menu` still held old IA and frontend preferred backend menus over static fallback.

Completed:

- production menu seed rebuilt
- role menu grants aligned
- production seed rerun locally
- browser confirmed new menu
- frontend `fetchFreights` deleted
- backend `GET /api/v1/freight` deleted
- transportation opportunity page removed page-local KPI cards

Verified:

- backend focused pytest passed
- frontend type-check/build passed
- `GET /api/v1/freight` returns 404

### Round 09

Final documentation deletion/rebuild round.

Plan:

1. Delete old backend and frontend docs, including round fragments and stale historical reports.
2. Regenerate a unified final documentation pack.
3. Keep docs aligned with current code, seed profiles, production menus and deleted APIs.
4. Record remaining hardening honestly.
5. Verify backend tests, frontend checks and local page state.

Report:

- Old docs were removed.
- Final backend docs now consist of README plus product, backend, database, API, frontend, seed, deployment, test and execution-log documents.
- Frontend docs are reduced to README plus current frontend architecture and acceptance docs.
- Final docs no longer cite deleted pages, old branch names or historical migration chains as the source of truth.

## Final Documentation Pack

- `README.md`
- `docs/PRODUCT_SPEC.md`
- `docs/BACKEND_ARCHITECTURE.md`
- `docs/DATABASE_SCHEMA.md`
- `docs/API_REFERENCE.md`
- `docs/FRONTEND_ARCHITECTURE.md`
- `docs/SEED_AND_INITIALIZATION.md`
- `docs/DEPLOYMENT_AND_CONFIG.md`
- `docs/TEST_AND_ACCEPTANCE.md`
- `docs/REBUILD_EXECUTION_LOG.md`

## Remaining Work

- Continue splitting oversized backend service files.
- Continue splitting oversized frontend pages.
- Complete migration of chart-style analysis endpoints into the full insight contract.
- Expand E2E tests for cross-page analysis context propagation and map failure states.

## Continuing Execution

### Round 10: Freight Insight Center IA Remediation

Plan:

1. Do not change backend or frontend code in this round.
2. Treat this round as an information architecture and product remediation round for the Freight Insight Center.
3. Combine the previous findings: demo-like seed, weak cross-page linkage, missing vessel matching data, quote feature regression and analysis pages that still behave like reports.
4. Produce a concrete delete-style target for the Freight Insight Center secondary navigation, page responsibilities and later implementation sequence.
5. End the round with a clear Round 11 plan for experience seed rebuilding.

Current secondary navigation observed:

- `微信采集`
- `采集批次`
- `候选确认`
- `手工录入`
- `运输机会`
- `数据清洗`
- `TMS 入站`
- `货源分析`

Diagnosis:

- The entry order is still operation-led. Users see collection channels first, not freight market status, data readiness, supply-demand gaps or pricing questions.
- `货源分析` is placed like a late report page. In an analysis platform it must be the first workbench-level entry.
- `运输机会` is a transport execution/business-development term. It is useful as a domain object, but as a menu name it makes the product feel like an operations backend rather than an analytical sample library.
- `候选确认` hides the real analytical value: raw-text evidence, AI split boundaries, confidence, candidate identity and field lineage.
- `数据清洗` is too generic. The platform must express quality as a closed loop: find issue, fix source field, recalculate analysis, improve matching or pricing confidence.
- `手工录入` should not be a primary second-level analysis navigation item. It is an action, not a business insight surface.
- Vessel matching is semantically misplaced. A user starts from freight context, but `船货适配分析` currently lives under the vessel/capacity side and is seeded poorly.
- Price estimation and quote decision are not visible from the freight context even though freight origin/destination, tonnage, commodity and loading time are the natural inputs.

Target secondary navigation:

1. `货源态势总览`
   - Target route: current `/analysis/freight`.
   - Purpose: first screen for freight insight, not a chart report.
   - Must show sample volume, analyzable coverage, node coverage, commodity standardization, route computability, price coverage, abnormal flows and recommended actions.

2. `来源解析工作台`
   - Target routes: current `/freight/wechat`, `/freight/tms-inbounds`, later manual text/import entry.
   - Purpose: manage source ingestion and AI/TMS parsing as data production, not as "collection pages".
   - UI direction: tabs or source lanes for WeChat, TMS and manual supplement; all output must go to candidate evidence.

3. `解析批次监控`
   - Target route: current `/freight/batches`.
   - Purpose: observe parse tasks, AI stage, heartbeat, failure cause, retry state, candidate count and evidence replay.
   - Naming removes the vague "采集批次" backend feel.

4. `候选证据池`
   - Target route: current `/freight/candidates`.
   - Purpose: inspect and confirm candidates through evidence, not just approve rows.
   - Must emphasize raw text, candidate boundary, origin/destination confidence, commodity confidence, tonnage ambiguity, contact scope and AI review reasons.

5. `机会样本库`
   - Target route: current `/freight/list`.
   - Purpose: the confirmed, analyzable freight sample library.
   - Keep `ShippingOpportunity` as backend object, but stop using `运输机会` as the primary menu label.
   - This page must become the bridge to route computability, capacity matching, price estimation, quote decision and data quality.

6. `质量治理与回算`
   - Target route: current `/freight/normalization`.
   - Purpose: not just clean fields, but show which bad fields block analysis and which insights will improve after fixing.
   - Required workflow: issue found -> fix node/commodity/tonnage/price -> recalculate facts -> improve freight insight, matching and pricing confidence.

7. `供需适配分析`
   - Target route short term: current `/vessels/candidate-analysis` with freight context.
   - Target route long term: `/freight/matching` or `/freight/supply-demand-match`.
   - Purpose: a freight-originated matching workbench answering "which vessels can serve this freight and why".
   - Must not remain a generic "候选船舶分析" entry.

8. `运价预估测算`
   - New target route in a later round.
   - Purpose: unknown market price estimation from origin, destination, tonnage, commodity and expected loading time.
   - Must be separate from `智能报价测算`, which is for known shipper price / owner quote decision.

Delete-style menu decision:

- Remove `手工录入` from primary second-level navigation. Keep the underlying create route as a button action from `来源解析工作台` or `机会样本库`.
- Rename `运输机会` to `机会样本库`.
- Rename `候选确认` to `候选证据池`.
- Rename `数据清洗` to `质量治理与回算`.
- Rename `货源分析` to `货源态势总览` and move it to the top.
- Rename `微信采集` to `微信语义解析`.
- Rename `TMS 入站` to `TMS 结构化入站`.
- Rename `采集批次` to `解析批次监控`.
- Add freight-context entry for `供需适配分析`; do not force users to discover it from the vessel menu.
- Add future `运价预估测算`; keep existing `智能报价测算` under quote decision.

Page responsibility model:

- `货源态势总览`: explains what freight data can currently support analytically.
- `来源解析工作台`: produces candidate samples from raw sources.
- `解析批次监控`: explains whether parsing succeeded and why it failed.
- `候选证据池`: proves whether a candidate should become an analyzable sample.
- `机会样本库`: connects confirmed samples to route, capacity, price, quality and lineage actions.
- `质量治理与回算`: fixes the data facts that block analysis.
- `供需适配分析`: evaluates available capacity against freight context.
- `运价预估测算`: estimates market price before a known quote exists.

Implementation constraints for the later code round:

- No shell-only rename. Every renamed menu item must have page copy, route title, role menu seed and documentation aligned.
- No empty "analysis" page. Every analytical card must have backend sample size, coverage, confidence and action.
- No page-local pagination summary pretending to be global KPI.
- No production analysis depending on `LOCAL_SAMPLE`.
- Manual creation must be treated as a data supplement action, not as a primary analytical surface.
- Freight-to-capacity and freight-to-price jumps must carry context: date range, origin node/city, destination node/city, commodity, tonnage, loading time and quality level.

Acceptance criteria for the implementation round:

- Sidebar no longer shows the old second-level labels.
- Browser titles, breadcrumbs and page headers use the same target names.
- `货源态势总览` appears before ingestion pages.
- From one confirmed freight sample, the user can continue to data quality, route computability, capacity matching and price/quote actions.
- `供需适配分析` can be entered from freight context, not only from vessel navigation.
- `手工录入` is no longer a primary second-level menu item.

Round 10 Report:

- Completed the IA remediation plan only.
- No backend service, frontend page, seed, API or database code was changed in this round.
- The next code round should start from this IA decision and first rebuild experience seed, because menu improvements without usable sample chains would still feel like a demo shell.

### Round 11: Experience Seed Rebuild Plan

Goal:

Build a complete local-demo experience chain for freight insight, capacity matching, route segments, navigation constraints and quote/price pages.

Scope:

1. Audit current local-demo seed and identify why `机会样本库`, `供需适配分析`, `节点周边`, `航线段` and quote pages do not show enough meaningful data.
2. Define 3-4 scenario packs:
   - Taicang -> Wuhu mineral/building material lane.
   - Suzhou/Huzhou -> Nanjing/Wuhu steel/building material lane.
   - A high-risk/not-computable lane with missing node, stale AIS or draft/bridge restriction.
   - A pricing lane with known shipper quote, owner quote and unknown market-price estimation.
3. Seed confirmed freight samples, candidate evidence, parse batches and raw-source records as one traceable lifecycle.
4. Seed vessel profiles, latest AIS snapshots, node observations, route-segment match samples and navigation-constraint evidence.
5. If ES is available, create a snapshot import path from ES realtime positions into demo snapshots with source trace. If ES is unavailable, create `DEMO_ES_MIRROR` data with the same schema and explicit demo marking.
6. Add seed verification checks for sample volume, matching rows, node observations, route-segment samples, constraint evidence and quote-ready freight samples.

Round 11 must not:

- Change pricing algorithms.
- Restore the quote UI yet.
- Rename menus until seed and route/context data can support the new IA.
- Mix demo data into production seed.

Round 11 acceptance criteria:

- Freight sample list has nonzero, scenario-coherent data.
- Candidate analysis has visible freight-context results.
- Node surrounding vessel page has node-level observed vessels.
- Route-segment page has route/segment match samples.
- Navigation constraints have pass/warning/blocked examples tied to vessels and lanes.
- At least five freight samples can continue to matching and quote/price actions.
