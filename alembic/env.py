"""
Alembic环境配置
支持异步 SQLAlchemy（PostgreSQL/PostGIS / MySQL / SQLite）
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import text

from alembic import context

# 加载应用配置
from app.core.config import settings

# 导入所有模型（确保Alembic能检测到所有表）
from app.core.database import Base
from app.models import (  # noqa: F401
    address,
    analysis,
    commodity,
    common,
    dictionary,
    freight,
    navigation,
    operation,
    approval,
    route,
    vessel,
    system,
)

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
    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) NOT NULL)"))
        connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"))
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                          FROM pg_constraint
                         WHERE contype = 'p'
                           AND conrelid = 'alembic_version'::regclass
                    ) THEN
                        ALTER TABLE alembic_version
                        ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);
                    END IF;
                END $$;
                """
            )
        )
    elif dialect_name == "mysql":
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) NOT NULL)"))
        connection.execute(text("ALTER TABLE alembic_version MODIFY version_num VARCHAR(64) NOT NULL"))
        primary_key_count = connection.scalar(
            text(
                """
                SELECT COUNT(*)
                  FROM information_schema.table_constraints
                 WHERE table_schema = DATABASE()
                   AND table_name = 'alembic_version'
                   AND constraint_type = 'PRIMARY KEY'
                """
            )
        )
        if not primary_key_count:
            connection.execute(text("ALTER TABLE alembic_version ADD PRIMARY KEY (version_num)"))
    if connection.in_transaction():
        connection.commit()

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
