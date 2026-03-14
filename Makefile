# 内河航运平台 — 开发命令
.PHONY: dev seed migrate migrate-create test lint

# 启动开发服务器
dev:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 初始化种子数据
seed:
	python -m scripts.seed_data

# 执行数据库迁移
migrate:
	alembic upgrade head

# 生成迁移文件（用法: make migrate-create msg="add new column"）
migrate-create:
	alembic revision --autogenerate -m "$(msg)"

# 回滚迁移
migrate-rollback:
	alembic downgrade -1

# 运行测试
test:
	pytest tests/ -v

# 启动Celery Worker（需要Redis）
celery-worker:
	celery -A app.tasks.celery_app worker --loglevel=info -Q ai,analysis,dispatch

# 启动Celery Beat调度器（需要Redis）
celery-beat:
	celery -A app.tasks.celery_app beat --loglevel=info

# 代码格式检查
lint:
	ruff check app/ --fix

# 清理缓存
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
