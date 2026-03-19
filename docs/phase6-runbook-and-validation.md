# Phase 6 Runbook And Validation

## 1. 阶段目标与结论
执行日期：2026-03-19（Asia/Shanghai）

本阶段目标是验证返工后的主线是否“可迁移、可启动、可调用、可验证”。本次已完成：
1. `README.md` 已按当前真实主线重写并校对。
2. 核心测试已补齐并可执行通过。
3. 在全新数据库上完成迁移、初始化、启动和核心接口调用验证。
4. 至少一条 AI 标准化链路已跑通（无外部 LLM Key 时走降级解析，仍写入解析结果并可追踪）。

## 2. 环境与前置
项目目录：`/Users/hj/Documents/paltform_data/inland-shipping-platform`

本次验证使用数据库：
1. `/tmp/phase6_validation_20260319.db`（迁移 + 初始化 + 服务验证）

## 3. 初始化与迁移 Runbook
### 3.1 安装依赖
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.2 迁移建库（主链）
```bash
export DATABASE_URL="sqlite+aiosqlite:////tmp/phase6_validation_20260319.db"
PYTHONPATH=. .venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/alembic heads
```

本次实测结果：
1. 迁移链执行到 `6b4b44f84a6a (head)`。
2. `code_sequence` 已由主迁移链创建，不再依赖 legacy 迁移。

### 3.3 初始化数据
```bash
export DATABASE_URL="sqlite+aiosqlite:////tmp/phase6_validation_20260319.db"
PYTHONPATH=. .venv/bin/python -m scripts.seed_data
```

本次实测结果（关键项）：
1. 角色与用户初始化成功（`admin/Admin@2026`）。
2. 标准数据初始化成功（水系、区域、行政区、节点、货品、船型、AI 提示词）。
3. 初始统计聚合已执行。

## 4. 启动与任务 Runbook
### 4.1 启动应用
```bash
export DATABASE_URL="sqlite+aiosqlite:////tmp/phase6_validation_20260319.db"
DEBUG=False PYTHONPATH=. .venv/bin/uvicorn main:app --host 127.0.0.1 --port 18000
```

### 4.2 统计任务手动运行
```bash
PYTHONPATH=. python -c "import asyncio; from datetime import date; from app.jobs.cargo_stats import run_cargo_stats; print(asyncio.run(run_cargo_stats(date.today())))"
PYTHONPATH=. python -c "import asyncio; from app.jobs.ship_stats import run_ship_stats; print(asyncio.run(run_ship_stats()))"
```

## 5. 测试执行记录
执行命令：
```bash
PYTHONPATH=. .venv/bin/pytest -q
```

实测结果：
1. `13 passed`
2. 失败用例：`0`
3. 现存 warning：Pydantic v2 class-based config deprecation（不影响当前功能）

覆盖范围：
1. API smoke tests
2. domain/service tests
3. analysis jobs tests
4. AI parse 链路 smoke tests

## 6. 核心链路在线验证记录
以下调用均在已启动服务上完成，验证输出保存在：
1. `/tmp/phase6_validation_outputs_v2`

### 6.1 服务健康检查
接口：`GET /health`

结果：
```json
{"status":"ok","version":"2.0.0"}
```

### 6.2 登录鉴权
接口：`POST /api/v1/system/auth/login`

结果：返回 JWT `access_token`（用于后续受保护接口调用）。

### 6.3 标准数据接口（standard_data）
接口：`POST /api/v1/standard-data/address/waterway`

结果摘要：
1. 返回 `code=200`
2. 创建成功，返回新水系 `id=25`, `code=01-01-002`

### 6.4 数据接入接口（ingestion）
接口：`POST /api/v1/ingestion/vessel/dynamic/419001235`

结果摘要：
1. 返回 `code=200`
2. 动态记录写入成功，返回 `id=2`

### 6.5 分析接口（analysis）
接口：`GET /api/v1/analysis/dashboard`

结果摘要：
1. 返回 `code=200`
2. 返回统计字段：`cargo_total / cargo_confirmed / cargo_pending / cargo_tonnage / active_vessels`

### 6.6 AI 标准化链路（至少一条）
调用链路：
1. `POST /api/v1/ingestion/cargo/text`（提交原始货源文本）
2. `GET /api/v1/ai/parse-status/{raw_message_id}`（查询解析状态）

本次实测结果（`raw_message_id=2`）：
1. `raw_message.status = PARSED`
2. `parse_count = 1`
3. `parse_results[0].parse_status = PENDING_CONFIRM`

说明：
1. 在未配置外部 LLM Key 时，系统使用降级解析结果继续完成链路，保证“可追踪、可确认、不中断”。
2. 该行为符合一期“规则优先 + AI 增强”的工程可用性要求。

## 7. 当前未完成项（必须明确）
1. Pydantic v2 deprecation warning 尚未清理（`class Config` 需迁移为 `ConfigDict`）。
2. 未配置外部 LLM API Key 时，AI 结果为降级空字段（`overall_confidence=0`），需要人工确认。
3. 本阶段未扩展高并发/压测验证，仅完成功能完整性与主链可运行验证。

## 8. Phase 6 变更清单
1. 新增迁移：`alembic/versions/6b4b44f84a6a_phase6_add_code_sequence_table.py`
2. 更新模型：`app/models/system.py`（新增 `CodeSequence`）
3. 更新 AI 降级策略：`app/tools/cargo_tools.py`（provider 异常时继续产出可追踪解析结果）
4. 完善测试：`tests/integration/*`、`tests/unit/test_domain/*`、`tests/unit/test_jobs/*`
5. 更新文档：`README.md`、本文件
