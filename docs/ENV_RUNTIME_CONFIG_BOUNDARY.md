# ENV 与 Runtime Config 边界说明

## 1. ENV / settings 的职责

`ENV` / `app.core.config.settings` 负责“启动级”与“基础平台级”配置，包括但不限于：

- 应用启动参数与版本信息
- 数据库连接（如 `DATABASE_URL`）
- JWT 密钥与认证算法（如 `SECRET_KEY`）
- CORS 与部署环境开关
- Docker/K8s 等部署注入参数
- 系统启动前必须存在的配置

## 2. system_config 的职责

`system_config` 负责“运行期可维护”配置，包括：

- 外部集成配置（AMap / HIFLEET / ES）
- 业务运行参数（超时、模式、开关等）
- 连接测试状态记录（`last_test_*`）
- 运营可观察、可在线维护的配置项

## 3. 读取优先级

`RuntimeConfigService` 读取优先级：

1. DB：`system_config` 中 `ACTIVE` 配置
2. ENV/settings 回退
3. 调用方 `default`
4. `EMPTY`

## 4. 敏感配置安全

- 即使 DB 敏感值为空并回退到 ENV，诊断接口也不会返回明文。
- 内部服务读取（`get_value`）仍可获得真实值，以保障业务调用。
- 前端配置中心只展示掩码，不回显敏感明文。
- 禁止在日志和错误 message 中输出真实密钥。

## 5. 不进入 system_config 的配置

以下配置保持在 ENV/settings：

- `DATABASE_URL`
- `SECRET_KEY`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `ALLOWED_ORIGINS` / CORS 配置
- `DEBUG`
- `ENVIRONMENT`
- Alembic / migration 运行配置

## 6. 可进入 system_config 的配置

以下配置可进入 `system_config` 进行运行期治理：

- `ROUTE_AMAP_WEB_API_KEY`
- `ROUTE_GEOMETRY_TIMEOUT_SECONDS`
- `ROUTE_GEOMETRY_MODE`
- `AMAP_JS_API_KEY`
- `AMAP_SECURITY_JS_CODE`
- `AI_PROVIDER`
- `DASHSCOPE_BASE_URL`
- `DASHSCOPE_FAST_MODEL`
- `DASHSCOPE_MODEL`
- `DASHSCOPE_TIMEOUT_SECONDS`
- `DASHSCOPE_STREAM_TIMEOUT_SECONDS`
- `DASHSCOPE_STRONG_REVIEW_ENABLED`
- `FREIGHT_AI_STALE_HEARTBEAT_SECONDS`
- `HIFLEET_*`
- `ES_REALTIME / ES_HISTORY` 连接配置

说明：

- 前端地图配置通过 `GET /api/v1/system/frontend-map-config` 获取。
- 该接口只返回 `AMAP_JS_API_KEY` 与 `AMAP_SECURITY_JS_CODE`，不返回 `ROUTE_AMAP_WEB_API_KEY`。
- 通义千问真实密钥 `DASHSCOPE_API_KEY` 优先从 ENV 读取，seed 只保存脱敏占位。
- 微信货源解析主链路使用 DashScope SDK 流式调用，`DASHSCOPE_FAST_MODEL` 负责 AI 切分和抽取，`DASHSCOPE_MODEL` 负责强模型复核。

## 7. 后续扩展规则

新增外部集成时，按以下步骤收口：

1. 在 `app/integrations/config_keys.py` 定义 key 常量
2. 在 `scripts/seed_system_base.py` 增加配置 seed
3. 在 `RuntimeConfigService` 调用链或客户端中通过统一 key 读取
4. 如需连接测试，在 `ConfigTestService` 增加 profile 测试逻辑
5. 前端配置中心自动通过 `/system/configs` 展示，无需新增页面
