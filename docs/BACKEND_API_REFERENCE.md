# Backend API Reference

Base URL: `/api/v1`

认证方式：`Authorization: Bearer <access_token>`。响应统一包含请求追踪能力，后端会回写 `X-Request-ID`。

## Auth / System

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /auth/me/menus`
- `PUT /auth/me/password`
- `GET /system/users`
- `GET /system/roles`
- `GET /system/permissions`
- `GET /system/menus`
- `GET /system/menus/tree`
- `GET /system/configs`
- `GET /system/configs/{config_key}`
- `GET /system/runtime-configs/{config_key}`
- `GET /system/frontend-map-config`
- `POST /system/config-tests/{profile_code}`
- `GET /system/login-logs`

系统配置接口对通义千问、地图等敏感项只返回掩码和配置状态，不返回真实密钥。

## Dictionary

- `GET /dictionary/dicts`
- `GET /dictionary/dicts/{dict_code}`
- `POST /dictionary/dicts`
- `PUT /dictionary/dicts/{dict_id}`
- `DELETE /dictionary/dicts/{dict_id}`
- `GET /dictionary/dicts/{dict_code}/items`
- `POST /dictionary/dicts/{dict_code}/items`
- `PUT /dictionary/items/{item_id}`
- `DELETE /dictionary/items/{item_id}`
- `PUT /dictionary/dicts/{dict_code}/items/order`
- `GET /dictionary/code-sequences`
- `GET /dictionary/code-sequences/{business_code}`

## Address

- `GET /address/admin-regions`
- `GET /address/admin-regions/{admin_code}`
- `GET /address/admin-regions/{admin_code}/children`
- `GET /address/options/cities`
- `GET /address/options/cities/{city_code}/districts`
- `GET /address/regions`
- `GET /address/regions/{region_id}`
- `POST /address/regions`
- `PUT /address/regions/{region_id}`
- `GET /address/regions/{region_id}/boundaries`
- `POST /address/regions/{region_id}/boundaries`
- `PUT /address/regions/{region_id}/boundaries/{version_id}/activate`
- `PUT /address/regions/{region_id}/cities`
- `GET /address/nodes`
- `GET /address/nodes/{node_id}`
- `POST /address/nodes`
- `PUT /address/nodes/{node_id}`
- `PUT /address/nodes/{node_id}/profile`
- `PUT /address/nodes/{node_id}/aliases`
- `PUT /address/nodes/{node_id}/business-categories`
- `PUT /address/nodes/{node_id}/packaging-forms`
- `PUT /address/nodes/{node_id}/handling-modes`
- `GET /address/constraint-points`
- `GET /address/constraint-points/{point_id}`
- `POST /address/constraint-points`
- `PUT /address/constraint-points/{point_id}`
- `PUT /address/constraint-points/{point_id}/profile`
- `PUT /address/constraint-points/{point_id}/status`

## Commodity

- `GET /commodity/metadata`
- `GET /commodity/standards`
- `GET /commodity/standards/{standard_id}`
- `POST /commodity/standards`
- `PUT /commodity/standards/{standard_id}`
- `PUT /commodity/standards/{standard_id}/aliases`
- `PUT /commodity/standards/{standard_id}/attributes`
- `PUT /commodity/standards/{standard_id}/packaging-forms`
- `PUT /commodity/standards/{standard_id}/transport-modes`
- `PUT /commodity/standards/{standard_id}/ship-type-rules`
- `PUT /commodity/standards/{standard_id}/node-type-rules`
- `PUT /commodity/standards/{standard_id}/handling-mode-rules`

## Ship

- `GET /ship`
- `POST /ship`
- `GET /ship/{ship_id}`
- `PUT /ship/{ship_id}`
- `PUT /ship/{ship_id}/status`
- `GET /ship/statistics/overview`
- `GET /ship/{ship_id}/capacity`
- `PUT /ship/{ship_id}/capacity`
- `GET /ship/{ship_id}/operation`
- `PUT /ship/{ship_id}/operation`
- `PUT /ship/{ship_id}/owners`
- `PUT /ship/{ship_id}/contacts`
- `GET /ship/{ship_id}/certificates`
- `POST /ship/{ship_id}/certificates`
- `PUT /ship/certificates/{certificate_id}`
- `DELETE /ship/certificates/{certificate_id}`
- `PUT /ship/certificates/{certificate_id}/files`
- `GET /ship/{ship_id}/name-history`
- `POST /ship/{ship_id}/name-history`
- `GET /ship/{ship_id}/mmsi-history`
- `POST /ship/{ship_id}/mmsi-history`

## Freight

- `GET /freight`
- `GET /freight/{freight_id}`
- `POST /freight`
- `PUT /freight/{freight_id}`
- `PUT /freight/{freight_id}/status`
- `GET /freight/source-inbounds`
- `POST /freight/source-inbounds`
- `GET /freight/source-inbounds/{id}`
- `GET /freight/ai/parse-tasks`
- `POST /freight/ai/parse-tasks`
- `GET /freight/ai/parse-tasks/{id}`
- `POST /freight/ai/parse-tasks/{id}/run`
- `GET /freight/candidates`
- `GET /freight/candidates/{id}`
- `PUT /freight/candidates/{id}`
- `POST /freight/candidates/{id}/confirm`
- `POST /freight/candidates/{id}/reject`

## Route

- `GET /route`
- `GET /route/{route_id}`
- `POST /route`
- `PUT /route/{route_id}`
- `PUT /route/{route_id}/status`
- `GET /route/{route_id}/plans`
- `POST /route/{route_id}/plans`
- `GET /route/plans/{plan_id}`
- `PUT /route/plans/{plan_id}`
- `PUT /route/plans/{plan_id}/status`
- `PUT /route/{route_id}/plans/{plan_id}/activate`
- `GET /route/plans/{plan_id}/lines`
- `POST /route/plans/{plan_id}/lines`
- `GET /route/lines/{line_id}`
- `PUT /route/lines/{line_id}`
- `DELETE /route/lines/{line_id}`
- `GET /route/lines/{line_id}/structure`
- `PUT /route/lines/{line_id}/structure`
- `GET /route/lines/{line_id}/track`
- `POST /route/lines/{line_id}/track/generate`

## Analysis

- `GET /analysis/overview`
- `GET /analysis/freight/overview`
- `GET /analysis/freight/trend`
- `GET /analysis/freight/commodity-structure`
- `GET /analysis/freight/tonnage-distribution`
- `GET /analysis/freight/price-distribution`
- `GET /analysis/freight/hot-routes`
- `GET /analysis/freight/flow-map`
- `GET /analysis/ships/overview`
- `GET /analysis/ships/type-distribution`
- `GET /analysis/ships/age-distribution`
- `GET /analysis/ships/deadweight-distribution`
- `GET /analysis/ships/active-trend`
- `GET /analysis/ships/flow-map`
- `GET /analysis/regions/overview`
- `GET /analysis/regions/heat-map`
- `GET /analysis/flows/overview`
- `GET /analysis/flows/map`
- `GET /analysis/prices/overview`
- `GET /analysis/jobs`
- `GET /analysis/jobs/{job_run_id}`

## Audit

- `GET /audit/metadata`
- `GET /audit/tasks`
- `GET /audit/tasks/{task_id}`
- `POST /audit/tasks`
- `PUT /audit/tasks/{task_id}/assign`
- `PUT /audit/tasks/{task_id}/approve`
- `PUT /audit/tasks/{task_id}/reject`
- `PUT /audit/tasks/{task_id}/cancel`
- `GET /audit/pending-count`
- `GET /audit/tasks/{task_id}/records`
