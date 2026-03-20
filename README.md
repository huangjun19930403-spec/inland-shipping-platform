# 中国内河航运数据采集与分析平台

AI Native 的内河航运业务平台，当前代码基线为单主线可持续开发版本：
- 入口：`main.py`
- API：`/api/v1/*`
- 业务层：`app/services/*`
- 数据访问层：`app/repositories/*`
- 模型层：`app/models/*`
- 任务层：`app/tasks/*`
- 迁移链：`alembic/versions/0001_initial_schema.py`（单基线）

## 当前主线能力

1. 认证与系统管理（用户、角色、JWT）
2. 地址与节点管理（水系、区域、节点、别名）
3. 货品与货源主线（原始文本、AI解析、人工确认、货源主表）
4. 船舶与航线管理（船舶档案、动态、航线与路径）
5. 审核中心（任务+记录）
6. 统计分析（货源统计日表 + 船舶快照统计）
7. AI 模块（提示词模板、调用日志、重解析）

## 目录（主干）

```text
inland-shipping-platform/
├── main.py
├── app/
│   ├── api/v1/
│   ├── services/
│   ├── repositories/
│   ├── models/
│   ├── tasks/
│   ├── ai/
│   ├── agents/
│   ├── workflows/
│   ├── schemas/
│   └── core/
├── alembic/
│   └── versions/
├── scripts/
│   └── seed_data.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DB_DESIGN.md
│   └── LOCAL_DEVELOPMENT.md
└── tests/
```

## 快速启动

### 1. 环境准备

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. 数据库迁移

```bash
alembic upgrade head
```

### 3. 初始化种子数据（可选）

```bash
python -m scripts.seed_data
```

### 4. 启动服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## 常用命令

```bash
make dev              # 启动开发服务
make migrate          # 升级到最新迁移
make migrate-create msg="xxx"
make test             # 运行测试
make lint             # ruff 检查
```

## API 主模块

全部挂载在 `/api/v1`：
- `/auth`
- `/system`
- `/address`
- `/cargo`
- `/freight`
- `/vessel`
- `/route`
- `/analysis`
- `/ai`
- `/audit`

## 数据库迁移说明

当前迁移链为单基线版本：
- `0001_initial_schema`

运行时不执行 `create_all`，数据库结构仅由 Alembic 维护。

## 文档

- 架构说明：`docs/ARCHITECTURE.md`
- 数据库设计：`docs/DB_DESIGN.md`
- 本地开发：`docs/LOCAL_DEVELOPMENT.md`
