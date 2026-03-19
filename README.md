# 内河航运标准数据与分析平台（一期）

## 项目定位
本项目一期是“内河航运标准数据与分析平台”，只做以下核心能力：
1. 标准数据体系建设（地址/货品/船舶/航线）。
2. 多源数据接入与标准化（微信群文本、TMS、AIS、Excel）。
3. 分析能力输出（货源与船舶统计）。
4. AI 融合（货源文本解析、匹配建议、解释生成）。

一期不做交易闭环，不做订单/运单/结算主流程，不做多租户 SaaS。

## 当前代码结构（真实主线）
```text
app/
  api/v1/
    standard_data/    # 标准数据域 API
    ingestion/        # 数据接入域 API
    analysis/         # 分析域 API
    ai/               # AI 能力域 API
    system/           # 系统域 API（登录/用户/审核）
  api/legacy/         # 旧路由归档（不作为主入口）

  domain/             # 领域服务主链（业务编排）
  repositories/       # 数据访问层
  models/             # ORM 模型
  jobs/               # 统计任务主链
  tasks/              # Celery/APScheduler 触发入口（主实现在 jobs）
  ai/                 # AI 解析、提示词、Provider、工作流
  core/               # 配置、数据库、安全、异常

alembic/
  versions/           # 当前有效迁移链
  versions_legacy/    # 历史迁移归档

docs/
  phase1-*.md
  phase2-*.md
  phase3-*.md
  phase4-*.md
  phase5-*.md
```

主 API 入口：`main.py -> app/api/v1/__init__.py`，只挂载五个新域。

## 环境准备
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

常用配置项：
1. `DATABASE_URL`
2. `DEBUG`
3. `SECRET_KEY`
4. AI Provider 相关密钥（按需）

## 数据库迁移
> 启动流程不再执行 `create_all`，统一走 Alembic。

```bash
source .venv/bin/activate
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. alembic current
```

## 初始化方式
```bash
source .venv/bin/activate
PYTHONPATH=. python -m scripts.seed_data
```

默认账号（开发数据）：
1. `admin / Admin@2026`
2. `collector1 / Test@2026`

## 启动方式
```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn main:app --host 127.0.0.1 --port 8000
```

文档：
1. `http://127.0.0.1:8000/docs`
2. `http://127.0.0.1:8000/redoc`

## 统计任务运行
主统计实现位于 `app/jobs/`。

```bash
# 货源统计（指定日期）
PYTHONPATH=. python -c "import asyncio; from datetime import date; from app.jobs.cargo_stats import run_cargo_stats; print(asyncio.run(run_cargo_stats(date.today())))"

# 船舶统计快照
PYTHONPATH=. python -c "import asyncio; from app.jobs.ship_stats import run_ship_stats; print(asyncio.run(run_ship_stats()))"
```

## 核心接口（一期）
统一前缀：`/api/v1`

1. `standard_data`
- `/standard-data/address/*`
- `/standard-data/commodity/*`
- `/standard-data/vessel/*`
- `/standard-data/route/*`

2. `ingestion`
- `/ingestion/cargo/text`
- `/ingestion/cargo/parse-result/{id}/confirm`
- `/ingestion/cargo/tms/raw`
- `/ingestion/vessel/dynamic/{mmsi}`
- `/ingestion/excel/vessel`

3. `analysis`
- `/analysis/dashboard`
- `/analysis/cargo/*`
- `/analysis/ship/*`
- `/analysis/run-stats`

4. `ai`
- `/ai/parse-status/{raw_message_id}`
- `/ai/reparse/{raw_message_id}`
- `/ai/prompts`
- `/ai/prompts/{template_id}/versions`
- `/ai/prompts/{template_id}/activate/{version}`
- `/ai/call-logs`
- `/ai/call-logs/stats`

5. `system`
- `/system/auth/login`
- `/system/auth/me`
- `/system/users*`
- `/system/audit/*`

## 测试
```bash
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Phase 6 已补齐：
1. API smoke tests
2. domain/service tests
3. analysis jobs tests
4. AI 解析链路 smoke tests

## 部署说明（生产）
1. 配置生产 `.env`（关闭 DEBUG，使用生产数据库）。
2. 执行迁移：`PYTHONPATH=. alembic upgrade head`。
3. 执行初始化脚本（按需一次）。
4. 启动应用：
```bash
PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```
5. 使用反向代理与进程守护（Nginx + systemd/supervisor）。

## 相关文档
1. `docs/phase1-architecture.md`
2. `docs/phase1-database-design.md`
3. `docs/phase1-analysis-design.md`
4. `docs/phase5-database-finalization.md`
5. `docs/phase6-runbook-and-validation.md`
6. `docs/refactor-changelog.md`
