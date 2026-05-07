# Backend API Reference

Base URL: `/api/v1`

认证方式：`Authorization: Bearer <access_token>`。响应统一包含请求追踪能力，后端会回写 `X-Request-ID`。

基础数据接口默认要求登录，包括 `dictionary`、`address`、`commodity` 下的只读元数据和 options 接口。

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

内置字典包含 `COMMODITY_UNIT` 和 `DANGEROUS_GOODS_LEVEL`，业务接口默认返回 code 与中文 name，前端主视觉应展示中文名。

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

业务区域、地址节点、通航约束点新增时由后端自动生成编码。地址节点创建和编辑根据 `city_code` 自动回填 `city_region_id`，响应补充行政区划、节点类型、生命周期、状态等中文名字段。

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

标准货品新增时由后端自动生成编码。创建接口只接收核心字段，主单位字段为 `main_unit_code`，响应补充 `main_unit_name`、`dangerous_grade_name` 和 `audit_status_name`。

标准货品详情接口返回结构化规则明细，不再以 code 数组作为主契约：

- `packaging_forms`: `{ code, name, is_default }`
- `transport_modes`: `{ code, name, is_default }`
- `ship_type_rules`: `{ code, name, allow_flag, rule_desc }`
- `node_type_rules`: `{ code, name, allow_flag, rule_desc }`
- `handling_mode_rules`: `{ code, name, allow_flag, rule_desc }`

规则维护接口同步接收结构化 `items`。包装形式、运输方式使用 `{ code, is_default }`；船型、节点类型、作业方式使用 `{ code, allow_flag, rule_desc }`。

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
- `POST /freight/manual`
- `PUT /freight/{freight_id}`
- `PUT /freight/{freight_id}/status`
- `PUT /freight/{freight_id}/contacts`
- `GET /freight/{freight_id}/attachments`
- `POST /freight/{freight_id}/attachments`
- `PUT /freight/attachments/{attachment_id}`
- `DELETE /freight/attachments/{attachment_id}`
- `GET /freight/{freight_id}/tags`
- `PUT /freight/{freight_id}/tags`
- `GET /freight/batches`
- `POST /freight/batches/wechat`
- `GET /freight/batches/{batch_id}`
- `POST /freight/batches/{batch_id}/parse`
- `GET /freight/tms-inbounds`
- `POST /freight/tms-inbounds`
- `GET /freight/tms-inbounds/{inbound_id}`
- `POST /freight/tms-inbounds/{inbound_id}/parse`
- `GET /freight/candidates`
- `GET /freight/candidates/{id}`
- `PUT /freight/candidates/{id}`
- `POST /freight/candidates/{id}/confirm`
- `POST /freight/candidates/{id}/reject`

手工录入直接生成正式货源。微信批次和 TMS 入站先执行 AI 线索切分，再通过节点、城市、区域和标准货品匹配生成候选货源，人工确认后写入 `freight`。旧 `/freight/source-inbounds*` 和 `/freight/ai/parse-tasks*` 已移除。

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
- `GET /analysis/freight/node-ranking`
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
- `GET /analysis/tasks`
- `GET /analysis/tasks/{job_code}`
- `POST /analysis/tasks/{job_code}/trigger`
- `GET /analysis/tasks/{job_code}/runs`
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
