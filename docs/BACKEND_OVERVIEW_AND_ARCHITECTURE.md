# BACKEND OVERVIEW AND ARCHITECTURE

## 1. 项目定位

`inland-shipping-platform` 后端为非 AI 正式业务基线，采用模块化单体结构。  
当前仅保留正式业务域，不包含历史 AI/workflow/workspace/ship_analysis 链路。

## 2. 业务模块

- `dictionary`：标准字典、字典项、编码序列查询与生成
- `system`（含 `auth`）：登录认证、用户/角色/权限/菜单/配置/日志
- `audit`：审核任务与审核记录
- `address`：行政区划、业务区域、运输节点、约束点
- `commodity`：货品分类、类型、标准货品及规则关系
- `ship`：船舶主档、扩展信息、证书、导入批次
- `freight`：正式货源主档、联系人、附件、标签
- `route`：航线、方案、航段、点位与几何刷新
- `analysis`：统计结果查询与统计任务记录查询

## 3. 目录结构

```text
app/
  api/v1/                  # API 聚合装配
  core/                    # 配置、数据库、异常、日志、安全
  integrations/            # amap / hifleet / es / http
  models/                  # ORM 真值
  modules/                 # 唯一正式业务实现层
alembic/                   # 数据库迁移框架（单一初始迁移）
scripts/                   # 正式 seed 初始化链
scripts/seed_data/         # 正式初始化数据源
docs/                      # 后端核心文档
```

## 4. 运行配置

配置由 `app/core/config.py` 读取，环境变量模板见 `.env.example`。  
核心配置分组：

- 基础：`APP_NAME`、`APP_VERSION`、`DEBUG`
- 数据库：`DATABASE_URL`
- 认证：`SECRET_KEY`、`ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`
- 跨域：`ALLOWED_ORIGINS`
- 外部集成：`ES_*`、`ES_R_*`、`ROUTE_AMAP_WEB_API_KEY`、`HIFLEET_*`

`system` 模块提供 `RuntimeConfigService` 作为统一运行时读取入口，规则为：

1. DB 优先：优先读取 `system_config` 中 `ACTIVE` 配置
2. ENV/settings 回退：DB 无值或空值时回退 `settings`
3. default 兜底：仍无值时使用调用方默认值

说明：

- 内部服务读取时可拿到敏感配置真实值（用于后续集成调用）。
- API 响应层仍遵循敏感值隐藏规则，不泄露明文。
- 当前阶段不包含连接测试执行与真实加密能力。

## 5. 启动与初始化

本地最小流程：

1. `alembic upgrade head`
2. `python -m scripts.seed_system_init`
3. `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`

容器入口由 `docker/entrypoint.sh` 收口：

1. 等待数据库连通（可配置重试）
2. 执行迁移
3. 执行正式 seed 链
4. 启动 `uvicorn`

## 6. 外部依赖边界

- AMap：航线几何刷新
- HiFleet：水路路径能力（按开关启用）
- Elasticsearch：统计查询与历史查询数据源

外部依赖未配置不会改变后端正式业务模型语义，但会影响相关接口真实数据能力。

## 7. 开发约束

- 业务实现仅允许写入 `app/modules/*`
- `app/api/v1` 仅做 router 聚合装配
- 不恢复旧平铺 `services/repositories/schemas` 结构
- 不恢复 AI/workflow/workspace/ship_analysis 历史域
- 不在当前基线上新增与真值文档无关的业务表与业务模块
