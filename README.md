# 内河航运标准数据与分析平台（一期）

## 1. 项目定位
本项目一期定位为 **“内河航运标准数据与分析平台”**，聚焦：
1. 标准数据体系建设（地址/货品/船舶/航线）
2. 多源数据接入与标准化（微信/TMS/AIS/Excel）
3. 内部分析能力输出与 AI 融合增强

一期不做交易闭环、订单/运单/结算主流程、多租户 SaaS、外部客户中心。

## 2. 项目结构

```text
app/
  api/v1/
    standard_data/   # 标准数据域接口
    ingestion/       # 数据接入域接口
    analysis/        # 分析域接口
    ai/              # AI域接口
    system_domain/   # 系统域接口（认证/用户/审核）

  domain/            # 领域层聚合入口
  repositories/      # 数据访问层
  services/          # 业务编排层
  models/            # ORM模型
  jobs/              # 统计任务入口
  ai/                # AI能力组件
  infrastructure/    # 基础设施适配层
  core/              # 配置/安全/异常/数据库

alembic/
  versions/          # 一期基线迁移
  versions_legacy/   # 旧迁移归档（不再作为主链）

docs/
  phase1-architecture.md
  phase1-database-design.md
  phase1-analysis-design.md
  phase1-refactor-progress.md
  refactor-changelog.md
```

## 3. 环境准备

### 3.1 Python 与依赖
1. Python 3.9+
2. 创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.2 配置
复制并修改环境变量：

```bash
cp .env.example .env
```

常用变量：
1. `DATABASE_URL`（默认 SQLite）
2. `DEBUG`
3. JWT/AI 相关配置

## 4. 迁移建库（必须先执行）

> 启动已不再执行 `create_all`，统一走 Alembic。

```bash
source .venv/bin/activate
PYTHONPATH=. alembic upgrade head
```

查看当前迁移版本：

```bash
PYTHONPATH=. alembic current
```

## 5. 初始化方式

执行种子初始化（角色、账号、基础主数据）：

```bash
source .venv/bin/activate
PYTHONPATH=. python -m scripts.seed_data
```

默认账号：
1. `admin / Admin@2026`
2. `collector1 / Test@2026`

## 6. 开发启动

```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

文档地址：
1. `http://127.0.0.1:8000/docs`
2. `http://127.0.0.1:8000/redoc`

## 7. 定时任务 / 统计任务

一期统计任务入口在 `app/jobs/`：
1. `app/jobs/cargo_stats.py`
2. `app/jobs/ship_stats.py`
3. `app/jobs/region_compute.py`
4. `app/jobs/route_compute.py`

调用方式示例：

```bash
source .venv/bin/activate
PYTHONPATH=. python -c "import asyncio; from app.jobs.cargo_stats import run_cargo_stats; asyncio.run(run_cargo_stats())"
```

## 8. 核心接口说明（一期分域）

统一前缀：`/api/v1`

### 8.1 standard_data
1. `/standard-data/address/*` 地址标准体系
2. `/standard-data/commodity/*` 货品标准体系
3. `/standard-data/vessel/*` 船舶标准体系
4. `/standard-data/route/*` 航线与路线方案

### 8.2 ingestion
1. `/ingestion/cargo/text` 微信文本接入
2. `/ingestion/cargo/parse-result/{id}/confirm` AI 解析确认
3. `/ingestion/cargo/tms/raw` TMS 原始数据接入
4. `/ingestion/vessel/dynamic/{mmsi}` AIS 动态接入
5. `/ingestion/excel/vessel` Excel 批量船舶接入

### 8.3 analysis
1. `/analysis/dashboard`
2. `/analysis/cargo/heatmap`
3. `/analysis/cargo/trend`
4. `/analysis/cargo/commodity_rank`
5. `/analysis/cargo/od_flow`
6. `/analysis/ship/region_heatmap`
7. `/analysis/ship/city_heatmap`
8. `/analysis/ship/dwt_dist`
9. `/analysis/ship/age_dist`

### 8.4 ai
1. `/ai/parse-status/{raw_message_id}`
2. `/ai/reparse/{raw_message_id}`
3. `/ai/prompts/*` 提示词模板管理
4. `/ai/call-logs*` AI 调用日志
5. `/ai/match-suggestions/node`
6. `/ai/match-suggestions/commodity`
7. `/ai/analysis-explain`

### 8.5 system
1. `/system/auth/login`
2. `/system/users*` 用户与角色
3. `/system/audit/*` 审核任务

## 9. 部署说明（生产）

1. 拉取代码并安装依赖
2. 配置生产环境变量（`DEBUG=false`，配置外部数据库）
3. 执行迁移：`PYTHONPATH=. alembic upgrade head`
4. 执行初始化：`PYTHONPATH=. python -m scripts.seed_data`
5. 启动服务：

```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

建议：Nginx 反向代理 + 进程守护（systemd/supervisor）。

## 10. 文档索引
1. [一期架构设计](docs/phase1-architecture.md)
2. [一期数据库设计](docs/phase1-database-design.md)
3. [一期分析口径设计](docs/phase1-analysis-design.md)
4. [重构进度](docs/phase1-refactor-progress.md)
5. [重构变更日志](docs/refactor-changelog.md)
