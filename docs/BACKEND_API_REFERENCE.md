# BACKEND API REFERENCE

## 1. 通用约定

- Base URL: `/api/v1`
- 认证方式：`Authorization: Bearer <access_token>`
- 无需登录的接口：
  - `POST /api/v1/auth/login`
  - `GET /health`
  - `GET /docs`

## 2. Auth & System

### 2.1 Auth
- `POST /auth/login`：账号登录
- `POST /auth/logout`：登出
- `GET /auth/me`：当前用户信息
- `GET /auth/me/menus`：当前用户菜单树
- `PUT /auth/me/password`：修改本人密码

### 2.2 System
- `GET /system/users`：用户列表
- `GET /system/users/{user_id}`：用户详情
- `POST /system/users`：创建用户
- `PUT /system/users/{user_id}`：更新用户
- `PUT /system/users/{user_id}/reset-password`：重置密码
- `PUT /system/users/{user_id}/status`：变更用户状态
- `PUT /system/users/{user_id}/roles`：替换用户角色
- `GET /system/users/{user_id}/status-logs`：用户状态变更记录

- `GET /system/roles`：角色列表
- `GET /system/roles/{role_id}`：角色详情
- `POST /system/roles`：创建角色
- `PUT /system/roles/{role_id}`：更新角色
- `PUT /system/roles/{role_id}/permissions`：替换角色权限
- `PUT /system/roles/{role_id}/menus`：替换角色菜单
- `PUT /system/roles/{role_id}/data-scopes`：替换角色数据权限

- `GET /system/permissions`：权限分页
- `GET /system/permissions/all`：全部权限
- `GET /system/menus`：菜单分页
- `GET /system/menus/tree`：菜单树
- `POST /system/menus`：创建菜单
- `PUT /system/menus/{menu_id}`：更新菜单
- `GET /system/data-scopes`：数据权限分页
- `GET /system/data-scopes/all`：全部数据权限
- `GET /system/configs`：系统配置分页
- `GET /system/configs/{config_key}`：系统配置详情
- `GET /system/runtime-configs/{config_key}`：运行时配置读取诊断
- `GET /system/frontend-map-config`：前端地图加载配置
- `POST /system/config-tests/{profile_code}`：外部集成连接测试
- `POST /system/configs`：创建系统配置
- `PUT /system/configs/{config_key}`：更新系统配置
- `GET /system/login-logs`：登录日志分页

#### 阶段 1 系统治理接口范围

阶段 1 系统治理相关接口固定为以下四组：

- 配置中心：`/system/configs*`
- 运行时诊断：`/system/runtime-configs/{config_key}`
- 连接测试：`/system/config-tests/{profile_code}`
- 菜单管理：`/system/menus*`

详细边界与职责见：

- `docs/STAGE_1_SYSTEM_GOVERNANCE_ACCEPTANCE.md`
- `docs/ENV_RUNTIME_CONFIG_BOUNDARY.md`
- `docs/MENU_ROUTE_SEED_ALIGNMENT.md`

#### /system/menus 与 /system/menus/tree（阶段 1E）

- `GET /system/menus`
  - 用途：菜单分页查询（后台菜单管理页）。
  - 常用查询参数：`keyword`、`status_code`、`page`、`page_size`。
- `GET /system/menus/tree`
  - 用途：返回树结构菜单，供左侧树与父级菜单选择器使用。
- `POST /system/menus`
  - 用途：新增菜单。
  - 核心字段：`parent_id`、`menu_code`、`menu_name`、`menu_type_code`、`route_path`、`component_path`、`icon`、`sort_order`、`visible_flag`、`status_code`。
  - 约束：`menu_code` 唯一；`visible_flag` 仅允许 `0/1`；`parent_id` 非空时必须存在。
- `PUT /system/menus/{menu_id}`
  - 用途：更新菜单（不允许改 `menu_code`）。
  - 核心字段：`parent_id`、`menu_name`、`menu_type_code`、`route_path`、`component_path`、`icon`、`sort_order`、`visible_flag`、`status_code`。
  - 约束：`parent_id` 不能指向自身；`parent_id` 非空时必须存在；空更新会返回业务校验错误。

菜单与路由对齐规则见文档：`docs/MENU_ROUTE_SEED_ALIGNMENT.md`。

#### /system/configs 补充说明（阶段 1A）

- `GET /system/configs` 支持查询参数：
  - `keyword`
  - `group_code`
  - `profile_code`（映射到 `config_profile_code`）
  - `status_code`（映射到 `config_status_code`）
  - `page`
  - `page_size`
- 返回字段新增：
  - `config_value_masked`
  - `config_profile_code`
  - `sensitive_flag`
  - `encrypted_flag`
  - `editable_flag`
  - `sort_order`
  - `config_status_code`
  - `last_test_status_code`
  - `last_test_message`
  - `last_tested_at`
- 敏感值响应规则：
  - 当 `sensitive_flag=1` 时，`config_value` 固定返回空字符串，真实值不明文返回。
  - 同时 `config_value_masked` 返回掩码值（用于前端展示）。
  - 当 `sensitive_flag!=1` 时，`config_value` 返回原值，`config_value_masked` 为 `null`。
- `last_test_*` 字段用于记录连接测试结果，占位与回写由 `/system/config-tests/{profile_code}` 配合完成。
- 阶段 1C-1 已在 seed 中补齐 AMap / HiFleet / ES 的 `INTEGRATION` 配置项，后续外部集成通过统一 key 读取。

#### /system/runtime-configs/{config_key}（阶段 1B）

- 用途：运行时配置读取诊断（DB 优先、ENV 回退、default 兜底）。
- 查询参数：
  - `profile_code`（可选）
  - `default`（可选）
- 返回字段：
  - `config_key`
  - `profile_code`
  - `value`
  - `source`（`DB/ENV/DEFAULT/EMPTY`）
- 敏感配置规则：
  - 如果 key 被识别为敏感，`value` 固定返回空字符串（不区分 `DB/ENV/DEFAULT/EMPTY` 来源）。
  - 敏感识别来源包括：`system_config.sensitive_flag` 与后端内置敏感 key 集合。
  - `source` 仍真实返回 `DB/ENV/DEFAULT/EMPTY`，用于排查读取来源。
- 阶段 1C-1 说明：
  - AMap / HiFleet / ES 客户端已支持注入 `RuntimeConfigService`，可复用该诊断接口对 key 来源进行排查。

#### /system/frontend-map-config（阶段 2A）

- 用途：前端地图组件加载配置读取（登录态可访问）。
- 返回字段：
  - `provider`
  - `amap_js_api_key`
  - `amap_security_js_code`
  - `configured`
  - `default_center_lng`
  - `default_center_lat`
  - `default_zoom`
  - `message`
- 规则：
  - `provider` 固定返回 `AMAP`。
  - `configured=true` 表示 `amap_js_api_key` 非空。
  - 如果 JS Key 未配置，返回 `configured=false` 且 `message=AMAP_JS_API_KEY 未配置`。
- 安全边界：
  - 该接口只返回前端 JS 地图加载所需配置。
  - 不返回 `ROUTE_AMAP_WEB_API_KEY` 等后端 WebService 密钥。
  - 通用 `/system/configs` 的敏感掩码规则保持不变。

#### /system/config-tests/{profile_code}（阶段 1C-2）

- 用途：执行外部集成连接测试，并回写 `system_config.last_test_*` 结果字段。
- 支持 `profile_code`：
  - `AMAP`
  - `HIFLEET`
  - `ES_REALTIME`
  - `ES_HISTORY`
- Request：
  - `timeout_seconds`（可选）
  - `remark`（可选）
- Response：
  - `profile_code`
  - `status_code`（`SUCCESS/FAILED/SKIPPED`）
  - `message`
  - `tested_at`
  - `affected_config_count`
- 安全规则：
  - `message` 不应包含敏感配置明文。
  - `GET /system/configs` 仍按既有敏感值掩码规则返回，不泄露密码/密钥。

## 3. Dictionary

- `GET /dictionary/dicts`：字典列表
- `GET /dictionary/dicts/{dict_code}`：字典详情
- `POST /dictionary/dicts`：创建字典
- `PUT /dictionary/dicts/{dict_id}`：更新字典
- `DELETE /dictionary/dicts/{dict_id}`：禁用字典

- `GET /dictionary/dicts/{dict_code}/items`：字典项列表
- `POST /dictionary/dicts/{dict_code}/items`：创建字典项
- `PUT /dictionary/items/{item_id}`：更新字典项
- `DELETE /dictionary/items/{item_id}`：禁用字典项
- `PUT /dictionary/dicts/{dict_code}/items/order`：字典项排序

- `GET /dictionary/code-sequences`：编码序列列表
- `GET /dictionary/code-sequences/{business_code}`：编码序列详情

## 4. Address

### 4.1 行政区划
- `GET /address/admin-regions`
- `GET /address/admin-regions/{admin_code}`
- `GET /address/admin-regions/{admin_code}/children`
- `GET /address/options/cities`
- `GET /address/options/cities/{city_code}/districts`

### 4.2 业务区域
- `GET /address/regions`
- `GET /address/regions/{region_id}`
- `POST /address/regions`
- `PUT /address/regions/{region_id}`
- `GET /address/regions/{region_id}/boundaries`
- `POST /address/regions/{region_id}/boundaries`
- `PUT /address/regions/{region_id}/boundaries/{version_id}/activate`
- `PUT /address/regions/{region_id}/cities`

### 4.3 运输节点与约束点
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

## 5. Commodity

- `GET /commodity/categories`
- `GET /commodity/categories/{category_id}`
- `POST /commodity/categories`
- `PUT /commodity/categories/{category_id}`

- `GET /commodity/types`
- `GET /commodity/types/{type_id}`
- `POST /commodity/types`
- `PUT /commodity/types/{type_id}`

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

## 6. Ship

- `GET /ship`
- `POST /ship`
- `GET /ship/{ship_id}`
- `PUT /ship/{ship_id}`
- `PUT /ship/{ship_id}/status`
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

### 6.1 Ship Import
- `GET /ship/import/batches`
- `GET /ship/import/batches/{batch_id}`
- `POST /ship/import/batches`
- `GET /ship/import/batches/{batch_id}/raw-records`
- `POST /ship/import/batches/{batch_id}/raw-records`
- `GET /ship/import/batches/{batch_id}/records`

## 7. Freight

- `GET /freight`
- `GET /freight/{freight_id}`
- `POST /freight`
- `PUT /freight/{freight_id}`
- `PUT /freight/{freight_id}/status`
- `PUT /freight/{freight_id}/contacts`
- `GET /freight/{freight_id}/attachments`
- `POST /freight/{freight_id}/attachments`
- `PUT /freight/attachments/{attachment_id}`
- `DELETE /freight/attachments/{attachment_id}`
- `GET /freight/{freight_id}/tags`
- `PUT /freight/{freight_id}/tags`

## 8. Route

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

- `GET /route/plans/{plan_id}/segments`
- `POST /route/plans/{plan_id}/segments`
- `PUT /route/segments/{segment_id}`
- `DELETE /route/segments/{segment_id}`
- `PUT /route/plans/{plan_id}/segments/order`

- `GET /route/segments/{segment_id}/points`
- `POST /route/segments/{segment_id}/points`
- `PUT /route/points/{point_id}`
- `DELETE /route/points/{point_id}`
- `PUT /route/segments/{segment_id}/points/order`

- `POST /route/plans/{plan_id}/geometry/refresh`
- `POST /route/segments/{segment_id}/geometry/refresh`

## 9. Analysis

- `GET /analysis/cargo/daily`
- `GET /analysis/cargo/cities`
- `GET /analysis/cargo/flows`
- `GET /analysis/cargo/commodities`
- `GET /analysis/cargo/channels`
- `GET /analysis/ships/cities`
- `GET /analysis/ships/flows`
- `GET /analysis/jobs`
- `GET /analysis/jobs/{job_run_id}`

## 10. Audit

- `GET /audit/tasks`
- `GET /audit/tasks/{task_id}`
- `POST /audit/tasks`
- `PUT /audit/tasks/{task_id}/assign`
- `PUT /audit/tasks/{task_id}/approve`
- `PUT /audit/tasks/{task_id}/reject`
- `PUT /audit/tasks/{task_id}/cancel`
- `GET /audit/pending-count`
- `GET /audit/tasks/{task_id}/records`
