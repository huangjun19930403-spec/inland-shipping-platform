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

Round 11 Report:

- Added `scripts/seed_experience_scenarios.py` as a local-demo-only补数层.
- Kept production seed unchanged; experience rows are explicitly marked through `FR-DEMO-*`, `FCA-DEMO-*`, `FBT-DEMO-*`, `FTI-DEMO-*`, `LOCAL_DEMO` and `DEMO_ES_MIRROR`.
- Local-demo seed order now runs route samples before experience scenarios, and runs analysis/audit after the scenario rows are present.
- Added 42 scenario freight samples across:
  - `SCN_TCWUHU_AGG`
  - `SCN_SUZHOU_NANJING_STEEL`
  - `SCN_HUZHOU_WUHU_CEMENT`
  - `SCN_RISK_NOT_COMPUTABLE`
- Each scenario freight has source evidence with raw shipper quote, owner/boat-owner quote text and advanced quote configuration text. Round 11 keeps these as evidence only; formal owner quote modeling is left for Round 12.
- Added AIS, node and route snapshots:
  - `DEMO_AIS_EXPERIENCE_CURRENT`
  - `DEMO_NODE_TAICANG_CURRENT`
  - `DEMO_NODE_JIANGYIN_CURRENT`
  - `DEMO_NODE_NANJING_CURRENT`
  - `DEMO_NODE_WUHU_CURRENT`
  - `DEMO_ROUTE_TAICANG_WUHU_CURRENT`
  - `DEMO_ROUTE_SUZHOU_NANJING_CURRENT`
  - `DEMO_ROUTE_HUZHOU_WUHU_CURRENT`
- Rebuilt route graph data for the three demo lanes with ready line/segment geometry for local-demo route-segment matching.
- Added freight-context vessel candidate analyses covering high match, medium match, stale AIS, high risk, blocked constraint and wrong ship-type cases.
- Added local acceptance checks for `FR-DEMO-*`, quote-ready freights, source evidence, candidate analyses, AIS snapshot usability, node observations, route-segment samples, constraint statuses and automation/E2E pollution.

Round 11 Verification Notes:

- `scripts.seed_experience_scenarios` ran successfully on the current local database and produced 42 `FR-DEMO-*` rows, 6 freight candidate analyses and `DEMO_AIS_EXPERIENCE_CURRENT`.
- The new Round 11 verification checks pass on the current local database.
- Full `scripts.seeds.validation.local_acceptance` still fails on pre-existing local environment conditions: one old automation constraint row, missing history ES local values, external connection test statuses and an existing role-menu hierarchy issue. A full local-demo reset should clear the automation row; the remaining config and role-menu issues are not caused by Round 11.

Round 12 Plan:

1. Restore and harden `智能报价测算` without deleting its original business semantics.
2. Reintroduce owner/boat-owner quote as a first-class pricing input instead of only raw evidence.
3. Restore the advanced quote configuration panel and persist its assumptions in the quote decision request/response.
4. Keep `智能报价测算` scoped to known-price decisioning: known shipper price, known owner quote or owner quote range, platform service fee, risk reserve, margin, tax/settlement, route cost and fallback line.
5. Add a separate `运价预估测算` design and API contract for unknown market-price estimation based on origin, destination, tonnage, commodity, expected loading time, route computability, capacity tightness, AIS freshness, historical price facts, node/region coverage and data quality.
6. Build pricing responses with sample size, coverage, confidence, lineage, not-computable reasons and recommended actions.
7. Keep AI limited to explanation and summary. It must not fabricate price facts or replace deterministic pricing evidence.
8. Update frontend entry points so quote-ready `FR-DEMO-*` samples can enter both known-price quote decision and future unknown-price freight estimate flows with analysis context preserved.

Round 12 Report:

- Added `pricing_decision_record` to the single `001_initial_schema` baseline and model layer.
- Added `PricingDecisionService` as the backend owner for both pricing capabilities:
  - `QUOTE_DECISION`: known shipper price plus owner/boat-owner quote or quote range.
  - `RATE_ESTIMATE`: unknown market-rate estimation from historical samples and fallback layers.
- Restored智能报价的船主/船户报价、报价区间、高级配置、航线证据、成本安全线、毛利、毛利率、议价/拒绝/可接决策和落库追溯。
- Added运价预估测算 as a separate capability and page. It returns low/recommended/high price, sample size, coverage, confidence, fallback layer, route evidence, sample evidence and persisted record id.
- Added pricing APIs:
  - `GET /api/v1/analysis/quote-simulator/context`
  - `POST /api/v1/analysis/quote-simulator/decision`
  - `POST /api/v1/analysis/rate-estimator/estimate`
- Kept `POST /api/v1/analysis/quote-simulator/route-estimate` as the shared real-route evidence endpoint.
- Updated opportunity actions so confirmed freight samples can enter both智能报价测算 and运价预估测算 with freight context.
- Updated seed/menu verification for the new pricing table, API routes, menu entry and Round 11 quote evidence parsing.
- Updated product, backend, database, API, frontend and seed docs for the new pricing split.

Round 12 Verification Notes:

- `pytest tests/test_seed_profiles.py tests/test_analysis_quote_route_estimate.py tests/test_quote_decision_service.py tests/test_rate_estimator_service.py tests/test_shipping_opportunity_service.py` passed.
- `pnpm type-check` passed in the frontend repo.
- `pnpm build` passed in the frontend repo.
- The current local SQLite database was non-destructively patched with the new `pricing_decision_record` table because it already had the rebuilt `001` revision stamped before this round changed the baseline. Production seed was rerun to sync menus without resetting demo data.
- `scripts.seeds.validation.local_acceptance` now passes the Round 12 schema, menu, experience quote parsing and pollution checks. Remaining local failures are external/environmental: missing history ES local values (`ES_HOST`, `ES_PASSWORD`) and external connection test statuses for AMAP, ES_HISTORY, ES_REALTIME and HIFLEET.

Round 13 Plan:

1. Implement the Round 10货源洞察中心命名和信息架构整改 now that pricing actions are usable.
2. Rename old freight second-level entries with code, seed, routes, page headers, breadcrumbs and docs aligned:
   - `货源分析` -> `货源态势总览`
   - `微信采集` -> `微信语义解析`
   - `TMS 入站` -> `TMS 结构化入站`
   - `采集批次` -> `解析批次监控`
   - `候选确认` -> `候选证据池`
   - `正式货源/运输机会` -> `机会样本库`
   - `数据清洗` -> `质量治理与回算`
3. Add freight-context `供需适配分析` entry instead of forcing users to discover it under the vessel menu.
4. Move手工录入 out of the primary analysis path and keep it as a supplement action.
5. Verify that one `FR-DEMO-*` freight can flow through data quality, route computability, ship matching,智能报价 and运价预估 with preserved context.

Round 13 Report:

- Rebuilt the货源洞察中心 second-level information architecture in production seed and frontend fallback menu.
- Renamed visible entries to `货源态势总览 / 微信语义解析 / TMS 结构化入站 / 解析批次监控 / 候选证据池 / 机会样本库 / 供需适配分析 / 质量治理与回算`.
- Moved `/freight/manual-create` out of primary navigation. The route remains available as a hidden `补录样本` action from the opportunity sample library.
- Added `/freight/supply-demand-fit` as the freight-context entry for existing vessel candidate analysis. It defaults to `FREIGHT_SAMPLE` context and keeps the underlying candidate analysis service instead of creating a shell page.
- Normalized structured local-demo candidate analysis `data_sources_json` in the response layer so `DEMO_ES_MIRROR` / `LOCAL_DEMO` evidence does not break the candidate analysis API while the public response remains `list[str]`.
- Updated freight page headers, buttons, empty states, error copy, breadcrumbs, dashboard quick links and opportunity actions to use the new analysis-platform language.
- Updated seed profile tests, local acceptance checks and frontend/backend documentation for the new menu contract.

Round 13 Verification Notes:

- Backend focused tests passed: `pytest tests/test_vessel_candidate_analysis.py tests/test_seed_profiles.py tests/test_shipping_opportunity_service.py tests/test_security_permissions.py`.
- Frontend checks passed: `pnpm type-check` and `pnpm build`.
- Production seed was rerun to refresh the local menu tree; the visible freight menu now appears in the expected order and `补录样本` remains hidden.
- Browser verification confirmed `/freight` redirects to `/analysis/freight`, old freight submenu names are not visible, and `/freight/supply-demand-fit` can list `FREIGHT_SAMPLE` histories and open candidate-ship rows.
- `scripts.seeds.validation.local_acceptance` passes the Round 13 menu, hidden supplement route and supply-demand entry checks. Remaining failures are external/environmental: missing history ES local values (`ES_HOST`, `ES_PASSWORD`) and external connection test statuses for AMAP, ES_HISTORY, ES_REALTIME and HIFLEET.

Round 14 Plan:

1. Enhance `货源态势总览` from chart aggregation into an insight workbench.
2. Add problem-oriented insight cards for supply growth, route concentration, node quality gaps, price outliers and capacity-matching gaps.
3. Make chart/table/map clicks write an `AnalysisContext` and drill into `机会样本库`, `供需适配分析`, `质量治理与回算`, `智能报价测算` or `运价预估测算`.
4. Move long lineage, not-computable reasons and quality impact into an evidence drawer instead of scattering them across chart surfaces.
5. Add acceptance checks that one `FR-DEMO-*` lane can move from态势 insight to样本列表, candidate fit, quote decision and rate estimate with context preserved.

Round 14 Final Report:

- Fixed the local SQLite pricing failure. `pricing_decision_record.id` now uses an SQLite `INTEGER PRIMARY KEY` variant while production databases keep the large-integer primary-key model. Quote and rate estimate APIs can persist records and return `record_id`.
- Backed up and reset the local SQLite database, rebuilt from the single `001_initial_schema`, and reran `local-demo` seed.
- Expanded local-demo experience seed from hidden matching samples to visible opportunity coverage. Computable main `FR-DEMO-*` rows now receive freight-context candidate analyses, and the top visible opportunity rows have 10 candidate vessels each.
- Added local-demo historical comparable freight samples so运价预估测算 can demonstrate exact-node and fallback sample weighting instead of returning an empty or formula-only result.
- Rebuilt the rate estimator algorithm around comparable-sample weighting, fallback trace, factor breakdown, outlier handling, quality warnings and confidence scoring. It no longer uses `distance * fixed coefficient` as the final market price.
- Split the pricing implementation into `PricingDecisionService` and `RateSampleEstimator`, and moved freight insight card construction into `freight_insights.py` so Round 14 did not add another oversized service object.
- Extended pricing responses with `factor_breakdown`, `comparable_samples`, `fallback_trace` and `quality_warnings`.
- Reworked智能报价测算 and运价预估测算 into three-zone workbenches: context/input, route/evidence, result/actions. The quote advanced configuration is restored in a drawer.
- Added freight overview insight cards for growth/capacity gaps, hot-route concentration, quality gaps, price anomaly review and candidate-fit gaps, each with evidence and drill-down actions.
- Fixed the freight-context supply-demand page so a `freight_id` entry loads existing READY candidate analysis by default instead of showing an empty table.
- Updated local acceptance to verify pricing autoincrement, executable quote decisions, executable rate estimates, visible opportunity fit analyses and optional degraded external providers.

Round 14 Final Verification Notes:

- `scripts.seeds.cli --profile local-demo` completed successfully after local DB reset.
- `scripts.seeds.validation.local_acceptance` passed. External AMAP/HIFLEET/ES checks are recorded as degraded local provider states instead of blocking local-demo seed.
- Backend focused tests passed for seed profiles, quote decision, rate estimator, opportunity service, vessel candidate analysis, vessel spatial analysis and vessel facts.
- Frontend `pnpm type-check` and `pnpm build` passed.
- Browser verification on the locally running frontend confirmed:
  - `FR-DEMO-0042` opens智能报价测算 with shipper quote, owner quote and advanced configuration; generating a decision returns a record number and no backend 500.
  - The same freight opens运价预估测算 with low/recommended/high price, comparable samples, fallback layer and factor breakdown.
  - `货源态势总览` shows five business insights and insight actions drill into downstream pages.
  - `/freight/supply-demand-fit?freight_id=282` loads an existing READY analysis with 10 candidate vessels.

Final State:

- The delete-style rebuild branch now has the production baseline, seed profiles, pricing decision flow, rate estimation flow, freight insight navigation and local-demo data chain required for the current acceptance target.
- Remaining hardening is incremental, not a blocker for this round: continue splitting oversized historical services/pages, broaden E2E coverage, and connect real production ES/AMMS providers outside the local-demo fallback path.

Round 15 Report:

- Rebuilt `/analysis/flows` into a two-tab analysis workbench:
  - `货源流向分析` now focuses on freight OD heat, real route map, source/region/commodity structure flow and freight corridor actions.
  - `船舶流向分析` now focuses on vessel OD heat, AIS freshness, active vessels, average deadweight, corridor occupancy, return opportunity and vessel-flow details.
- Kept the existing `/api/v1/analysis/flows/overview` route and expanded it with `subject=freight|ship|all` plus optional flow filters. Existing `freight_flows` and `ship_flows` remain compatible.
- Extended flow response items with city codes, active capacity, average deadweight, AIS freshness, route occupancy, return opportunity, confidence, risk and recommended actions.
- Added structured response blocks for `freight_summary`, `freight_structure`, `freight_corridors`, `ship_summary`, `ship_quality`, `ship_corridors` and `ship_flow_details`.
- Added backend enrichment so freight lanes can show matched nearby capacity and reverse/return opportunity without requiring exact same-node ship-flow facts.
- Added vessel-flow enrichment from `VesselProfileSummary` and ship-flow facts, including AIS freshness, average deadweight and same-city return freight opportunities.
- Reworked the frontend OD heat matrix to support both freight mode and ship mode; ship mode uses `voyage_count` and surfaces active ships/AIS freshness.
- Added new frontend components for flow Sankey structure and route/capacity corridor cards.
- Updated local acceptance to assert the new freight and ship flow workbench response blocks are populated and enriched.

Round 15 Verification Notes:

- Backend tests passed: `pytest tests/test_analysis_flow_overview_round15.py tests/test_analysis_quote_route_estimate.py tests/test_seed_profiles.py`.
- Frontend checks passed: `pnpm type-check` and `pnpm build`.
- API spot checks on the locally running backend confirmed:
  - `subject=freight` returns 20 freight flows, 23 structure links, 8 corridors, 645 matched-capacity vessels and enriched first-lane return opportunity.
  - `subject=ship` returns 20 ship flows, ship quality data, 8 corridors, 20 detail rows, 40% AIS freshness and 180 return-opportunity freight rows.
- Browser smoke test on the locally running frontend confirmed both tabs render, the freight OD matrix and ship OD matrix are visible, and the ship detail section loads.
- Follow-up browser tuning fixed the oversized CSS Grid issue that pushed the ship-flow ranking column offscreen. The ship workbench now keeps the map and ranking/quality panels in a bounded two-column layout, and the ship OD/corridor/detail sections remain visible below.
- The ship tab no longer auto-submits AMMS route precompute and polling when opened. It displays existing route readiness and only draws the top vessel corridors, which removes the visible tab-load stall.
- The freight structure Sankey now includes a readable side evidence list, and route corridor panels use fixed-height internal scrolling so long corridor data no longer stretches the whole page.
- Latest browser smoke test on the refreshed local frontend completed with no browser console errors.
