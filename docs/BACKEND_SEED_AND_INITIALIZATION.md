# BACKEND SEED AND INITIALIZATION

## 1. 正式 seed 与 demo 数据边界

### 1.1 正式初始化链（线上/测试/本地统一）

正式初始化链包含：

1. `seed_builtin_dicts`
2. `seed_code_sequences`
3. `seed_admin_regions`
4. `seed_commodity_taxonomy`
5. `seed_commodity_standards`
6. `seed_system_base`
7. `seed_route_map_e2e`

统一入口：

- `python -m scripts.seed_system_init`

### 1.2 demo 数据边界

demo freight/ship/route/analysis 数据不在正式初始化链中。  
当前后端初始化默认不加载演示数据。

## 2. seed 数据目录

正式数据源位于 `scripts/seed_data/`：

- 行政区划：
  - `scripts/seed_data/admin_region/admin_region_raw.json`
  - `scripts/seed_data/admin_region/admin_region_boundary_city_raw.json`
- 货品：
  - `scripts/seed_data/commodity/commodity_categories.json`
  - `scripts/seed_data/commodity/commodity_types.json`
  - `scripts/seed_data/commodity/commodity_standards.json`

说明：

- 行政区划 seed 运行时只读取 `scripts/seed_data/admin_region/*`
- 不再从历史 `docs/v3/*` 目录读取 seed 数据

## 3. 各 seed 脚本职责

- `scripts/seed_builtin_dicts.py`
  - 初始化 `std_dict / std_dict_item` 的正式基础字典

- `scripts/seed_code_sequences.py`
  - 初始化 `code_sequence`
  - 包含 `REGION_CODE/NODE_CODE/ROUTE_CODE/FREIGHT_NO/...` 等业务编码序列

- `scripts/seed_admin_regions.py`
  - 初始化 `admin_region` 与行政区划边界信息

- `scripts/seed_commodity_taxonomy.py`
  - 初始化 `commodity_category / commodity_type`

- `scripts/seed_commodity_standards.py`
  - 初始化首版 `commodity_standard / commodity_alias`

- `scripts/seed_system_base.py`
  - 初始化系统基础对象（管理员、角色、权限、菜单、系统配置最小集合）

- `scripts/seed_route_map_e2e.py`
  - 初始化航线地图 E2E 稳定基线数据（起终业务区域、区域边界、航线、路径方案、航段、点位）
  - 数据以 `E2E_*` 编码前缀标识，仅用于本地开发/CI/Playwright 验收链路

- `scripts/seed_system_init.py`
  - 统一串联上述正式初始化步骤

## 4. 初始化执行方式

### 4.1 本地命令

```bash
alembic upgrade head
PYTHONPATH=. python -m scripts.seed_system_init
```

### 4.2 容器入口

`docker/entrypoint.sh` 默认执行：

1. 数据库可达等待
2. `alembic upgrade head`
3. `python -m scripts.seed_system_init`
4. `uvicorn main:app ...`

## 5. 幂等与顺序约束

- 正式初始化应按固定顺序执行，避免外键与字典依赖冲突
- 同一环境重复执行时，脚本应尽量幂等（按唯一键更新或跳过）
- `code_sequence` 与系统基础对象初始化必须在业务数据写入前完成

## 6. SYSTEM_CONFIGS 收口范围（阶段 1）

`seed_system_base.py` 中 `SYSTEM_CONFIGS` 当前覆盖以下 profile：

- `SYSTEM`
- `AMAP`
- `HIFLEET`
- `ES_REALTIME`
- `ES_HISTORY`

说明：

- 仅纳入运行期可维护配置与外部集成配置。
- 不将所有 ENV 变量搬入 `system_config`。
- 启动级配置（数据库、JWT、CORS、环境开关）仍由 ENV/settings 维护。
- 阶段 2A 为本地联调预置了 AMap 测试 Key（`AMAP_JS_API_KEY`、`AMAP_SECURITY_JS_CODE`、`ROUTE_AMAP_WEB_API_KEY`）。
- 这些 Key 仅用于测试环境；上线前必须替换为正式 Key，并建议在高德控制台轮换测试 Key。
- `ROUTE_AMAP_WEB_API_KEY` 属于后端 WebService 密钥，不通过前端地图配置接口下发。

## 8. 航线地图 E2E 稳定基线（阶段 3D）

`seed_route_map_e2e.py` 由 `seed_system_init.py` 自动接入，提供稳定的航线地图自动化验收数据：

- 起终业务区域：
  - `E2E_ROUTE_ORIGIN`
  - `E2E_ROUTE_DEST`
- 航线：
  - `E2E_ROUTE_MAP`
- 路径方案：
  - `E2E_ROUTE_PLAN_MAP`
- 方案内至少 2 条航段、每条至少 3 个点位：
  - 航段 1：有 `geometry_json`（LineString）
  - 航段 2：`geometry_json` 为空，依赖点位 fallback 连线

幂等策略：

- 区域按 `code`
- 航线按 `code`
- 方案按 `plan_code`
- 航段按 `(plan_id, segment_no)`
- 点位按 `(segment_id, point_no)`
- 区域边界按 `(region_id, version_no)`，并维护 `is_current/current_boundary_version_id`

边界说明：

- 仅更新/维护 `E2E_*` 专属测试数据，不影响非 E2E 业务记录。
- 用途限定为本地开发、CI、Playwright 自动化验收，不作为生产业务主数据来源。

## 9. 通航约束点 E2E 基线（阶段 4C）

`seed_navigation_constraints.py` 由 `seed_system_init.py` 自动接入，提供通航约束点管理页面和后续路径节点串能力所需的稳定基础数据：

- `E2E_CONSTRAINT_LOCK`：船闸约束点，带吨位、吃水、船宽、船长、通行时间窗口 Profile。
- `E2E_CONSTRAINT_BRIDGE`：桥梁净空约束点，带净空和船宽 Profile。
- `E2E_CONSTRAINT_SHALLOW`：浅滩/水深约束点，带最小水深、最大允许吃水和富余水深 Profile。

幂等策略：

- 通航约束点按 `code` upsert。
- Profile 按 `constraint_point_id` upsert。
- 仅维护 `E2E_CONSTRAINT_*` 专属数据，不影响非 E2E 业务记录。

该 seed 同时依赖 `NAVIGATION_CONSTRAINT_TYPE` 字典项，用于约束类型选择和前端筛选展示。

## 7. MENUS 收口范围（阶段 1）

- `MENUS` 维护左侧导航可见入口和目录节点。
- `menu_type_code=DIRECTORY` 的节点可不设置 `route_path/component_path`。
- 详情页、编辑页等 `hidden route` 不进入 seed，由前端 `routes.ts` 维护并通过 `activeMenu` 归属。
- 菜单与路由对齐规则见 `docs/MENU_ROUTE_SEED_ALIGNMENT.md`。
