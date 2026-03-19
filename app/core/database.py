from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings
from app.models.base import Base


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """开发辅助：按元数据直接建表（生产环境禁用，统一使用 Alembic）"""
    from app.models import (  # noqa: F401
        address, cargo, vessel, route, analysis, system, audit, ai
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
