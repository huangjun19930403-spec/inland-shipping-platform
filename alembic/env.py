"""
Alembic环境配置
支持异步SQLAlchemy (asyncpg/aiosqlite)
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 加载应用配置
from app.core.config import settings

# 导入所有模型（确保 Alembic 能检测到所有表）
from app.core.database import Base
from app.models import system, address, cargo, vessel, route, analysis, audit  # noqa: F401

# Alembic配置对象
config = context.config

# 设置数据库URL（覆盖alembic.ini中的空值）
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据（用于自动生成迁移）
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：不连接数据库，生成SQL脚本"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite兼容
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite兼容
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """异步模式：使用async引擎"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
