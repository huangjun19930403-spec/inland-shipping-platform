# Frontend Architecture

Frontend repo:

```text
/Users/hj/Documents/paltform_data_V2/frontend
```

## Stack

- Vue 3
- Vue Router
- Pinia
- Element Plus
- ECharts
- AMap JSAPI loader
- Axios
- TypeScript
- Vite

## Application Shell

`src/layout/AppLayout.vue` renders the left menu, header, breadcrumb and route outlet. Menu priority:

1. backend `/auth/me/menus`
2. static fallback `src/config/menu.ts`

This is why production seed must initialize the new `sys_menu` structure. If backend menus are old, the local page will look old even when frontend static config is already updated.

## Production Menu

The frontend menu mirrors backend seed:

- 经营总览
- 货源洞察中心
- 运力中心
- 航线与区域中心
- 运价与报价中心
- 数据质量与治理
- 系统配置

## Global Analysis Context

`src/stores/analysisContext.ts` persists `AnalysisContext` in local storage and exposes query conversion for pages.

Context fields:

- `date_from`, `date_to`
- `origin_region_code`, `destination_region_code`
- `origin_node_id`, `destination_node_id`
- `commodity_id`
- `tonnage_bucket_code`
- `vessel_type_code`, `deadweight_bucket_code`
- `route_id`
- `source_type_code`
- `quality_level_code`
- `confidence_level_code`

Pages should pass this context when navigating from dashboards, charts, maps and tables into detail pages.

## API Clients

API clients live in `src/api/*`.

Important clients:

- `auth.ts`: login and current user/menu context
- `freight.ts`: freight lifecycle and shipping opportunities
- `vessel*.ts`: capacity, AIS, governance, compliance, recognition and candidate fit
- `analysis.ts`: overview, freight, vessel, region, flow, pricing and jobs
- `route.ts`: shipping route and track APIs
- `address.ts`: administrative region, business region, node, water system and map APIs

Freight pages use `fetchShippingOpportunities`; old `fetchFreights` has been deleted.

## Page Organization

- `modules/system/pages/DashboardPage.vue`
- `modules/freight/pages/*`
- `modules/vessel/pages/*`
- `modules/analysis/pages/*`
- `modules/address/pages/*`
- `modules/route/pages/*`
- `modules/audit/pages/*`
- `modules/dictionary/pages/*`
- `modules/commodity/pages/*`

New large pages should be split into workbench, panel, table, drawer, map and composable pieces. Current remaining oversize pages are tracked as hardening work in the acceptance doc.

## Map Components

- `BaseAmap.vue`
- `NodeLocationPicker.vue`
- `RegionBoundaryEditor.vue`
- `MapStatePanel.vue`

`MapStatePanel` is the frontend expression of backend map-state semantics. It must show provider state, not-computable reasons, missing fields, retry action and business impact. Empty maps must not be used as the only failure signal.

## UI Rules

- KPI cards must be backed by backend aggregate APIs, not current page rows.
- Long evidence, AI warnings and not-computable reasons belong in drawers or evidence panels.
- Chart, table and map interactions should carry `AnalysisContext`.
- Production analysis must show source, freshness, confidence and action.
