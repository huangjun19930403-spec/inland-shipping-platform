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
- `POST /system/configs`：创建系统配置
- `PUT /system/configs/{config_key}`：更新系统配置
- `GET /system/login-logs`：登录日志分页

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
