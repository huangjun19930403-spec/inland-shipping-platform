# 本地开发指南（当前主线）

## 1. 环境要求

- Python 3.11+
- `pip`
- （可选）Redis：需要本地验证 Celery 时使用

## 2. 初始化

```bash
cd /path/to/inland-shipping-platform
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. 数据库准备

### 推荐：迁移到最新版本

```bash
alembic upgrade head
```

### 可选：初始化种子数据

```bash
python -m scripts.seed_data
```

## 4. 启动应用

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后：
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## 5. 常用命令

```bash
make dev
make migrate
make migrate-create msg="add_xxx"
make test
make lint
```

## 6. 核心验证清单

### 6.1 健康检查

```bash
curl -sS http://127.0.0.1:8000/health
```

### 6.2 登录获取 Token

```bash
curl -sS -X POST "http://127.0.0.1:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=Admin@2026"
```

### 6.3 核心接口冒烟

- `GET /api/v1/system/roles`
- `GET /api/v1/address/waterway`
- `GET /api/v1/freight`
- `GET /api/v1/analysis/dashboard`

## 7. 调试说明

- `DEBUG=true` 时会自动执行 `seed_all()` 与开发调度器
- 开发模式 AI 解析走 `BackgroundTask`，生产环境可切换到 Celery
- 表结构初始化统一通过 Alembic：`alembic upgrade head`

## 8. Celery（可选）

```bash
make celery-worker
make celery-beat
```

仅在需要验证生产异步模式时开启。
