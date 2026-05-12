# Inland Shipping Platform

内河航运数据分析平台后端。当前分支已经完成删除式生产级重构的主线收口：系统围绕运输机会、运力中心、航线区域、运价报价、数据质量治理组织，而不是按演示后台模块堆叠。

## 当前定位

- 业务主线：货源接入 -> 候选确认 -> 数据清洗 -> 运输机会 -> 船货匹配 -> 航线/区域分析 -> 报价决策 -> 治理回算。
- 后端栈：FastAPI、SQLAlchemy、Alembic、Celery、SQLite/MySQL、外部地图/AIS/AI/对象存储配置骨架。
- 数据库：仅保留 `alembic/versions/001_initial_schema.py` 作为当前生产基线。
- Seed：必须显式选择 `production` 或 `local-demo`，二者不得混写。
- 生产入口：货源业务列表使用 `/api/v1/freight/opportunities`，旧 `GET /api/v1/freight` 已删除。

## Local Run

```bash
cd /Users/hj/Documents/paltform_data_V2/inland-shipping-platform
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
.venv/bin/python -m scripts.seed_system_init --profile production
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

本地演示数据使用独立 profile，会重置本地库且要求本地外部服务配置完整：

```bash
.venv/bin/python -m scripts.seed_system_init --profile local-demo
```

## Checks

```bash
.venv/bin/pytest
.venv/bin/python -m scripts.verify_local_acceptance
.venv/bin/python -m scripts.verify_foundation_data_acceptance
```

## Final Docs

1. [PRODUCT_SPEC.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/PRODUCT_SPEC.md)
2. [BACKEND_ARCHITECTURE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_ARCHITECTURE.md)
3. [DATABASE_SCHEMA.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/DATABASE_SCHEMA.md)
4. [API_REFERENCE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/API_REFERENCE.md)
5. [FRONTEND_ARCHITECTURE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/FRONTEND_ARCHITECTURE.md)
6. [SEED_AND_INITIALIZATION.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/SEED_AND_INITIALIZATION.md)
7. [DEPLOYMENT_AND_CONFIG.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/DEPLOYMENT_AND_CONFIG.md)
8. [TEST_AND_ACCEPTANCE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/TEST_AND_ACCEPTANCE.md)
9. [REBUILD_EXECUTION_LOG.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/REBUILD_EXECUTION_LOG.md)
