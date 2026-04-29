# 阶段 1 系统治理底座验收报告

## 1. 阶段目标

阶段 1 的目标是建立一套可持续维护的系统治理底座，覆盖：

- 建立配置中心（`system_config` 元数据化）
- 建立运行时配置读取服务（`RuntimeConfigService`）
- 建立外部集成配置 key 规范（`app/integrations/config_keys.py`）
- 建立连接测试能力（`ConfigTestService`）
- 建立菜单管理能力（菜单查询/创建/更新 + 前端管理页）
- 建立后端 seed 与前端静态路由对齐规则

## 2. 已完成能力清单

### 1A：SystemConfig 元数据扩展

- `system_config` 扩展为配置中心元数据表：
  - `config_profile_code`
  - `sensitive_flag`
  - `encrypted_flag`
  - `editable_flag`
  - `sort_order`
  - `config_status_code`
  - `last_test_status_code`
  - `last_test_message`
  - `last_tested_at`
- 响应层支持敏感值掩码：`config_value_masked`
- 列表查询支持：`profile_code`、`status_code`

### 1B：RuntimeConfigService

- 新增 `RuntimeConfigService`
- 读取优先级：DB 优先 -> settings/env 回退 -> default 兜底 -> EMPTY
- 方法覆盖：
  - `get_value`
  - `get_bool`
  - `get_int`
  - `get_float`
  - `get_json`
  - `get_group`
- 新增诊断接口：`GET /api/v1/system/runtime-configs/{config_key}`

### 1C-1：外部集成配置 key 规范 + runtime_config 注入

- 新增统一 key 常量文件：`app/integrations/config_keys.py`
- AMap / HiFleet / ES 客户端支持可选 `runtime_config` 注入
- 未注入 `runtime_config` 时，保持 `settings` fallback，兼容旧调用

### 1C-1-fix：敏感 ENV fallback 防泄露

- 敏感识别采用双重机制：
  - DB 元数据 `sensitive_flag`
  - 内置敏感 key 集合（`SENSITIVE_RUNTIME_CONFIG_KEYS`）
- 即使 DB 敏感值为空并回退 ENV，诊断接口仍不返回明文

### 1C-2：外部集成连接测试

- 新增 `ConfigTestService`
- 新增连接测试接口：`POST /api/v1/system/config-tests/{profile_code}`
- 支持 profile：
  - `AMAP`
  - `HIFLEET`
  - `ES_REALTIME`
  - `ES_HISTORY`
- 测试结果写回：
  - `last_test_status_code`
  - `last_test_message`
  - `last_tested_at`

### 1D：前端配置中心页面

- 前端配置中心支持：
  - 配置查询/编辑
  - 敏感值不回显明文
  - profile 级连接测试
  - 测试状态字段展示

### 1E：菜单管理与 seed/routes 对齐

- 菜单管理后端校验增强（父级存在、自引用、基础字段清洗）
- 菜单管理前端页面支持新增/编辑/启停
- 固化 seed 与前端静态路由的边界规则

## 3. 后端接口清单

配置中心：

- `GET /api/v1/system/configs`
- `GET /api/v1/system/configs/{config_key}`
- `POST /api/v1/system/configs`
- `PUT /api/v1/system/configs/{config_key}`

运行时配置：

- `GET /api/v1/system/runtime-configs/{config_key}`

连接测试：

- `POST /api/v1/system/config-tests/{profile_code}`

菜单管理：

- `GET /api/v1/system/menus`
- `GET /api/v1/system/menus/tree`
- `POST /api/v1/system/menus`
- `PUT /api/v1/system/menus/{menu_id}`

## 4. 配置 profile 清单

当前阶段 1 有效 profile：

- `SYSTEM`：系统级基础运行配置
- `AMAP`：高德地图/路线相关配置
- `HIFLEET`：HiFleet（AMMS）路径与登录配置
- `ES_REALTIME`：实时 ES 连接配置
- `ES_HISTORY`：历史 ES 连接配置

## 5. 敏感配置规则

- `sensitive_flag=1` 时，`/system/configs` 不返回明文 `config_value`
- `config_value_masked` 按掩码规则展示（空或短值返回 `****`，长值返回 `******`+后四位）
- `/system/runtime-configs` 遇敏感 key 返回 `value=""`
- `RuntimeConfigService` 内部读取（如 `get_value`）仍可获取真实值，用于服务调用
- 已知敏感 key 集合包含：
  - `ROUTE_AMAP_WEB_API_KEY`
  - `AMAP_JS_API_KEY`
  - `AMAP_SECURITY_JS_CODE`
  - `HIFLEET_USERNAME`
  - `HIFLEET_PASSWORD`
  - `ES_PASSWORD`
  - `ES_R_PASSWORD`
- 禁止在日志、测试 message、前端页面中输出真实 `key/password/token/secret`

## 6. 连接测试规则

- `AMAP`：调用逆地理编码进行基础可用性测试
- `HIFLEET`：
  - 未启用（`HIFLEET_ENABLED=false`）返回 `SKIPPED`
  - 启用后执行登录测试
- `ES_REALTIME`：调用 `RealtimeEsClient.ping`
- `ES_HISTORY`：调用 `HistoryEsClient.ping`
- 测试结果写回对应 profile 下 `ACTIVE` 配置项

## 7. seed 规则

- `scripts/seed_system_base.py` 是系统治理基础 seed 真值
- `SYSTEM_CONFIGS` 初始化阶段 1 所需基础配置与外部集成配置
- `MENUS` 初始化左侧导航可见菜单与目录节点
- 不把所有 `.env` 变量搬进 `system_config`
- 不把所有隐藏详情页写入 `MENUS`

## 8. 当前边界

- 当前仍使用前端静态路由
- 当前不做完全动态路由
- 当前没有 `config_test_log` 表
- 当前没有 profile 独立表
- 当前没有真实加密/解密
- 当前配置中心承担运行配置管理，不承担密钥托管系统职责

## 9. 进入阶段 2 的前置条件

进入阶段 2（地图底座与地址模块）前，应满足：

- 配置中心页面可用
- AMap 配置项已存在（seed 与页面可见）
- `RuntimeConfigService` 可读取 AMap 配置
- 菜单 seed 与前端 routes 对齐
- 阶段 1 验收命令全部通过

## 10. 验收命令

后端基础验收：

```bash
python -m compileall app scripts alembic
```

或：

```bash
.venv/bin/python -m compileall app scripts alembic
```

数据库与服务验收：

```bash
rm -f inland_shipping.db
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed_system_init
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 18011
```

接口验收建议：

- `GET /api/v1/system/configs?profile_code=AMAP`
- `GET /api/v1/system/configs?profile_code=HIFLEET`
- `GET /api/v1/system/configs?profile_code=ES_REALTIME`
- `GET /api/v1/system/configs?profile_code=ES_HISTORY`
- `GET /api/v1/system/runtime-configs/ROUTE_GEOMETRY_TIMEOUT_SECONDS?profile_code=AMAP`
- `POST /api/v1/system/config-tests/HIFLEET`
- `GET /api/v1/system/menus`
- `GET /api/v1/system/menus/tree`
