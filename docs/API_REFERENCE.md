# API Reference

All business APIs are mounted under `/api/v1`. Most module routers are protected by module permission guards, and write operations additionally rely on service-level checks.

## Common Rules

- Auth uses bearer tokens.
- Response errors include `code`, `message`, `data` and `request_id`.
- Pagination response shape is:

```json
{
  "total": 0,
  "page": 1,
  "page_size": 20,
  "items": []
}
```

## Auth And System

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/me/menus`
- `GET /api/v1/system/users`
- `GET /api/v1/system/roles`
- `GET /api/v1/system/menus`
- `GET /api/v1/system/configs`

System menus are not decoration. They define the production information architecture used by the frontend after login.

## Freight And Shipping Opportunity

Main business endpoints:

- `GET /api/v1/freight/opportunities`
- `GET /api/v1/freight/opportunities/{freight_id}`
- `POST /api/v1/freight/manual`
- `GET /api/v1/freight/{freight_id}`
- `PUT /api/v1/freight/{freight_id}`
- `PUT /api/v1/freight/{freight_id}/status`
- `PUT /api/v1/freight/{freight_id}/contacts`
- `GET /api/v1/freight/{freight_id}/attachments`
- `POST /api/v1/freight/{freight_id}/attachments`
- `GET /api/v1/freight/{freight_id}/tags`
- `PUT /api/v1/freight/{freight_id}/tags`

Collection and confirmation:

- `GET /api/v1/freight/batches`
- `POST /api/v1/freight/batches/wechat`
- `GET /api/v1/freight/batches/{batch_id}`
- `POST /api/v1/freight/batches/{batch_id}/parse`
- `POST /api/v1/freight/batches/{batch_id}/candidates/bulk-confirm`
- `POST /api/v1/freight/batches/{batch_id}/handoff-review`
- `GET /api/v1/freight/tms-inbounds`
- `POST /api/v1/freight/tms-inbounds`
- `GET /api/v1/freight/candidates`
- `GET /api/v1/freight/candidates/{candidate_id}`
- `POST /api/v1/freight/candidates/{candidate_id}/confirm`
- `POST /api/v1/freight/candidates/{candidate_id}/reject`

Data quality:

- `GET /api/v1/freight/normalization/quality`
- `POST /api/v1/freight/normalization/clean`
- `GET /api/v1/freight/normalization/tasks`
- `GET /api/v1/freight/normalization/tasks/{task_id}`
- `GET /api/v1/freight/normalization/tasks/{task_id}/suggestions`
- `POST /api/v1/freight/normalization/tasks/{task_id}/suggestions/{suggestion_id}/apply`
- `POST /api/v1/freight/normalization/tasks/{task_id}/suggestions/{suggestion_id}/reject`

Deleted endpoint:

- `GET /api/v1/freight` is intentionally removed. Use `/freight/opportunities`.

## Vessel Capacity Center

Asset and profile:

- `GET /api/v1/vessels/assets/summary`
- `GET /api/v1/vessels/assets`
- `GET /api/v1/vessels`
- `POST /api/v1/vessels`
- `GET /api/v1/vessels/{vessel_id}`
- `GET /api/v1/vessels/{vessel_id}/profile-card`
- `GET /api/v1/vessels/{vessel_id}/profile-card/evidence`
- `PUT /api/v1/vessels/{vessel_id}/profile`
- `PUT /api/v1/vessels/{vessel_id}/registration`
- `PUT /api/v1/vessels/{vessel_id}/capacity`

AIS and spatial:

- `GET /api/v1/vessels/ais/city-situation`
- `GET /api/v1/vessels/ais/positions`
- `GET /api/v1/vessels/ais/node-situation`
- `GET /api/v1/vessels/ais/route-situation`
- `GET /api/v1/vessels/position-monitor`
- `GET /api/v1/vessels/navigation-constraints`

Quality and governance:

- `GET /api/v1/vessels/quality`
- `POST /api/v1/vessels/quality/{issue_id}/recheck`
- `GET /api/v1/vessels/governance/dashboard`
- `GET /api/v1/vessels/governance/tasks`
- `POST /api/v1/vessels/governance/tasks/sync`
- `GET /api/v1/vessels/compliance-risks`
- `GET /api/v1/vessels/blacklist-signals`
- `GET /api/v1/vessels/recognitions`
- `POST /api/v1/vessels/candidate-analyses`
- `GET /api/v1/vessels/candidate-analyses`

## Route, Region And Foundation

Address and foundation:

- `GET /api/v1/address/admin-regions`
- `GET /api/v1/address/admin-regions/{admin_code}/current-boundary`
- `GET /api/v1/address/regions`
- `GET /api/v1/address/nodes`
- `GET /api/v1/address/water-systems`
- `GET /api/v1/address/constraint-points`
- `GET /api/v1/address/map/geocode`
- `GET /api/v1/address/map/reverse-geocode`

Route:

- `GET /api/v1/route`
- `POST /api/v1/route`
- `GET /api/v1/route/{route_id}`
- `GET /api/v1/route/{route_id}/plans`
- `POST /api/v1/route/{route_id}/plans`
- `GET /api/v1/route/plans/{plan_id}/lines`
- `GET /api/v1/route/lines/{line_id}/structure`
- `PUT /api/v1/route/lines/{line_id}/structure`
- `GET /api/v1/route/lines/{line_id}/track`
- `POST /api/v1/route/lines/{line_id}/track/generate`

## Analysis And Pricing

- `GET /api/v1/analysis/overview`
- `GET /api/v1/analysis/freight/overview`
- `GET /api/v1/analysis/freight/trend`
- `GET /api/v1/analysis/freight/flow-map`
- `GET /api/v1/analysis/ships/overview`
- `GET /api/v1/analysis/ships/flow-map`
- `GET /api/v1/analysis/vessels/assets`
- `GET /api/v1/analysis/vessels/trajectory`
- `GET /api/v1/analysis/vessels/quality`
- `GET /api/v1/analysis/vessels/risks`
- `GET /api/v1/analysis/regions/overview`
- `GET /api/v1/analysis/regions/supply-demand`
- `GET /api/v1/analysis/flows/overview`
- `GET /api/v1/analysis/flows/map`
- `POST /api/v1/analysis/flows/route-cache/precompute`
- `GET /api/v1/analysis/prices/overview`
- `POST /api/v1/analysis/quote-simulator/route-estimate`
- `GET /api/v1/analysis/jobs`
- `GET /api/v1/analysis/tasks`
- `POST /api/v1/analysis/tasks/{job_code}/trigger`

Analysis responses should include evidence, lineage, quality, confidence and actions where the endpoint has been migrated to the production insight contract.

## Audit And Files

- `GET /api/v1/audit/tasks`
- `GET /api/v1/audit/tasks/{task_id}`
- `POST /api/v1/audit/tasks/{task_id}/approve`
- `POST /api/v1/audit/tasks/{task_id}/reject`
- `POST /api/v1/files/upload`
- `GET /api/v1/files/{file_id}/content`
