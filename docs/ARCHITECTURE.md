# 架构说明（当前主线）

本文档仅描述当前仓库真实生效的架构与调用主线。

## 1. 应用入口与启动

- 应用入口：`main.py`
- FastAPI 挂载：`app.include_router(api_router, prefix="/api/v1")`
- 生命周期：
  1. 数据库结构由 Alembic 迁移维护（启动前执行 `alembic upgrade head`）
  2. `DEBUG=true` 时执行 `scripts.seed_data.seed_all()`
  3. `DEBUG=true` 时启动 `app.tasks.scheduler.setup_scheduler()`

## 2. 分层主线

```text
HTTP Request
  -> app/api/v1/*/router.py
  -> app/core/dependencies.py (DI)
  -> app/services/*
  -> app/repositories/*
  -> app/models/*
  -> Database
```

约束：
- Router 层只做参数校验、鉴权、调用 Service、返回响应
- Service 层编排业务流程
- Repository 层承载数据访问
- Analysis API 只读取统计表，不直接读取业务表

## 3. API 主模块

全部挂载在 `/api/v1`：
- `/auth` 认证
- `/system` 用户与角色
- `/address` 水系/区域/节点
- `/cargo` 货品体系
- `/freight` 货源主流程（文本提交、解析结果确认、货源记录）
- `/vessel` 船舶档案与动态
- `/route` 航线与路径
- `/analysis` 统计分析
- `/ai` AI 管理（提示词、调用日志、重解析）
- `/audit` 审核中心

## 4. 业务主线

### 4.1 货源主线

1. `POST /api/v1/freight/text` 提交原始文本
2. 后台触发 `app.tasks.ai_tasks.trigger_cargo_parse`
3. 工作流 `app.workflows.cargo_parse_workflow.CargoParseWorkflow` 写入解析结果
4. `POST /api/v1/freight/parse-result/{id}/confirm` 确认后落库 `cargo_freight`
5. 触发 `refresh_cargo_stats()` 刷新货源统计表

### 4.2 船舶主线

- 船舶 CRUD 与动态更新走 `VesselService`
- 动态落库时补齐 `current_region_id/current_city_code/position_match_*`
- 统计接口读取船舶快照统计表（`ship_stat_*`）
- 可通过 `POST /api/v1/analysis/run-stats/ship` 强制刷新船舶统计

### 4.3 审核主线

- 业务 Service 调用 `AuditService.submit_for_audit()` 创建审核任务
- 审核接口调用 `approve_task/reject_task` 回写业务表审核状态

## 5. 任务与调度主线

- `app/tasks/stat_tasks.py`
  - `refresh_cargo_stats()`：货源事件驱动统计刷新
  - `run_ship_stats()` / 船舶统计快照刷新
  - `daily_stat_job()`：日统计聚合
- `app/tasks/ai_tasks.py`
  - `trigger_cargo_parse()`：开发环境 BackgroundTask 触发
  - Celery 任务封装（生产）
- `app/tasks/scheduler.py`
  - 开发环境 APScheduler 注册定时任务
- `app/tasks/celery_app.py`
  - 生产环境 Celery 配置

## 6. AI 主线

```text
CargoParseWorkflow
  -> CargoAgent
  -> CargoParseTextTool + EntityMatchTool
  -> LLM Registry (Anthropic/OpenAI/DeepSeek/Tongyi)
  -> cargo_ai_parse_result / ai_call_log
```

提示词模板由数据库管理：
- `ai_prompt_template`
- `ai_prompt_version`
- `app.ai.prompt_manager` 提供缓存读取

## 7. 数据库与迁移主线

- ORM Base：`app.core.database.Base`（唯一）
- Alembic 元数据：`alembic/env.py` 使用同一 Base
- 迁移链：`0001_initial_schema` 单基线，无分叉
- 应用运行时不执行 `create_all`

## 8. 当前保留文档

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DB_DESIGN.md`
- `docs/LOCAL_DEVELOPMENT.md`

其他历史设计稿与过时接口文档已移除，不再作为主线参考。
