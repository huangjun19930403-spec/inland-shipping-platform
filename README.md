# 内河航运数据分析平台后端

本后端是内河航运数据分析平台的业务 API、数据治理、分析任务和外部能力接入层。系统围绕货源接入、运输机会、船舶运力、航线区域、报价分析、审核治理和系统配置组织，目标是支撑生产级长期迭代，而不是演示页面堆叠。

## 技术栈

- FastAPI + Pydantic v2
- SQLAlchemy async ORM + Alembic
- SQLite 本地开发，MySQL 生产可选
- Celery + Redis 用于分析、AI 解析、AIS 预计算等后台任务
- DashScope Qwen、AMap/AMMS、HiFleet、ES、COS 作为可配置外部能力

## 目录结构

- `main.py`：FastAPI 入口，注册中间件、异常处理、CORS、生命周期清理。
- `app/api/v1`：API 聚合装配，只负责挂载模块 router。
- `app/core`：配置、数据库、安全、异常、日志、公共枚举。
- `app/models`：SQLAlchemy 数据模型。
- `app/modules`：业务模块，按 `dictionary/address/commodity/vessel/freight/route/analysis/audit/system/tasks/storage` 组织。
- `app/integrations`：AI、地图、AIS/ES、HiFleet、对象存储等外部接口封装。
- `app/tasks`：Celery 任务入口。
- `scripts/seeds`：显式 seed profile、loader、demo/test fixture、validation。
- `scripts/seed_data`：生产预制、演示、测试 seed 数据。
- `tests`：后端单元、契约和 seed 验证测试。

## 模块边界

- `freight`：微信/TMS 货源接入、候选证据、正式货源档案、清洗治理和运输机会读模型。生产入口应使用 `batch_service.py`、`tms_service.py`、`candidate_service.py`、`freight_profile_service.py`、`normalization_service.py`、`opportunity_service.py` 等明确边界。`service.py` 仅保留兼容导出。
- `vessel`：船舶台账、画像、证照、船东/经营人/联系人、合规风险、治理任务、OCR、AIS 态势和船货适配。新增代码必须优先使用 `app/modules/vessel/<domain>/service.py`，不要回到聚合 `VesselService`。
- `route` 与 `address`：航线、路线段、运输节点、业务区域、行政区划、航道、通航约束点和地图地理能力。
- `analysis`：经营总览、货源态势、运力指标、区域供需、流向、报价、任务运行。展示查询入口使用 `dashboard_service.py`，报价决策和运价估算分别由独立 service 承担。
- `commodity`：标准货品、分类、类型、别名、属性、运输规则和货品识别。
- `audit/system/tasks/storage`：审核流、认证授权、菜单权限、系统参数、异步任务与文件存储。

## 分层约定

- Router 只接收请求、校验参数、取当前用户并调用 Service。
- Service 承担业务用例，不直接堆积展示拼装、外部调用和状态机细节。
- Repository 只负责数据访问，不承载业务判断。
- Model 是数据库结构，Schema 是 API 入参/响应结构。
- 外部接口、AI 编排、后台任务、seed 初始化必须与普通 CRUD 分离。
- 公共响应、异常、分页、状态枚举、字典标签解析必须复用现有公共能力。

## 配置与环境变量

配置类在 `app/core/config.py`，示例在 `.env.example`。常用项：

- `DATABASE_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `SECRET_KEY`
- `ALLOWED_ORIGINS`
- `ROUTE_GEOMETRY_MODE`
- `ROUTE_AMAP_WEB_API_KEY`
- `DASHSCOPE_API_KEY`
- `HIFLEET_*`
- `ES_*`
- `COS_*`

本地敏感配置放 `.env.local` 或运行环境，不提交明文密钥。

## 本地启动

```bash
cd /Users/hj/Documents/paltform_data_V2/inland-shipping-platform
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
.venv/bin/python -m scripts.seeds.cli --profile local-demo
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Seed 与数据库初始化

Seed 必须显式指定 profile：

```bash
.venv/bin/python -m scripts.seeds.cli --profile production
.venv/bin/python -m scripts.seeds.cli --profile local-demo
.venv/bin/python -m scripts.seeds.cli --profile test
```

- `production`：生产预制基础数据，不写入 demo/test/LOCAL_DEMO 数据。
- `local-demo`/`demo`：先加载 production，再追加带 `FR-DEMO-*`、`DEMO_ROUTE_*`、`LOCAL_DEMO` 标识的演示链路。
- `test`：生产基础 seed 加自动化测试夹具，只写 `TEST_*` / `TEST-FR-*`。

生产 seed 只读取 `scripts/seed_data/production_manifest.json` 列出的 curated JSON。不要把临时 SQL、中间清洗输出或调试数据加入 production profile。

## 常用验证

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.seeds.validation.foundation_data_acceptance
.venv/bin/python -m scripts.seeds.validation.local_acceptance
```

后台任务本地运行：

```bash
cd /Users/hj/Documents/paltform_data_V2/inland-shipping-platform
.venv/bin/celery -A app.tasks.celery_app:celery_app worker \
  -n inland_worker@%h \
  -Q analysis,freight_ai,vessel_ai \
  -B \
  -s /private/tmp/inland_celerybeat_schedule.db \
  --loglevel=info
```

更稳妥的方式是 worker 与 beat 分开运行：

```bash
cd /Users/hj/Documents/paltform_data_V2/inland-shipping-platform
.venv/bin/celery -A app.tasks.celery_app:celery_app worker \
  -n inland_worker@%h \
  -Q analysis,freight_ai,vessel_ai \
  --loglevel=info

.venv/bin/celery -A app.tasks.celery_app:celery_app beat \
  -s /private/tmp/inland_celerybeat_schedule.db \
  --loglevel=info
```

启动后用只读健康检查确认在线 worker 注册了最新任务：

```bash
.venv/bin/python scripts/check_celery_registered_tasks.py --inspect-workers
```

如果缺少 `route.generate_track_version` 或 `vessel.precompute_production_candidate_analyses`，说明旧 worker 没有加载当前代码；先停止旧 worker，再从后端仓库根目录按上面的命令重启，不要通过重复点击业务按钮恢复。

## 接口调试

- 认证：`POST /api/v1/auth/login`，`GET /api/v1/auth/me`，`GET /api/v1/auth/me/menus`
- 货源机会：`GET /api/v1/freight/opportunities`
- 船舶台账：`GET /api/v1/vessels/assets`
- AIS 态势：`GET /api/v1/vessels/ais/city-situation`
- 航线：`GET /api/v1/route`
- 报价：`POST /api/v1/analysis/quote-simulator/decision`
- 运价估算：`POST /api/v1/analysis/rate-estimator/estimate`

## 后续开发规范

新增模块前先阅读根目录 `docs/DEVELOPMENT_GOVERNANCE.md`。新增接口、Service、seed、文档必须有明确业务归属；禁止复制已有实现后改名形成平行体系；禁止让 `service.py`、Vue 页面和 docs 目录继续膨胀。
