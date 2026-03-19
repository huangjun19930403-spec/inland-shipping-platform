# Phase 2 API 主线切断与旧入口退场

更新时间：2026-03-19

## 1. 旧 API 退场方式

本阶段采用“主入口切断 + 旧路由迁入 legacy”策略：

1. `app/api/v1/__init__.py` 不再引用任何旧 router 目录（`address/cargo/vessel/route/freight/auth/audit/system_domain`）。
2. 旧 router 目录整体从 `app/api/v1/` 迁移到 `app/api/legacy/v1/`。
3. 新域入口文件不再 `include` 旧 router：
   - `app/api/v1/standard_data/router.py` 仅包含 `standard_data/*.py`
   - `app/api/v1/ingestion/router.py` 仅包含 `ingestion/*.py`
   - `app/api/v1/system/router.py` 仅包含 `system/*.py`

## 2. 新 API 主入口位置

系统现在只有一套主入口：

1. 应用入口：`main.py`
2. v1 路由分发：`app/api/v1/__init__.py`
3. 五大域入口：
   - `app/api/v1/standard_data/router.py`
   - `app/api/v1/ingestion/router.py`
   - `app/api/v1/analysis/router.py`
   - `app/api/v1/ai/router.py`
   - `app/api/v1/system/router.py`

## 3. 旧 router 删除清单（本阶段）

本阶段未做物理删除，统一迁移到 legacy，删除动作延后到后续阶段完成。

## 4. 旧 router 迁移到 legacy 清单

以下目录已从 `app/api/v1/` 迁出至 `app/api/legacy/v1/`：

1. `address/`
2. `cargo/`
3. `vessel/`
4. `route/`
5. `freight/`
6. `auth/`
7. `audit/`
8. `system_domain/`

## 5. 当前系统唯一 API 主入口结论

当前主应用只挂载新域 API：

- `/api/v1/standard-data`
- `/api/v1/ingestion`
- `/api/v1/analysis`
- `/api/v1/ai`
- `/api/v1/system`

旧 router 已不在 `app/api/v1` 主线路径中，不再作为主 API 入口。

## 6. 本阶段重构的关键文件

1. 更新：`app/api/v1/__init__.py`
2. 更新：`app/api/v1/standard_data/router.py`
3. 更新：`app/api/v1/ingestion/router.py`
4. 更新：`app/api/v1/system/router.py`
5. 新增：
   - `app/api/v1/standard_data/address.py`
   - `app/api/v1/standard_data/commodity.py`
   - `app/api/v1/standard_data/vessel.py`
   - `app/api/v1/standard_data/route.py`
   - `app/api/v1/ingestion/cargo.py`
   - `app/api/v1/ingestion/tms.py`
   - `app/api/v1/ingestion/vessel.py`
   - `app/api/v1/system/auth.py`
   - `app/api/v1/system/user.py`
   - `app/api/v1/system/audit.py`
6. 迁移：`app/api/legacy/v1/*`（旧 router 目录归档）
