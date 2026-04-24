# Inland Shipping Platform Backend

非 AI 正式业务后端基线（模块化单体）。当前仅保留正式业务域：字典、系统、审核、地址、货品、船舶、货源、航线、分析。

## 当前模块

- `dictionary`
- `system`（含 `auth`）
- `audit`
- `address`
- `commodity`
- `ship`
- `freight`
- `route`
- `analysis`

## 目录结构

```text
app/
  core/                 # 配置、数据库、异常、日志、安全
  integrations/         # amap / hifleet / es / http
  models/               # ORM 真值
  modules/              # 业务实现层（router/service/repository/schemas）
  api/v1/               # 路由聚合装配层
scripts/
  seed_*.py             # 正式初始化链
  seed_data/            # 正式初始化数据源
alembic/
docs/
```

## 环境变量

- 复制 `.env.example` 为 `.env` 后再启动。
- 变量说明与运行边界见文档：
  - [BACKEND_OVERVIEW_AND_ARCHITECTURE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_OVERVIEW_AND_ARCHITECTURE.md)
  - [BACKEND_SEED_AND_INITIALIZATION.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_SEED_AND_INITIALIZATION.md)

## Migration

```bash
alembic upgrade head
```

## 正式 Seed 初始化

```bash
python -m scripts.seed_system_init
```

## 启动方式

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Docs 阅读顺序

1. [BACKEND_OVERVIEW_AND_ARCHITECTURE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_OVERVIEW_AND_ARCHITECTURE.md)
2. [BACKEND_DATA_MODEL_AND_SEQUENCE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_DATA_MODEL_AND_SEQUENCE.md)
3. [BACKEND_SEED_AND_INITIALIZATION.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_SEED_AND_INITIALIZATION.md)
4. [BACKEND_API_REFERENCE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_API_REFERENCE.md)
5. [BACKEND_FINAL_ACCEPTANCE_REPORT.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_FINAL_ACCEPTANCE_REPORT.md)
